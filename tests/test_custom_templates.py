"""Admin-authored brand templates: save any built journey as a reusable
template, instantiate it with fresh ids, and delete it. Built-ins are
protected."""
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

TPL = f"{API}/journey-builder/v0/journey-templates"


def promo_body():
    ids = {k: uid() for k in ("src", "promo", "end")}
    return journey_body(
        "JBCL | AUG | Gran Promo",
        [
            activity("external_system_source", ids["src"],
                     events=[activation_event(ids["promo"])],
                     init={"targetSystem": "Randomizer", "webhookId": "wh-123"}),
            activity("promotion", ids["promo"],
                     events=[completion("PromotionAccepted", ids["end"]),
                             completion("PromotionExpired", ids["end"])],
                     init={"autoAccept": True,
                           "promotionDisplayId": 677571,
                           "visual": {"headerColor": "#7a1f2b", "title": "Gran Promo"}}),
            activity("end_of_journey", ids["end"]),
        ],
    ), ids


def test_save_instantiate_twice_and_delete(client):
    body, ids = promo_body()

    saved = client.post(TPL, json={
        "name": "Gran Promo de Agosto", "description": "Monthly headline promo",
        "body": body, "actor": "maria",
    })
    assert saved.status_code == 201, saved.text
    key = saved.json()["key"]
    assert saved.json()["custom"] is True
    assert saved.json()["brand"] == "JBCL"

    # listed alongside built-ins, marked custom
    items = client.get(TPL).json()["items"]
    mine = next(i for i in items if i["key"] == key)
    assert mine["custom"] is True and mine["createdBy"] == "maria"
    assert any(not i["custom"] for i in items)  # built-ins still there

    # sanitized: server-minted identity is blanked (create re-mints it),
    # the visual stays
    one = client.get(f"{TPL}/{key}").json()["body"]
    promo = next(a for a in one["activities"] if a["activityName"] == "promotion")
    assert promo["initializationData"]["promotionDisplayId"] is None
    assert promo["initializationData"]["visual"]["title"] == "Gran Promo"
    src = next(a for a in one["activities"] if a["activityName"] == "external_system_source")
    assert "webhookId" not in src["initializationData"]

    # two instantiations -> disjoint structural ids -> both drafts create
    two = client.get(f"{TPL}/{key}").json()["body"]
    ids_one = {a["activityId"] for a in one["activities"]}
    ids_two = {a["activityId"] for a in two["activities"]}
    assert ids_one.isdisjoint(ids_two)
    for instance, name in ((one, "copy A"), (two, "copy B")):
        instance["journeyName"] = f"JBCL | AUG | {name}"
        created = client.post(
            f"{API}/journey-builder/v0/journey-drafts", json=instance
        )
        assert created.status_code == 201, created.text

    # a journey made from the template actually runs (fresh instantiation —
    # copy A's ids are already owned by the draft created above)
    three = client.get(f"{TPL}/{key}").json()["body"]
    journey = create_and_publish(client, three | {"journeyName": "JBCL | AUG | runs"})
    entry = next(a["activityId"] for a in three["activities"]
                 if a["activityName"] == "external_system_source")
    entered = client.post(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}"
        f"/activities/{entry}/enter", json={"playerId": "tpl-player"},
    )
    assert entered.status_code == 201
    offer = client.get(f"{API}/runtime/v0/players/tpl-player/offers").json()["items"][0]
    assert offer["visual"]["title"] == "Gran Promo"

    # delete: custom yes, built-in no
    assert client.delete(f"{TPL}/{key}").status_code == 200
    assert client.get(f"{TPL}/{key}").status_code == 404
    assert client.delete(f"{TPL}/promotion").status_code == 409

    # both actions landed in the audit trail
    audit = client.get(f"{API}/compliance/v0/audit").json()["items"]
    actions = [row["action"] for row in audit]
    assert "template-created" in actions and "template-deleted" in actions


def test_template_requires_name_and_known_types(client):
    body, _ = promo_body()
    assert client.post(TPL, json={"name": "", "body": body}).status_code == 400
    body["activities"][0]["activityName"] = "made_up_node"
    bad = client.post(TPL, json={"name": "x", "body": body})
    assert bad.status_code == 400
    assert "made_up_node" in bad.json()["detail"]