"""P1 + P9: the compliance wall, marketing policy, GDPR, four-eyes
approval and test-player rehearsals."""
from __future__ import annotations

from datetime import timedelta

from app.config import settings
from app.db import SessionLocal
from app.durations import utcnow
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

COMPLIANCE = f"{API}/compliance/v0"


def reward_journey(spins: int = 10):
    """source -> deposit gate -> sms -> freespin -> end (+ red path)."""
    ids = {k: uid() for k in ("src", "gate", "sms", "spin", "end", "sorry")}
    body = journey_body(
        f"JBCL | COMPLY | {uid()[:8]}",
        [
            activity("external_system_source", ids["src"],
                     events=[activation_event(ids["gate"])]),
            activity("deposit", ids["gate"],
                     events=[completion("DepositConditionSatisfied", ids["sms"]),
                             completion("DepositConditionUnsatisfied", ids["sorry"])],
                     init={"depositConditions": {
                         "expirationTimeout": "P0Y0M1DT0H0M0S",
                         "minDepositAmounts": [{"brand": "JBCL", "amount": 10000,
                                                "currencyCode": "CLP"}]}}),
            activity("dextra_sms", ids["sms"],
                     events=[completion("SuccessSmsSend", ids["spin"]),
                             completion("FailedSmsSend", ids["spin"])],
                     init={"rawValues": {"messageText": "premio!"}}),
            activity("freespin_bonus", ids["spin"],
                     events=[completion("FreespinBonusCollectingFinished", ids["end"]),
                             completion("FreespinBonusAwardAborted", ids["sorry"])],
                     init={"freespinActivity": {"spins": spins, "provider": "p"}}),
            activity("end_of_journey", ids["end"]),
            activity("end_of_path", ids["sorry"]),
        ],
    )
    return body, ids


def enter(client, journey, ids, player):
    return client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": player},
    )


def deposit(client, player, amount=20000):
    return client.post(f"{API}/platform/v0/events", json={
        "eventName": "deposit.approved", "playerId": player,
        "properties": {"amount": amount, "currencyCode": "CLP"},
    })


# ── P1: the exclusion wall ──────────────────────────────────────────

def test_excluded_player_cannot_enter(client):
    body, ids = reward_journey()
    journey = create_and_publish(client, body)
    added = client.post(f"{COMPLIANCE}/exclusions", json={
        "playerId": "banned", "reason": "self_exclusion", "actor": "rg-team",
    })
    assert added.status_code == 201

    blocked = enter(client, journey, ids, "banned")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["type"] == "player-excluded"

    client.delete(f"{COMPLIANCE}/exclusions/banned")
    assert enter(client, journey, ids, "banned").status_code == 201


def test_exclusion_wall_mid_journey(client):
    """Excluded AFTER entering: the reward is suppressed and the token
    takes the red path — the wall applies to in-flight players too."""
    body, ids = reward_journey()
    journey = create_and_publish(client, body)
    assert enter(client, journey, ids, "midway").status_code == 201

    client.post(f"{COMPLIANCE}/exclusions", json={
        "playerId": "midway", "reason": "vulnerable",
    })
    deposit(client, "midway")

    activation = client.get(
        f"{API}/runtime/v0/journeys/{journey['journeyId']}/activations"
    ).json()["items"][0]
    assert activation["status"] == "Completed"
    names = [e["eventName"] for e in activation["eventsHistory"]]
    assert "FreespinBonusAwardFailed" in names
    assert "FreespinBonusAwardAborted" in names

    grants = client.get(f"{API}/runtime/v0/players/midway/rewards").json()["items"]
    assert grants[0]["status"] == "Suppressed"
    comms = client.get(f"{API}/runtime/v0/players/midway/comms").json()["items"]
    assert comms[0]["status"] == "Suppressed"


def test_cool_off_expires(client):
    body, ids = reward_journey()
    journey = create_and_publish(client, body)
    past = (utcnow() - timedelta(hours=1)).isoformat()
    client.post(f"{COMPLIANCE}/exclusions", json={
        "playerId": "cooled", "reason": "cool_off", "expiresAt": past,
    })
    # the cool-off ended an hour ago -> entry is allowed again
    assert enter(client, journey, ids, "cooled").status_code == 201
    listed = client.get(f"{COMPLIANCE}/exclusions").json()["items"]
    assert listed[0]["active"] is False


# ── P1: frequency caps & quiet hours ────────────────────────────────

