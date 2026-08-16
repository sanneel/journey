"""Runtime engine tests — players actually walking through journeys."""
from __future__ import annotations

from .conftest import (
    API,
    activation_event,
    activity,
    completion,
    create_and_publish,
    journey_body,
    uid,
)


def reward_journey() -> tuple[dict, dict[str, str]]:
    """source -> promotion(auto) -> deposit -> freespin -> notification -> end"""
    ids = {
        "source": uid(),
        "promo": uid(),
        "deposit": uid(),
        "freespin": uid(),
        "notify": uid(),
        "end": uid(),
    }
    body = journey_body(
        "JBCL | TEST | reward flow",
        [
            activity(
                "external_system_source",
                ids["source"],
                events=[activation_event(ids["promo"])],
                init={"targetSystem": "Randomizer"},
            ),
            activity(
                "promotion",
                ids["promo"],
                events=[
                    completion("PromotionAccepted", ids["deposit"]),
                    completion("PromotionExpired", None),
                ],
                init={"autoAccept": True},
            ),
            activity(
                "deposit",
                ids["deposit"],
                events=[
                    completion("DepositConditionSatisfied", ids["freespin"]),
                    completion("DepositConditionUnsatisfied", None),
                ],
                init={
                    "depositConditions": {
                        "expirationTimeout": "P0Y0M1DT0H0M0S",
                        "minDepositAmounts": [
                            {"brand": "JBCL", "amount": 10000, "currencyCode": "CLP"}
                        ],
                        "depositAccountingType": "Any",
                    }
                },
            ),
            activity(
                "freespin_bonus",
                ids["freespin"],
                events=[completion("FreespinBonusCollectingFinished", ids["notify"])],
                init={
                    "freespinActivity": {
                        "spins": 30,
                        "provider": "jugabet-games",
                        "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
                        "spinsExpirationDuration": 86400000,
                    }
                },
                display_name="jugabet-games | La Gran Copa",
            ),
            activity(
                "notification_center",
                ids["notify"],
                events=[
                    completion("NotificationSent", ids["end"]),
                    completion("NotificationNotSent", None),
                ],
                init={"contract": 1, "templates": {"es": "tmpl-123"}},
            ),
            activity("end_of_journey", ids["end"]),
        ],
    )
    return body, ids


def test_full_walk_webhook_deposit_reward_comms(client):
    body, ids = reward_journey()
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]

    entered = client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}",
        json={"playerId": "player-1"},
    )
    assert entered.status_code == 201, entered.text
    activation = entered.json()
    # promotion auto-accepted, token parked at the deposit gate
    assert activation["status"] == "Active"
    assert activation["currentActivityId"] == ids["deposit"]
    event_names = [e["eventName"] for e in activation["eventsHistory"]]
    assert event_names == [
        "PlayerAdded",
        "PromotionOffered",
        "PromotionAccepted",
        "DepositConditionAccepted",
    ]

    # a deposit that is too small does not open the gate
    small = client.post(
        f"{API}/platform/v0/events",
        json={
            "eventName": "deposit.approved",
            "playerId": "player-1",
            "properties": {"amount": 5000, "currencyCode": "CLP"},
        },
    )
    assert small.status_code == 202
    assert small.json()["resolved"] == []

    # a qualifying deposit resolves the condition and the walk continues
    big = client.post(
        f"{API}/platform/v0/events",
        json={
            "eventName": "deposit.approved",
            "playerId": "player-1",
            "properties": {"amount": 15000, "currencyCode": "CLP"},
        },
    )
    assert big.json()["resolved"][0]["completion"] == "DepositConditionSatisfied"

    final = client.get(
        f"{API}/runtime/v0/activations/{activation['activationId']}"
    ).json()
    assert final["status"] == "Completed"
    event_names = [e["eventName"] for e in final["eventsHistory"]]
    assert "FreespinBonusAwarded" in event_names  # grant boundary
    assert "NotificationSent" in event_names

    rewards = client.get(f"{API}/runtime/v0/players/player-1/rewards").json()["items"]
    assert len(rewards) == 1
    assert rewards[0]["rewardType"] == "freespin_bonus"
    assert rewards[0]["detail"]["spins"] == 30

    comms = client.get(f"{API}/runtime/v0/players/player-1/comms").json()["items"]
    assert len(comms) == 1
    assert comms[0]["channel"] == "onsite"


