"""The activity palette.

Mirrors the Tools panel of the source Journey Builder. Every activity type
declares:

  - ``category``     the palette group it appears under
  - ``kind``         how the runtime treats it (source / instant / parked / split /
                     reward / comms / terminal / connector)
  - ``activation``   events fired when a player is injected (sources only)
  - ``boundary``     moment events (attach notifications; no transition)
  - ``completion``   real transitions — the graph is wired entirely through
                     ``events[].nextActivityId`` on these
  - ``happy_path``   the completion event the engine follows after the
                     activity's work succeeds (when several are wired)
  - ``failure_path`` the completion event for the failure outcome

The event vocabulary below is taken verbatim from captured journeys — the
runtime speaks the same language as the system it imitates.
"""
from __future__ import annotations

from typing import Any

ACTIVITY_TYPES: dict[str, dict[str, Any]] = {
    # ── Input sources ────────────────────────────────────────────────
    "dwh_source": {
        "category": "Input Source",
        "label": "Custom Segment",
        "kind": "source",
        "activation": ["PlayerAdded"],
        "boundary": [],
        "completion": [],
        "init_keys": ["currentTemplate", "dataSourceName", "filterDetails", "displayData", "placements"],
    },
    "external_system_source": {
        "category": "Input Source",
        "label": "API",
        "kind": "source",
        "activation": ["PlayerAdded"],
        "boundary": [],
        "completion": [],
        "init_keys": ["description", "targetSystem", "webhookId", "isWebhookUrlHidden", "displayData", "placements"],
    },
    "registration": {
        "category": "Input Source",
        "label": "Reference codes",
        "kind": "source",
        "activation": ["PlayerAdded"],
        "boundary": [],
        "completion": [],
        "init_keys": ["promocodeSettings", "refCodeTypes", "displayData", "placements", "version"],
    },
    # ── Flow control ─────────────────────────────────────────────────
    "ams_decision_split": {
        "category": "Flow control",
        "label": "Decision split",
        "kind": "split",
        "activation": [],
        "boundary": [],
        "completion": [f"DecisionSplitPassedPath{i:02d}" for i in range(1, 21)]
        + ["DecisionSplitPassedRemainderPath"],
        "init_keys": ["rules", "remainder", "pathesConfig", "displayData", "placements", "usedSourceVariables"],
    },
    "random_split": {
        "category": "Flow control",
        "label": "Random split",
        "kind": "split",
        "activation": [],
        "boundary": [],
        "completion": [f"RandomSplitPassedPath{i}" for i in range(1, 11)],
        "init_keys": ["paths", "pathesConfig", "displayData", "placements"],
    },
    "notification_center_engagement_split": {
        "category": "Flow control",
        "label": "On-site engagement split",
        "kind": "split",
        "activation": [],
        "boundary": [],
        "completion": [f"NCEngagementSplitPassedPath{i:02d}" for i in range(1, 6)],
        "init_keys": ["properties", "pathesConfig", "displayData", "placements"],
    },
    "email_engagement_split": {
        "category": "Flow control",
        "label": "Email engagement split",
        "kind": "split",
        "activation": [],
        "boundary": [],
        "completion": [f"Path{i}" for i in range(1, 7)],
        "init_keys": ["properties", "pathesConfig", "displayData"],
    },
    # ── Communication ────────────────────────────────────────────────
    "notification_center": {
        "category": "Communication",
        "label": "On-site messaging",
        "kind": "comms",
        "channel": "onsite",
        "activation": [],
        "boundary": [],
        "completion": ["NotificationSent", "NotificationNotSent"],
        "happy_path": "NotificationSent",
        "failure_path": "NotificationNotSent",
        "init_keys": ["contract", "channel", "templates", "deliveryType", "validityAmount", "languages", "objectForSend", "displayData", "placements"],
    },
    "dextra_sms": {
        "category": "Communication",
        "label": "SMS",
        "kind": "comms",
        "channel": "sms",
        "activation": [],
        "boundary": [],
        "completion": ["SuccessSmsSend", "FailedSmsSend"],
        "happy_path": "SuccessSmsSend",
        "failure_path": "FailedSmsSend",
        "init_keys": ["smsSettings", "rawValues", "listOfUsedVariables", "displayData", "placements", "version"],
    },
    "dextra_email": {
        "category": "Communication",
        "label": "Email",
        "kind": "comms",
        "channel": "email",
        "activation": [],
        "boundary": [],
        "completion": ["SuccessEmailSend", "FailedEmailSend"],
        "happy_path": "SuccessEmailSend",
        "failure_path": "FailedEmailSend",
        "init_keys": ["emailSettings", "displayData", "placements"],
    },
    "native_push": {
        "category": "Communication",
        "label": "Native push",
        "kind": "comms",
        "channel": "push",
        "activation": [],
        "boundary": [],
        "completion": ["PushSent", "PushNotSent"],
        "happy_path": "PushSent",
        "failure_path": "PushNotSent",
        "init_keys": ["displayData", "placements"],
    },
    # ── Delays ───────────────────────────────────────────────────────
    "wait_interval": {
        "category": "Delays",
        "label": "Wait",
        "kind": "parked",
        "activation": [],
        "boundary": ["WaitTimeStarted"],
        "completion": ["WaitTimeCompleted"],
        "happy_path": "WaitTimeCompleted",
        "init_keys": ["waitPeriod", "exitCriteria", "displayData", "placements"],
    },
    "wait_date": {
        "category": "Delays",
        "label": "Date",
        "kind": "parked",
        "activation": [],
        "boundary": ["WaitTimeStarted"],
        "completion": ["WaitTimeCompleted"],
        "happy_path": "WaitTimeCompleted",
        "init_keys": ["waitTo", "waitStrategy", "timezoneMode", "exitCriteria", "displayData", "placements"],
    },
    "event_detector": {
        "category": "Delays",
        "label": "Event Detector",
        "kind": "parked",
        "activation": [],
        "boundary": ["DetectorStarted", "EventReceived", "EventNotReceived"],
        "completion": ["DetectorSuccess", "DetectorFailed"],
        "happy_path": "DetectorSuccess",
        "failure_path": "DetectorFailed",
        "init_keys": ["properties", "usedVariables", "displayData", "placements"],
    },
    # ── Connectors ───────────────────────────────────────────────────
    "campaign_connector": {
        "category": "Connectors",
        "label": "Campaign Connector",
        "kind": "connector",
        "activation": [],
        "boundary": [],
        "completion": ["PlayerAddedToCampaign", "PlayerNotAddedToCampaign"],
        "happy_path": "PlayerAddedToCampaign",
        "failure_path": "PlayerNotAddedToCampaign",
        "init_keys": ["campaignConnectorConditions", "displayData", "placements"],
    },
    # ── Promotion type ───────────────────────────────────────────────
    "promotion": {
        "category": "Promotion type",
        "label": "Promotion",
        "kind": "offer",
        "activation": [],
        "boundary": ["PromotionOffered", "PromotionUpcoming"],
        "completion": ["PromotionAccepted", "PromotionExpired"],
        "happy_path": "PromotionAccepted",
        "failure_path": "PromotionExpired",
        "init_keys": ["promotionId", "promotionLinkId", "promotionDisplayId", "promotionStatus", "autoAccept", "timeToAccept", "channelsCondition", "languages", "displayData", "placements"],
    },
    "multipurpose_promotion": {
        "category": "Promotion type",
        "label": "Multipurpose Promotion",
        "kind": "offer",
        "activation": [],
        "boundary": ["PromotionOffered", "PromotionUpcoming"],
        "completion": ["PromotionAccepted", "PromotionExpired"],
        "happy_path": "PromotionAccepted",
        "failure_path": "PromotionExpired",
        "init_keys": ["promotionId", "promotionLinkId", "promotionDisplayId", "promotionStatus", "autoAccept", "timeToAccept", "channelsCondition", "languages", "displayData", "placements"],
    },
    # ── Conditions ───────────────────────────────────────────────────
    "deposit": {
        "category": "Conditions",
        "label": "Deposit",
        "kind": "parked",
        "activation": [],
        "boundary": ["DepositConditionAccepted"],
        "completion": [
            "DepositConditionSatisfied",
            "DepositConditionUnsatisfied",
            "DepositConditionCanceled",
        ],
        "happy_path": "DepositConditionSatisfied",
        "failure_path": "DepositConditionUnsatisfied",
        "init_keys": ["depositConditions", "displayData", "placements"],
    },
    "sport_bet_condition": {
        "category": "Conditions",
        "label": "Bet",
        "kind": "parked",
        "activation": [],
        "boundary": ["Activated"],
        "completion": ["Satisfied", "Unsatisfied", "Terminated", "Canceled"],
        "happy_path": "Satisfied",
        "failure_path": "Unsatisfied",
        "init_keys": ["betTypes", "betsCount", "channels", "lineTypes", "minBetAmount", "minItems", "minOdd", "expireInDays", "displayData", "placements"],
    },
    # ── Reward type ──────────────────────────────────────────────────
    "freespin_bonus": {
        "category": "Reward type",
        "label": "Casino FreeSpin",
        "kind": "reward",
        "activation": [],
        "boundary": [
            "FreespinBonusAwarded",
            "FreespinBonusAwardConfirmed",
            "FreespinBonusAwardFailed",
            "FreespinBonusCollectingStarted",
            "FreespinBonusRejected",
            "FreespinBonusRejectFailed",
            "FreespinBonusCancelled",
            "FreespinBonusCancelFailed",
            "FreespinBonusStatusReverted",
        ],
        "completion": [
            "FreespinBonusCollectingFinished",
            "FreespinBonusNotUsed",
            "FreespinBonusAwardAborted",
            "FreespinBonusRejectConfirmed",
            "FreespinBonusCancelConfirmed",
            "FreespinBonusCancelledByWithdrawalConfirmed",
            "FreeSpinsBonusTermsNotComplied",
        ],
        "happy_path": "FreespinBonusCollectingFinished",
        "failure_path": "FreespinBonusAwardAborted",
        "grant_boundary": "FreespinBonusAwarded",
        "init_keys": ["freespinActivity", "allowReject", "pathesConfig", "displayData", "placements"],
    },
    "casino_bonus_v2": {
        "category": "Reward type",
        "label": "Casino Bonus",
        "kind": "reward",
        "activation": [],
        "boundary": [
            "WageringBonusAwarded",
            "WageringBonusAwardConfirmed",
            "WageringBonusAwardFailed",
            "WageringBonusStarted",
            "WageringBonusRejected",
            "WageringBonusRejectFailed",
            "WageringBonusCancelled",
            "WageringBonusCancelFailed",
            "WageringBonusExpirationFailed",
            "WageringBonusFinishFailed",
            "WageringBonusLoseFailed",
        ],
        "completion": [
            "WageringBonusFinished",
            "WageringBonusExpired",
            "WageringBonusLost",
            "WageringBonusForfeited",
            "WageringBonusAwardAborted",
            "WageringBonusRejectConfirmed",
            "WageringBonusCancelConfirmed",
            "WageringBonusCancelledByWithdrawalConfirmed",
        ],
        "happy_path": "WageringBonusFinished",
        "failure_path": "WageringBonusAwardAborted",
        "grant_boundary": "WageringBonusAwarded",
        "init_keys": ["activitySubtype", "productType", "bonusPercent", "wageringRequirement", "limitType", "releaseLimitMultiplier", "bonusExpirationTime", "withoutLockBalance", "allowReject", "currenciesConfig", "wageringActivity", "displayData", "placements"],
    },
    "freebet": {
        "category": "Reward type",
        "label": "Sport FreeBet",
        "kind": "reward",
        "activation": [],
        "boundary": ["FreebetIssued"],
        "completion": [
            "PlayerFreebetUsed",
            "PlayerFreebetExpired",
            "PlayerFreebetCanceled",
            "FreebetNotIssued",
        ],
        "happy_path": "PlayerFreebetUsed",
        "failure_path": "FreebetNotIssued",
        "grant_boundary": "FreebetIssued",
        "init_keys": ["properties", "displayData", "placements"],
    },
    "sport_bonus": {
        "category": "Reward type",
        "label": "Sport Bonus",
        "kind": "reward",
        "activation": [],
        "boundary": ["Issued", "WageringStarted"],
        "completion": ["Completed", "Expired", "Lost", "Canceled", "Terminated", "NotIssued"],
        "happy_path": "Completed",
        "failure_path": "NotIssued",
        "grant_boundary": "Issued",
        "init_keys": ["properties", "displayData", "placements"],
    },
    # ── Terminals ────────────────────────────────────────────────────
    "end_of_path": {
        "category": "Terminals",
        "label": "End of path",
        "kind": "terminal",
        "activation": [],
        "boundary": [],
        "completion": [],
        "init_keys": [],
    },
    "end_of_journey": {
        "category": "Terminals",
        "label": "End of journey",
        "kind": "terminal",
        "activation": [],
        "boundary": [],
        "completion": [],
        "init_keys": [],
    },
}

SOURCE_TYPES = {name for name, spec in ACTIVITY_TYPES.items() if spec["kind"] == "source"}
TERMINAL_TYPES = {name for name, spec in ACTIVITY_TYPES.items() if spec["kind"] == "terminal"}


def spec_for(activity_name: str) -> dict[str, Any] | None:
    return ACTIVITY_TYPES.get(activity_name)


def known_events(activity_name: str) -> set[str]:
    spec = ACTIVITY_TYPES.get(activity_name)
    if not spec:
        return set()
    return set(spec["activation"]) | set(spec["boundary"]) | set(spec["completion"])


def palette() -> list[dict[str, Any]]:
    """The Tools panel, grouped by category, for a UI or an AI planner."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for name, spec in ACTIVITY_TYPES.items():
        groups.setdefault(spec["category"], []).append(
            {
                "activityName": name,
                "label": spec["label"],
                "kind": spec["kind"],
                "events": {
                    "activation": spec["activation"],
                    "boundary": spec["boundary"],
                    "completion": spec["completion"],
                },
                "initializationDataKeys": spec["init_keys"],
            }
        )
    return [{"category": cat, "activities": items} for cat, items in groups.items()]
