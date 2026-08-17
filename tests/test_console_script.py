"""Console-script export — the journey-cloner operator workflow."""
from __future__ import annotations

import re

from .conftest import API


def _create_promotion(client) -> dict:
    body = client.get(f"{API}/journey-builder/v0/journey-templates/promotion").json()["body"]
    return client.post(f"{API}/journey-builder/v0/journey-drafts", json=body).json()


def test_console_script_shape(client):
    journey = _create_promotion(client)
    response = client.get(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}/console-script"
    )
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    script = response.text
    # the operator workflow, verbatim concepts from the cloner scripts
    for marker in (
        "HOW TO RUN",
        "allow pasting",
        "reserveId",
        "/journey-drafts",
        "MANUAL_TOKEN",
        "DONE",
        journey["journeyName"],
    ):
        assert marker in script, marker


def test_console_script_mints_fresh_ids(client):
    journey = _create_promotion(client)
    source_ids = {a["activityId"] for a in journey["body"]["activities"]}
    first = client.get(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}/console-script"
    ).text
    second = client.get(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}/console-script"
    ).text
    uuid_re = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}")
    first_ids, second_ids = set(uuid_re.findall(first)), set(uuid_re.findall(second))
    assert first_ids and second_ids
    assert first_ids.isdisjoint(source_ids), "script must not reuse the source's activity ids"
    assert first_ids.isdisjoint(second_ids), "every download mints fresh ids"
    # display ids are blanked so the server re-mints them
    assert '"promotionDisplayId": null' in first
    # the script reserves its own journey id at run time: the payload
    # carries no journeyId/reservedJourneyId (header mentions the source
    # unquoted, which is fine)
    assert f"\"{journey['journeyId']}\"" not in first
    assert '"reservedJourneyId"' not in first


def test_console_script_draft_mode(client):
    journey = _create_promotion(client)
    script = client.get(
        f"{API}/journey-builder/v0/journeys/{journey['journeyId']}/console-script",
        params={"publish": "false"},
    ).text
    assert "const PUBLISH = false;" in script
