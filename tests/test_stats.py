"""Journey stats — the campaign numbers a CRM manager runs on."""
from __future__ import annotations

from .conftest import API, create_and_publish
from .test_engine import reward_journey


def test_journey_stats_track_the_funnel(client):
    body, ids = reward_journey()
    journey = create_and_publish(client, body)
    webhook_id = journey["publish"]["webhooks"][0]["webhookId"]

    # ana completes (deposit arrives); bruno parks at the gate
    for player in ("ana", "bruno"):
        client.post(
            f"{API}/journey-builder/v0/webhooks/{webhook_id}",
            json={"playerId": player},
        )
    client.post(f"{API}/platform/v0/events", json={
        "eventName": "deposit.approved", "playerId": "ana",
        "properties": {"amount": 15000, "currencyCode": "CLP"},
    })

    stats = client.get(
        f"{API}/runtime/v0/journeys/{journey['journeyId']}/stats"
    ).json()

    assert stats["totals"] == {
        "entered": 2, "active": 1, "completed": 1, "terminated": 0,
        "completionRate": 0.5,
    }
    # both players reached the deposit gate; one is still parked there
    gate = stats["activities"][ids["deposit"]]
    assert gate["entered"] == 2
    assert gate["activeHere"] == 1
    assert gate["events"]["DepositConditionSatisfied"] == 1
    # only ana reached the reward
    spin = stats["activities"][ids["freespin"]]
    assert spin["entered"] == 1
    assert stats["rewards"] == {"grants": 1, "spinsGranted": 30}
    assert stats["comms"]["sent"] == 1
    assert stats["offers"]["presented"] == 2
    assert stats["offers"]["accepted"] == 2  # autoAccept offers

    # the list is a dashboard: counts ride along
    listed = client.get(f"{API}/journey-builder/v0/journeys").json()["items"]
    row = next(item for item in listed if item["journeyId"] == journey["journeyId"])
    assert row["allJourneyActivationsCount"] == 2
    assert row["activeActivationsCount"] == 1
    assert row["completedActivationsCount"] == 1
    assert row["completionRate"] == 0.5
    assert row["rewardGrantsCount"] == 1
