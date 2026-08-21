"""Journey templates — ready-made, runnable campaign shapes.

A template is a factory that builds a complete draft body with FRESH
activity ids on every instantiation, so two journeys created from the
same template never collide on the brand-wide activity-id registry.

The shapes follow the captured campaign patterns of the imitated
platform: an offer gated by a deposit, value-based reward tiers via a
decision split, comms after the reward, and a delayed follow-up.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any, Callable

from .catalog import ACTIVITY_TYPES


def _activity(
    name: str,
    activity_id: str,
    display_name: str | None = None,
    init: dict | None = None,
) -> dict[str, Any]:
    """Build an activity envelope with the type's full event vocabulary
    (unwired events carry nextActivityId: null, like the wire format)."""
    spec = ACTIVITY_TYPES[name]
    events: list[dict[str, Any]] = []
    for event_name in spec["activation"]:
        events.append({"eventName": event_name, "eventType": "Activation", "nextActivityId": None})
    for event_name in spec["completion"]:
        events.append({"eventName": event_name, "eventType": "Completion", "nextActivityId": None})
    return {
        "activityId": activity_id,
        "activityName": name,
        "activityDisplayName": display_name or spec["label"],
        "events": events,
        "dependencies": [],
        "dataDependencies": [],
        "initializationData": init or {},
    }


def _wire(activity: dict, event_name: str, target_id: str) -> None:
    for event in activity["events"]:
        if event["eventName"] == event_name:
            event["nextActivityId"] = target_id
            return
    raise KeyError(f"{activity['activityName']} does not emit {event_name}")


def _body(name_hint: str, activities: list[dict], brand: str = "JBCL") -> dict[str, Any]:
    return {
        "journeyName": name_hint,
        "brand": brand,
        "currencyCodes": ["CLP"],
        "timeZoneId": "Chile/Continental",
        "isImmediatelyAfterPublish": True,
        "isUnlimited": True,
        "reEntryRule": {"reEntryMode": "Prohibited"},
        "activities": activities,
        "rawJourneyData": {
            "elements": [],  # no saved positions -> the builder auto-lays-out
            "activitiesConfiguration": {
                a["activityId"]: {"displayName": a["activityDisplayName"]}
                for a in activities
            },
            "infoValues": {"journeyName": name_hint},
        },
    }


def _build_promotion() -> dict[str, Any]:
    """The full promotion campaign shape:

    API entry -> promotion offer (1 day to accept)
      accepted -> deposit gate ($100+, 1 day)
        satisfied -> value split -> 100 FS (premium) / 30 FS (standard)
                       -> "you won" notification -> wait 1 day
                       -> follow-up email -> end of journey
        unsatisfied -> reminder SMS -> end of path
      expired -> "offer expired" pop-up -> end of path
    """
    ids = {key: str(uuid.uuid4()) for key in (
        "src", "offer", "expired_note", "gate", "reminder", "split",
        "premium", "standard", "win_note", "wait", "email",
        "end_journey", "end_expired", "end_reminder",
    )}

    src = _activity("external_system_source", ids["src"], "API entry", {
        "targetSystem": "Randomizer",
        "description": "Promo page / randomizer prize routes players here",
    })
    offer = _activity("promotion", ids["offer"], "Promotion offer", {
        "autoAccept": False,
        "timeToAccept": "P0Y0M1DT0H0M0S",
        "channelsCondition": {"values": [], "isEnabled": False},
        "languages": ["es", "en"],
        # every promotion carries its visual — the promo card the player sees
        "visual": {
            "headerColor": "#175a41",
            "accentColor": "#96752b",
            "title": "Oferta del mes",
            "subtitle": "Deposita $100+ y llévate tu recompensa",
        },
    })
    expired_note = _activity("notification_center", ids["expired_note"], "Offer expired pop-up", {
        "contract": 5,  # 5 = pop-up, 1 = bell
        "templates": {"es": "tmpl-offer-expired"},
    })
    gate = _activity("deposit", ids["gate"], "Qualifying deposit $100+", {
        "depositConditions": {
            "expirationTimeout": "P0Y0M1DT0H0M0S",
            "minDepositAmounts": [{"brand": "JBCL", "amount": 10000, "currencyCode": "CLP"}],
            "depositAccountingType": "Any",
            "payGroups": [{"names": [], "currencyCode": "CLP"}],
            "channelsCondition": {"values": [], "isEnabled": False},
        },
    })
    reminder = _activity("dextra_sms", ids["reminder"], "Deposit reminder SMS", {
        "rawValues": {"messageText": "Tu bono te espera — deposita hoy y gira."},
        "smsSettings": {},
    })
    split = _activity("ams_decision_split", ids["split"], "Player value split", {
        "rules": [{
            "name": "high value",
            "filter": {
                "property": {"name": "playerValue", "type": "number", "value": "100", "operator": "gte"},
                "variables": [],
            },
        }],
        "remainder": {"name": "standard"},
        "pathesConfig": [{
            "events": [{"eventName": "DecisionSplitPassedPath01", "eventType": "Completion",
                        "eventDisplayName": "high value"}],
            "pathId": "path1", "pathName": "high value",
        }],
    })
    premium = _activity("freespin_bonus", ids["premium"], "Premium — 100 freespins", {
        "freespinActivity": {
            "spins": 100, "provider": "jugabet-games",
            "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
            "spinsExpirationDuration": 86400000,
        },
        "allowReject": False,
    })
    standard = _activity("freespin_bonus", ids["standard"], "Standard — 30 freespins", {
        "freespinActivity": {
            "spins": 30, "provider": "jugabet-games",
            "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
            "spinsExpirationDuration": 86400000,
        },
        "allowReject": False,
    })
    win_note = _activity("notification_center", ids["win_note"], "You won! (bell)", {
        "contract": 1,
        "templates": {"es": "tmpl-reward-granted"},
    })
    wait = _activity("wait_interval", ids["wait"], "Wait 1 day", {
        "waitPeriod": "P0Y0M1DT0H0M0S",
    })
    email = _activity("dextra_email", ids["email"], "Follow-up email", {
        "emailSettings": {"contentId": "CSE-0-10001"},
    })
    end_journey = _activity("end_of_journey", ids["end_journey"])
    end_expired = _activity("end_of_path", ids["end_expired"])
    end_reminder = _activity("end_of_path", ids["end_reminder"])

    _wire(src, "PlayerAdded", ids["offer"])
    _wire(offer, "PromotionAccepted", ids["gate"])
    _wire(offer, "PromotionExpired", ids["expired_note"])
    _wire(expired_note, "NotificationSent", ids["end_expired"])
    _wire(gate, "DepositConditionSatisfied", ids["split"])
    _wire(gate, "DepositConditionUnsatisfied", ids["reminder"])
    _wire(reminder, "SuccessSmsSend", ids["end_reminder"])
    _wire(split, "DecisionSplitPassedPath01", ids["premium"])
    _wire(split, "DecisionSplitPassedRemainderPath", ids["standard"])
    _wire(premium, "FreespinBonusCollectingFinished", ids["win_note"])
    _wire(standard, "FreespinBonusCollectingFinished", ids["win_note"])
    _wire(win_note, "NotificationSent", ids["wait"])
    _wire(wait, "WaitTimeCompleted", ids["email"])
    _wire(email, "SuccessEmailSend", ids["end_journey"])

    return _body("JBCL | PROMO | promotion campaign", [
        src, offer, expired_note, gate, reminder, split, premium, standard,
        win_note, wait, email, end_journey, end_expired, end_reminder,
    ])


def _build_welcome_freespins() -> dict[str, Any]:
    """The small starter flow: offer -> deposit -> freespins -> notify."""
    ids = {key: str(uuid.uuid4()) for key in (
        "src", "offer", "gate", "spins", "notify", "end", "sorry",
    )}
    src = _activity("external_system_source", ids["src"], "API entry",
                    {"targetSystem": "Randomizer"})
    offer = _activity("promotion", ids["offer"], "Welcome offer", {
        "autoAccept": True,
        "timeToAccept": "P0Y0M1DT0H0M0S",
        "visual": {
            "headerColor": "#2d6c9e",
            "accentColor": "#96752b",
            "title": "Bienvenida con giros",
            "subtitle": "30 giros gratis por tu primer depósito",
        },
    })
    gate = _activity("deposit", ids["gate"], "Deposit $100+", {
        "depositConditions": {
            "expirationTimeout": "P0Y0M1DT0H0M0S",
            "minDepositAmounts": [{"brand": "JBCL", "amount": 10000, "currencyCode": "CLP"}],
            "depositAccountingType": "Any",
        },
    })
    spins = _activity("freespin_bonus", ids["spins"], "30 freespins", {
        "freespinActivity": {"spins": 30, "provider": "jugabet-games",
                             "spinsExpirationDuration": 86400000},
    })
    notify = _activity("notification_center", ids["notify"], "You won!",
                       {"contract": 1, "templates": {}})
    end = _activity("end_of_journey", ids["end"])
    sorry = _activity("end_of_path", ids["sorry"])

    _wire(src, "PlayerAdded", ids["offer"])
    _wire(offer, "PromotionAccepted", ids["gate"])
    _wire(offer, "PromotionExpired", ids["sorry"])
    _wire(gate, "DepositConditionSatisfied", ids["spins"])
    _wire(gate, "DepositConditionUnsatisfied", ids["sorry"])
    _wire(spins, "FreespinBonusCollectingFinished", ids["notify"])
    _wire(notify, "NotificationSent", ids["end"])

    return _body("JBCL | SAMPLE | welcome freespins",
                 [src, offer, gate, spins, notify, end, sorry])


TEMPLATES: dict[str, dict[str, Any]] = {
    "promotion": {
        "name": "Promotion campaign",
        "description": "Offer with 1-day accept window, $100 deposit gate, "
                       "player-value reward tiers (100/30 freespins), reward "
                       "notification, next-day follow-up email; SMS reminder "
                       "and expiry pop-up on the failure paths.",
        "build": _build_promotion,
    },
    "welcome_freespins": {
        "name": "Welcome freespins",
        "description": "Small starter: auto-accepted offer, deposit gate, "
                       "30 freespins, on-site notification.",
        "build": _build_welcome_freespins,
    },
}


def list_templates(session=None) -> list[dict[str, Any]]:
    """Built-in shapes first, then the brand's own saved templates."""
    items = []
    for key, template in TEMPLATES.items():
        body = template["build"]()
        items.append({
            "key": key,
            "name": template["name"],
            "description": template["description"],
            "activities": len(body["activities"]),
            "journeyName": body["journeyName"],
            "custom": False,
        })
    if session is not None:
        from sqlalchemy import select

        from .models import JourneyTemplate

        for row in session.execute(
            select(JourneyTemplate).order_by(JourneyTemplate.id)
        ).scalars():
            items.append({
                "key": row.key,
                "name": row.name,
                "description": row.description or "",
                "activities": len(row.body.get("activities", [])),
                "journeyName": row.body.get("journeyName", row.name),
                "custom": True,
                "brand": row.brand,
                "createdBy": row.created_by,
            })
    return items


