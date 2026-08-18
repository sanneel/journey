"""Application configuration.

Everything is overridable through environment variables so the same code
runs as a local sandbox (SQLite, no auth) or something closer to a real
deployment (Postgres, API key).
"""
from __future__ import annotations

import os


class Settings:
    # SQLAlchemy database URL. SQLite file in the repo root by default.
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./journey.db")

    # Optional static bearer token. When set, every /api request must carry
    # `Authorization: Bearer <token>`. Empty = auth disabled (sandbox mode).
    api_token: str = os.environ.get("JOURNEY_API_TOKEN", "")

    # Default brand used when a payload does not carry one.
    default_brand: str = os.environ.get("JOURNEY_DEFAULT_BRAND", "JBCL")

    # How often (seconds) the background scheduler scans for due timers.
    scheduler_interval: float = float(os.environ.get("JOURNEY_SCHEDULER_INTERVAL", "1.0"))

    # Disable the background scheduler thread (tests drive timers manually).
    scheduler_enabled: bool = os.environ.get("JOURNEY_SCHEDULER_ENABLED", "1") not in (
        "0",
        "false",
        "no",
    )

    # Four-eyes publishing: journeys must be submitted for review and
    # approved by a second person before publish is allowed.
    require_approval: bool = os.environ.get("JOURNEY_REQUIRE_APPROVAL", "0") in (
        "1",
        "true",
        "yes",
    )


settings = Settings()
