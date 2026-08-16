"""Journey duplication — the clone mechanism, server-side.

Implements the four ID classes:

  KEEP        external references (promotionId, promotionLinkId, contentId,
              frontId, notification templates) — they point at real objects
  REGENERATE  structural ids: activityId / id and every embedded reference
              (nextActivityId, journeyActivityId, canvas edges, ports,
              handles, activitiesConfiguration keys) via consistent
              string-replace over the serialized payload
  STRIP       server-minted promotionDisplayId (re-minted on create)
  BLANK       campaignConnectorConditions.campaignId ("" so the server
              re-mints; reusing one is a 409)
  REMOVE      lineage: duplicatedFromId / duplicatedFromVersion (the copy
              records its own lineage instead)
"""
from __future__ import annotations

import copy
from typing import Any

from .ids import regenerate_structural_ids


def _walk(node: Any, fn) -> None:
    if isinstance(node, dict):
        fn(node)
        for value in node.values():
            _walk(value, fn)
    elif isinstance(node, list):
        for item in node:
            _walk(item, fn)


def strip_promotion_display_ids(payload: dict) -> None:
    def fn(node: dict) -> None:
        if "promotionDisplayId" in node:
            node["promotionDisplayId"] = None

    _walk(payload, fn)


def blank_campaign_ids(payload: dict) -> None:
    def fn(node: dict) -> None:
        conditions = node.get("campaignConnectorConditions")
        if isinstance(conditions, dict) and "campaignId" in conditions:
            conditions["campaignId"] = ""

    _walk(payload, fn)


def clone_journey_body(
    body: dict,
    *,
    new_journey_id: str,
    new_name: str,
    source_journey_id: str,
    source_version: int,
) -> tuple[dict, dict[str, str]]:
    """Produce a postable copy of a journey body.

    Returns ``(new_body, id_mapping)`` where ``id_mapping`` maps old
    structural UUIDs to their regenerated replacements (callers use it to
    repoint prizes / promo pages at the copy's entry activity).
    """
    payload = copy.deepcopy(body)

    # REMOVE lineage from the source, then record our own
    payload.pop("duplicatedFromId", None)
    payload.pop("duplicatedFromVersion", None)

    # STRIP / BLANK server-minted identity
    strip_promotion_display_ids(payload)
    blank_campaign_ids(payload)

    # Server-assigned runtime/metrics fields never survive a clone
    for key in (
        "status",
        "createdAt",
        "changedAt",
        "changeHistory",
        "allJourneyActivationsCount",
        "overJourneyActivationsCount",
        "areJourneyMetricsAvailable",
        "activityEventConversionMetrics",
        "version",
    ):
        payload.pop(key, None)

    # REGENERATE structural ids consistently
    payload, mapping = regenerate_structural_ids(payload)

    payload["journeyId"] = new_journey_id
    payload["reservedJourneyId"] = new_journey_id
    payload["journeyName"] = new_name
    payload["duplicatedFromId"] = None  # lineage lives in the DB row
    payload.pop("duplicatedFromVersion", None)
    return payload, mapping
