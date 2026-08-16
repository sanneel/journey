"""Builder API tests: identifiers, drafts, validation slugs, duplication."""
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


def simple_draft() -> dict:
    source, promo, end = uid(), uid(), uid()
    return journey_body(
        "JBCL | TEST | simple",
        [
            activity(
                "external_system_source",
                source,
                events=[activation_event(promo)],
                init={"targetSystem": "Randomizer"},
            ),
            activity(
                "promotion",
                promo,
                events=[
                    completion("PromotionAccepted", end),
                    completion("PromotionExpired", None),
                ],
                init={"autoAccept": True},
            ),
            activity("end_of_journey", end),
        ],
    )


def test_reserve_identifier(client):
    response = client.post(f"{API}/journey-builder/v0/journeys/identifier", json={})
    assert response.status_code == 200
    assert response.json()["journeyId"].startswith("JRN-0-")


def test_create_draft_mints_ids(client):
    response = client.post(
        f"{API}/journey-builder/v0/journey-drafts", json=simple_draft()
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["journeyId"].startswith("JRN-0-")
    assert draft["status"] == "Draft"
    promo = next(
        a for a in draft["body"]["activities"] if a["activityName"] == "promotion"
    )
    # display id re-minted server-side during create
    assert isinstance(promo["initializationData"]["promotionDisplayId"], int)


def test_reserved_identifier_is_honoured(client):
    reserved = client.post(
        f"{API}/journey-builder/v0/journeys/identifier", json={}
    ).json()["journeyId"]
    body = simple_draft()
    body["reservedJourneyId"] = reserved
    draft = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body).json()
    assert draft["journeyId"] == reserved


def test_unknown_reserved_identifier_rejected(client):
    body = simple_draft()
    body["reservedJourneyId"] = "JRN-0-999999"
    response = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    assert response.status_code == 400
    slugs = _slugs(response)
    assert "unknown-reserved-journey-id" in slugs


def _slugs(response) -> set[str]:
    detail = response.json()["detail"]
    return {
        problem["type"]
        for entry in detail["aggregatedError"]["journeyActivityError"]
        for problem in entry["problemDetails"]
    }


def test_lineage_must_be_stripped(client):
    body = simple_draft()
    body["duplicatedFromId"] = "JRN-0-123456"
    response = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    assert response.status_code == 400
    assert "journey-with-same-identifier-already-exists" in _slugs(response)


def test_reused_activity_ids_rejected(client):
    body = simple_draft()
    first = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    assert first.status_code == 201
    # a "clone" that forgot to regenerate internal ids
    body2 = journey_body("JBCL | TEST | clone-fail", body["activities"])
    response = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body2)
    assert response.status_code == 400
    assert "activities-with-same-identifier-already-exist" in _slugs(response)


def test_reused_promotion_display_id_is_422(client):
    body = simple_draft()
    first = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body).json()
    taken = next(
        a["initializationData"]["promotionDisplayId"]
        for a in first["body"]["activities"]
        if a["activityName"] == "promotion"
    )
    body2 = simple_draft()
    promo = next(a for a in body2["activities"] if a["activityName"] == "promotion")
    promo["initializationData"]["promotionDisplayId"] = taken
    response = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body2)
    assert response.status_code == 422
    assert "already-existing-promotion-display-id" in _slugs(response)


def test_unknown_event_and_dangling_transition_rejected(client):
    source, promo = uid(), uid()
    body = journey_body(
        "JBCL | TEST | bad-graph",
        [
            activity(
                "external_system_source", source, events=[activation_event(promo)]
            ),
            activity(
                "promotion",
                promo,
                events=[
                    completion("NotARealEvent", None),
                    completion("PromotionAccepted", uid()),  # dangling target
                ],
            ),
        ],
    )
    response = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    assert response.status_code == 400
    slugs = _slugs(response)
    assert "unknown-event-for-activity" in slugs
    assert "transition-target-not-found" in slugs


def test_raw_journey_data_mirror_checked(client):
    body = simple_draft()
    body["rawJourneyData"] = {
        "activitiesConfiguration": {uid(): {"displayName": "ghost"}}
    }
    response = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body)
    assert response.status_code == 400
    assert "raw-journey-data-out-of-sync" in _slugs(response)


def test_duplicate_regenerates_everything(client):
    original = client.post(
        f"{API}/journey-builder/v0/journey-drafts", json=simple_draft()
    ).json()
    response = client.post(
        f"{API}/journey-builder/v0/journeys/{original['journeyId']}/duplicate",
        json={"journeyName": "JBCL | TEST | the copy"},
    )
    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["journeyId"] != original["journeyId"]
    assert copy["duplicatedFromId"] == original["journeyId"]

    old_ids = {a["activityId"] for a in original["body"]["activities"]}
    new_ids = {a["activityId"] for a in copy["body"]["activities"]}
    assert old_ids.isdisjoint(new_ids)

    old_display = {
        a["initializationData"].get("promotionDisplayId")
        for a in original["body"]["activities"]
        if a["activityName"] == "promotion"
    }
    new_display = {
        a["initializationData"].get("promotionDisplayId")
        for a in copy["body"]["activities"]
        if a["activityName"] == "promotion"
    }
    assert old_display.isdisjoint(new_display)
    # the wiring survived the rename
    copy_source = next(
        a
        for a in copy["body"]["activities"]
        if a["activityName"] == "external_system_source"
    )
    copy_promo = next(
        a for a in copy["body"]["activities"] if a["activityName"] == "promotion"
    )
    assert copy_source["events"][0]["nextActivityId"] == copy_promo["activityId"]


def test_publish_and_catalog(client):
    journey = create_and_publish(client, simple_draft())
    assert journey["publish"]["status"] == "Published"
    assert journey["publish"]["webhooks"], "external_system_source must get a webhook"

    catalog = client.get(f"{API}/journey-builder/v0/activities/catalog").json()
    names = {
        entry["activityName"]
        for group in catalog["palette"]
        for entry in group["activities"]
    }
    assert {"promotion", "freespin_bonus", "wait_interval", "deposit"} <= names
