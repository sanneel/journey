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
    offer = _activity("promotion", ids["offer"], "Welcome offer",
                      {"autoAccept": True, "timeToAccept": "P0Y0M1DT0H0M0S"})
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


def _build_fiestas_patrias() -> dict[str, Any]:
    """The mid-September flagship — Fiestas Patrias ("el Dieciocho"):

    promo-page entry -> "Pase a la Fonda" offer (2 days to accept, terms attached)
      accepted -> deposit gate ($10.000+, 3 days)
        satisfied -> Ruleta de la Fonda (weighted random split)
            50%  Empanada  -> 50 freespins
            35%  Chicha    -> $10.000 freebet
            15%  Terremoto -> 100% reload bonus up to $100.000
          any prize -> "¡Ganaste en la fonda!" bell -> hold until the 18th
            -> VIP split -> $18.000 aguinaldo (money bonus) for high value
            -> both paths -> "Programa del 18" email -> end of journey
        unsatisfied -> reminder SMS -> end of path
      expired -> "la fonda te esperó" pop-up -> end of path
    """
    ids = {key: str(uuid.uuid4()) for key in (
        "src", "offer", "expired_note", "end_expired", "gate", "reminder",
        "end_reminder", "ruleta", "spins", "fbet", "recarga", "win_note",
        "hold18", "vip_split", "aguinaldo", "email", "end_journey",
    )}

    src = _activity("external_system_source", ids["src"], "Promo page entry", {
        "targetSystem": "PromoPage",
        "description": "Fiestas Patrias landing page routes players here",
    })
    offer = _activity("promotion", ids["offer"], "Pase a la Fonda", {
        "autoAccept": False,
        "timeToAccept": "P0Y0M2DT0H0M0S",
        "channelsCondition": {"values": [], "isEnabled": False},
        "languages": ["es"],
        "terms": "Válido del 12 al 19 de septiembre. Depósito mínimo $10.000 CLP. "
                 "Un premio por jugador. Giros y freebets expiran a los 3 días; "
                 "bono de recarga con rollover x25. Juega responsablemente.",
    })
    expired_note = _activity("notification_center", ids["expired_note"], "La fonda te esperó (pop-up)", {
        "contract": 5,  # 5 = pop-up, 1 = bell
        "templates": {"es": "tmpl-fonda-expired"},
    })
    gate = _activity("deposit", ids["gate"], "Depósito dieciochero $10.000+", {
        "depositConditions": {
            "expirationTimeout": "P0Y0M3DT0H0M0S",
            "minDepositAmounts": [{"brand": "JBCL", "amount": 10000, "currencyCode": "CLP"}],
            "depositAccountingType": "Any",
            "payGroups": [{"names": [], "currencyCode": "CLP"}],
            "channelsCondition": {"values": [], "isEnabled": False},
        },
    })
    reminder = _activity("dextra_sms", ids["reminder"], "Deposit reminder SMS", {
        "rawValues": {"messageText": "La fonda ya está armada — deposita $10.000 y gira la ruleta del 18."},
        "smsSettings": {},
    })
    ruleta = _activity("random_split", ids["ruleta"], "Ruleta de la Fonda", {
        "paths": [
            {"pathName": "Empanada — 50 giros", "probability": 50},
            {"pathName": "Chicha — freebet $10.000", "probability": 35},
            {"pathName": "Terremoto — 100% recarga", "probability": 15},
        ],
        "pathesConfig": [
            {"pathId": "path1", "pathName": "Empanada — 50 giros",
             "events": [{"eventName": "RandomSplitPassedPath1", "eventType": "Completion",
                         "eventDisplayName": "Empanada"}]},
            {"pathId": "path2", "pathName": "Chicha — freebet $10.000",
             "events": [{"eventName": "RandomSplitPassedPath2", "eventType": "Completion",
                         "eventDisplayName": "Chicha"}]},
            {"pathId": "path3", "pathName": "Terremoto — 100% recarga",
             "events": [{"eventName": "RandomSplitPassedPath3", "eventType": "Completion",
                         "eventDisplayName": "Terremoto"}]},
        ],
    })
    spins = _activity("freespin_bonus", ids["spins"], "Empanada — 50 freespins", {
        "freespinActivity": {
            "spins": 50, "provider": "jugabet-games",
            "lobbyGameId": "jugabet-games-fiesta-dieciochera",
            "spinsExpirationDuration": 259200000,  # 3 days
        },
        "allowReject": False,
    })
    fbet = _activity("freebet", ids["fbet"], "Chicha — freebet $10.000", {
        "properties": {
            "amount": 10000, "currencyCode": "CLP",
            "expireInDays": 3, "minOdd": 1.5,
        },
    })
    recarga = _activity("casino_bonus_v2", ids["recarga"], "Terremoto — 100% recarga", {
        "activitySubtype": "Deposit",
        "productType": "Casino",
        "bonusPercent": 100,
        "wageringRequirement": 25,
        "limitType": "Fixed",
        "bonusExpirationTime": 604800000,  # 7 days
        "currenciesConfig": [{"currencyCode": "CLP", "maxBonusAmount": 100000}],
        "allowReject": False,
    })
    win_note = _activity("notification_center", ids["win_note"], "¡Ganaste en la fonda! (bell)", {
        "contract": 1,
        "templates": {"es": "tmpl-fonda-prize"},
    })
    hold18 = _activity("wait_date", ids["hold18"], "Hasta el 18 de septiembre", {
        "waitTo": "2026-09-18T15:00:00Z",  # noon in Chile on the Dieciocho
        "waitStrategy": "Wait",
        "timezoneMode": "Journey",
    })
    vip_split = _activity("ams_decision_split", ids["vip_split"], "VIP del Dieciocho", {
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
    aguinaldo = _activity("money_bonus", ids["aguinaldo"], "Aguinaldo $18.000", {
        "currencyAmounts": [{"amount": 18000, "currencyCode": "CLP"}],
        "transactionTitle": "Aguinaldo Fiestas Patrias",
        "amountAccrualType": "Fixed",
    })
    email = _activity("dextra_email", ids["email"], "Programa del 18 (email)", {
        "emailSettings": {"contentId": "CSE-0-10018"},
    })
    end_journey = _activity("end_of_journey", ids["end_journey"])
    end_expired = _activity("end_of_path", ids["end_expired"])
    end_reminder = _activity("end_of_path", ids["end_reminder"])

    _wire(src, "PlayerAdded", ids["offer"])
    _wire(offer, "PromotionAccepted", ids["gate"])
    _wire(offer, "PromotionExpired", ids["expired_note"])
    _wire(expired_note, "NotificationSent", ids["end_expired"])
    _wire(gate, "DepositConditionSatisfied", ids["ruleta"])
    _wire(gate, "DepositConditionUnsatisfied", ids["reminder"])
    _wire(reminder, "SuccessSmsSend", ids["end_reminder"])
    _wire(ruleta, "RandomSplitPassedPath1", ids["spins"])
    _wire(ruleta, "RandomSplitPassedPath2", ids["fbet"])
    _wire(ruleta, "RandomSplitPassedPath3", ids["recarga"])
    _wire(spins, "FreespinBonusCollectingFinished", ids["win_note"])
    _wire(fbet, "PlayerFreebetUsed", ids["win_note"])
    _wire(recarga, "WageringBonusFinished", ids["win_note"])
    _wire(win_note, "NotificationSent", ids["hold18"])
    _wire(hold18, "WaitTimeCompleted", ids["vip_split"])
    _wire(vip_split, "DecisionSplitPassedPath01", ids["aguinaldo"])
    _wire(vip_split, "DecisionSplitPassedRemainderPath", ids["email"])
    _wire(aguinaldo, "MoneyBonusAccrued", ids["email"])
    _wire(email, "SuccessEmailSend", ids["end_journey"])

    return _body("JBCL | PROMO | Fiestas Patrias — La Gran Fonda 12–19.09", [
        src, offer, expired_note, gate, reminder, ruleta, spins, fbet, recarga,
        win_note, hold18, vip_split, aguinaldo, email,
        end_journey, end_expired, end_reminder,
    ])


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
    "fiestas_patrias": {
        "name": "Fiestas Patrias — La Gran Fonda",
        "description": "Mid-September flagship: opt-in offer with T&C, "
                       "$10.000 deposit gate, weighted prize roulette "
                       "(50 freespins / $10.000 freebet / 100% reload), "
                       "prize bell, hold until the 18th, then a VIP "
                       "$18.000 aguinaldo and the Programa del 18 email; "
                       "SMS reminder and expiry pop-up on the failure paths.",
        "build": _build_fiestas_patrias,
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