def test_deposit_window_timeout_takes_failure_path(client):
    source, deposit, notify, end = uid(), uid(), uid(), uid()
    body = journey_body(
        "JBCL | TEST | deposit timeout",
        [
            activity(
                "external_system_source", source, events=[activation_event(deposit)]
            ),
            activity(
                "deposit",
                deposit,
                events=[
                    completion("DepositConditionSatisfied", None),
                    completion("DepositConditionUnsatisfied", notify),
                ],
                init={
                    "depositConditions": {
                        "expirationTimeout": "P0Y0M0DT0H0M0S",  # expires immediately
                        "minDepositAmounts": [
                            {"brand": "JBCL", "amount": 10000, "currencyCode": "CLP"}
                        ],
                    }
                },
            ),
            activity(
                "notification_center",
                notify,
                events=[completion("NotificationSent", end)],
                init={"contract": 5},
            ),
            activity("end_of_journey", end),
        ],
    )
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]
    activation = client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}",
        json={"playerId": "player-2"},
    ).json()

    fired = client.post(f"{API}/runtime/v0/timers/run").json()
    assert fired["fired"] == 1

    final = client.get(
        f"{API}/runtime/v0/activations/{activation['activationId']}"
    ).json()
    assert final["status"] == "Completed"
    names = [e["eventName"] for e in final["eventsHistory"]]
    assert "DepositConditionUnsatisfied" in names
    assert "NotificationSent" in names


def test_wait_interval_and_drip(client):
    """The daily-drip shape: freespin -> wait -> freespin."""
    source, spin1, wait, spin2, end = uid(), uid(), uid(), uid(), uid()
    body = journey_body(
        "JBCL | TEST | drip",
        [
            activity("external_system_source", source, events=[activation_event(spin1)]),
            activity(
                "freespin_bonus",
                spin1,
                events=[completion("FreespinBonusCollectingFinished", wait)],
                init={"freespinActivity": {"spins": 100, "provider": "p"}},
            ),
            activity(
                "wait_interval",
                wait,
                events=[completion("WaitTimeCompleted", spin2)],
                init={"waitPeriod": "P0Y0M0DT0H0M0S"},
            ),
            activity(
                "freespin_bonus",
                spin2,
                events=[completion("FreespinBonusCollectingFinished", end)],
                init={"freespinActivity": {"spins": 100, "provider": "p"}},
            ),
            activity("end_of_journey", end),
        ],
    )
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]
    activation = client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}",
        json={"playerId": "player-3"},
    ).json()
    assert activation["currentActivityId"] == wait

    client.post(f"{API}/runtime/v0/timers/run")
    rewards = client.get(f"{API}/runtime/v0/players/player-3/rewards").json()["items"]
    assert len(rewards) == 2
    final = client.get(
        f"{API}/runtime/v0/activations/{activation['activationId']}"
    ).json()
    assert final["status"] == "Completed"


