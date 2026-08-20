"""P3 (deep): the delivery-connector adapters build the right provider
request and route per channel. No network — we inspect what each adapter
would send, and drive the executor with a fake transport."""
from __future__ import annotations

import base64
import json
import urllib.parse

import pytest

from app import connectors
from app.connectors import (
    Gr8WalletAdapter,
    HttpCall,
    SendGridAdapter,
    TwilioAdapter,
    WebhookAdapter,
    deliver_comms,
    deliver_reward,
)


# ── provider request shapes ─────────────────────────────────────────

def test_twilio_builds_messages_api_request(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxx")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("TWILIO_FROM", "+15550000000")
    call = TwilioAdapter().build({
        "contact": {"phone": "+15551234567"},
        "body": {"messageText": "Tus giros te esperan"},
    })
    assert isinstance(call, HttpCall)
    assert call.url == "https://api.twilio.com/2010-04-01/Accounts/ACxxx/Messages.json"
    assert call.headers["authorization"] == "Basic " + base64.b64encode(b"ACxxx:secret").decode()
    form = urllib.parse.parse_qs(call.body.decode())
    assert form["To"] == ["+15551234567"]
    assert form["From"] == ["+15550000000"]
    assert form["Body"] == ["Tus giros te esperan"]


def test_twilio_without_phone_fails_clearly(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxx")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setenv("TWILIO_FROM", "+15550000000")
    result = TwilioAdapter().build({"contact": {}, "body": {"messageText": "hi"}})
    assert result.ok is False
    assert "no phone" in result.detail


def test_twilio_unconfigured_fails_clearly(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    result = TwilioAdapter().build({"contact": {"phone": "+1"}, "body": {}})
    assert result.ok is False
    assert "not configured" in result.detail


def test_sendgrid_builds_v3_mail_send(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.key")
    monkeypatch.setenv("SENDGRID_FROM", "promos@casino.example")
    call = SendGridAdapter().build({
        "contact": {"email": "player@example.com"},
        "body": {"subject": "Weekly bonus", "messageText": "Claim it"},
    })
    assert call.url == "https://api.sendgrid.com/v3/mail/send"
    assert call.headers["authorization"] == "Bearer SG.key"
    payload = json.loads(call.body)
    assert payload["personalizations"][0]["to"][0]["email"] == "player@example.com"
    assert payload["from"]["email"] == "promos@casino.example"
    assert payload["subject"] == "Weekly bonus"
    assert payload["content"][0]["value"] == "Claim it"


def test_gr8_wallet_builds_bonus_credit(monkeypatch):
    monkeypatch.setenv("GR8_WALLET_URL", "https://wallet.example/bonus")
    monkeypatch.setenv("GR8_TOKEN", "jwt")
    monkeypatch.setenv("GR8_BRAND", "JBCL")
    call = Gr8WalletAdapter().build({
        "playerId": "nino", "rewardType": "freespin_bonus",
        "detail": {"spins": 50}, "expiresAt": None,
        "journeyId": "JRN-0-1", "activityId": "a1",
    })
    assert call.url == "https://wallet.example/bonus"
    assert call.headers["authorization"] == "Bearer jwt"
    assert call.headers["x-brand"] == "JBCL"
    payload = json.loads(call.body)
    assert payload["playerId"] == "nino"
    assert payload["detail"]["spins"] == 50


# ── per-channel routing ─────────────────────────────────────────────

def test_channel_routing_picks_the_right_adapter(monkeypatch, capture_calls):
    monkeypatch.setenv("CONNECTOR_SMS_PROVIDER", "twilio")
    monkeypatch.setenv("CONNECTOR_EMAIL_PROVIDER", "sendgrid")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "t")
    monkeypatch.setenv("TWILIO_FROM", "+1")
    monkeypatch.setenv("SENDGRID_API_KEY", "SG")
    monkeypatch.setenv("SENDGRID_FROM", "a@b.c")

    deliver_comms(message_id=1, channel="sms", player_id="p", journey_id="j",
                  activity_id="a", body={"messageText": "hi"}, contact={"phone": "+1999"})
    deliver_comms(message_id=2, channel="email", player_id="p", journey_id="j",
                  activity_id="a", body={"messageText": "hi"}, contact={"email": "p@e.com"})

    assert "api.twilio.com" in capture_calls[0].url
    assert "sendgrid.com" in capture_calls[1].url


def test_rewards_route_to_gr8(monkeypatch, capture_calls):
    monkeypatch.setenv("CONNECTOR_REWARDS_PROVIDER", "gr8")
    monkeypatch.setenv("GR8_WALLET_URL", "https://wallet.example/bonus")
    deliver_reward(grant_id=1, reward_type="freespin_bonus", player_id="p",
                   journey_id="j", activity_id="a", detail={"spins": 10}, expires_at=None)
    assert capture_calls[0].url == "https://wallet.example/bonus"


# ── the webhook fallback stays byte-compatible ──────────────────────

def test_webhook_fallback_posts_self_describing_payload(monkeypatch, capture_calls):
    monkeypatch.setenv("CONNECTOR_MODE", "webhook")
    monkeypatch.setenv("CONNECTOR_COMMS_URL", "http://gateway.example/comms")
    deliver_comms(message_id=7, channel="onsite", player_id="p", journey_id="j",
                  activity_id="a", body={"messageText": "hi"})
    call = capture_calls[0]
    assert call.url == "http://gateway.example/comms"
    payload = json.loads(call.body)
    assert payload["type"] == "comms"
    assert payload["messageId"] == 7


def test_log_mode_never_calls_network(monkeypatch, capture_calls):
    monkeypatch.setenv("CONNECTOR_MODE", "log")
    result = deliver_reward(grant_id=1, reward_type="freebet", player_id="p",
                            journey_id="j", activity_id="a", detail={}, expires_at=None)
    assert result.ok is True
    assert capture_calls == []  # nothing sent


@pytest.fixture()
def capture_calls(monkeypatch):
    """Replace the HTTP transport; record every HttpCall, answer 200."""
    calls: list = []

    def fake_http(call):
        calls.append(call)
        return 200, '{"accepted": true}'

    monkeypatch.setattr(connectors, "_http", fake_http)
    return calls