def instantiate(key: str, session=None) -> dict[str, Any] | None:
    template = TEMPLATES.get(key)
    if template is not None:
        build: Callable[[], dict[str, Any]] = template["build"]
        return build()  # fresh uuids on every call
    if session is None:
        return None
    from sqlalchemy import select

    from .ids import regenerate_structural_ids
    from .models import JourneyTemplate

    row = session.execute(
        select(JourneyTemplate).where(JourneyTemplate.key == key)
    ).scalar_one_or_none()
    if row is None:
        return None
    # every instantiation gets fresh structural ids — two drafts made from
    # the same saved template never collide on the activity-id registry
    body, _ = regenerate_structural_ids(copy.deepcopy(row.body))
    return body


def sanitize_template_body(body: dict) -> dict:
    """Make a live journey body storable as a template: drop identity,
    lineage and server-minted fields so nothing collides on reuse. The
    canvas positions and every visual stay — the design IS the template."""
    from .cloner import blank_campaign_ids, strip_promotion_display_ids

    payload = copy.deepcopy(body)
    for key in (
        "journeyId", "reservedJourneyId", "duplicatedFromId",
        "duplicatedFromVersion", "status", "version", "createdAt",
        "changedAt", "changeHistory", "author", "allJourneyActivationsCount",
        "overJourneyActivationsCount", "areJourneyMetricsAvailable",
        "activityEventConversionMetrics", "terminatedAt", "isArchived",
    ):
        payload.pop(key, None)
    strip_promotion_display_ids(payload)
    blank_campaign_ids(payload)
    # webhook ids are minted per journey at publish
    for activity in payload.get("activities", []):
        (activity.get("initializationData") or {}).pop("webhookId", None)
    return payload


def slugify_key(session, name: str) -> str:
    from sqlalchemy import select

    from .models import JourneyTemplate

    base = "".join(
        ch if ch.isalnum() else "-" for ch in name.strip().lower()
    ).strip("-") or "template"
    base = "-".join(part for part in base.split("-") if part)[:60]
    candidate = base
    suffix = 2
    while (
        candidate in TEMPLATES
        or session.execute(
            select(JourneyTemplate.id).where(JourneyTemplate.key == candidate)
        ).first()
        is not None
    ):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
