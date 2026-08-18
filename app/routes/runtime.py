"""`/runtime/v0` + `/platform/v0` — the execution surface.

This is the half the imitated platform never shows you: what happens after
a draft is published. Players enter (webhook / {journeyId, activityId} /
segment / registration event), platform events resolve parked conditions,
timers fire, rewards land in a ledger and comms in an outbox — all
inspectable here.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..engine import Engine, EngineError, entry_sources
from ..models import (
    CommsMessage,
    Journey,
    JourneyActivation,
    Player,
    PromotionOffer,
    RewardGrant,
    Timer,
    Webhook,
)

router = APIRouter(tags=["runtime"])


def _engine_http(error: EngineError) -> HTTPException:
    return HTTPException(
        status_code=409, detail={"type": error.slug, "detail": error.detail}
    )


def _get_journey(session: Session, journey_id: str) -> Journey:
    journey = session.execute(
        select(Journey).where(Journey.journey_id == journey_id)
    ).scalar_one_or_none()
    if journey is None:
        raise HTTPException(status_code=404, detail=f"journey {journey_id} not found")
    return journey


def _serialize_activation(activation: JourneyActivation) -> dict:
    return {
        "activationId": activation.id,
        "journeyId": activation.journey_id,
        "playerId": activation.player_id,
        "status": activation.status,
        "currentActivityId": activation.current_activity_id,
        "entryActivityId": activation.entry_activity_id,
        "context": activation.context,
        "eventsHistory": activation.events_history,
        "createdAt": activation.created_at.isoformat() if activation.created_at else None,
    }


# ── players ──────────────────────────────────────────────────────────


@router.post("/platform/v0/players", status_code=201)
def upsert_player(payload: dict = Body(...), session: Session = Depends(get_session)):
    player_id = payload.get("playerId")
    if not player_id:
        raise HTTPException(status_code=400, detail="playerId is required")
    player = session.get(Player, player_id)
    if player is None:
        player = Player(
            player_id=player_id,
            brand=payload.get("brand", "JBCL"),
            currency=payload.get("currency", "CLP"),
            attributes=payload.get("attributes", {}),
        )
        session.add(player)
    else:
        player.brand = payload.get("brand", player.brand)
        player.currency = payload.get("currency", player.currency)
        player.attributes = {**(player.attributes or {}), **payload.get("attributes", {})}
    session.flush()
    return {
        "playerId": player.player_id,
        "brand": player.brand,
        "currency": player.currency,
        "attributes": player.attributes,
    }


# ── entry points ─────────────────────────────────────────────────────


@router.post("/journey-builder/v0/webhooks/{webhook_id}", status_code=201)
def webhook_entry(
    webhook_id: str, payload: dict = Body(...), session: Session = Depends(get_session)
):
    """The `external_system_source` hand-off — how a Randomizer prize or a
    Promo Page routes a player into its reward journey."""
    webhook = session.get(Webhook, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail=f"webhook {webhook_id} not found")
    player_id = payload.get("playerId")
    if not player_id:
        raise HTTPException(status_code=400, detail="playerId is required")
    journey = _get_journey(session, webhook.journey_id)
    try:
        activation = Engine(session).enter(
            journey,
            webhook.activity_id,
            player_id,
            context=payload.get("context") or {},
        )
    except EngineError as error:
        raise _engine_http(error)
    return _serialize_activation(activation)


@router.post(
    "/journey-builder/v0/journeys/{journey_id}/activities/{activity_id}/enter",
    status_code=201,
)
def enter_by_pair(
    journey_id: str,
    activity_id: str,
    payload: dict = Body(...),
    session: Session = Depends(get_session),
):
    """Direct `{journeyId, activityId}` entry — the pair every prize and
    promo page carries."""
    journey = _get_journey(session, journey_id)
    player_id = payload.get("playerId")
    if not player_id:
        raise HTTPException(status_code=400, detail="playerId is required")
    try:
        activation = Engine(session).enter(
            journey, activity_id, player_id, context=payload.get("context") or {}
        )
    except EngineError as error:
        raise _engine_http(error)
    return _serialize_activation(activation)


@router.post("/journey-builder/v0/journeys/{journey_id}/players", status_code=201)
def segment_entry(
    journey_id: str,
    payload: dict = Body(...),
    session: Session = Depends(get_session),
):
    """Bulk segment injection (dwh_source): add many players at once."""
    journey = _get_journey(session, journey_id)
    player_ids = payload.get("playerIds") or []
    if not player_ids:
        raise HTTPException(status_code=400, detail="playerIds is required")
    sources = [
        s
        for s in entry_sources(journey)
        if s.get("activityName") in ("dwh_source", "external_system_source", "registration")
    ]
    if not sources:
        raise HTTPException(status_code=409, detail="journey has no input source")
    preferred = next(
        (s for s in sources if s.get("activityName") == "dwh_source"), sources[0]
    )
    engine = Engine(session)
    results = []
    for player_id in player_ids:
        try:
            activation = engine.enter(journey, preferred["activityId"], player_id)
            results.append({"playerId": player_id, "activationId": activation.id})
        except EngineError as error:
            results.append({"playerId": player_id, "error": error.slug})
    return {"journeyId": journey_id, "results": results}


# ── platform events ──────────────────────────────────────────────────


@router.post("/platform/v0/events", status_code=202)
def ingest_event(payload: dict = Body(...), session: Session = Depends(get_session)):
    event_name = payload.get("eventName")
    player_id = payload.get("playerId")
    if not event_name or not player_id:
        raise HTTPException(status_code=400, detail="eventName and playerId are required")
    engine = Engine(session)
    result = engine.ingest_platform_event(
        event_name,
        player_id,
        properties=payload.get("properties") or {},
        source_name=payload.get("sourceName", "platform"),
        # optional idempotency key: replays of the same eventId are
        # acknowledged but processed exactly once
        event_key=payload.get("eventId"),
    )
    return result


@router.post("/runtime/v0/timers/run")
def run_timers(session: Session = Depends(get_session)):
    """Fire every due timer now (the background scheduler does this on its
    own; the endpoint exists for tests and demos)."""
    fired = Engine(session).run_due_timers()
    return {"fired": fired}


# ── offers / comms interactions ──────────────────────────────────────


@router.post("/runtime/v0/offers/{offer_id}/accept")
def accept_offer(offer_id: int, session: Session = Depends(get_session)):
    offer = session.get(PromotionOffer, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail=f"offer {offer_id} not found")
    try:
        activation = Engine(session).accept_offer(offer)
    except EngineError as error:
        raise _engine_http(error)
    return {"offerId": offer.id, "status": offer.status, "activation": _serialize_activation(activation)}


@router.get("/runtime/v0/players/{player_id}/offers")
def list_offers(player_id: str, session: Session = Depends(get_session)):
    offers = (
        session.execute(
            select(PromotionOffer)
            .where(PromotionOffer.player_id == player_id)
            .order_by(PromotionOffer.id)
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "offerId": o.id,
                "activationId": o.activation_id,
                "activityId": o.activity_id,
                "status": o.status,
                "promotionDisplayId": o.promotion_display_id,
                "createdAt": o.created_at.isoformat() if o.created_at else None,
            }
            for o in offers
        ]
    }


@router.post("/runtime/v0/comms/{message_id}/{action}")
def engage_comms(
    message_id: int, action: str, session: Session = Depends(get_session)
):
    message = session.get(CommsMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail=f"message {message_id} not found")
    try:
        Engine(session).engage_comms(message, action)
    except EngineError as error:
        raise _engine_http(error)
    return {"messageId": message.id, "status": message.status}


@router.get("/runtime/v0/players/{player_id}/comms")
def list_comms(player_id: str, session: Session = Depends(get_session)):
    messages = (
        session.execute(
            select(CommsMessage)
            .where(CommsMessage.player_id == player_id)
            .order_by(CommsMessage.id)
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "messageId": m.id,
                "journeyId": m.journey_id,
                "activityId": m.activity_id,
                "channel": m.channel,
                "status": m.status,
                "body": m.body,
                "deliveryAttempts": m.delivery_attempts,
                "deliveryDetail": m.delivery_detail,
                "createdAt": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ]
    }


# ── observability ────────────────────────────────────────────────────


@router.get("/runtime/v0/journeys/{journey_id}/stats")
def journey_stats(journey_id: str, session: Session = Depends(get_session)):
    """The campaign view of a journey: who entered, where they are now,
    which transitions they took, and what the rewards cost so far."""
    _get_journey(session, journey_id)
    activations = (
        session.execute(
            select(JourneyActivation).where(
                JourneyActivation.journey_id == journey_id
            )
        )
        .scalars()
        .all()
    )

    per_activity: dict[str, dict] = {}

    def bucket(activity_id: str) -> dict:
        if activity_id not in per_activity:
            per_activity[activity_id] = {"entered": 0, "activeHere": 0, "events": {}}
        return per_activity[activity_id]

    totals = {"entered": 0, "active": 0, "completed": 0, "terminated": 0}
    for activation in activations:
        totals["entered"] += 1
        key = activation.status.lower()
        if key in totals:
            totals[key] += 1
        seen: set[str] = set()
        for event in activation.events_history or []:
            slot = bucket(event["activityId"])
            slot["events"][event["eventName"]] = (
                slot["events"].get(event["eventName"], 0) + 1
            )
            if event["activityId"] not in seen:
                seen.add(event["activityId"])
                slot["entered"] += 1
        if activation.status == "Active" and activation.current_activity_id:
            bucket(activation.current_activity_id)["activeHere"] += 1
    totals["completionRate"] = (
        round(totals["completed"] / totals["entered"], 4) if totals["entered"] else None
    )

    grants = (
        session.execute(
            select(RewardGrant).where(RewardGrant.journey_id == journey_id)
        )
        .scalars()
        .all()
    )
    spins_granted = sum(
        (g.detail or {}).get("spins") or 0 for g in grants if g.reward_type == "freespin_bonus"
    )
    comms_count = len(
        session.execute(
            select(CommsMessage.id).where(CommsMessage.journey_id == journey_id)
        ).all()
    )
    activation_ids = [a.id for a in activations]
    offers = (
        session.execute(
            select(PromotionOffer).where(
                PromotionOffer.activation_id.in_(activation_ids)
            )
        )
        .scalars()
        .all()
        if activation_ids
        else []
    )
    accepted = sum(1 for offer in offers if offer.status == "Accepted")

    return {
        "journeyId": journey_id,
        "totals": totals,
        "activities": per_activity,
        "rewards": {"grants": len(grants), "spinsGranted": spins_granted},
        "comms": {"sent": comms_count},
        "offers": {
            "presented": len(offers),
            "accepted": accepted,
            "acceptRate": round(accepted / len(offers), 4) if offers else None,
        },
    }


@router.get("/runtime/v0/activations/{activation_id}")
def read_activation(activation_id: int, session: Session = Depends(get_session)):
    activation = session.get(JourneyActivation, activation_id)
    if activation is None:
        raise HTTPException(status_code=404, detail=f"activation {activation_id} not found")
    return _serialize_activation(activation)


@router.get("/runtime/v0/journeys/{journey_id}/activations")
def list_activations(journey_id: str, session: Session = Depends(get_session)):
    activations = (
        session.execute(
            select(JourneyActivation)
            .where(JourneyActivation.journey_id == journey_id)
            .order_by(JourneyActivation.id)
        )
        .scalars()
        .all()
    )
    return {"items": [_serialize_activation(a) for a in activations]}


@router.get("/runtime/v0/players/{player_id}/rewards")
def list_rewards(player_id: str, session: Session = Depends(get_session)):
    grants = (
        session.execute(
            select(RewardGrant)
            .where(RewardGrant.player_id == player_id)
            .order_by(RewardGrant.id)
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "grantId": g.id,
                "journeyId": g.journey_id,
                "activityId": g.activity_id,
                "rewardType": g.reward_type,
                "status": g.status,
                "detail": g.detail,
                "deliveryAttempts": g.delivery_attempts,
                "deliveryDetail": g.delivery_detail,
                "expiresAt": g.expires_at.isoformat() if g.expires_at else None,
                "createdAt": g.created_at.isoformat() if g.created_at else None,
            }
            for g in grants
        ]
    }


@router.get("/runtime/v0/timers")
def list_timers(
    pending_only: bool = True, session: Session = Depends(get_session)
):
    query = select(Timer).order_by(Timer.due_at)
    if pending_only:
        query = query.where(Timer.fired.is_(False))
    timers = session.execute(query).scalars().all()
    return {
        "items": [
            {
                "timerId": t.id,
                "activationId": t.activation_id,
                "activityId": t.activity_id,
                "kind": t.kind,
                "dueAt": t.due_at.isoformat() if t.due_at else None,
                "fired": t.fired,
            }
            for t in timers
        ]
    }
