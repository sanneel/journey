"""Every activity type in the palette executes for real.

For each type: build a minimal published journey around it, walk a player
in, resolve whatever it parks on (offers, platform events, timers), and
assert the node recorded at least one event of its own — plus its
side-effect artifact (offer / reward grant / comms message / webhook)
where the kind has one.
"""
from __future__ import annotations

import pytest

from app.catalog import ACTIVITY_TYPES

from .conftest import API, activation_event, activity, journey_body, uid

# runnable initializationData per type; zero windows so parked nodes
# resolve on the first timer sweep even when no event arrives
INITS = {
    "external_system_source": {"targetSystem": "Test"},
    "dwh_source": {"dataSourceName": "segment"},
    "registration": {"promocodeSettings": {"refCodes": ["GO"]}},
    "promotion": {"autoAccept": True},
    "multipurpose_promotion": {"autoAccept": False, "timeToAccept": 1},  # 1 ms
    "deposit": {
        "depositConditions": {
            "expirationTimeout": "P0Y0M0DT0H0M0S",
            "minDepositAmounts": [{"brand": "JBCL", "amount": 1000, "currencyCode": "CLP"}],
        }
    },
    "sport_bet_condition": {"minBetAmount": 100, "minOdd": 1.1, "expireInDays": 0.0000001},
    "csv_import": {"fileId": "file-1", "uploadStatus": "UPLOADED"},
    "money_bonus": {
        "currencyAmounts": [{"brand": "JBCL", "amount": 250000, "currencyCode": "CLP"}],
        "amountAccrualType": "Fixed",
    },
    "sport_bet_insurance": {
        "conditions": [{"minBetAmount": {"CLP": "0"}, "minOddParlay": 1.0}],
        "expireInDays": 0.0000001,
    },
    "wait_interval": {"waitPeriod": "P0Y0M0DT0H0M0S"},
    "wait_date": {"waitTo": ""},
    "event_detector": {
        "properties": {
            "startingOptions": {"durationTime": "P0Y0M0DT0H0M0S"},
            "subscriptionOptions": [
                {"event": {"eventName": "deposit.approved"}, "filter": None}
            ],
        }
    },
    "freespin_bonus": {"freespinActivity": {"spins": 5, "provider": "p"}},
    "casino_bonus_v2": {"bonusPercent": 50, "wageringRequirement": 10},
    "freebet": {"properties": {}},
    "sport_bonus": {"properties": {}},
    "notification_center": {"contract": 1},
    "dextra_sms": {"rawValues": {"messageText": "hola"}},
    "dextra_email": {"emailSettings": {"contentId": "CSE-0-1"}},
    "native_push": {},
    "ams_decision_split": {
        "rules": [{
            "name": "always",
            "filter": {"property": {"name": "playerValue", "type": "number",
                                    "value": "0", "operator": "gte"}},
        }],
        "pathesConfig": [],
    },
    "random_split": {
        "paths": [{"pathId": "p1", "pathName": "P1", "probability": 100}],
        "pathesConfig": [],
    },
    "notification_center_engagement_split": {
        "properties": {"paths": [{
            "pathId": "any", "pathName": "Any",
            "notificationCenterEngagementStatuses": ["NotSent", "Sent", "Shown", "Read", "Clicked"],
        }]},
        "pathesConfig": [],
    },
    "email_engagement_split": {
        "properties": {"paths": [{
            "pathId": "any", "pathName": "Any",
            "engagementStatuses": ["NotSent", "Sent", "Shown", "Read", "Clicked"],
        }]},
        "pathesConfig": [],
    },
    "campaign_connector": {
        "campaignConnectorConditions": {"campaignId": "", "activityData": {}}
    },
    "end_of_path": {},
    "end_of_journey": {},
}

SIDE_EFFECTS = {
    "offer": "offers",
    "reward": "rewards",
    "comms": "comms",
}


def build_case(target_type: str) -> tuple[dict, str, str]:
    """source -> target -> end, every completion of target wired to end."""
    source_id, target_id, end_id = uid(), uid(), uid()
    spec = ACTIVITY_TYPES[target_type]
    target = activity(target_type, target_id, init=INITS.get(target_type, {}))
    for event_name in spec["activation"]:
        target["events"].append(
            {"eventName": event_name, "eventType": "Activation", "nextActivityId": end_id}
        )
    for event_name in spec["completion"]:
        target["events"].append(
            {"eventName": event_name, "eventType": "Completion", "nextActivityId": end_id}
        )
    body = journey_body(
        f"JBCL | COVER | {target_type}",
        [
            activity("external_system_source", source_id,
                     events=[activation_event(target_id)]),
            target,
            activity("end_of_journey", end_id),
        ],
    )
    return body, source_id, target_id


@pytest.mark.parametrize("target_type", sorted(ACTIVITY_TYPES))
def test_activity_type_executes(client, target_type):
    body, source_id, target_id = build_case(target_type)
    created = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    assert created.status_code == 201, created.text
    journey = created.json()
    published = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}/publish"
    )
    assert published.status_code == 200, published.text

    player = f"cover-{target_type}"
    entered = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{source_id}/enter",
        json={"playerId": player},
    )
    assert entered.status_code == 201, entered.text

    # resolve anything the node parked on: offers, qualifying platform
    # events (deterministic — no racing tiny timer windows), then timers
    offers = client.get(f"{API}/runtime/v0/players/{player}/offers").json()["items"]
    for offer in offers:
        if offer["status"] == "Offered":
            client.post(f"{API}/runtime/v0/offers/{offer['offerId']}/accept")
    for event_name, props in (
        ("deposit.approved", {"amount": 99999, "currencyCode": "CLP"}),
        ("bet.settled", {"amount": 99999, "odd": 2.5}),
    ):
        client.post(f"{API}/platform/v0/events", json={
            "eventName": event_name, "playerId": player, "properties": props,
        })
    client.post(f"{API}/runtime/v0/timers/run")

    activation = client.get(
        f"{API}/runtime/v0/journeys/{journey['journeyId']}/activations"
    ).json()["items"][0]
    assert activation["status"] == "Completed", (
        f"{target_type} left the token stuck at "
        f"{activation['currentActivityId']}: {activation['eventsHistory']}"
    )

    spec = ACTIVITY_TYPES[target_type]
    if spec["kind"] != "terminal":
        node_events = [
            event for event in activation["eventsHistory"]
            if event["activityId"] == target_id
        ]
        assert node_events, f"{target_type} recorded no events of its own"

    # kinds with artifacts must have produced one
    artifact = SIDE_EFFECTS.get(spec["kind"])
    if artifact:
        items = client.get(
            f"{API}/runtime/v0/players/{player}/{artifact}"
        ).json()["items"]
        assert items, f"{target_type} produced no {artifact} artifact"
