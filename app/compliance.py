"""The compliance layer — the rules that make a CRM legally usable.

Three mechanisms, all enforced inside the engine (not the API surface,
so no route can forget them):

  exclusions      an active ``PlayerExclusion`` row is a hard wall:
                  the player cannot enter any journey, and no comms or
                  reward may be delivered to them — including tokens
                  already in flight when the exclusion was added.
  quiet hours     marketing channels (sms / email / push) are not sent
                  inside the configured UTC window; the message is
                  stored as ``Held`` and a release timer delivers it
                  when the window ends. On-site messages are exempt.
  frequency caps  at most N sends per channel per rolling 24 hours;
                  beyond the cap the message is ``Suppressed``.

Policy lives in the single-row ``CompliancePolicy`` table (absent row =
everything allowed), so it is operator-editable at runtime — not a
deploy-time constant.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .durations import utcnow
from .models import CommsMessage, CompliancePolicy, PlayerExclusion

# channels quiet hours apply to; the on-site bell/pop-up only shows when
# the player is already on the site, so it is exempt
QUIET_CHANNELS = ("sms", "email", "push")


def get_policy(session: Session) -> CompliancePolicy | None:
    return session.get(CompliancePolicy, 1)


def set_policy(
    session: Session,
    quiet_hours: dict | None,
    frequency_caps: dict | None,
) -> CompliancePolicy:
    policy = session.get(CompliancePolicy, 1)
    if policy is None:
        policy = CompliancePolicy(id=1)
        session.add(policy)
    policy.quiet_hours = quiet_hours
    policy.frequency_caps = frequency_caps
    session.flush()
    return policy


def active_exclusion(session: Session, player_id: str) -> PlayerExclusion | None:
    exclusion = session.get(PlayerExclusion, player_id)
    if exclusion is None:
        return None
    if exclusion.expires_at is not None:
        expires = exclusion.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= utcnow():
            return None
    return exclusion


def _parse_wall_clock(value: str) -> time | None:
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except (ValueError, AttributeError):
        return None


def quiet_hours_release(session: Session, channel: str, now: datetime | None = None) -> datetime | None:
    """If `now` falls inside the policy's quiet window for this channel,
    return the moment the window ends (= when a Held message may go out).
    None = sending is allowed right now."""
    if channel not in QUIET_CHANNELS:
        return None
    policy = get_policy(session)
    window = (policy.quiet_hours or {}) if policy else {}
    start = _parse_wall_clock(window.get("start", ""))
    end = _parse_wall_clock(window.get("end", ""))
    if start is None or end is None or start == end:
        return None
    now = now or utcnow()
    wall = now.timetz().replace(tzinfo=None)
    today_end = datetime.combine(now.date(), end, tzinfo=timezone.utc)
    if start < end:  # same-day window, e.g. 02:00–06:00
        if start <= wall < end:
            return today_end
        return None
    # crosses midnight, e.g. 21:00–09:00
    if wall >= start:
        return today_end + timedelta(days=1)
    if wall < end:
        return today_end
    return None


def frequency_cap_hit(
    session: Session,
    player_id: str,
    channel: str,
    exclude_message_id: int | None = None,
) -> int | None:
    """Returns the cap when this send would exceed it, else None.
    Held messages count (they will go out); Suppressed/Failed do not.
    The message being decided on is excluded from its own count."""
    policy = get_policy(session)
    caps = (policy.frequency_caps or {}) if policy else {}
    cap = caps.get(channel)
    if not isinstance(cap, (int, float)) or cap <= 0:
        return None
    since = utcnow() - timedelta(hours=24)
    query = select(CommsMessage.id).where(
        CommsMessage.player_id == player_id,
        CommsMessage.channel == channel,
        CommsMessage.status.notin_(("Suppressed", "Failed")),
        CommsMessage.created_at >= since,
    )
    if exclude_message_id is not None:
        query = query.where(CommsMessage.id != exclude_message_id)
    sent = len(session.execute(query).all())
    return int(cap) if sent >= cap else None
