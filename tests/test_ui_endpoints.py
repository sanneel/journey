"""UI-facing endpoints: dry-run validate, draft delete, static shell."""
from __future__ import annotations

from .conftest import API, activation_event, activity, completion, journey_body, uid


def draft() -> dict:
    source, end = uid(), uid()
    return journey_body(
        "JBCL | TEST | ui",
        [
            activity("external_system_source", source, events=[activation_event(end)]),
            activity("end_of_journey", end),
        ],
    )


def test_validate_dry_run_valid(client):
    response = client.post(
        f"{API}/journey-builder/v0/journey-drafts/validate", json=draft()
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_validate_dry_run_reports_problems_without_persisting(client):
    body = draft()
    body["duplicatedFromId"] = "JRN-0-1"
    response = client.post(
        f"{API}/journey-builder/v0/journey-drafts/validate", json=body
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    slugs = {
        problem["type"]
        for entry in payload["aggregatedError"]["journeyActivityError"]
        for problem in entry["problemDetails"]
    }
    assert "journey-with-same-identifier-already-exists" in slugs
    # nothing was created
    assert client.get(f"{API}/journey-builder/v0/journeys").json()["items"] == []


def test_validate_existing_draft_does_not_collide_with_itself(client):
    created = client.post(
        f"{API}/journey-builder/v0/journey-drafts", json=draft()
    ).json()
    body = created["body"]
    response = client.post(
        f"{API}/journey-builder/v0/journey-drafts/validate", json=body
    )
    assert response.json()["valid"] is True, response.text


def test_delete_draft_frees_activity_ids(client):
    body = draft()
    created = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body).json()

    # while the draft exists, its activity ids are taken
    body2 = journey_body("JBCL | TEST | ui 2", body["activities"])
    conflict = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body2)
    assert conflict.status_code == 400

    deleted = client.delete(
        f"{API}/journey-builder/v0/journey-drafts/{created['id']}"
    )
    assert deleted.status_code == 200

    retry = client.post(f"{API}/journey-builder/v0/journey-drafts", json=body2)
    assert retry.status_code == 201, retry.text


def test_published_journey_cannot_be_deleted(client):
    created = client.post(f"{API}/journey-builder/v0/journey-drafts", json=draft()).json()
    client.post(f"{API}/journey-builder/v0/journeys/{created['journeyId']}/publish")
    response = client.delete(
        f"{API}/journey-builder/v0/journey-drafts/{created['id']}"
    )
    assert response.status_code == 409


def test_ui_shell_and_assets_served(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "Journey Builder" in index.text
    for asset in ("app.css", "app.js", "builder.js", "runtime.js"):
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200, asset
