"""Draft validation.

Failures are reported the way the imitated platform reports them: an
``aggregatedError`` whose ``journeyActivityError[].problemDetails[].type``
carries a *stable slug* (the human title is decoration). The slugs below
reproduce the documented failure playbook:

  journey-with-same-identifier-already-exists   duplicate JRN / lineage present
  activities-with-same-identifier-already-exist reused activityIds
  already-existing-promotion-display-id         reused promotionDisplayId (422)

plus structural checks a draft must pass before the engine can run it.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog import SOURCE_TYPES, TERMINAL_TYPES, known_events, spec_for
from .models import ActivityIdRegistry, Journey, PromotionDisplayId, ReservedJourneyId


class Problem:
    def __init__(self, slug: str, title: str, detail: str = "", activity_id: str | None = None):
        self.slug = slug
        self.title = title
        self.detail = detail
        self.activity_id = activity_id

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.slug, "title": self.title, "detail": self.detail}


def aggregate(problems: list[Problem]) -> dict[str, Any]:
    """Shape the error body the way clients of the real system expect it."""
    by_activity: dict[str | None, list[Problem]] = {}
    for problem in problems:
        by_activity.setdefault(problem.activity_id, []).append(problem)
    return {
        "aggregatedError": {
            "journeyActivityError": [
                {
                    "activityId": activity_id,
                    "problemDetails": [p.as_dict() for p in items],
                }
                for activity_id, items in by_activity.items()
            ]
        }
    }


def _activities(body: dict) -> list[dict]:
    activities = body.get("activities")
    return activities if isinstance(activities, list) else []


def validate_draft(
    session: Session,
    body: dict,
    brand: str,
    *,
    existing_journey_id: str | None = None,
) -> list[Problem]:
    """Validate a journey draft body. ``existing_journey_id`` is set on PUT so
    the journey does not collide with itself."""
    problems: list[Problem] = []
    activities = _activities(body)

    if not body.get("journeyName"):
        problems.append(Problem("journey-name-required", "Journey name is required"))
    if not activities:
        problems.append(Problem("journey-has-no-activities", "Journey has no activities"))
        return problems

    # ── uniqueness: journey identity ────────────────────────────────
    if body.get("duplicatedFromId"):
        problems.append(
            Problem(
                "journey-with-same-identifier-already-exists",
                "Journey with the same identifier already exists",
                "Lineage fields (duplicatedFromId / duplicatedFromVersion) must be "
                "stripped before posting a draft.",
            )
        )

    reserved = body.get("reservedJourneyId") or body.get("journeyId")
    if reserved:
        owner = session.execute(
            select(Journey).where(Journey.journey_id == reserved)
        ).scalar_one_or_none()
        if owner is not None and owner.journey_id != existing_journey_id:
            problems.append(
                Problem(
                    "journey-with-same-identifier-already-exists",
                    "Journey with the same identifier already exists",
                    f"{reserved} is already taken by draft {owner.draft_id}.",
                )
            )
        reservation = session.get(ReservedJourneyId, reserved)
        if owner is None and reservation is None:
            problems.append(
                Problem(
                    "unknown-reserved-journey-id",
                    "Reserved journey id was never issued",
                    f"Reserve an id first (POST /journeys/identifier); got {reserved}.",
                )
            )

    # ── uniqueness: activity ids (brand-wide) ───────────────────────
    seen: set[str] = set()
    for activity in activities:
        activity_id = activity.get("activityId")
        if not activity_id:
            problems.append(
                Problem("activity-id-required", "Activity is missing activityId")
            )
            continue
        if activity_id in seen:
            problems.append(
                Problem(
                    "activities-with-same-identifier-already-exist",
                    "Activities with the same identifier already exist",
                    f"activityId {activity_id} appears more than once in the draft.",
                    activity_id=activity_id,
                )
            )
        seen.add(activity_id)
        registered = (
            session.execute(
                select(ActivityIdRegistry)
                .where(ActivityIdRegistry.activity_id == activity_id)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if registered is not None and registered.journey_id != existing_journey_id:
            problems.append(
                Problem(
                    "activities-with-same-identifier-already-exist",
                    "Activities with the same identifier already exist",
                    f"activityId {activity_id} is already used by journey "
                    f"{registered.journey_id}. Regenerate internal ids when cloning.",
                    activity_id=activity_id,
                )
            )

    # ── uniqueness: promotion display ids ───────────────────────────
    for activity in activities:
        init = activity.get("initializationData") or {}
        display_id = init.get("promotionDisplayId")
        if display_id in (None, "", 0):
            continue
        row = session.get(PromotionDisplayId, int(display_id))
        if row is not None and row.journey_id not in (None, existing_journey_id):
            problems.append(
                Problem(
                    "already-existing-promotion-display-id",
                    "Already existing promotion display id",
                    f"promotionDisplayId {display_id} is registered to journey "
                    f"{row.journey_id}. Strip it and let the server re-mint.",
                    activity_id=activity.get("activityId"),
                )
            )

    # ── structure: known types, wired graph ─────────────────────────
    by_id = {a.get("activityId"): a for a in activities if a.get("activityId")}
    sources = [a for a in activities if a.get("activityName") in SOURCE_TYPES]
    if not sources:
        problems.append(
            Problem(
                "journey-has-no-input-source",
                "Journey has no input source",
                "At least one Input Source activity is required to admit players.",
            )
        )

    for activity in activities:
        activity_id = activity.get("activityId")
        name = activity.get("activityName")
        spec = spec_for(name) if name else None
        if spec is None:
            problems.append(
                Problem(
                    "unknown-activity-type",
                    "Unknown activity type",
                    f"activityName {name!r} is not in the palette.",
                    activity_id=activity_id,
                )
            )
            continue
        vocabulary = known_events(name)
        for event in activity.get("events") or []:
            event_name = event.get("eventName")
            next_id = event.get("nextActivityId")
            if event_name not in vocabulary:
                problems.append(
                    Problem(
                        "unknown-event-for-activity",
                        "Unknown event for activity type",
                        f"{name} does not emit {event_name!r}.",
                        activity_id=activity_id,
                    )
                )
            if next_id is not None and next_id not in by_id:
                problems.append(
                    Problem(
                        "transition-target-not-found",
                        "Transition points at a missing activity",
                        f"{event_name} -> {next_id} has no matching activity.",
                        activity_id=activity_id,
                    )
                )
        if name not in TERMINAL_TYPES and name not in SOURCE_TYPES:
            wired = any(
                e.get("nextActivityId") for e in (activity.get("events") or [])
            )
            if not wired and spec["completion"]:
                problems.append(
                    Problem(
                        "activity-has-no-outgoing-transition",
                        "Activity has no outgoing transition",
                        f"{name} {activity_id} never reaches another activity; "
                        "wire a Completion event or end the path.",
                        activity_id=activity_id,
                    )
                )

    # ── dual storage: the editor mirror must agree ──────────────────
    raw = body.get("rawJourneyData")
    if isinstance(raw, str):
        import json as _json

        try:
            raw = _json.loads(raw)
        except ValueError:
            raw = None
    if isinstance(raw, dict):
        mirror = raw.get("activitiesConfiguration") or {}
        if isinstance(mirror, dict) and mirror:
            missing = set(mirror) - set(by_id)
            orphaned = {
                a_id
                for a_id in by_id
                if a_id not in mirror
                and (by_id[a_id].get("activityName") not in TERMINAL_TYPES)
            }
            if missing:
                problems.append(
                    Problem(
                        "raw-journey-data-out-of-sync",
                        "rawJourneyData does not match activities",
                        "activitiesConfiguration keys with no matching activity: "
                        + ", ".join(sorted(missing)),
                    )
                )
            if orphaned:
                problems.append(
                    Problem(
                        "raw-journey-data-out-of-sync",
                        "rawJourneyData does not match activities",
                        "activities missing from activitiesConfiguration: "
                        + ", ".join(sorted(orphaned)),
                    )
                )

    return problems