def test_offer_waits_for_accept_and_expiry(client):
    source, promo, spin, end = uid(), uid(), uid(), uid()
    body = journey_body(
        "JBCL | TEST | manual offer",
        [
            activity("external_system_source", source, events=[activation_event(promo)]),
            activity(
                "promotion",
                promo,
                events=[
                    completion("PromotionAccepted", spin),
                    completion("PromotionExpired", None),
                ],
                init={"autoAccept": False, "timeToAccept": "P0Y0M1DT0H0M0S"},
            ),
            activity(
                "freespin_bonus",
                spin,
                events=[completion("FreespinBonusCollectingFinished", end)],
                init={"freespinActivity": {"spins": 10, "provider": "p"}},
            ),
            activity("end_of_journey", end),
        ],
    )
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]
    activation = client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}",
        json={"playerId": "player-4"},
    ).json()
    assert activation["currentActivityId"] == promo

    offers = client.get(f"{API}/runtime/v0/players/player-4/offers").json()["items"]
    assert len(offers) == 1 and offers[0]["status"] == "Offered"

    accepted = client.post(f"{API}/runtime/v0/offers/{offers[0]['offerId']}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["activation"]["status"] == "Completed"
    rewards = client.get(f"{API}/runtime/v0/players/player-4/rewards").json()["items"]
    assert len(rewards) == 1


def test_decision_split_routes_by_player_attributes(client):
    source, split, high, low, end1, end2 = uid(), uid(), uid(), uid(), uid(), uid()
    body = journey_body(
        "JBCL | TEST | decision split",
        [
            activity("external_system_source", source, events=[activation_event(split)]),
            activity(
                "ams_decision_split",
                split,
                events=[
                    completion("DecisionSplitPassedPath01", high),
                    completion("DecisionSplitPassedRemainderPath", low),
                ],
                init={
                    "rules": [
                        {
                            "name": "high value",
                            "filter": {
                                "property": {
                                    "name": "playerValue",
                                    "type": "number",
                                    "value": "100",
                                    "operator": "gte",
                                },
                                "variables": [],
                            },
                        }
                    ],
                    "pathesConfig": [
                        {
                            "events": [
                                {
                                    "eventName": "DecisionSplitPassedPath01",
                                    "eventType": "Completion",
                                }
                            ],
                            "pathId": "path1",
                            "pathName": "high value",
                        }
                    ],
                },
            ),
            activity(
                "freespin_bonus",
                high,
                events=[completion("FreespinBonusCollectingFinished", end1)],
                init={"freespinActivity": {"spins": 100, "provider": "p"}},
            ),
            activity(
                "freespin_bonus",
                low,
                events=[completion("FreespinBonusCollectingFinished", end2)],
                init={"freespinActivity": {"spins": 10, "provider": "p"}},
            ),
            activity("end_of_journey", end1),
            activity("end_of_journey", end2),
        ],
    )
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]

    client.post(
        f"{API}/platform/v0/players",
        json={"playerId": "whale", "attributes": {"playerValue": 500}},
    )
    client.post(
        f"{API}/platform/v0/players",
        json={"playerId": "minnow", "attributes": {"playerValue": 5}},
    )
    client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}", json={"playerId": "whale"}
    )
    client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}", json={"playerId": "minnow"}
    )

    whale_rewards = client.get(f"{API}/runtime/v0/players/whale/rewards").json()["items"]
    minnow_rewards = client.get(f"{API}/runtime/v0/players/minnow/rewards").json()["items"]
    assert whale_rewards[0]["detail"]["spins"] == 100
    assert minnow_rewards[0]["detail"]["spins"] == 10


def test_reentry_prohibited(client):
    body, _ = reward_journey()
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]
    first = client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}", json={"playerId": "p5"}
    )
    assert first.status_code == 201
    second = client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}", json={"playerId": "p5"}
    )
    assert second.status_code == 409
    assert second.json()["detail"]["type"] == "player-already-in-journey"


def test_event_detector_success_and_failure(client):
    source, detector, win, lose, end1, end2 = uid(), uid(), uid(), uid(), uid(), uid()
    body = journey_body(
        "JBCL | TEST | detector",
        [
            activity("external_system_source", source, events=[activation_event(detector)]),
            activity(
                "event_detector",
                detector,
                events=[
                    completion("DetectorSuccess", win),
                    completion("DetectorFailed", lose),
                ],
                init={
                    "properties": {
                        "startingOptions": {"durationTime": "P0Y0M1DT0H0M0S"},
                        "subscriptionOptions": [
                            {
                                "event": {
                                    "eventName": "deposit.approved",
                                    "sourceName": "platform.orders",
                                },
                                "filter": {
                                    "property": {
                                        "name": "amount",
                                        "type": "number",
                                        "value": "5000",
                                        "operator": "greaterThanOrEqualCurrency",
                                    },
                                    "variables": [
                                        {"name": "currency", "type": "currency", "value": "CLP"}
                                    ],
                                },
                            }
                        ],
                    }
                },
            ),
            activity(
                "notification_center",
                win,
                events=[completion("NotificationSent", end1)],
                init={"contract": 1},
            ),
            activity(
                "notification_center",
                lose,
                events=[completion("NotificationSent", end2)],
                init={"contract": 1},
            ),
            activity("end_of_journey", end1),
            activity("end_of_journey", end2),
        ],
    )
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]
    activation = client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}", json={"playerId": "p6"}
    ).json()

    # wrong currency does not trigger it
    miss = client.post(
        f"{API}/platform/v0/events",
        json={
            "eventName": "deposit.approved",
            "playerId": "p6",
            "properties": {"amount": 9000, "currencyCode": "USD"},
        },
    ).json()
    assert miss["resolved"] == []

    hit = client.post(
        f"{API}/platform/v0/events",
        json={
            "eventName": "deposit.approved",
            "playerId": "p6",
            "properties": {"amount": 9000, "currencyCode": "CLP"},
        },
    ).json()
    assert hit["resolved"][0]["completion"] == "DetectorSuccess"

    final = client.get(
        f"{API}/runtime/v0/activations/{activation['activationId']}"
    ).json()
    names = [e["eventName"] for e in final["eventsHistory"]]
    assert "EventReceived" in names and "DetectorSuccess" in names


