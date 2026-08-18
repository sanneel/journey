"""`/journey-builder/v0` — the builder API.

Mirrors the endpoint catalogue of the imitated platform:

  POST /journeys/identifier          reserve a JRN-0-* before drafting
  POST /journey-drafts               create a draft (201, full body back)
  PUT  /journey-drafts/{draft_id}    update a draft (numeric id!)
  GET  /journeys                     list
  GET  /journeys/{journey_id}        read one (JRN-0-*)
  POST /journeys/{journey_id}/publish | /stop | /archive
  POST /journeys/{journey_id}/duplicate
  GET  /activities/catalog           the Tools palette
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import delete as sql_delete

from ..audit import record
from ..catalog import palette
from ..cloner import clone_journey_body
from ..config import settings
from ..db import get_session
from ..drafts import DraftError, create_draft, serialize_journey, update_draft
from ..engine import Engine, EngineError
from ..ids import mint_journey_id
from ..models import ActivityIdRegistry, Journey, PromotionDisplayId, ReservedJourneyId
from ..validation import aggregate, validate_draft

router = APIRouter(prefix="/journey-builder/v0", tags=["journey-builder"])


def _get_journey(session: Session, journey_id: str) -> Journey:
    journey = session.execute(
        select(Journey).where(Journey.journey_id == journey_id)
    ).scalar_one_or_none()
    if journey is None:
        raise HTTPException(status_code=404, detail=f"journey {journey_id} not found")
    return journey


@router.post("/journeys/identifier")
def reserve_identifier(
    payload: dict = Body(default={}), session: Session = Depends(get_session)
):
    brand = payload.get("brand") or settings.default_brand
    journey_id = mint_journey_id(session)
    session.add(ReservedJourneyId(journey_id=journey_id, brand=brand))
    return {"journeyId": journey_id}


@router.post("/journey-drafts", status_code=201)
def create_journey_draft(
    body: dict = Body(...), session: Session = Depends(get_session)
):
    try:
        journey = create_draft(session, body, settings.default_brand)
    except DraftError as error:
        raise HTTPException(status_code=error.status_code, detail=error.body())
    return serialize_journey(session, journey)


@router.post("/journey-drafts/validate")
def validate_journey_draft(
    body: dict = Body(...), session: Session = Depends(get_session)
):
    """Dry-run validation: same checks as create, nothing persisted.
    The builder UI calls this on every save-preview."""
    brand = body.get("brand") or settings.default_brand
    # treat the body's own id as "self" so editing an existing draft does
    # not collide with itself
    existing = body.get("journeyId") or body.get("reservedJourneyId")
    problems = validate_draft(session, body, brand, existing_journey_id=existing)
    # non-blocking compliance advisories: an offer that advertises a bonus
    # without significant terms is a regulatory problem, not a graph one
    warnings = [
        {
            "type": "promotion-terms-missing",
            "activityId": activity.get("activityId"),
            "detail": "offers must carry significant terms (wagering, expiry, "
            "max win) — add initializationData.terms",
        }
        for activity in body.get("activities", [])
        if activity.get("activityName") in ("promotion", "multipurpose_promotion")
        and not (
            (activity.get("initializationData") or {}).get("terms")
            or (activity.get("initializationData") or {}).get("termsAndConditions")
        )
    ]
    return {
        "valid": not problems,
        "warnings": warnings,
        **(aggregate(problems) if problems else {}),
    }


@router.delete("/journey-drafts/{draft_id}")
def delete_journey_draft(draft_id: int, session: Session = Depends(get_session)):
    journey = session.get(Journey, draft_id)
    if journey is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
    if journey.status not in ("Draft", "Archived"):
        raise HTTPException(
            status_code=409,
            detail=f"draft {draft_id} is {journey.status}; only Draft or Archived "
            "journeys can be deleted",
        )
    # free the structural-id registry; minted display ids stay minted but
    # become unassigned (the sequence is never reused)
    session.execute(
        sql_delete(ActivityIdRegistry).where(
            ActivityIdRegistry.journey_id == journey.journey_id
        )
    )
    for row in (
        session.execute(
            select(PromotionDisplayId).where(
                PromotionDisplayId.journey_id == journey.journey_id
            )
        )
        .scalars()
        .all()
    ):
        row.journey_id = None
    session.delete(journey)
    return {"deleted": draft_id, "journeyId": journey.journey_id}


@router.put("/journey-drafts/{draft_id}")
def update_journey_draft(
    draft_id: int, body: dict = Body(...), session: Session = Depends(get_session)
):
    journey = session.get(Journey, draft_id)
    if journey is None:
        raise HTTPException(status_code=404, detail=f"draft {draft_id} not found")
    if journey.status not in ("Draft", "Stopped", "Published"):
        raise HTTPException(
            status_code=409,
            detail=f"draft {draft_id} is {journey.status} and cannot be edited",
        )
    was_published = journey.status == "Published"
    try:
        journey = update_draft(session, journey, body)
    except DraftError as error:
        raise HTTPException(status_code=error.status_code, detail=error.body())
    # the content changed — any standing approval covered the old body
    journey.approval_state = None
    journey.submitted_by = None
    journey.approved_by = None
    journey.review_note = None
    if was_published:
        # live edit: this save IS the new published version. In-flight
        # players keep walking the revision they entered on; new entrants
        # get this body from now on.
        engine = Engine(session)
        engine.register_webhooks(journey)
        engine.snapshot_revision(journey)
        record(
            session,
            body.get("actor"),
            "live-edit",
            journey.journey_id,
            f"published v{journey.version} replaced in place",
        )
    result = serialize_journey(session, journey)
    if was_published:
        result["liveEdit"] = True
    return result


@router.get("/journeys")
def list_journeys(
    brand: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    query = select(Journey).order_by(Journey.draft_id)
    if brand:
        query = query.where(Journey.brand == brand)
    if status:
        query = query.where(Journey.status == status)
    journeys = session.execute(query).scalars().all()
    return {
        "items": [serialize_journey(session, j, with_body=False) for j in journeys]
    }


@router.get("/journeys/{journey_id}")
def read_journey(journey_id: str, session: Session = Depends(get_session)):
    journey = _get_journey(session, journey_id)
    return serialize_journey(session, journey)


@router.post("/journeys/{journey_id}/submit-review")
def submit_review(
    journey_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    """First half of four-eyes publishing: the author hands the journey
    to a reviewer. Any later edit voids the submission."""
    journey = _get_journey(session, journey_id)
    if journey.status not in ("Draft", "Stopped"):
        raise HTTPException(
            status_code=409,
            detail=f"{journey_id} is {journey.status}; only Draft or Stopped "
            "journeys can be submitted for review",
        )
    journey.approval_state = "InReview"
    journey.submitted_by = payload.get("requestedBy", "operator")
    journey.approved_by = None
    journey.review_note = None
    record(session, journey.submitted_by, "submitted-for-review", journey_id)
    return serialize_journey(session, journey, with_body=False)


@router.post("/journeys/{journey_id}/approve")
def approve_journey(
    journey_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    journey = _get_journey(session, journey_id)
    if journey.approval_state != "InReview":
        raise HTTPException(
            status_code=409,
            detail={"type": "journey-not-in-review",
                    "detail": f"approval state is {journey.approval_state}"},
        )
    approver = payload.get("approvedBy", "operator")
    if journey.submitted_by and approver.strip().lower() == journey.submitted_by.strip().lower():
        raise HTTPException(
            status_code=409,
            detail={"type": "four-eyes-violation",
                    "detail": "the approver must be a different person than the submitter"},
        )
    journey.approval_state = "Approved"
    journey.approved_by = approver
    record(session, approver, "approved", journey_id,
           f"submitted by {journey.submitted_by}")
    return serialize_journey(session, journey, with_body=False)


@router.post("/journeys/{journey_id}/reject")
def reject_journey(
    journey_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    journey = _get_journey(session, journey_id)
    if journey.approval_state != "InReview":
        raise HTTPException(
            status_code=409,
            detail={"type": "journey-not-in-review",
                    "detail": f"approval state is {journey.approval_state}"},
        )
    journey.approval_state = "Rejected"
    journey.review_note = payload.get("reason")
    record(session, payload.get("rejectedBy"), "rejected", journey_id,
           payload.get("reason"))
    return serialize_journey(session, journey, with_body=False)


@router.get("/journeys/{journey_id}/audit")
def journey_audit(journey_id: str, session: Session = Depends(get_session)):
    from ..models import AuditLog

    _get_journey(session, journey_id)
    rows = (
        session.execute(
            select(AuditLog)
            .where(AuditLog.journey_id == journey_id)
            .order_by(AuditLog.id.desc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "actor": r.actor,
                "action": r.action,
                "detail": r.detail,
                "at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("/journeys/{journey_id}/publish")
def publish_journey(
    journey_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    journey = _get_journey(session, journey_id)
    try:
        result = Engine(session).publish(journey)
    except EngineError as error:
        raise HTTPException(
            status_code=409, detail={"type": error.slug, "detail": error.detail}
        )
    record(session, payload.get("actor"), "published", journey_id,
           f"v{journey.version}")
    return result


@router.post("/journeys/{journey_id}/stop")
def stop_journey(
    journey_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    """mode "terminate" (default) ends active runs now; mode "drain"
    closes the doors and lets in-flight players finish — the journey
    flips to Stopped by itself when the last one completes."""
    journey = _get_journey(session, journey_id)
    mode = payload.get("mode", "terminate")
    if mode not in ("terminate", "drain"):
        raise HTTPException(status_code=400, detail="mode must be terminate or drain")
    result = Engine(session).stop(journey, mode=mode)
    record(session, payload.get("actor"), "stopped", journey_id, f"mode={mode}")
    return result


@router.post("/journeys/{journey_id}/archive")
def archive_journey(
    journey_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    journey = _get_journey(session, journey_id)
    if journey.status == "Published":
        Engine(session).stop(journey)
    journey.status = "Archived"
    record(session, payload.get("actor"), "archived", journey_id)
    return {"journeyId": journey.journey_id, "status": "Archived"}


@router.post("/journeys/{journey_id}/duplicate", status_code=201)
def duplicate_journey(
    journey_id: str,
    payload: dict = Body(default={}),
    session: Session = Depends(get_session),
):
    source = _get_journey(session, journey_id)
    new_journey_id = mint_journey_id(session)
    session.add(ReservedJourneyId(journey_id=new_journey_id, brand=source.brand, used=True))
    session.flush()
    new_name = payload.get("journeyName") or f"{source.journey_name} (copy)"
    body, id_mapping = clone_journey_body(
        source.body,
        new_journey_id=new_journey_id,
        new_name=new_name,
        source_journey_id=source.journey_id,
        source_version=source.version,
    )
    body["duplicatedFromId"] = None
    try:
        journey = create_draft(session, body, source.brand)
    except DraftError as error:
        raise HTTPException(status_code=error.status_code, detail=error.body())
    journey.duplicated_from_id = source.journey_id
    result = serialize_journey(session, journey)
    result["idMapping"] = id_mapping
    return result


@router.get("/journeys/{journey_id}/console-script")
def journey_console_script(
    journey_id: str,
    publish: bool = True,
    session: Session = Depends(get_session),
):
    """A paste-able browser console script that recreates this journey —
    the operators' journey-cloner workflow, generated from the canvas.
    Every download mints fresh internal ids."""
    from fastapi.responses import Response

    from ..console_script import render_console_script

    journey = _get_journey(session, journey_id)
    script = render_console_script(journey, publish=publish)
    filename = f"{journey.journey_id}_console.js"
    return Response(
        script,
        media_type="application/javascript; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/activities/catalog")
def activities_catalog():
    return {"palette": palette()}


@router.get("/journey-templates")
def list_journey_templates():
    from ..journey_templates import list_templates

    return {"items": list_templates()}


@router.get("/journey-templates/{key}")
def instantiate_journey_template(key: str):
    """Returns a complete draft body with FRESH activity ids on every
    call — load it in the builder, tweak, then save as a normal draft."""
    from ..journey_templates import instantiate

    body = instantiate(key)
    if body is None:
        raise HTTPException(status_code=404, detail=f"template {key} not found")
    return {"key": key, "body": body}
