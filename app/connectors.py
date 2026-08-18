"""Delivery connectors — where comms and rewards leave the building.

Two modes, chosen by ``CONNECTOR_MODE``:

  log      (default) the sandbox behaviour: the outbox/ledger row IS the
           delivery. Always succeeds.
  webhook  the production shape: every send/grant is POSTed to the
           casino platform's endpoints with retries and a timeout.
           A final failure is a real outcome — the engine routes the
           node's red path with the delivery error as detail.

The webhook payloads are self-describing (``type`` field), so one
receiver can multiplex, or point CONNECTOR_COMMS_URL / CONNECTOR_REWARDS_URL
at different systems (SMS gateway vs wallet API).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class DeliveryResult:
    ok: bool
    detail: str
    attempts: int


def _mode() -> str:
    return os.environ.get("CONNECTOR_MODE", "log")


def _timeout() -> float:
    return float(os.environ.get("CONNECTOR_TIMEOUT", "3"))


def _retries() -> int:
    return int(os.environ.get("CONNECTOR_RETRIES", "2"))


def _post(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"content-type": "application/json"},
    )
    token = os.environ.get("CONNECTOR_TOKEN")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=_timeout()) as response:
        response.read()


def _deliver(url_env: str, payload: dict) -> DeliveryResult:
    if _mode() != "webhook":
        return DeliveryResult(True, "logged (sandbox mode)", 1)
    url = os.environ.get(url_env)
    if not url:
        return DeliveryResult(False, f"{url_env} is not configured", 0)
    attempts = _retries() + 1
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            _post(url, payload)
            return DeliveryResult(True, f"delivered to platform", attempt)
        except urllib.error.HTTPError as error:
            last_error = f"HTTP {error.code}"
        except Exception as error:  # timeouts, refused connections, DNS
            last_error = type(error).__name__
        if attempt < attempts:
            time.sleep(0.2 * attempt)
    return DeliveryResult(False, f"{last_error} after {attempts} attempts", attempts)


def deliver_comms(
    *, message_id: int, channel: str, player_id: str, journey_id: str,
    activity_id: str, body: dict,
) -> DeliveryResult:
    return _deliver("CONNECTOR_COMMS_URL", {
        "type": "comms",
        "messageId": message_id,
        "channel": channel,
        "playerId": player_id,
        "journeyId": journey_id,
        "activityId": activity_id,
        "body": body,
    })


def deliver_reward(
    *, grant_id: int, reward_type: str, player_id: str, journey_id: str,
    activity_id: str, detail: dict, expires_at: str | None,
) -> DeliveryResult:
    return _deliver("CONNECTOR_REWARDS_URL", {
        "type": "reward",
        "grantId": grant_id,
        "rewardType": reward_type,
        "playerId": player_id,
        "journeyId": journey_id,
        "activityId": activity_id,
        "detail": detail,
        "expiresAt": expires_at,
    })