def test_campaign_connector_links_journeys(client):
    # host journey: source -> freespin -> end
    h_source, h_spin, h_end = uid(), uid(), uid()
    host = create_and_publish(
        client,
        journey_body(
            "JBCL | TEST | host",
            [
                activity(
                    "external_system_source", h_source, events=[activation_event(h_spin)]
                ),
                activity(
                    "freespin_bonus",
                    h_spin,
                    events=[completion("FreespinBonusCollectingFinished", h_end)],
                    init={"freespinActivity": {"spins": 7, "provider": "p"}},
                ),
                activity("end_of_journey", h_end),
            ],
        ),
    )
    # linking journey: source -> campaign_connector -> end
    l_source, l_conn, l_end = uid(), uid(), uid()
    linker = create_and_publish(
        client,
        journey_body(
            "JBCL | TEST | linker",
            [
                activity(
                    "external_system_source", l_source, events=[activation_event(l_conn)]
                ),
                activity(
                    "campaign_connector",
                    l_conn,
                    events=[
                        completion("PlayerAddedToCampaign", l_end),
                        completion("PlayerNotAddedToCampaign", l_end),
                    ],
                    init={
                        "campaignConnectorConditions": {
                            "campaignId": "",
                            "activityData": {"HostJourneyId": host["journeyId"]},
                        }
                    },
                ),
                activity("end_of_journey", l_end),
            ],
        ),
    )
    webhook_id = linker["publish"]["webhooks"][0]["webhookId"]
    client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}", json={"playerId": "p7"}
    )
    rewards = client.get(f"{API}/runtime/v0/players/p7/rewards").json()["items"]
    assert len(rewards) == 1 and rewards[0]["journeyId"] == host["journeyId"]

    host_activations = client.get(
        f"{API}/runtime/v0/journeys/{host['journeyId']}/activations"
    ).json()["items"]
    assert len(host_activations) == 1


def test_engagement_split_branches_on_comms_status(client):
    source, notify, split, clicked, other, end1, end2 = (
        uid(),
        uid(),
        uid(),
        uid(),
        uid(),
        uid(),
        uid(),
    )
    body = journey_body(
        "JBCL | TEST | engagement",
        [
            activity("external_system_source", source, events=[activation_event(notify)]),
            activity(
                "notification_center",
                notify,
                events=[completion("NotificationSent", split)],
                init={"contract": 1},
            ),
            activity(
                "notification_center_engagement_split",
                split,
                events=[
                    completion("NCEngagementSplitPassedPath01", clicked),
                    completion("NCEngagementSplitPassedPath02", other),
                ],
                init={
                    "properties": {
                        "paths": [
                            {
                                "pathId": "path1",
                                "pathName": "Clicked",
                                "notificationCenterEngagementStatuses": ["Clicked"],
                            },
                            {
                                "pathId": "other",
                                "pathName": "Other",
                                "notificationCenterEngagementStatuses": [
                                    "NotSent",
                                    "Sent",
                                    "Shown",
                                    "Read",
                                ],
                            },
                        ],
                        "DextraNotificationCenterActivityId": notify,
                    },
                    "pathesConfig": [
                        {
                            "events": [
                                {
                                    "eventName": "NCEngagementSplitPassedPath01",
                                    "eventType": "Completion",
                                }
                            ],
                            "pathId": "path1",
                        },
                        {
                            "events": [
                                {
                                    "eventName": "NCEngagementSplitPassedPath02",
                                    "eventType": "Completion",
                                }
                            ],
                            "pathId": "other",
                        },
                    ],
                },
            ),
            activity(
                "freespin_bonus",
                clicked,
                events=[completion("FreespinBonusCollectingFinished", end1)],
                init={"freespinActivity": {"spins": 50, "provider": "p"}},
            ),
            activity(
                "freespin_bonus",
                other,
                events=[completion("FreespinBonusCollectingFinished", end2)],
                init={"freespinActivity": {"spins": 5, "provider": "p"}},
            ),
            activity("end_of_journey", end1),
            activity("end_of_journey", end2),
        ],
    )
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]
    client.post(
        f"{API}/journey-builder/v0/webhooks/{webhook_id}", json={"playerId": "p8"}
    )
    # the notification was only Sent (never clicked) -> the "Other" branch
    rewards = client.get(f"{API}/runtime/v0/players/p8/rewards").json()["items"]
    assert rewards[0]["detail"]["spins"] == 5
