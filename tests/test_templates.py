"""Journey templates: listing, instantiation, and full lifecycle."""
from __future__ import annotations

from .conftest import API


def test_templates_listed(client):
    data = client.get(f"{API}/journey-builder/v0/journey-templates").json()
    keys = {item["key"] for item in data["items"]}
    assert {"promotion", "welcome_freespins", "fiestas_patrias",
            "big_promo_day", "big_promo_special_card", "big_promo_plan_b"} <= keys
    promotion = next(i for i in data["items"] if i["key"] == "promotion")
    assert promotion["activities"] == 14
    assert "deposit gate" in promotion["description"]


def test_unknown_template_404(client):
    assert client.get(f"{API}/journey-builder/v0/journey-templates/nope").status_code == 404


def test_instantiations_never_share_ids(client):
    first = client.get(f"{API}/journey-builder/v0/journey-templates/promotion").json()["body"]
    second = client.get(f"{API}/journey-builder/v0/journey-templates/promotion").json()["body"]
    ids_first = {a["activityId"] for a in first["activities"]}
    ids_second = {a["activityId"] for a in second["activities"]}
    assert ids_first.isdisjoint(ids_second)
    # the editor mirror is keyed consistently with the fresh ids
    assert set(first["rawJourneyData"]["activitiesConfiguration"]) == ids_first


def test_promotion_template_is_valid_and_publishable(client):
    body = client.get(f"{API}/journey-builder/v0/journey-templates/promotion").json()["body"]

    validated = client.post(f"{API}/journey-builder/v0/journey-drafts/validate", json=body)
    assert validated.json()["valid"] is True, validated.text

    created = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    assert created.status_code == 201, created.text
    draft = created.json()
    # the promotion activity got a display id minted on create
    offer = next(a for a in draft["body"]["activities"] if a["activityName"] == "promotion")
    assert isinstance(offer["initializationData"]["promotionDisplayId"], int)

    published = client.post(
        f"{API}/journey-builder/v0/journeys/{draft['journeyId']}/publish"
    )
    assert published.status_code == 200
    assert published.json()["webhooks"], "the API entry must expose a webhook"


def test_promotion_template_walks_both_reward_tiers(client):
    """Two players through the template: a whale hits the premium tier,
    a casual player the standard tier."""
    body = client.get(f"{API}/journey-builder/v0/journey-templates/promotion").json()["body"]
    draft = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body).json()
    client.post(f"{API}/journey-builder/v0/journeys/{draft['journeyId']}/publish")

    source = next(
        a for a in draft["body"]["activities"]
        if a["activityName"] == "external_system_source"
    )
    for player_id, value in (("whale", 500), ("casual", 10)):
        client.post(f"{API}/platform/v0/players",
                    json={"playerId": player_id, "attributes": {"playerValue": value}})
        entered = client.post(
            f"{API}/journey-builder/v0/journeys/{draft['journeyId']}"
            f"/activities/{source['activityId']}/enter",
            json={"playerId": player_id},
        )
        assert entered.status_code == 201, entered.text
        # accept the offer, then deposit
        offers = client.get(f"{API}/runtime/v0/players/{player_id}/offers").json()["items"]
        client.post(f"{API}/runtime/v0/offers/{offers[0]['offerId']}/accept")
        client.post(f"{API}/platform/v0/events", json={
            "eventName": "deposit.approved", "playerId": player_id,
            "properties": {"amount": 15000, "currencyCode": "CLP"},
        })

    whale = client.get(f"{API}/runtime/v0/players/whale/rewards").json()["items"]
    casual = client.get(f"{API}/runtime/v0/players/casual/rewards").json()["items"]
    assert whale[0]["detail"]["spins"] == 100
    assert casual[0]["detail"]["spins"] == 30

    # both parked at the 1-day wait; fire it -> follow-up email + completion
    client.post(f"{API}/runtime/v0/timers/run")  # nothing due yet (1 day)
    timers = client.get(f"{API}/runtime/v0/timers").json()["items"]
    assert len(timers) == 2 and all(t["kind"] == "wait" for t in timers)


