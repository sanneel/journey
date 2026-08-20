"""Journey templates — ready-made, runnable campaign shapes.

A template is a factory that builds a complete draft body with FRESH
activity ids on every instantiation, so two journeys created from the
same template never collide on the brand-wide activity-id registry.

The shapes follow the captured campaign patterns of the imitated
platform: an offer gated by a deposit, value-based reward tiers via a
decision split, comms after the reward, and a delayed follow-up.
"""
from __future__ import annotations

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


def list_templates() -> list[dict[str, Any]]:
    items = []
    for key, template in TEMPLATES.items():
        body = template["build"]()
        items.append({
            "key": key,
            "name": template["name"],
            "description": template["description"],
            "activities": len(body["activities"]),
            "journeyName": body["journeyName"],
        })
    return items


def instantiate(key: str) -> dict[str, Any] | None:
    template = TEMPLATES.get(key)
    if template is None:
        return None
    build: Callable[[], dict[str, Any]] = template["build"]
    return build()  # fresh uuids on every call
