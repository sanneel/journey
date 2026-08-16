"""Unit tests: durations, timestamps, structural id regeneration."""
from __future__ import annotations

from datetime import timedelta

from app.durations import parse_iso_duration, parse_timestamp
from app.ids import collect_structural_ids, regenerate_structural_ids


def test_iso_durations():
    assert parse_iso_duration("P0Y0M1DT0H0M0S") == timedelta(days=1)
    assert parse_iso_duration("P0Y0M0DT0H30M0S") == timedelta(minutes=30)
    assert parse_iso_duration("P0Y0M0DT0H0M0S") == timedelta(0)


def test_both_timestamp_flavours():
    dotnet = parse_timestamp("2026-07-18T04:00:00.0000000Z")
    plain = parse_timestamp("2026-07-18T04:00:00Z")
    assert dotnet == plain


def test_structural_id_regeneration_is_consistent():
    payload = {
        "activities": [
            {
                "activityId": "11111111-1111-1111-1111-111111111111",
                "events": [
                    {
                        "eventName": "PromotionAccepted",
                        "nextActivityId": "22222222-2222-2222-2222-222222222222",
                    }
                ],
            },
            {"activityId": "22222222-2222-2222-2222-222222222222", "events": []},
        ],
        "rawJourneyData": {
            "activitiesConfiguration": {
                "11111111-1111-1111-1111-111111111111": {"displayName": "a"},
                "22222222-2222-2222-2222-222222222222": {"displayName": "b"},
            }
        },
        # not a structural key: must survive untouched
        "promotionId": "33333333-3333-3333-3333-333333333333",
    }
    regenerated, mapping = regenerate_structural_ids(payload)
    assert len(mapping) == 2
    old_first, old_second = (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )
    new_first, new_second = mapping[old_first], mapping[old_second]
    assert regenerated["activities"][0]["activityId"] == new_first
    # embedded reference followed the rename
    assert regenerated["activities"][0]["events"][0]["nextActivityId"] == new_second
    # the editor-mirror dict keys followed too
    assert set(regenerated["rawJourneyData"]["activitiesConfiguration"]) == {
        new_first,
        new_second,
    }
    # external reference untouched
    assert regenerated["promotionId"] == "33333333-3333-3333-3333-333333333333"
    assert collect_structural_ids(regenerated) == {new_first, new_second}
