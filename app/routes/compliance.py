"""`/compliance/v0` — the operator's responsible-gambling surface.

Exclusion list, marketing policy (quiet hours / frequency caps), the
audit trail, and the GDPR pair (export / erase). Enforcement itself
lives in the engine; these endpoints only manage the rules and prove
what happened.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from ..audit import record
from ..compliance import active_exclusion, get_policy, set_policy
from ..db import get_session
from ..durations import parse_timestamp
from ..models import (
    AuditLog,
    CommsMessage,
    JourneyActivation,
    ParkedSubscription,
    PlatformEvent,
    Player,
    PlayerExclusion,
    PromotionOffer,
    RewardGrant,
    Timer,
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/compliance/v0", tags=["compliance"])


def _serialize_exclusion(row: PlayerExclusion, session: Session) -> dict:
    return {
        "playerId": row.player_id,
        "reason": row.reason,
        "note": row.note,
        "addedBy": row.added_by,
        "expiresAt": row.expires_at.isoformat() if row.expires_at else None,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "active": active_exclusion(session, row.player_id) is not None,
    }


# ── exclusion list ───────────────────────────────────────────────────


@router.get("/exclusions")
def list_exclusions(session: Session = Depends(get_session)):
    rows = (
        session.execute(select(PlayerExclusion).order_by(PlayerExclusion.created_at))
        .scalars()
        .all()
    )
    return {"items": [_serialize_exclusion(r, session) for r in rows]}


@router.post("/exclusions", status_code=201)
def add_exclusion(payload: dict = Body(...), session: Session = Depends(get_session)):
    player_id = payload.get("playerId")
    if not player_id:
        raise HTTPException(status_code=400, detail="playerId is required")
    reason = payload.get("reason", "self_exclusion")
    if reason not in ("self_exclusion", "vulnerable", "cool_off"):
        raise HTTPException(
            status_code=400,
            detail="reason must be self_exclusion, vulnerable or cool_off",
        )
    expires_at = None
    if payload.get("expiresAt"):
        expires_at = parse_timestamp(payload["expiresAt"])
    row = session.get(PlayerExclusion, player_id)
    if row is None:
        row = PlayerExclusion(player_id=player_id, reason=reason)
        session.add(row)
    row.reason = reason
    row.note = payload.get("note")
    row.added_by = payload.get("actor", "operator")
    row.expires_at = expires_at
    record(
        session,
        payload.get("actor"),
        "exclusion-added",
        detail=f"{player_id}: {reason}",
    )
    session.flush()
    return _serialize_exclusion(row, session)


@router.delete("/exclusions/{player_id}")
def remove_exclusion(
    player_id: str, actor: str = "operator", session: Session = Depends(get_session)
):
    row = session.get(PlayerExclusion, player_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{player_id} is not excluded")
    session.delete(row)
    record(session, actor, "exclusion-removed", detail=player_id)
    return {"removed": player_id}


# ── marketing policy ─────────────────────────────────────────────────


@router.get("/policy")
def read_policy(session: Session = Depends(get_session)):
    policy = get_policy(session)
    return {
        "quietHours": policy.quiet_hours if policy else None,
        "frequencyCaps": policy.frequency_caps if policy else None,
    }


@router.put("/policy")
def write_policy(payload: dict = Body(...), session: Session = Depends(get_session)):
    quiet_hours = payload.get("quietHours")
    if quiet_hours is not None and not (
        isinstance(quiet_hours, dict)
        and quiet_hours.get("start")
        and quiet_hours.get("end")
    ):
        raise HTTPException(
            status_code=400,
            detail='quietHours must be {"start": "HH:MM", "end": "HH:MM"} (UTC) or null',
        )
    caps = payload.get("frequencyCaps")
    if caps is not None and not isinstance(caps, dict):
        raise HTTPException(status_code=400, detail="frequencyCaps must be an object")
    policy = set_policy(session, quiet_hours, caps)
    record(
        session,
        payload.get("actor"),
        "policy-updated",
        detail=f"quietHours={quiet_hours} frequencyCaps={caps}",
    )
    return {"quietHours": policy.quiet_hours, "frequencyCaps": policy.frequency_caps}


# ── audit trail ──────────────────────────────────────────────────────


@router.get("/audit")
def list_audit(
    journey_id: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
):
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))
    if journey_id:
        query = query.where(AuditLog.journey_id == journey_id)
    rows = session.execute(query).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "actor": r.actor,
                "action": r.action,
                "journeyId": r.journey_id,
                "detail": r.detail,
                "at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


# ── GDPR: export & erase ─────────────────────────────────────────────


@router.get("/players/{player_id}/export")
def export_player(player_id: str, session: Session = Depends(get_session)):
    """Everything the system holds about one player, as one document —
    the data-subject access request."""
    player = session.get(Player, player_id)
    activations = (
        session.execute(
            select(JourneyActivation).where(JourneyActivation.player_id == player_id)
        )
        .scalars()
        .all()
    )
    exclusion = session.get(PlayerExclusion, player_id)
    return {
        "playerId": player_id,
        "player": {
            "brand": player.brand,
            "currency": player.currency,
            "attributes": player.attributes,
            "isTest": player.is_test,
            "createdAt": player.created_at.isoformat() if player.created_at else None,
        }
        if player
        else None,
        "exclusion": _serialize_exclusion(exclusion, session) if exclusion else None,
        "activations": [
            {
                "activationId": a.id,
                "journeyId": a.journey_id,
                "status": a.status,
                "eventsHistory": a.events_history,
                "createdAt": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activations
        ],
        "offers": [
            {"offerId": o.id, "status": o.status, "terms": o.terms}
            for o in session.execute(
                select(PromotionOffer).where(PromotionOffer.player_id == player_id)
            ).scalars()
        ],
        "rewards": [
            {"grantId": g.id, "rewardType": g.reward_type, "status": g.status, "detail": g.detail}
            for g in session.execute(
                select(RewardGrant).where(RewardGrant.player_id == player_id)
            ).scalars()
        ],
        "comms": [
            {"messageId": m.id, "channel": m.channel, "status": m.status, "body": m.body}
            for m in session.execute(
                select(CommsMessage).where(CommsMessage.player_id == player_id)
            ).scalars()
        ],
        "platformEvents": [
            {"eventName": e.event_name, "properties": e.properties,
             "at": e.created_at.isoformat() if e.created_at else None}
            for e in session.execute(
                select(PlatformEvent).where(PlatformEvent.player_id == player_id)
            ).scalars()
        ],
    }


@router.delete("/players/{player_id}")
def erase_player(
    player_id: str, actor: str = "operator", session: Session = Depends(get_session)
):
    """Right-to-erasure: delete every trace of the player. The exclusion
    row is deliberately KEPT — honouring a self-exclusion is a legal
    obligation that survives erasure."""
    activation_ids = [
        row[0]
        for row in session.execute(
            select(JourneyActivation.id).where(
                JourneyActivation.player_id == player_id
            )
        ).all()
    ]
    erased: dict[str, int] = {}
    if activation_ids:
        for model, key in ((Timer, "timers"), (ParkedSubscription, "subscriptions")):
            erased[key] = session.execute(
                sql_delete(model).where(model.activation_id.in_(activation_ids))
            ).rowcount
    for model, key in (
        (PromotionOffer, "offers"),
        (RewardGrant, "rewards"),
        (CommsMessage, "comms"),
        (PlatformEvent, "platformEvents"),
        (JourneyActivation, "activations"),
    ):
        erased[key] = session.execute(
            sql_delete(model).where(model.player_id == player_id)
        ).rowcount
    player = session.get(Player, player_id)
    if player is not None:
        session.delete(player)
        erased["player"] = 1
    record(session, actor, "player-erased", detail=f"{player_id}: {erased}")
    kept = "exclusion record (regulatory obligation)" if session.get(
        PlayerExclusion, player_id
    ) else None
    return {"erased": erased, "kept": kept}
