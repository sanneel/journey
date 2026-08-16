"""Duration and date handling.

The wire format uses three different clocks; all are supported here:

  - ISO-8601 durations for waits / deposit windows / detector windows
    (``P0Y0M1DT0H0M0S`` = 1 day)
  - integer milliseconds for bonus expiries (``86400000`` = 24h)
  - two timestamp flavours: .NET fractional seconds
    (``2026-07-18T04:00:00.0000000Z``) at the top level, plain
    (``2026-07-18T04:00:00Z``) inside ``rawJourneyData.infoValues``.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def parse_iso_duration(value: str) -> timedelta:
    match = ISO_DURATION_RE.match(value.strip())
    if not match:
        raise ValueError(f"invalid ISO-8601 duration: {value!r}")
    parts = {k: float(v) for k, v in match.groupdict().items() if v is not None}
    days = (
        parts.get("years", 0) * 365
        + parts.get("months", 0) * 30
        + parts.get("weeks", 0) * 7
        + parts.get("days", 0)
    )
    return timedelta(
        days=days,
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
        seconds=parts.get("seconds", 0),
    )


def parse_timestamp(value: str) -> datetime:
    """Accept both wire timestamp flavours (and offsets)."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # .NET emits 7 fractional digits; Python accepts at most 6.
    text = re.sub(r"\.(\d{6})\d+(?=[+-])", r".\1", text)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_dotnet(moment: datetime) -> str:
    """Top-level journey fields use .NET style fractional seconds."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f0Z")


def format_plain(moment: datetime) -> str:
    """rawJourneyData.infoValues uses plain seconds."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