def test_fiestas_patrias_template_grants_one_fonda_prize(client):
    """A player opts in, deposits $15.000, spins the fonda roulette and
    lands exactly one of the three prizes, then parks on the wait-date
    hold for the 18th."""
    body = client.get(
        f"{API}/journey-builder/v0/journey-templates/fiestas_patrias"
    ).json()["body"]

    validated = client.post(f"{API}/journey-builder/v0/journey-drafts/validate", json=body)
    assert validated.json()["valid"] is True, validated.text

    draft = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body).json()
    published = client.post(
        f"{API}/journey-builder/v0/journeys/{draft['journeyId']}/publish"
    )
    assert published.status_code == 200, published.text

    source = next(
        a for a in draft["body"]["activities"]
        if a["activityName"] == "external_system_source"
    )
    client.post(f"{API}/platform/v0/players",
                json={"playerId": "huaso", "attributes": {"playerValue": 500}})
    entered = client.post(
        f"{API}/journey-builder/v0/journeys/{draft['journeyId']}"
        f"/activities/{source['activityId']}/enter",
        json={"playerId": "huaso"},
    )
    assert entered.status_code == 201, entered.text

    offers = client.get(f"{API}/runtime/v0/players/huaso/offers").json()["items"]
    assert "12 al 19 de septiembre" in (offers[0]["terms"] or "")
    client.post(f"{API}/runtime/v0/offers/{offers[0]['offerId']}/accept")
    client.post(f"{API}/platform/v0/events", json={
        "eventName": "deposit.approved", "playerId": "huaso",
        "properties": {"amount": 15000, "currencyCode": "CLP"},
    })

    rewards = client.get(f"{API}/runtime/v0/players/huaso/rewards").json()["items"]
    assert len(rewards) == 1
    assert rewards[0]["rewardType"] in {"freespin_bonus", "freebet", "casino_bonus_v2"}

    # the prize bell went out and the token is parked until the 18th
    comms = client.get(f"{API}/runtime/v0/players/huaso/comms").json()["items"]
    assert any(c["channel"] == "onsite" for c in comms)
    timers = client.get(f"{API}/runtime/v0/timers").json()["items"]
    assert any(t["kind"] == "wait" for t in timers)


def test_big_promo_day_two_deposits_unlock_special_card(client):
    """The Big Promo September mechanic end to end: a player picks Bonus N3,
    deposits $30.000 (40 FS granted), then a second deposit of the day
    trips the detector and the campaign connector drops them into the
    published Special Card journey."""
    scratch = client.get(
        f"{API}/journey-builder/v0/journey-templates/big_promo_special_card"
    ).json()["body"]
    scratch_draft = client.post(f"{API}/journey-builder/v0/journey-drafts", json=scratch).json()
    scratch_jrn = scratch_draft["journeyId"]
    assert client.post(f"{API}/journey-builder/v0/journeys/{scratch_jrn}/publish").status_code == 200

    body = client.get(
        f"{API}/journey-builder/v0/journey-templates/big_promo_day"
    ).json()["body"]
    for activity in body["activities"]:
        if activity["activityName"] == "campaign_connector":
            conditions = activity["initializationData"]["campaignConnectorConditions"]
            conditions["activityData"]["HostJourneyId"] = scratch_jrn

    validated = client.post(f"{API}/journey-builder/v0/journey-drafts/validate", json=body)
    assert validated.json()["valid"] is True, validated.text
    draft = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body).json()
    assert client.post(
        f"{API}/journey-builder/v0/journeys/{draft['journeyId']}/publish"
    ).status_code == 200

    source = next(
        a for a in draft["body"]["activities"]
        if a["activityName"] == "external_system_source"
    )
    client.post(f"{API}/platform/v0/players",
                json={"playerId": "dieciochero", "attributes": {"bonusOption": 3}})
    entered = client.post(
        f"{API}/journey-builder/v0/journeys/{draft['journeyId']}"
        f"/activities/{source['activityId']}/enter",
        json={"playerId": "dieciochero"},
    )
    assert entered.status_code == 201, entered.text

    # first deposit satisfies the N3 gate -> 40 freespins
    client.post(f"{API}/platform/v0/events", json={
        "eventName": "deposit.approved", "playerId": "dieciochero",
        "properties": {"amount": 30000, "currencyCode": "CLP"},
    })
    rewards = client.get(f"{API}/runtime/v0/players/dieciochero/rewards").json()["items"]
    assert [r["detail"].get("spins") for r in rewards
            if r["rewardType"] == "freespin_bonus"] == [40]

    # second deposit of the day -> detector -> Special Card journey entry
    client.post(f"{API}/platform/v0/events", json={
        "eventName": "deposit.approved", "playerId": "dieciochero",
        "properties": {"amount": 12000, "currencyCode": "CLP"},
    })
    scratch_runs = client.get(
        f"{API}/runtime/v0/journeys/{scratch_jrn}/activations"
    ).json()["items"]
    assert [run["playerId"] for run in scratch_runs] == ["dieciochero"]
