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


# ── Big Promo September (the "Big Promo August" architecture) ────────
#
# One journey per promo day plus two scratch-card journeys, following the
# captured campaign family:
#   JBCL | CS | Big Promo - August | Bonuses - 15.08
#   JBCL | CS | Big promo August | Scratch Card | ...
#
# Mechanic: the promo page routes every visitor in with a `bonusOption`
# attribute (1-4). Each option is a deposit-gated free-spin bonus; after
# the first bonus lands, an event detector waits for a SECOND deposit of
# the day — two deposits unlock the Special Card journey through a
# campaign connector. Players who never deposit are routed to the plan-B
# scratch card instead.

# tier: (option, spins, bet/spin, bonus amount, min dep, provider, lobby game)
_BIG_PROMO_TIERS = [
    (1, 20, 400, 8000, 10000, "jugabet-games", "jugabet-games-la-gran-copa-jugabet"),
    (2, 20, 600, 12000, 15000, "tada", "tada-fortune-gems-2"),
    (3, 40, 600, 24000, 30000, "endorphina", "endorphina-fortune-chests"),
    (4, 60, 800, 48000, 50000, "playson", "playson-4-pots-riches-hold-and-win"),
]


def _big_promo_freespin_init(spins: int, bet: int, bonus_amount: int,
                             provider: str, game: str,
                             contribution: float = 0.8) -> dict[str, Any]:
    """The brief's full bonus sheet travels with the activity; the engine
    reads freespinActivity, the rest documents the offer for the ops team."""
    return {
        "freespinActivity": {
            "spins": spins, "provider": provider, "lobbyGameId": game,
            "betPerSpin": bet,
            "spinsExpirationDuration": 86400000,  # 1 day to activate
        },
        "bonusTerms": {
            "bonusAmount": bonus_amount, "maxBonusAmount": 200000,
            "contribution": contribution, "cashout": 20, "maxWin": 4000000,
            "wager": 30, "wageringDays": 3,
        },
        "allowReject": False,
    }


