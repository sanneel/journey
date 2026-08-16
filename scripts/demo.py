#!/usr/bin/env python3
"""End-to-end demo: a miniature birthday-style campaign, in process.

Builds three journeys through the same API a UI (or the journey-cloner)
would use, publishes them, then simulates a player's day:

  1. an "empty prize" journey    — source -> end (the wheel's no-win target)
  2. a  "freespin prize" journey — source -> promotion -> decision split
                                   (player value) -> 100 or 30 freespins
                                   -> on-site notification -> end
  3. a  "casino follow-up"       — source -> deposit gate -> 3x freespin
                                   drip separated by waits -> end

Run:  python scripts/demo.py
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///./demo_journey.db")
os.environ.setdefault("JOURNEY_SCHEDULER_ENABLED", "0")

from fastapi.testclient import TestClient  # noqa: E402

from app import create_app  # noqa: E402
from app.db import Base, engine  # noqa: E402

API = "/api/v0/crm"


def uid() -> str:
    return str(uuid.uuid4())


def act(name, activity_id, events=None, init=None, label=None):
    return {
        "activityId": activity_id,
        "activityName": name,
        "activityDisplayName": label or name,
        "events": events or [],
        "dependencies": [],
        "dataDependencies": [],
        "initializationData": init or {},
    }


def done(event, target):
    return {"eventName": event, "eventType": "Completion", "nextActivityId": target}


def added(target):
    return {"eventName": "PlayerAdded", "eventType": "Activation", "nextActivityId": target}


def body(name, activities):
    return {
        "journeyName": name,
        "brand": "JBCL",
        "currencyCodes": ["CLP"],
        "timeZoneId": "Chile/Continental",
        "isImmediatelyAfterPublish": True,
        "isUnlimited": True,
        "reEntryRule": {"reEntryMode": "Prohibited"},
        "activities": activities,
    }


def create_publish(client, journey_body):
    draft = client.post(f"{API}/journey-builder/v0/journey-drafts", json=journey_body)
    assert draft.status_code == 201, draft.text
    journey = draft.json()
    published = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}/publish"
    ).json()
    journey["publish"] = published
    print(f"  {journey['journeyId']}  {journey['journeyName']}  -> Published")
    return journey


def main() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    client = TestClient(create_app())

    print("== Building the campaign ==")

    # 1. empty prize journey (every wheel needs a routable no-win target)
    source_id, end_id = uid(), uid()
    empty = create_publish(
        client,
        body(
            "JBCL | BD | EMPTY PRIZE",
            [
                act("external_system_source", source_id,
                    events=[added(end_id)], init={"targetSystem": "Randomizer"}),
                act("end_of_journey", end_id),
            ],
        ),
    )

    # 2. freespin prize journey with a value-based decision split
    ids = {k: uid() for k in ("src", "promo", "split", "big", "small", "notify", "end")}
    freespin_prize = create_publish(
        client,
        body(
            "JBCL | BD | FREESPIN PRIZE",
            [
                act("external_system_source", ids["src"],
                    events=[added(ids["promo"])], init={"targetSystem": "Randomizer"}),
                act("promotion", ids["promo"],
                    events=[done("PromotionAccepted", ids["split"]),
                            done("PromotionExpired", None)],
                    init={"autoAccept": True}, label="Birthday freespins"),
                act("ams_decision_split", ids["split"],
                    events=[done("DecisionSplitPassedPath01", ids["big"]),
                            done("DecisionSplitPassedRemainderPath", ids["small"])],
                    init={
                        "rules": [{
                            "name": "high value",
                            "filter": {"property": {
                                "name": "playerValue", "type": "number",
                                "value": "100", "operator": "gte"}, "variables": []},
                        }],
                        "pathesConfig": [{
                            "events": [{"eventName": "DecisionSplitPassedPath01",
                                        "eventType": "Completion"}],
                            "pathId": "path1", "pathName": "high value"}],
                    }),
                act("freespin_bonus", ids["big"],
                    events=[done("FreespinBonusCollectingFinished", ids["notify"])],
                    init={"freespinActivity": {
                        "spins": 100, "provider": "jugabet-games",
                        "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
                        "spinsExpirationDuration": 86400000}},
                    label="jugabet-games | La Gran Copa"),
                act("freespin_bonus", ids["small"],
                    events=[done("FreespinBonusCollectingFinished", ids["notify"])],
                    init={"freespinActivity": {
                        "spins": 30, "provider": "jugabet-games",
                        "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
                        "spinsExpirationDuration": 86400000}},
                    label="jugabet-games | La Gran Copa"),
                act("notification_center", ids["notify"],
                    events=[done("NotificationSent", ids["end"]),
                            done("NotificationNotSent", None)],
                    init={"contract": 1, "templates": {"es": "tmpl-bday"}}),
                act("end_of_journey", ids["end"]),
            ],
        ),
    )

    # 3. casino follow-up: deposit gate then a 3-day freespin drip
    f = {k: uid() for k in ("src", "dep", "s1", "w1", "s2", "w2", "s3", "end")}
    spin = lambda aid, nxt: act(  # noqa: E731
        "freespin_bonus", aid,
        events=[done("FreespinBonusCollectingFinished", nxt)],
        init={"freespinActivity": {"spins": 100, "provider": "jugabet-games",
                                   "spinsExpirationDuration": 86400000}},
        label="daily 100 FS")
    wait = lambda aid, nxt: act(  # noqa: E731
        "wait_interval", aid,
        events=[done("WaitTimeCompleted", nxt)],
        init={"waitPeriod": "P0Y0M0DT0H0M0S"})  # 1 day in production; 0 for the demo
    followup = create_publish(
        client,
        body(
            "JBCL | BD | CASINO FOLLOW-UP",
            [
                act("external_system_source", f["src"],
                    events=[added(f["dep"])], init={"targetSystem": "PromoPage"}),
                act("deposit", f["dep"],
                    events=[done("DepositConditionSatisfied", f["s1"]),
                            done("DepositConditionUnsatisfied", None)],
                    init={"depositConditions": {
                        "expirationTimeout": "P0Y0M1DT0H0M0S",
                        "minDepositAmounts": [{"brand": "JBCL", "amount": 10000,
                                               "currencyCode": "CLP"}],
                        "depositAccountingType": "Any"}}),
                spin(f["s1"], f["w1"]), wait(f["w1"], f["s2"]),
                spin(f["s2"], f["w2"]), wait(f["w2"], f["s3"]),
                spin(f["s3"], f["end"]),
                act("end_of_journey", f["end"]),
            ],
        ),
    )

    # the wheel: weighted prizes, each carrying {journeyId, activityId}
    wheel = [
        {"weight": 69.9, "name": "freespins", "journey": freespin_prize},
        {"weight": 30.1, "name": "nothing", "journey": empty},
    ]
    print("\n== The wheel ==")
    for prize in wheel:
        webhook = prize["journey"]["publish"]["webhooks"][0]
        prize["webhookId"] = webhook["webhookId"]
        print(f"  {prize['weight']:>5}%  {prize['name']:<10} -> "
              f"{prize['journey']['journeyId']} / {webhook['activityId'][:8]}...")

    # ── a player's day ───────────────────────────────────────────────
    print("\n== Player 'lucia' (high value) spins the wheel ==")
    client.post(f"{API}/platform/v0/players",
                json={"playerId": "lucia", "attributes": {"playerValue": 350}})
    prize = wheel[0]  # the RNG smiled today
    activation = client.post(
        f"{API}/journey-builder/v0/webhooks/{prize['webhookId']}",
        json={"playerId": "lucia"}).json()
    print(f"  entered {activation['journeyId']}, status={activation['status']}")
    for event in activation["eventsHistory"]:
        print(f"    {event['eventType']:<10} {event['eventName']}")

    print("\n== lucia hits the follow-up promo page and deposits $150 ==")
    followup_webhook = followup["publish"]["webhooks"][0]["webhookId"]
    parked = client.post(
        f"{API}/journey-builder/v0/webhooks/{followup_webhook}",
        json={"playerId": "lucia"}).json()
    print(f"  parked at deposit gate: activation {parked['activationId']}")
    resolved = client.post(f"{API}/platform/v0/events", json={
        "eventName": "deposit.approved", "playerId": "lucia",
        "properties": {"amount": 15000, "currencyCode": "CLP"}}).json()
    print(f"  deposit.approved resolved: {resolved['resolved']}")

    print("\n== the scheduler ticks (drip waits elapse) ==")
    fired = client.post(f"{API}/runtime/v0/timers/run").json()
    print(f"  timers fired: {fired['fired']}")

    print("\n== The ledger ==")
    rewards = client.get(f"{API}/runtime/v0/players/lucia/rewards").json()["items"]
    for reward in rewards:
        print(f"  {reward['rewardType']:<16} {reward['detail'].get('spins')} spins  "
              f"({reward['journeyId']})")
    comms = client.get(f"{API}/runtime/v0/players/lucia/comms").json()["items"]
    for message in comms:
        print(f"  comms: {message['channel']} {message['status']} "
              f"(contract {message['body'].get('contract')})")

    total_spins = sum(r["detail"].get("spins") or 0 for r in rewards)
    print(f"\nlucia ended the day with {total_spins} freespins "
          f"across {len(rewards)} grants. The mechanism works.")


if __name__ == "__main__":
    main()
