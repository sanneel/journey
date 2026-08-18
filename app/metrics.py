"""In-process operational counters, served at /metrics in Prometheus
text format. Deliberately dependency-free; a real deployment can swap in
prometheus_client without touching call sites."""
from __future__ import annotations

import threading

_lock = threading.Lock()
_counters: dict[str, int] = {}

HELP = {
    "journey_activations_entered_total": "Players admitted into journeys",
    "journey_events_ingested_total": "Platform events accepted",
    "journey_events_duplicate_total": "Platform events rejected as duplicates (idempotency)",
    "journey_timers_fired_total": "Scheduler timers fired",
    "journey_comms_delivered_total": "Comms messages delivered",
    "journey_comms_failed_total": "Comms deliveries that exhausted retries",
    "journey_rewards_delivered_total": "Reward grants delivered",
    "journey_rewards_failed_total": "Reward deliveries that exhausted retries",
    "journey_published_total": "Journeys published",
}


def inc(name: str, amount: int = 1) -> None:
    with _lock:
        _counters[name] = _counters.get(name, 0) + amount


def render() -> str:
    lines = []
    with _lock:
        for name in sorted(HELP):
            lines.append(f"# HELP {name} {HELP[name]}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {_counters.get(name, 0)}")
    return "\n".join(lines) + "\n"
