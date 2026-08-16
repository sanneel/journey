"""Identifier minting and the clone-time ID regeneration mechanism.

The platform this imitates enforces uniqueness on *server-minted* identity
fields across all journeys of a brand:

  - journey ids      `JRN-0-<n>`   (reserved before the draft is posted)
  - promotion display ids           (minted per promotion activity)
  - activity ids                    (UUIDs, client-generated but unique)

Cloning follows four ID classes:
  KEEP        external references (promotionId, contentId, frontId, templates)
  REGENERATE  structural ids (activityId / id and everything embedding them)
  STRIP       server-minted (promotionDisplayId)
  BLANK       campaignConnectorConditions.campaignId
  REMOVE      lineage (duplicatedFromId / duplicatedFromVersion)
"""
from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Sequence

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# keys whose UUID values are a node's *identity* (regenerated on clone)
STRUCTURAL_ID_KEYS = {"activityId", "id"}


def next_sequence(session: Session, name: str, start: int = 100000) -> int:
    row = session.execute(
        select(Sequence).where(Sequence.name == name).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = Sequence(name=name, value=start)
        session.add(row)
    row.value += 1
    session.flush()
    return row.value


def mint_journey_id(session: Session) -> str:
    return f"JRN-0-{next_sequence(session, 'journey', start=600000)}"


def mint_promotion_display_id(session: Session) -> int:
    return next_sequence(session, "promotion_display", start=740000)


def mint_draft_id(session: Session) -> int:
    return next_sequence(session, "journey_draft", start=630000)


def new_activity_id() -> str:
    return str(uuid.uuid4())


def new_webhook_id() -> str:
    return uuid.uuid4().hex


def collect_structural_ids(node) -> set[str]:
    """Walk a journey payload and collect UUID values of structural id keys."""
    found: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if (
                    key in STRUCTURAL_ID_KEYS
                    and isinstance(value, str)
                    and UUID_RE.match(value)
                ):
                    found.add(value)
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(node)
    return found


def regenerate_structural_ids(payload: dict) -> tuple[dict, dict[str, str]]:
    """Regenerate every structural UUID consistently across the whole payload.

    Matches the cloner mechanism from the source system: find UUIDs that are
    values of keys named ``activityId``/``id``, then string-replace old->new on
    the serialized JSON so *all* embedded references (nextActivityId,
    journeyActivityId, activitiesConfiguration keys, canvas edge endpoints,
    ports, handles) update together.
    """
    mapping = {old: str(uuid.uuid4()) for old in collect_structural_ids(payload)}
    text = json.dumps(payload)
    for old, new in mapping.items():
        text = text.replace(old, new)
    return json.loads(text), mapping