def _build_big_promo_day() -> dict[str, Any]:
    """One promo day of Big Promo September:

    promo-page entry (bonusOption attribute set by the promo page)
      -> decision split on bonusOption (remainder -> Bonus N1)
        N1: dep $10.000 -> 20 FS   N2: dep $15.000 -> 20 FS
        N3: dep $30.000 -> 40 FS   N4: dep $50.000 -> 60 FS
      any bonus -> "bonus credited" bell
        -> detector: 2nd deposit ($10.000+) within the day
             success -> campaign connector -> Special Card journey
             failed  -> "one more deposit" pop-up -> end
      no deposit -> reminder SMS -> campaign connector -> plan-B scratch card
    """
    ids = {key: str(uuid.uuid4()) for key in (
        "src", "split",
        "offer1", "gate1", "spins1", "offer2", "gate2", "spins2",
        "offer3", "gate3", "spins3", "offer4", "gate4", "spins4",
        "bell", "detector", "sc_conn", "nudge", "sms", "pb_conn",
        "end_sc", "end_nudge", "end_pb",
    )}

    src = _activity("external_system_source", ids["src"], "Promo page entry", {
        "targetSystem": "PromoPage",
        "description": "Big Promo page routes visitors here with bonusOption 1-4",
    })
    split = _activity("ams_decision_split", ids["split"], "Bonus option split", {
        "rules": [{
            "name": f"option {option}",
            "filter": {
                "property": {"name": "bonusOption", "type": "number",
                             "value": str(option), "operator": "eq"},
                "variables": [],
            },
        } for option in (4, 3, 2)],
        "remainder": {"name": "option 1"},
        "pathesConfig": [{
            "events": [{"eventName": f"DecisionSplitPassedPath{position:02d}",
                        "eventType": "Completion",
                        "eventDisplayName": f"option {option}"}],
            "pathId": f"path{position}", "pathName": f"option {option}",
        } for position, option in ((1, 4), (2, 3), (3, 2))],
    })

    legs: dict[int, tuple[dict, dict, dict]] = {}
    for option, spins_n, bet, bonus_amount, min_dep, provider, game in _BIG_PROMO_TIERS:
        contribution = 0.96 if option == 4 else 0.8
        offer = _activity("promotion", ids[f"offer{option}"],
                          f"Bono N{option} — {spins_n} FS por ${min_dep:,}".replace(",", "."), {
            "autoAccept": True,
            "timeToAccept": "P0Y0M1DT0H0M0S",
            "languages": ["es"],
            "terms": f"Deposita ${min_dep:,} CLP o más dentro del día y recibe "
                     f"{spins_n} giros gratis. 1 día para activar; rollover x30 "
                     f"en 3 días; cashout x20; ganancia máxima $4.000.000 CLP. "
                     f"Juega responsablemente.".replace(",", "."),
        })
        gate = _activity("deposit", ids[f"gate{option}"],
                         f"Depósito ${min_dep:,}+".replace(",", "."), {
            "depositConditions": {
                "expirationTimeout": "P0Y0M1DT0H0M0S",
                "minDepositAmounts": [{"brand": "JBCL", "amount": min_dep,
                                       "currencyCode": "CLP"}],
                "depositAccountingType": "Any",
                "payGroups": [{"names": [], "currencyCode": "CLP"}],
                "channelsCondition": {"values": [], "isEnabled": False},
            },
        })
        spins = _activity("freespin_bonus", ids[f"spins{option}"],
                          f"N{option} — {spins_n} freespins",
                          _big_promo_freespin_init(spins_n, bet, bonus_amount,
                                                   provider, game, contribution))
        legs[option] = (offer, gate, spins)

    bell = _activity("notification_center", ids["bell"], "Bonus credited (bell)", {
        "contract": 1,
        "templates": {"es": "tmpl-big-promo-bonus"},
    })
    detector = _activity("event_detector", ids["detector"], "2nd deposit of the day", {
        "properties": {
            "startingOptions": {"durationTime": "P0Y0M1DT0H0M0S"},
            "subscriptionOptions": [{
                "event": {"eventName": "deposit.approved",
                          "sourceName": "platform.orders"},
                "filter": {
                    "property": {"name": "amount", "type": "number",
                                 "value": "10000", "operator": "gte"},
                    "variables": [{"name": "currencyCode", "type": "currency",
                                   "value": "CLP"}],
                },
            }],
        },
    })
    sc_conn = _activity("campaign_connector", ids["sc_conn"], "To Special Card", {
        "currencyMode": "automated",
        "campaignConnectorConditions": {
            "campaignId": "",
            "activityData": {"HostJourneyId": ""},  # link the Special Card JRN here
            "campaignProductType": "Journey",
        },
    })
    nudge = _activity("notification_center", ids["nudge"], "One more deposit (pop-up)", {
        "contract": 5,
        "templates": {"es": "tmpl-big-promo-nudge"},
    })
    sms = _activity("dextra_sms", ids["sms"], "No-deposit reminder SMS", {
        "rawValues": {"messageText": "4 bonos de giros te esperan hoy en la Gran "
                                     "Promo — deposita $10.000 y llévate el primero."},
        "smsSettings": {},
    })
    pb_conn = _activity("campaign_connector", ids["pb_conn"], "To plan-B scratch card", {
        "currencyMode": "automated",
        "campaignConnectorConditions": {
            "campaignId": "",
            "activityData": {"HostJourneyId": ""},  # link the plan-B JRN here
            "campaignProductType": "Journey",
        },
    })
    end_sc = _activity("end_of_journey", ids["end_sc"])
    end_nudge = _activity("end_of_path", ids["end_nudge"])
    end_pb = _activity("end_of_path", ids["end_pb"])

    _wire(src, "PlayerAdded", ids["split"])
    _wire(split, "DecisionSplitPassedPath01", ids["offer4"])
    _wire(split, "DecisionSplitPassedPath02", ids["offer3"])
    _wire(split, "DecisionSplitPassedPath03", ids["offer2"])
    _wire(split, "DecisionSplitPassedRemainderPath", ids["offer1"])
    for option, (offer, gate, spins) in legs.items():
        _wire(offer, "PromotionAccepted", ids[f"gate{option}"])
        _wire(gate, "DepositConditionSatisfied", ids[f"spins{option}"])
        _wire(gate, "DepositConditionUnsatisfied", ids["sms"])
        _wire(spins, "FreespinBonusCollectingFinished", ids["bell"])
    _wire(bell, "NotificationSent", ids["detector"])
    _wire(detector, "DetectorSuccess", ids["sc_conn"])
    _wire(detector, "DetectorFailed", ids["nudge"])
    _wire(sc_conn, "PlayerAddedToCampaign", ids["end_sc"])
    _wire(sc_conn, "PlayerNotAddedToCampaign", ids["end_sc"])
    _wire(nudge, "NotificationSent", ids["end_nudge"])
    _wire(sms, "SuccessSmsSend", ids["pb_conn"])
    _wire(pb_conn, "PlayerAddedToCampaign", ids["end_pb"])
    _wire(pb_conn, "PlayerNotAddedToCampaign", ids["end_pb"])

    activities = [src, split]
    for option in (1, 2, 3, 4):
        activities.extend(legs[option])
    activities += [bell, detector, sc_conn, nudge, sms, pb_conn,
                   end_sc, end_nudge, end_pb]
    return _body("JBCL | CS | Big Promo - September | Bonuses - 18.09", activities)


