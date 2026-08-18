"""P3/P4/P5: connectors, reliability, versioning — the casino-readiness set."""
from __future__ import annotations

import threading

from app.db import SessionLocal
from app.engine import Engine

from .conftest import (
    API,
    activation_event,
    activity,
    completion,
    create_and_publish,
    journey_body,
    uid,
)


def wait_reward_journey(spins: int = 10):
    """source -> deposit gate -> freespin(spins) -> end (+ red path)."""
    ids = {k: uid() for k in ("src", "gate", "spin", "end", "sorry")}
    body = journey_body(
        f"JBCL | HARD | {uid()[:8]}",
        [
            activity("external_system_source", ids["src"],
                     events=[activation_event(ids["gate"])]),
            activity("deposit", ids["gate"],
                     events=[completion("DepositConditionSatisfied", ids["spin"]),
                             completion("DepositConditionUnsatisfied", ids["sorry"])],
                     init={"depositConditions": {
                         "expirationTimeout": "P0Y0M1DT0H0M0S",
                         "minDepositAmounts": [{"brand": "JBCL", "amount": 10000,
                                                "currencyCode": "CLP"}]}}),
            activity("freespin_bonus", ids["spin"],
                     events=[completion("FreespinBonusCollectingFinished", ids["end"]),
                             completion("FreespinBonusAwardAborted", ids["sorry"])],
                     init={"freespinActivity": {"spins": spins, "provider": "p"}}),
            activity("end_of_journey", ids["end"]),
            activity("end_of_path", ids["sorry"]),
        ],
    )
    return body, ids


# ── P4: idempotent event ingestion ──────────────────────────────────

def test_duplicate_event_id_processed_once(client):
    body, ids = wait_reward_journey()
    journey = create_and_publish(client, body)
    client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "idem"},
    )
    event = {
        "eventName": "deposit.approved", "playerId": "idem",
        "eventId": "evt-12345",
        "properties": {"amount": 20000, "currencyCode": "CLP"},
    }
    first = client.post(f"{API}/platform/v0/events", json=event).json()
    assert first.get("duplicate") is None
    assert first["resolved"]
    second = client.post(f"{API}/platform/v0/events", json=event).json()
    assert second["duplicate"] is True
    assert second["resolved"] == []
    rewards = client.get(f"{API}/runtime/v0/players/idem/rewards").json()["items"]
    assert len(rewards) == 1


# ── P4: two scheduler workers never double-fire ─────────────────────

def test_parallel_schedulers_do_not_double_fire(client):
    ids = {k: uid() for k in ("src", "wait", "spin", "end")}
    body = journey_body(
        "JBCL | HARD | parallel",
        [
            activity("external_system_source", ids["src"],
                     events=[activation_event(ids["wait"])]),
            activity("wait_interval", ids["wait"],
                     events=[completion("WaitTimeCompleted", ids["spin"])],
                     init={"waitPeriod": "P0Y0M0DT0H0M0S"}),
            activity("freespin_bonus", ids["spin"],
                     events=[completion("FreespinBonusCollectingFinished", ids["end"])],
                     init={"freespinActivity": {"spins": 1, "provider": "p"}}),
            activity("end_of_journey", ids["end"]),
        ],
    )
    journey = create_and_publish(client, body)
    players = [f"par-{i}" for i in range(20)]
    for player in players:
        response = client.post(
            f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
            f"/activities/{ids['src']}/enter",
            json={"playerId": player},
        )
        assert response.status_code == 201

    def worker():
        session = SessionLocal()
        try:
            Engine(session).run_due_timers()
            session.commit()
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    total_grants = 0
    for player in players:
        grants = client.get(f"{API}/runtime/v0/players/{player}/rewards").json()["items"]
        total_grants += len(grants)
    assert total_grants == len(players), "a timer fired twice or was lost"


# ── P5: live edit — in-flight players finish on their version ───────

