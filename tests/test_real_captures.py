"""Ground-truth guard: the real GR8 journeys captured from the REA
backoffice must stay fully describable by our catalog.

Each fixture in tests/fixtures/rea_captures/ is an unmodified
``GET /journeys/{id}`` body pulled from the live backoffice. If our
catalog ever drifts — an activity type dropped, an event name renamed —
these break, which is exactly what we want: our imitation is only honest
while it still speaks for every real journey we've seen.
"""
from __future__ import annotations

import glob
import json
import os

import pytest

from app.catalog import ACTIVITY_TYPES, known_events

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "rea_captures")
JOURNEYS = sorted(glob.glob(os.path.join(FIXTURES, "JRN-*.json")))


def _graph(body: dict) -> dict:
    if body.get("activities"):
        return body
    inner = body.get("body")
    return inner if isinstance(inner, dict) and inner.get("activities") else body


@pytest.mark.skipif(not JOURNEYS, reason="no captured journeys checked in")
@pytest.mark.parametrize("path", JOURNEYS, ids=[os.path.basename(p) for p in JOURNEYS])
def test_captured_journey_is_fully_modelled(path):
    graph = _graph(json.load(open(path, encoding="utf-8")))
    activities = graph.get("activities", [])
    assert activities, f"{path} has no activities"

    unknown_types = sorted(
        {a.get("activityName") for a in activities if a.get("activityName") not in ACTIVITY_TYPES}
    )
    assert not unknown_types, f"activity types not in our catalog: {unknown_types}"

    unknown_events = []
    for a in activities:
        vocab = known_events(a["activityName"])
        for event in a.get("events") or []:
            name = event.get("eventName")
            if name and name not in vocab:
                unknown_events.append(f"{a['activityName']}.{name}")
    assert not unknown_events, f"wired events not in our vocabulary: {sorted(set(unknown_events))}"


def test_captures_cover_the_new_node_types():
    """The three types this capture round added are present in the fixtures."""
    seen = set()
    for path in JOURNEYS:
        graph = _graph(json.load(open(path, encoding="utf-8")))
        seen.update(a.get("activityName") for a in graph.get("activities", []))
    for node in ("csv_import", "money_bonus", "sport_bet_insurance"):
        assert node in seen, f"{node} missing from captured fixtures"
        assert node in ACTIVITY_TYPES, f"{node} missing from catalog"
