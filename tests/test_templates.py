"""Journey templates: listing, instantiation, and full lifecycle."""
from __future__ import annotations

from .conftest import API


def test_templates_listed(client):
    data = client.get(f"{API}/journey-builder/v0/journey-templates").json()
    keys = {item["key"] for item in data["items"]}
    assert {"promotion", "welcome_freespins"} <= keys
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