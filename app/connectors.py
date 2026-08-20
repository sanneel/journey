"""Delivery connectors — where comms and rewards leave the building.

A journey grants a reward or sends a message; a **connector** carries it to
the real system that fulfils it. Different casinos use different systems, so
delivery is an **adapter** per provider, chosen per channel by environment.

Selection (each falls back to ``CONNECTOR_MODE`` when unset):

  rewards / wallet   CONNECTOR_REWARDS_PROVIDER   gr8 | webhook | log
  sms                CONNECTOR_SMS_PROVIDER       twilio | webhook | log
  email              CONNECTOR_EMAIL_PROVIDER     sendgrid | webhook | log
  push               CONNECTOR_PUSH_PROVIDER      webhook | log
  on-site            CONNECTOR_ONSITE_PROVIDER    webhook | log

  CONNECTOR_MODE     the fallback: ``log`` (default; the outbox/ledger row IS
                     the delivery, always succeeds) or ``webhook`` (POST the
                     self-describing payload to CONNECTOR_COMMS_URL /
                     CONNECTOR_REWARDS_URL — the casino's own gateway).

Provider adapters (`twilio`, `sendgrid`, `gr8`) speak each vendor's real HTTP
shape; the generic `webhook` posts our self-describing payload to a gateway
that resolves the player and fans out. Whatever the provider, a final failure
is a real outcome: the engine routes the node's red path with the error as
detail. Retries + backoff + timeout are shared across every adapter.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass
class DeliveryResult:
    ok: bool
    detail: str
    attempts: int


@dataclass
class HttpCall:
    url: str
    headers: dict
    body: bytes
    method: str = "POST"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _mode() -> str:
    return os.environ.get("CONNECTOR_MODE", "log")


def _timeout() -> float:
    return float(os.environ.get("CONNECTOR_TIMEOUT", "3"))


def _retries() -> int:
    return int(os.environ.get("CONNECTOR_RETRIES", "2"))


def _fallback_provider() -> str:
    return "webhook" if _mode() == "webhook" else "log"


def _message_text(body: dict) -> str:
    """Best-effort human message text from a comms body — plain messageText,
    then a notification_center localized tab, then a sensible default."""
    if not isinstance(body, dict):
        return ""
    if body.get("messageText"):
        return str(body["messageText"])
    tab = ((body.get("singleChannel") or {}).get("localizedLanguagesTab")) or {}
    for lang in ("en", "es"):
        entry = tab.get(lang) or {}
        for key in (f"des-{lang}", f"description_{lang}", f"caption-{lang}", f"title-{lang}"):
            if entry.get(key):
                return str(entry[key])
    return body.get("activityDisplayName") or "You have a new message"


def _http(call: HttpCall) -> tuple[int, str]:
    request = urllib.request.Request(
        call.url, data=call.body, method=call.method, headers=call.headers
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:  # 4xx/5xx still carry a body
        text = error.read().decode("utf-8", "replace") if error.fp else ""
        return error.code, text


# ── adapters ─────────────────────────────────────────────────────────


class Adapter:
    name = "base"

    def build(self, req: dict) -> HttpCall | DeliveryResult:
        raise NotImplementedError

    def ok(self, status: int, text: str) -> bool:
        return 200 <= status < 300


class LogAdapter(Adapter):
    name = "log"

    def build(self, req: dict) -> HttpCall | DeliveryResult:
        return DeliveryResult(True, "logged (sandbox mode)", 1)


class WebhookAdapter(Adapter):
    """The casino's own gateway: POST our self-describing payload; the gateway
    resolves the player to a wallet / phone / inbox and fans out."""

    name = "webhook"

    def __init__(self, url_env: str):
        self.url_env = url_env

    def build(self, req: dict) -> HttpCall | DeliveryResult:
        url = _env(self.url_env)
        if not url:
            return DeliveryResult(False, f"{self.url_env} is not configured", 0)
        headers = {"content-type": "application/json"}
        token = _env("CONNECTOR_TOKEN")
        if token:
            headers["authorization"] = f"Bearer {token}"
        return HttpCall(url, headers, json.dumps(req["payload"]).encode())


class TwilioAdapter(Adapter):
    """Twilio Messages API — form-encoded, Basic auth. Needs the player's
    phone (from player attributes: ``phone``)."""

    name = "twilio"

    def build(self, req: dict) -> HttpCall | DeliveryResult:
        sid, token, sender = _env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN"), _env("TWILIO_FROM")
        if not (sid and token and sender):
            return DeliveryResult(False, "twilio not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM)", 0)
        to = (req.get("contact") or {}).get("phone")
        if not to:
            return DeliveryResult(False, "twilio: no phone on the player record", 0)
        data = urllib.parse.urlencode(
            {"To": to, "From": sender, "Body": _message_text(req["body"])}
        ).encode()
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        return HttpCall(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            {"authorization": f"Basic {auth}", "content-type": "application/x-www-form-urlencoded"},
            data,
        )

    def ok(self, status: int, text: str) -> bool:
        return status in (200, 201)


class SendGridAdapter(Adapter):
    """SendGrid v3 mail/send — JSON, Bearer. Needs the player's email
    (from player attributes: ``email``)."""

    name = "sendgrid"

    def build(self, req: dict) -> HttpCall | DeliveryResult:
        key, sender = _env("SENDGRID_API_KEY"), _env("SENDGRID_FROM")
        if not (key and sender):
            return DeliveryResult(False, "sendgrid not configured (SENDGRID_API_KEY/FROM)", 0)
        to = (req.get("contact") or {}).get("email")
        if not to:
            return DeliveryResult(False, "sendgrid: no email on the player record", 0)
        body = req["body"] if isinstance(req["body"], dict) else {}
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": sender},
            "subject": body.get("subject") or "A message from your casino",
            "content": [{"type": "text/plain", "value": _message_text(body)}],
        }
        return HttpCall(
            "https://api.sendgrid.com/v3/mail/send",
            {"authorization": f"Bearer {key}", "content-type": "application/json"},
            json.dumps(payload).encode(),
        )

    def ok(self, status: int, text: str) -> bool:
        return status in (200, 202)


class Gr8WalletAdapter(Adapter):
    """The GR8 UBO wallet / bonus API — credits the reward against the player.
    No contact lookup needed; the wallet keys on player id."""

    name = "gr8"

    def build(self, req: dict) -> HttpCall | DeliveryResult:
        url = _env("GR8_WALLET_URL")
        if not url:
            return DeliveryResult(False, "gr8 wallet not configured (GR8_WALLET_URL)", 0)
        headers = {"content-type": "application/json"}
        token = _env("GR8_TOKEN")
        if token:
            headers["authorization"] = f"Bearer {token}"
        brand = _env("GR8_BRAND")
        if brand:
            headers["x-brand"] = brand
        payload = {
            "playerId": req["playerId"],
            "rewardType": req["rewardType"],
            "detail": req["detail"],
            "expiresAt": req.get("expiresAt"),
            "journeyId": req["journeyId"],
            "activityId": req["activityId"],
        }
        return HttpCall(url, headers, json.dumps(payload).encode())


def _make(provider: str, url_env: str) -> Adapter:
    if provider == "twilio":
        return TwilioAdapter()
    if provider == "sendgrid":
        return SendGridAdapter()
    if provider == "gr8":
        return Gr8WalletAdapter()
    if provider == "webhook":
        return WebhookAdapter(url_env)
    return LogAdapter()


_CHANNEL_PROVIDER_ENV = {
    "sms": "CONNECTOR_SMS_PROVIDER",
    "email": "CONNECTOR_EMAIL_PROVIDER",
    "push": "CONNECTOR_PUSH_PROVIDER",
    "onsite": "CONNECTOR_ONSITE_PROVIDER",
}


def _execute(adapter: Adapter, req: dict) -> DeliveryResult:
    built = adapter.build(req)
    if isinstance(built, DeliveryResult):  # misconfigured / short-circuit
        return built
    attempts = _retries() + 1
    last = ""
    for attempt in range(1, attempts + 1):
        try:
            status, text = _http(built)
            if adapter.ok(status, text):
                return DeliveryResult(True, f"{adapter.name}: delivered (HTTP {status})", attempt)
            last = f"{adapter.name} HTTP {status}"
        except Exception as error:  # timeout, refused connection, DNS
            last = f"{adapter.name} {type(error).__name__}"
        if attempt < attempts:
            time.sleep(0.2 * attempt)
    return DeliveryResult(False, f"{last} after {attempts} attempts", attempts)


# ── the two calls the engine makes ───────────────────────────────────


def deliver_comms(
    *, message_id: int, channel: str, player_id: str, journey_id: str,
    activity_id: str, body: dict, contact: dict | None = None,
) -> DeliveryResult:
    payload = {
        "type": "comms",
        "messageId": message_id,
        "channel": channel,
        "playerId": player_id,
        "journeyId": journey_id,
        "activityId": activity_id,
        "body": body,
    }
    provider = _env(_CHANNEL_PROVIDER_ENV.get(channel, "")) or _fallback_provider()
    adapter = _make(provider, url_env="CONNECTOR_COMMS_URL")
    return _execute(adapter, {
        "kind": "comms",
        "channel": channel,
        "playerId": player_id,
        "journeyId": journey_id,
        "activityId": activity_id,
        "body": body,
        "contact": contact or {},
        "payload": payload,
    })


def deliver_reward(
    *, grant_id: int, reward_type: str, player_id: str, journey_id: str,
    activity_id: str, detail: dict, expires_at: str | None,
) -> DeliveryResult:
    payload = {
        "type": "reward",
        "grantId": grant_id,
        "rewardType": reward_type,
        "playerId": player_id,
        "journeyId": journey_id,
        "activityId": activity_id,
        "detail": detail,
        "expiresAt": expires_at,
    }
    provider = _env("CONNECTOR_REWARDS_PROVIDER") or _fallback_provider()
    adapter = _make(provider, url_env="CONNECTOR_REWARDS_URL")
    return _execute(adapter, {
        "kind": "reward",
        "playerId": player_id,
        "rewardType": reward_type,
        "journeyId": journey_id,
        "activityId": activity_id,
        "detail": detail,
        "expiresAt": expires_at,
        "payload": payload,
    })