def test_frequency_cap_suppresses_third_sms(client):
    client.put(f"{COMPLIANCE}/policy", json={"frequencyCaps": {"sms": 2}})
    ids = {k: uid() for k in ("src", "s1", "s2", "s3", "end")}
    body = journey_body(
        "JBCL | COMPLY | capped",
        [
            activity("external_system_source", ids["src"],
                     events=[activation_event(ids["s1"])]),
            activity("dextra_sms", ids["s1"],
                     events=[completion("SuccessSmsSend", ids["s2"])],
                     init={"rawValues": {"messageText": "uno"}}),
            activity("dextra_sms", ids["s2"],
                     events=[completion("SuccessSmsSend", ids["s3"])],
                     init={"rawValues": {"messageText": "dos"}}),
            activity("dextra_sms", ids["s3"],
                     events=[completion("SuccessSmsSend", ids["end"])],
                     init={"rawValues": {"messageText": "tres"}}),
            activity("end_of_journey", ids["end"]),
        ],
    )
    journey = create_and_publish(client, body)
    entered = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "chatty"},
    )
    assert entered.status_code == 201

    comms = client.get(f"{API}/runtime/v0/players/chatty/comms").json()["items"]
    statuses = [m["status"] for m in comms]
    assert statuses == ["Sent", "Sent", "Suppressed"]
    assert "frequency cap" in comms[2]["deliveryDetail"]
    # the journey itself still completed — suppression never strands a token
    activation = client.get(
        f"{API}/runtime/v0/journeys/{journey['journeyId']}/activations"
    ).json()["items"][0]
    assert activation["status"] == "Completed"


def test_quiet_hours_hold_then_release(client):
    now = utcnow()
    start = (now - timedelta(hours=1)).strftime("%H:%M")
    end = (now + timedelta(hours=1)).strftime("%H:%M")
    client.put(f"{COMPLIANCE}/policy", json={"quietHours": {"start": start, "end": end}})

    body, ids = reward_journey()
    journey = create_and_publish(client, body)
    enter(client, journey, ids, "nightowl")
    deposit(client, "nightowl")

    comms = client.get(f"{API}/runtime/v0/players/nightowl/comms").json()["items"]
    assert comms[0]["status"] == "Held"
    assert "quiet hours" in comms[0]["deliveryDetail"]
    # the walk was NOT held up: the reward landed and the run completed
    grants = client.get(f"{API}/runtime/v0/players/nightowl/rewards").json()["items"]
    assert grants[0]["status"] == "Awarded"

    # fast-forward past the window: the release timer delivers the message
    session = SessionLocal()
    try:
        Engine(session).run_due_timers(now=now + timedelta(hours=2))
        session.commit()
    finally:
        session.close()
    comms = client.get(f"{API}/runtime/v0/players/nightowl/comms").json()["items"]
    assert comms[0]["status"] == "Sent"
    assert "released after quiet hours" in comms[0]["deliveryDetail"]


# ── P1: offer terms & GDPR ──────────────────────────────────────────

def test_offer_carries_terms_and_validation_warns_without(client):
    terms = {"wageringRequirement": 30, "expiryDays": 7, "maxWin": 500000}
    ids = {k: uid() for k in ("src", "promo", "end")}
    body = journey_body(
        "JBCL | COMPLY | terms",
        [
            activity("external_system_source", ids["src"],
                     events=[activation_event(ids["promo"])]),
            activity("promotion", ids["promo"],
                     events=[completion("PromotionAccepted", ids["end"]),
                             completion("PromotionExpired", ids["end"])],
                     init={"autoAccept": False, "terms": terms}),
            activity("end_of_journey", ids["end"]),
        ],
    )
    journey = create_and_publish(client, body)
    client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{ids['src']}/enter",
        json={"playerId": "reader"},
    )
    offers = client.get(f"{API}/runtime/v0/players/reader/offers").json()["items"]
    assert offers[0]["terms"] == terms

    # the same shape without terms validates with a compliance warning
    fresh = {k: uid() for k in ("src", "promo", "end")}
    termless = journey_body(
        "JBCL | COMPLY | termless",
        [
            activity("external_system_source", fresh["src"],
                     events=[activation_event(fresh["promo"])]),
            activity("promotion", fresh["promo"],
                     events=[completion("PromotionAccepted", fresh["end"]),
                             completion("PromotionExpired", fresh["end"])],
                     init={"autoAccept": False}),
            activity("end_of_journey", fresh["end"]),
        ],
    )
    checked = client.post(
        f"{API}/journey-builder/v0/journey-drafts/validate", json=termless
    ).json()
    assert checked["valid"] is True
    assert checked["warnings"][0]["type"] == "promotion-terms-missing"


def test_gdpr_export_and_erase(client):
    body, ids = reward_journey()
    journey = create_and_publish(client, body)
    enter(client, journey, ids, "gdpr-guy")
    deposit(client, "gdpr-guy")
    client.post(f"{COMPLIANCE}/exclusions", json={
        "playerId": "gdpr-guy", "reason": "self_exclusion",
    })

    exported = client.get(f"{COMPLIANCE}/players/gdpr-guy/export").json()
    assert exported["player"] is not None
    assert len(exported["activations"]) == 1
    assert exported["rewards"] and exported["comms"] and exported["platformEvents"]

    erased = client.delete(f"{COMPLIANCE}/players/gdpr-guy").json()
    assert erased["erased"]["activations"] == 1
    assert erased["kept"] == "exclusion record (regulatory obligation)"

    after = client.get(f"{COMPLIANCE}/players/gdpr-guy/export").json()
    assert after["player"] is None
    assert after["activations"] == []
    # the exclusion survives erasure — honouring it is a legal obligation
    assert after["exclusion"]["active"] is True


