"""One-line audit trail helper — every lifecycle and compliance action
lands in ``audit_log`` with who did it."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AuditLog


def record(
    session: Session,
    actor: str | None,
    action: str,
    journey_id: str | None = None,
    detail: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor=(actor or "operator")[:128],
            action=action,
            journey_id=journey_id,
            detail=detail[:512] if detail else None,
        )
    )
