"""SQLAlchemy models.

A journey is stored as a JSON document (matching the wire format of the
system this imitates) with a handful of indexed columns lifted out for
queries. Runtime state lives in its own tables.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Sequence(Base):
    """Monotonic counters behind JRN ids, draft ids and display ids."""

    __tablename__ = "sequences"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


class ReservedJourneyId(Base):
    """`POST /journeys/identifier` reserves a JRN before the draft exists."""

    __tablename__ = "reserved_journey_ids"

    journey_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    brand: Mapped[str] = mapped_column(String(16), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromotionDisplayId(Base):
    """Pre-minted promotion display identifiers (uniqueness enforced brand-wide)."""

    __tablename__ = "promotion_display_ids"

    display_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    brand: Mapped[str] = mapped_column(String(16), nullable=False)
    journey_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Journey(Base):
    __tablename__ = "journeys"

    # numeric draft id — what create returns and what PUT addresses
    draft_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    journey_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    brand: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    journey_name: Mapped[str] = mapped_column(String(256), nullable=False)
    # Draft -> Published -> Stopped; Archived is a side exit
    status: Mapped[str] = mapped_column(String(16), default="Draft", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    body: Mapped[dict] = mapped_column(JSON, nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_immediately_after_publish: Mapped[bool] = mapped_column(Boolean, default=True)
    is_unlimited: Mapped[bool] = mapped_column(Boolean, default=True)
    author: Mapped[str] = mapped_column(String(128), default="sandbox")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    duplicated_from_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # four-eyes review: None -> InReview -> Approved | Rejected. Any edit
    # resets it — approval covers exactly one body.
    approval_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(512), nullable=True)

    activations: Mapped[list["JourneyActivation"]] = relationship(back_populates="journey")

    __table_args__ = (Index("ix_journeys_brand_name", "brand", "journey_name"),)


class JourneyRevision(Base):
    """Immutable snapshot of a journey body per published version. In-flight
    activations resume against the revision they entered on; new entrants
    always get the journey's current body."""

    __tablename__ = "journey_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journey_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_revision_journey_version", "journey_id", "version", unique=True),
    )


class ActivityIdRegistry(Base):
    """activityIds are unique across all journeys of a brand — reusing one on
    a fresh draft is the classic un-regenerated-clone failure."""

    __tablename__ = "activity_id_registry"

    activity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    brand: Mapped[str] = mapped_column(String(16), primary_key=True)
    journey_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)


class Webhook(Base):
    """external_system_source entry points (the {journeyId, activityId} hand-off)."""

    __tablename__ = "webhooks"

    webhook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    journey_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    activity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_system: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    brand: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CLP")
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    # test players walk journeys for real but nothing leaves the building
    # and their runs are excluded from campaign numbers
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayerExclusion(Base):
    """The compliance list: self-excluded / vulnerable / cooling-off
    players. An active row is a hard wall — no journey entry, no comms,
    no rewards, anywhere."""

    __tablename__ = "player_exclusions"

    player_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # self_exclusion | vulnerable | cool_off
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    added_by: Mapped[str] = mapped_column(String(128), default="operator")
    # cool-off periods end; self-exclusion rows usually never do
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompliancePolicy(Base):
    """Single-row marketing policy: quiet hours and per-channel frequency
    caps. Absent row = everything allowed (sandbox default)."""

    __tablename__ = "compliance_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # {"start": "21:00", "end": "09:00"} — UTC wall-clock; None = off
    quiet_hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"sms": 3, "email": 5, ...} — max sends per channel per rolling 24h
    frequency_caps: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    """Who did what: journey lifecycle, approvals, compliance changes."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    journey_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JourneyActivation(Base):
    """One player's run through one journey — the walking token."""

    __tablename__ = "journey_activations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journey_id: Mapped[str] = mapped_column(ForeignKey("journeys.journey_id"), index=True)
    player_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # the journey version this run entered on — the walk finishes on this
    # version's body even if the journey is live-edited underneath it
    journey_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # copied from the player at entry: test runs are excluded from stats
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Active | Completed | Terminated
    status: Mapped[str] = mapped_column(String(16), default="Active", nullable=False)
    current_activity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_activity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    events_history: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    journey: Mapped[Journey] = relationship(back_populates="activations")

    __table_args__ = (Index("ix_activation_player_journey", "player_id", "journey_id"),)


class Timer(Base):
    """Scheduled wake-ups: wait_interval / wait_date / offer expiry /
    deposit window / detector window."""

    __tablename__ = "timers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activation_id: Mapped[int] = mapped_column(ForeignKey("journey_activations.id"), index=True)
    activity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # wait | offer_expiry | deposit_window | detector_window | bet_window
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    fired: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromotionOffer(Base):
    """A promotion activity presented to a player, awaiting accept/expire."""

    __tablename__ = "promotion_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activation_id: Mapped[int] = mapped_column(ForeignKey("journey_activations.id"), index=True)
    activity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    player_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # Offered | Accepted | Expired
    status: Mapped[str] = mapped_column(String(16), default="Offered", nullable=False)
    promotion_display_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # bonus T&C shown with the offer (wagering, expiry, max win) — the
    # significant-terms disclosure regulators require next to any "free"
    terms: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RewardGrant(Base):
    """The reward ledger — what the journeys actually deliver."""

    __tablename__ = "reward_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activation_id: Mapped[int] = mapped_column(ForeignKey("journey_activations.id"), index=True)
    player_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    journey_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    activity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # freespin_bonus | casino_bonus_v2 | freebet | sport_bonus
    reward_type: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    # Awarded | Failed (connector exhausted retries) | Suppressed (compliance)
    status: Mapped[str] = mapped_column(String(16), default="Awarded", nullable=False)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_detail: Mapped[str | None] = mapped_column(String(256), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommsMessage(Base):
    """Outbox for notification_center / SMS / email / push sends."""

    __tablename__ = "comms_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activation_id: Mapped[int] = mapped_column(ForeignKey("journey_activations.id"), index=True)
    player_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    journey_id: Mapped[str] = mapped_column(String(32), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    # Sent -> Shown -> Read -> Clicked (monotonic ladder); Failed = the
    # connector exhausted its retries; Held = parked until quiet hours
    # end; Suppressed = compliance blocked it (exclusion / frequency cap)
    status: Mapped[str] = mapped_column(String(16), default="Sent", nullable=False)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    body: Mapped[dict] = mapped_column(JSON, default=dict)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_detail: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    engaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformEvent(Base):
    """Ingested platform events (deposit.approved, bet.settled, ...)."""

    __tablename__ = "platform_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # optional client-supplied idempotency key: the same eventId is
    # accepted once and acknowledged as a duplicate afterwards
    event_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    event_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False, default="platform")
    player_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ParkedSubscription(Base):
    """A parked activity (deposit / event_detector / bet) waiting for a
    platform event for a specific activation."""

    __tablename__ = "parked_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activation_id: Mapped[int] = mapped_column(ForeignKey("journey_activations.id"), index=True)
    activity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    player_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    activity_name: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