# ── P9: four-eyes approval ──────────────────────────────────────────

def test_four_eyes_approval_gates_publish(client, monkeypatch):
    monkeypatch.setattr(settings, "require_approval", True)
    body, ids = reward_journey()
    created = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    journey = created.json()
    jrn = journey["journeyId"]

    blocked = client.post(f"{API}/journey-builder/v0/journeys/{jrn}/publish")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["type"] == "journey-not-approved"

    client.post(f"{API}/journey-builder/v0/journeys/{jrn}/submit-review",
                json={"requestedBy": "maria"})
    selfie = client.post(f"{API}/journey-builder/v0/journeys/{jrn}/approve",
                         json={"approvedBy": "Maria"})
    assert selfie.status_code == 409
    assert selfie.json()["detail"]["type"] == "four-eyes-violation"

    approved = client.post(f"{API}/journey-builder/v0/journeys/{jrn}/approve",
                           json={"approvedBy": "nino"})
    assert approved.status_code == 200
    assert approved.json()["approvalState"] == "Approved"

    published = client.post(f"{API}/journey-builder/v0/journeys/{jrn}/publish",
                            json={"actor": "maria"})
    assert published.status_code == 200

    audit = client.get(
        f"{API}/journey-builder/v0/journeys/{jrn}/audit"
    ).json()["items"]
    actions = [row["action"] for row in audit]
    assert actions == ["published", "approved", "submitted-for-review"]


def test_edit_voids_approval(client, monkeypatch):
    monkeypatch.setattr(settings, "require_approval", True)
    body, ids = reward_journey()
    created = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    journey = created.json()
    jrn = journey["journeyId"]
    client.post(f"{API}/journey-builder/v0/journeys/{jrn}/submit-review",
                json={"requestedBy": "maria"})
    client.post(f"{API}/journey-builder/v0/journeys/{jrn}/approve",
                json={"approvedBy": "nino"})

    # any edit resets the approval — it covered the old body
    edited = client.put(
        f"{API}/journey-builder/v0/journey-drafts/{journey['id']}",
        json=journey["body"],
    )
    assert edited.status_code == 200
    assert edited.json()["approvalState"] is None
    blocked = client.post(f"{API}/journey-builder/v0/journeys/{jrn}/publish")
    assert blocked.status_code == 409


def test_reject_sends_back_with_reason(client):
    body, ids = reward_journey()
    created = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    jrn = created.json()["journeyId"]
    client.post(f"{API}/journey-builder/v0/journeys/{jrn}/submit-review",
                json={"requestedBy": "maria"})
    rejected = client.post(
        f"{API}/journey-builder/v0/journeys/{jrn}/reject",
        json={"rejectedBy": "nino", "reason": "bonus is too generous"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["approvalState"] == "Rejected"
    assert rejected.json()["reviewNote"] == "bonus is too generous"


# ── P9: test-player rehearsal ───────────────────────────────────────

def test_test_player_walks_but_nothing_leaves(client, monkeypatch):
    """Rehearsal in production: the connector is live (and broken — any
    real delivery would fail), yet the test player's walk succeeds
    because test deliveries never leave the building."""
    monkeypatch.setenv("CONNECTOR_MODE", "webhook")
    monkeypatch.setenv("CONNECTOR_RETRIES", "0")
    monkeypatch.setenv("CONNECTOR_TIMEOUT", "0.2")
    monkeypatch.setenv("CONNECTOR_REWARDS_URL", "http://127.0.0.1:1/wallet")
    monkeypatch.setenv("CONNECTOR_COMMS_URL", "http://127.0.0.1:1/comms")

    client.post(f"{API}/platform/v0/players",
                json={"playerId": "dry-run", "isTest": True})
    body, ids = reward_journey()
    journey = create_and_publish(client, body)
    enter(client, journey, ids, "dry-run")
    deposit(client, "dry-run")

    activation = client.get(
        f"{API}/runtime/v0/journeys/{journey['journeyId']}/activations"
    ).json()["items"][0]
    assert activation["isTest"] is True
    assert activation["status"] == "Completed"
    assert activation["context"]["completedVia"] == "end_of_journey"

    grants = client.get(f"{API}/runtime/v0/players/dry-run/rewards").json()["items"]
    assert grants[0]["status"] == "Awarded"
    assert "test player" in grants[0]["deliveryDetail"]
    comms = client.get(f"{API}/runtime/v0/players/dry-run/comms").json()["items"]
    assert comms[0]["status"] == "Sent"
    assert "test player" in comms[0]["deliveryDetail"]

    # campaign numbers ignore the rehearsal
    stats = client.get(
        f"{API}/runtime/v0/journeys/{journey['journeyId']}/stats"
    ).json()
    assert stats["totals"]["entered"] == 0
    assert stats["testRunsExcluded"] == 1
    assert stats["rewards"]["grants"] == 0
