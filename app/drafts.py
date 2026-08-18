"""Draft persistence: create / update journey drafts.

On create the server behaves like the platform being imitated:
  - the draft may carry a pre-reserved ``JRN-0-*`` (it is consumed), or one
    is minted on the fly;
  - missing/blank ``promotionDisplayId``s are re-minted server-side;
  - every activityId is registered brand-wide so a later draft reusing one
    fails validation ("activities with the same identifier already exist").
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .durations import parse_timestamp
from .ids import mint_draft_id, mint_journey_id, mint_promotion_display_id
from .models import ActivityIdRegistry, Journey, PromotionDisplayId, ReservedJourneyId
from .validation import Problem, aggregate, validate_draft


class DraftError(Exception):
    def __init__(self, problems: list[Problem], status_code: int = 400):
        super().__init__("draft validation failed")
        self.problems = problems
        self.status_code = status_code

    def body(self) -> dict:
        return aggregate(self.problems)


def _http_status(problems: list[Problem]) -> int:
    # the imitated platform answers 422 for display-id collisions, 400 otherwise
    if any(p.slug == "already-existing-promotion-display-id" for p in problems):
        return 422
    return 400


def _mint_missing_display_ids(session: Session, body: dict, brand: str, journey_id: str) -> None:
    for activity in body.get("activities", []):
        if activity.get("activityName") not in ("promotion", "multipurpose_promotion"):
            continue
        init = activity.setdefault("initializationData", {})
        display_id = init.get("promotionDisplayId")
        if display_id in (None, "", 0):
            display_id = mint_promotion_display_id(session)
            init["promotionDisplayId"] = display_id
        row = session.get(PromotionDisplayId, int(display_id))
        if row is None:
            session.add(
                PromotionDisplayId(display_id=int(display_id), brand=brand, journey_id=journey_id)
            )
        elif row.journey_id is None:
            row.journey_id = journey_id


def _register_activity_ids(session: Session, body: dict, brand: str, journey_id: str) -> None:
    session.execute(
        delete(ActivityIdRegistry).where(ActivityIdRegistry.journey_id == journey_id)
    )
    for activity in body.get("activities", []):
        activity_id = activity.get("activityId")
        if activity_id:
            session.add(
                ActivityIdRegistry(
                    activity_id=activity_id, brand=brand, journey_id=journey_id
                )
            )


def _parse_optional_ts(value):
    if not value:
        return None
    return parse_timestamp(value)


def create_draft(session: Session, body: dict, default_brand: str) -> Journey:
    brand = body.get("brand") or default_brand
    problems = validate_draft(session, body, brand)
    if problems:
        raise DraftError(problems, _http_status(problems))

    journey_id = body.get("reservedJourneyId") or body.get("journeyId")
    if journey_id:
        reservation = session.get(ReservedJourneyId, journey_id)
        if reservation is not None:
            reservation.used = True
    else:
        journey_id = mint_journey_id(session)

    body = dict(body)
    body["journeyId"] = journey_id
    body["reservedJourneyId"] = journey_id
    body.setdefault("brand", brand)

    _mint_missing_display_ids(session, body, brand, journey_id)
    _register_activity_ids(session, body, brand, journey_id)

    journey = Journey(
        draft_id=mint_draft_id(session),
        journey_id=journey_id,
        brand=brand,
        journey_name=body.get("journeyName", ""),
        status="Draft",
        version=1,
        body=body,
        start_at=_parse_optional_ts(body.get("startAt")),
        stop_at=_parse_optional_ts(body.get("stopAt")),
        is_immediately_after_publish=bool(body.get("isImmediatelyAfterPublish", True)),
        is_unlimited=bool(body.get("isUnlimited", True)),
        author=body.get("author") or "sandbox",
        duplicated_from_id=None,
    )
    session.add(journey)
    session.flush()
    return journey


def update_draft(session: Session, journey: Journey, body: dict) -> Journey:
    brand = body.get("brand") or journey.brand
    problems = validate_draft(
        session, body, brand, existing_journey_id=journey.journey_id
    )
    if problems:
        raise DraftError(problems, _http_status(problems))

    body = dict(body)
    body["journeyId"] = journey.journey_id
    body["reservedJourneyId"] = journey.journey_id
    body.setdefault("brand", brand)

    _mint_missing_display_ids(session, body, brand, journey.journey_id)
    _register_activity_ids(session, body, brand, journey.journey_id)

    journey.body = body
    journey.journey_name = body.get("journeyName", journey.journey_name)
    journey.brand = brand
    journey.start_at = _parse_optional_ts(body.get("startAt"))
    journey.stop_at = _parse_optional_ts(body.get("stopAt"))
    journey.is_immediately_after_publish = bool(body.get("isImmediatelyAfterPublish", True))
    journey.is_unlimited = bool(body.get("isUnlimited", True))
    journey.version += 1
    session.flush()
    return journey


def serialize_journey(session: Session, journey: Journey, *, with_body: bool = True) -> dict[str, Any]:
    from .models import JourneyActivation, RewardGrant

    statuses = [
        row[0]
        for row in session.execute(
            select(JourneyActivation.status).where(
                JourneyActivation.journey_id == journey.journey_id
            )
        ).all()
    ]
    entered = len(statuses)
    completed = sum(1 for status in statuses if status == "Completed")
    grants = len(
        session.execute(
            select(RewardGrant.id).where(RewardGrant.journey_id == journey.journey_id)
        ).all()
    )
    payload: dict[str, Any] = {
        "id": journey.draft_id,
        "journeyId": journey.journey_id,
        "journeyName": journey.journey_name,
        "brand": journey.brand,
        "status": journey.status,
        "version": journey.version,
        "author": journey.author,
        "createdAt": journey.created_at.isoformat() if journey.created_at else None,
        "changedAt": journey.changed_at.isoformat() if journey.changed_at else None,
        "duplicatedFromId": journey.duplicated_from_id,
        "approvalState": journey.approval_state,
        "submittedBy": journey.submitted_by,
        "approvedBy": journey.approved_by,
        "reviewNote": journey.review_note,
        "allJourneyActivationsCount": entered,
        "activeActivationsCount": sum(1 for status in statuses if status == "Active"),
        "completedActivationsCount": completed,
        "completionRate": round(completed / entered, 4) if entered else None,
        "rewardGrantsCount": grants,
    }
    if with_body:
        payload["body"] = journey.body
    return payload