def test_live_edit_pins_inflight_players(client):
    body, ids = wait_reward_journey(spins=10)
    journey = create_and_publish(client, body)

    # ana enters v1 and parks at the deposit gate
    client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "ana-v1"},
    )

    # live edit while she waits: v2 pays 99 spins
    live = client.get(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
    ).json()
    edited = live["body"]
    for act in edited["activities"]:
        if act["activityName"] == "freespin_bonus":
            act["initializationData"]["freespinActivity"]["spins"] = 99
    response = client.put(
        f"{API}/journey-builder/v0/journey-drafts/{live['id']}", json=edited
    )
    assert response.status_code == 200, response.text
    assert response.json()["liveEdit"] is True
    assert response.json()["status"] == "Published"

    # bruno enters after the edit
    client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "bruno-v2"},
    )

    for player in ("ana-v1", "bruno-v2"):
        client.post(f"{API}/platform/v0/events", json={
            "eventName": "deposit.approved", "playerId": player,
            "properties": {"amount": 20000, "currencyCode": "CLP"},
        })

    ana = client.get(f"{API}/runtime/v0/players/ana-v1/rewards").json()["items"]
    bruno = client.get(f"{API}/runtime/v0/players/bruno-v2/rewards").json()["items"]
    assert ana[0]["detail"]["spins"] == 10, "in-flight player must finish on v1"
    assert bruno[0]["detail"]["spins"] == 99, "new player must get the live-edited v2"


# ── P5: drain stop — doors close, in-flight finish, then Stopped ────

def test_drain_stop(client):
    body, ids = wait_reward_journey()
    journey = create_and_publish(client, body)
    client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "drainee"},
    )

    stopped = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}/stop",
        json={"mode": "drain"},
    ).json()
    assert stopped["status"] == "Stopping"
    assert stopped["draining"] == 1

    # doors are closed
    blocked = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "too-late"},
    )
    assert blocked.status_code == 409

    # the in-flight player finishes -> journey flips to Stopped by itself
    client.post(f"{API}/platform/v0/events", json={
        "eventName": "deposit.approved", "playerId": "drainee",
        "properties": {"amount": 20000, "currencyCode": "CLP"},
    })
    final = client.get(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
    ).json()
    assert final["status"] == "Stopped"
    rewards = client.get(f"{API}/runtime/v0/players/drainee/rewards").json()["items"]
    assert len(rewards) == 1


# ── P3: webhook connector failure takes the red path ────────────────

def test_connector_failure_routes_red_path(client, monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "webhook")
    monkeypatch.setenv("CONNECTOR_RETRIES", "0")
    monkeypatch.setenv("CONNECTOR_TIMEOUT", "0.2")
    # rewards URL points nowhere -> delivery must fail fast
    monkeypatch.setenv("CONNECTOR_REWARDS_URL", "http://127.0.0.1:1/wallet")
    monkeypatch.setenv("CONNECTOR_COMMS_URL", "http://127.0.0.1:1/comms")

    body, ids = wait_reward_journey()
    journey = create_and_publish(client, body)
    entered = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "unlucky"},
    )
    assert entered.status_code == 201
    client.post(f"{API}/platform/v0/events", json={
        "eventName": "deposit.approved", "playerId": "unlucky",
        "properties": {"amount": 20000, "currencyCode": "CLP"},
    })

    activation = client.get(
        f"{API}/runtime/v0/journeys/{journey['journeyId']}/activations"
    ).json()["items"][0]
    names = [e["eventName"] for e in activation["eventsHistory"]]
    assert "FreespinBonusAwardFailed" in names
    assert "FreespinBonusAwardAborted" in names
    grants = client.get(f"{API}/runtime/v0/players/unlucky/rewards").json()["items"]
    assert grants[0]["status"] == "Failed"
    assert grants[0]["deliveryAttempts"] == 1


def test_metrics_endpoint(client):
    body, ids = wait_reward_journey()
    journey = create_and_publish(client, body)
    client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "metered"},
    )
    text = client.get("/metrics").text
    assert "journey_activations_entered_total" in text
    assert "journey_published_total" in text