def _build_big_promo_scratch(plan_b: bool = False) -> dict[str, Any]:
    """The Special Card / plan-B scratch card journey:

    scratch page entry -> weighted prize split
      FS with deposit    (10% / plan B 48%): dep $10.000 -> 20 FS
      casino dep bonus   (10% / plan B 48%): dep $10.000 -> 50% up to $200.000
      FS without deposit (80% / plan B  4%): 20 FS, no wagering
    any prize -> "you won" bell -> end
    """
    ids = {key: str(uuid.uuid4()) for key in (
        "src", "split", "offer_fs", "gate_fs", "spins_dep",
        "offer_db", "gate_db", "dep_bonus", "spins_free",
        "bell", "end", "end_miss",
    )}
    chances = (48, 48, 4) if plan_b else (10, 10, 80)
    flavour = "Plan-B scratch card" if plan_b else "Special Card"

    src = _activity("external_system_source", ids["src"], f"{flavour} entry", {
        "targetSystem": "ScratchCard",
        "description": f"{flavour} page scratches here",
    })
    split = _activity("random_split", ids["split"], f"{flavour} prizes", {
        "paths": [
            {"pathName": "Free spins with deposit", "probability": chances[0]},
            {"pathName": "Casino deposit bonus", "probability": chances[1]},
            {"pathName": "Free spins without deposit", "probability": chances[2]},
        ],
        "pathesConfig": [],
    })
    offer_fs = _activity("promotion", ids["offer_fs"], "Prize: 20 FS for deposit", {
        "autoAccept": True,
        "timeToAccept": "P0Y0M1DT0H0M0S",
        "languages": ["es"],
        "terms": "Deposita $10.000 CLP dentro del día y recibe 20 giros gratis. "
                 "Rollover x30 en 3 días. Juega responsablemente.",
    })
    gate_fs = _activity("deposit", ids["gate_fs"], "Depósito $10.000+", {
        "depositConditions": {
            "expirationTimeout": "P0Y0M1DT0H0M0S",
            "minDepositAmounts": [{"brand": "JBCL", "amount": 10000,
                                   "currencyCode": "CLP"}],
            "depositAccountingType": "Any",
        },
    })
    spins_dep = _activity("freespin_bonus", ids["spins_dep"], "20 freespins (dep)",
                          _big_promo_freespin_init(20, 400, 8000, "jugabet-games",
                                                   "jugabet-games-la-gran-copa-jugabet"))
    offer_db = _activity("promotion", ids["offer_db"], "Prize: 50% deposit bonus", {
        "autoAccept": True,
        "timeToAccept": "P0Y0M1DT0H0M0S",
        "languages": ["es"],
        "terms": "Deposita $10.000 CLP dentro del día y recibe un bono del 50% "
                 "hasta $200.000 CLP. Rollover x30 en 3 días. Juega responsablemente.",
    })
    gate_db = _activity("deposit", ids["gate_db"], "Depósito $10.000+", {
        "depositConditions": {
            "expirationTimeout": "P0Y0M1DT0H0M0S",
            "minDepositAmounts": [{"brand": "JBCL", "amount": 10000,
                                   "currencyCode": "CLP"}],
            "depositAccountingType": "Any",
        },
    })
    dep_bonus = _activity("casino_bonus_v2", ids["dep_bonus"], "50% deposit bonus", {
        "activitySubtype": "Deposit",
        "productType": "Casino",
        "bonusPercent": 50,
        "wageringRequirement": 30,
        "limitType": "Fixed",
        "bonusExpirationTime": 259200000,  # 3 days for wagering
        "currenciesConfig": [{"currencyCode": "CLP", "maxBonusAmount": 200000}],
        "allowReject": False,
    })
    spins_free = _activity("freespin_bonus", ids["spins_free"], "20 freespins (no dep)", {
        "freespinActivity": {
            "spins": 20, "provider": "tada", "lobbyGameId": "tada-fortune-gems-2",
            "betPerSpin": 60,
            "spinsExpirationDuration": 86400000,
        },
        "bonusTerms": {"maxBonusAmount": 50000, "cashout": 5, "maxWin": 250000,
                       "wager": 0},
        "allowReject": False,
    })
    bell = _activity("notification_center", ids["bell"], "You won! (bell)", {
        "contract": 1,
        "templates": {"es": "tmpl-scratch-prize"},
    })
    end = _activity("end_of_journey", ids["end"])
    end_miss = _activity("end_of_path", ids["end_miss"])

    _wire(src, "PlayerAdded", ids["split"])
    _wire(split, "RandomSplitPassedPath1", ids["offer_fs"])
    _wire(split, "RandomSplitPassedPath2", ids["offer_db"])
    _wire(split, "RandomSplitPassedPath3", ids["spins_free"])
    _wire(offer_fs, "PromotionAccepted", ids["gate_fs"])
    _wire(gate_fs, "DepositConditionSatisfied", ids["spins_dep"])
    _wire(gate_fs, "DepositConditionUnsatisfied", ids["end_miss"])
    _wire(offer_db, "PromotionAccepted", ids["gate_db"])
    _wire(gate_db, "DepositConditionSatisfied", ids["dep_bonus"])
    _wire(gate_db, "DepositConditionUnsatisfied", ids["end_miss"])
    _wire(spins_dep, "FreespinBonusCollectingFinished", ids["bell"])
    _wire(dep_bonus, "WageringBonusFinished", ids["bell"])
    _wire(spins_free, "FreespinBonusCollectingFinished", ids["bell"])
    _wire(bell, "NotificationSent", ids["end"])

    suffix = "Scratch Card Plan B" if plan_b else "Special Card"
    return _body(f"JBCL | CS | Big Promo - September | {suffix} - 18.09", [
        src, split, offer_fs, gate_fs, spins_dep, offer_db, gate_db,
        dep_bonus, spins_free, bell, end, end_miss,
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
    "big_promo_day": {
        "name": "Big Promo — day of bonuses",
        "description": "One Big Promo day (the Big Promo August shape): promo-page "
                       "entry split on bonusOption 1-4, four deposit-gated "
                       "free-spin bonuses ($10/15/30/50k -> 20/20/40/60 FS), "
                       "2nd-deposit detector unlocking the Special Card via "
                       "campaign connector, plan-B scratch-card connector and "
                       "reminder SMS for non-depositors. Link both connectors' "
                       "HostJourneyId after creating the scratch-card journeys.",
        "build": _build_big_promo_day,
    },
    "big_promo_special_card": {
        "name": "Big Promo — Special Card",
        "description": "The two-deposit reward scratch card: 10% 20 FS for "
                       "deposit, 10% 50% deposit bonus, 80% 20 FS no deposit.",
        "build": lambda: _build_big_promo_scratch(plan_b=False),
    },
    "big_promo_plan_b": {
        "name": "Big Promo — plan-B scratch card",
        "description": "The consolation scratch card for players who skipped the "
                       "main offer: 48% 20 FS for deposit, 48% 50% deposit "
                       "bonus, 4% 20 FS no deposit.",
        "build": lambda: _build_big_promo_scratch(plan_b=True),
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
