"""The journey runtime — the mechanism that actually moves players.

A published journey is a node graph. A player enters through an Input
Source, which fires the ``PlayerAdded`` activation event into the first
real activity. From there the engine walks ``events[].nextActivityId``:

  - *instant* activities (comms, rewards, splits, connectors) do their work
    and immediately follow their happy-path Completion event;
  - *parked* activities (waits, offers, deposit / bet conditions, event
    detectors) stop the token and register either a timer, a platform-event
    subscription, or both — whichever resolves first decides which
    Completion event the token leaves through;
  - *terminals* end the path / the journey.

Boundary events are recorded on the activation's ``eventsHistory`` as they
happen (they never move the token — they are attachment points).

Everything the engine does is observable: reward grants land in the ledger,
comms land in the outbox, and every event ever fired is on the activation.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import metrics
from .catalog import SOURCE_TYPES, spec_for
from .compliance import active_exclusion, frequency_cap_hit, quiet_hours_release
from .config import settings
from .connectors import deliver_comms, deliver_reward
from .durations import parse_iso_duration, parse_timestamp, utcnow
from .ids import new_webhook_id
from .models import (
    CommsMessage,
    Journey,
    JourneyActivation,
    JourneyRevision,
    ParkedSubscription,
    PlatformEvent,
    Player,
    PromotionOffer,
    RewardGrant,
    Timer,
    Webhook,
)

MAX_STEPS_PER_ADVANCE = 500  # cycle guard for one synchronous walk


class EngineError(Exception):
    def __init__(self, slug: str, detail: str = ""):
        super().__init__(detail or slug)
        self.slug = slug
        self.detail = detail


# ── small helpers ────────────────────────────────────────────────────


def activity_index(journey: Journey) -> dict[str, dict]:
    return {
        a["activityId"]: a
        for a in journey.body.get("activities", [])
        if a.get("activityId")
    }


def entry_sources(journey: Journey) -> list[dict]:
    return [
        a
        for a in journey.body.get("activities", [])
        if a.get("activityName") in SOURCE_TYPES
    ]


def _event_on(activity: dict, event_name: str) -> dict | None:
    for event in activity.get("events") or []:
        if event.get("eventName") == event_name:
            return event
    return None


def _compare(op: str, actual: Any, expected: Any) -> bool:
    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    if op in ("eq", "equal", "equals"):
        return str(actual) == str(expected) or num(actual) == num(expected)
    if op in ("neq", "notEqual"):
        return not _compare("eq", actual, expected)
    if op in ("in",):
        return actual in expected if isinstance(expected, (list, tuple)) else False
    if op in ("contains",):
        return str(expected) in str(actual)
    a, b = num(actual), num(expected)
    if a is None or b is None:
        return False
    if op in ("lt", "lessThan", "lessThanCurrency"):
        return a < b
    if op in ("lte", "lessThanOrEqual", "lessThanOrEqualCurrency"):
        return a <= b
    if op in ("gt", "greaterThan", "greaterThanCurrency"):
        return a > b
    if op in ("gte", "greaterThanOrEqual", "greaterThanOrEqualCurrency"):
        return a >= b
    return False


def _lookup(properties: dict, dotted: str) -> Any:
    """Resolve ``a.b.c`` against a dict; falls back to the last segment."""
    node: Any = properties
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            node = None
            break
    if node is None and "." in dotted:
        return properties.get(dotted.rsplit(".", 1)[-1])
    if node is None:
        return properties.get(dotted)
    return node


def _matches_filter(filter_spec: dict | None, properties: dict) -> bool:
    """The shared filter grammar: {property: {name,type,value,operator}, variables[]}."""
    if not filter_spec:
        return True
    prop = filter_spec.get("property") or {}
    if not prop.get("name"):
        return True
    actual = _lookup(properties, prop["name"])
    if not _compare(prop.get("operator", "eq"), actual, prop.get("value")):
        return False
    # currency-flavoured operators carry the currency in variables
    for variable in filter_spec.get("variables") or []:
        if variable.get("type") in ("currency", "currencyCode") or variable.get(
            "name"
        ) in ("currency", "currencyCode"):
            event_currency = properties.get("currencyCode") or properties.get("currency")
            if event_currency and str(event_currency) != str(variable.get("value")):
                return False
    return True


class Engine:
    def __init__(self, session: Session):
        self.session = session

    # ── lifecycle ────────────────────────────────────────────────────

    def register_webhooks(self, journey: Journey) -> list[dict]:
        webhooks: list[dict] = []
        for activity in entry_sources(journey):
            if activity.get("activityName") != "external_system_source":
                continue
            init = activity.setdefault("initializationData", {})
            webhook_id = init.get("webhookId") or new_webhook_id()
            init["webhookId"] = webhook_id
            existing = self.session.get(Webhook, webhook_id)
            if existing is None:
                self.session.add(
                    Webhook(
                        webhook_id=webhook_id,
                        journey_id=journey.journey_id,
                        activity_id=activity["activityId"],
                        target_system=init.get("targetSystem"),
                    )
                )
            webhooks.append(
                {
                    "webhookId": webhook_id,
                    "activityId": activity["activityId"],
                    "targetSystem": init.get("targetSystem"),
                }
            )
        journey.body = dict(journey.body)  # force JSON column update
        return webhooks

    def snapshot_revision(self, journey: Journey) -> None:
        """Freeze the current body as this version's immutable revision —
        the body in-flight players will finish on."""
        existing = self.session.execute(
            select(JourneyRevision).where(
                JourneyRevision.journey_id == journey.journey_id,
                JourneyRevision.version == journey.version,
            )
        ).scalar_one_or_none()
        if existing is None:
            self.session.add(
                JourneyRevision(
                    journey_id=journey.journey_id,
                    version=journey.version,
                    body=journey.body,
                )
            )

    def publish(self, journey: Journey) -> dict:
        if journey.status not in ("Draft", "Stopped"):
            raise EngineError(
                "journey-not-publishable", f"status is {journey.status}"
            )
        if settings.require_approval and journey.approval_state != "Approved":
            raise EngineError(
                "journey-not-approved",
                "approval is required: submit for review and have a second "
                "person approve before publishing",
            )
        webhooks = self.register_webhooks(journey)
        journey.status = "Published"
        journey.version += 1
        self.snapshot_revision(journey)
        metrics.inc("journey_published_total")
        self.session.flush()
        return {"journeyId": journey.journey_id, "status": "Published", "webhooks": webhooks}

    def stop(self, journey: Journey, mode: str = "terminate") -> dict:
        """terminate: end every active run now. drain: close the doors —
        no new entries — and let in-flight players finish; the journey
        flips to Stopped by itself once the last one completes."""
        if mode == "drain":
            journey.status = "Stopping"
            active = len(
                self.session.execute(
                    select(JourneyActivation.id).where(
                        JourneyActivation.journey_id == journey.journey_id,
                        JourneyActivation.status == "Active",
                    )
                ).all()
            )
            if active == 0:
                journey.status = "Stopped"
            self.session.flush()
            return {
                "journeyId": journey.journey_id,
                "status": journey.status,
                "draining": active,
            }
        journey.status = "Stopped"
        activations = (
            self.session.execute(
                select(JourneyActivation).where(
                    JourneyActivation.journey_id == journey.journey_id,
                    JourneyActivation.status == "Active",
                )
            )
            .scalars()
            .all()
        )
        for activation in activations:
            activation.status = "Terminated"
            self._deactivate_waiting(activation)
        self.session.flush()
        return {
            "journeyId": journey.journey_id,
            "status": "Stopped",
            "terminatedActivations": len(activations),
        }

    # ── entry ────────────────────────────────────────────────────────

    def enter(
        self,
        journey: Journey,
        entry_activity_id: str,
        player_id: str,
        context: dict | None = None,
    ) -> JourneyActivation:
        if journey.status != "Published":
            raise EngineError(
                "journey-not-published",
                f"{journey.journey_id} is {journey.status}; players can only "
                "enter a published journey.",
            )
        now = utcnow()
        if journey.stop_at is not None and now > self._aware(journey.stop_at):
            raise EngineError("journey-window-closed", "stopAt has passed")
        if (
            journey.start_at is not None
            and not journey.is_immediately_after_publish
            and now < self._aware(journey.start_at)
        ):
            raise EngineError("journey-window-not-open", "startAt is in the future")

        index = activity_index(journey)
        entry = index.get(entry_activity_id)
        if entry is None or entry.get("activityName") not in SOURCE_TYPES:
            raise EngineError(
                "entry-activity-not-a-source",
                f"{entry_activity_id} is not an Input Source of {journey.journey_id}",
            )

        exclusion = active_exclusion(self.session, player_id)
        if exclusion is not None:
            metrics.inc("journey_entries_blocked_total")
            raise EngineError(
                "player-excluded",
                f"{player_id} is on the exclusion list ({exclusion.reason}); "
                "excluded players cannot enter any journey",
            )
        self._check_reentry(journey, player_id)
        player = self._ensure_player(player_id, journey.brand)

        activation = JourneyActivation(
            journey_id=journey.journey_id,
            player_id=player_id,
            journey_version=journey.version,
            is_test=player.is_test,
            entry_activity_id=entry_activity_id,
            current_activity_id=entry_activity_id,
            context=context or {},
        )
        self.session.add(activation)
        self.session.flush()
        metrics.inc("journey_activations_entered_total")

        self._record(
            activation,
            entry_activity_id,
            "PlayerAdded",
            "Activation",
            f"entered via {entry.get('activityName')}",
        )
        event = _event_on(entry, "PlayerAdded")
        next_id = event.get("nextActivityId") if event else None
        if next_id is None:
            self._complete(activation, "end_of_path")
        else:
            self._run(activation, journey, index, next_id)
        self.session.flush()
        return activation

    def _check_reentry(self, journey: Journey, player_id: str) -> None:
        rule = (journey.body.get("reEntryRule") or {}).get("reEntryMode", "Prohibited")
        existing = (
            self.session.execute(
                select(JourneyActivation).where(
                    JourneyActivation.journey_id == journey.journey_id,
                    JourneyActivation.player_id == player_id,
                )
            )
            .scalars()
            .all()
        )
        active = [a for a in existing if a.status == "Active"]
        if active:
            raise EngineError(
                "player-already-in-journey",
                f"{player_id} already has an active run in {journey.journey_id}",
            )
        if rule == "Prohibited" and existing:
            raise EngineError(
                "re-entry-prohibited",
                f"reEntryMode=Prohibited and {player_id} has already been through "
                f"{journey.journey_id}",
            )

    def _ensure_player(self, player_id: str, brand: str) -> Player:
        player = self.session.get(Player, player_id)
        if player is None:
            player = Player(player_id=player_id, brand=brand)
            self.session.add(player)
            self.session.flush()
        return player

    @staticmethod
    def _aware(moment: datetime) -> datetime:
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    # ── the walk ─────────────────────────────────────────────────────

    def _run(
        self,
        activation: JourneyActivation,
        journey: Journey,
        index: dict[str, dict],
        activity_id: str,
    ) -> None:
        steps = 0
        current: str | None = activity_id
        while current is not None:
            steps += 1
            if steps > MAX_STEPS_PER_ADVANCE:
                raise EngineError(
                    "journey-cycle-detected",
                    f"{journey.journey_id} walked {steps} steps without parking",
                )
            activation.current_activity_id = current
            activity = index.get(current)
            if activity is None:
                raise EngineError(
                    "transition-target-not-found", f"activity {current} missing"
                )
            result = self._enter_activity(activation, journey, index, activity)
            outcome, argument, detail = (*result, None)[:3]
            if outcome == "move":
                current = self._follow(activation, activity, argument, detail)
            elif outcome == "park":
                return
            elif outcome == "end":
                self._complete(activation, argument)
                return

    def _follow(
        self,
        activation: JourneyActivation,
        activity: dict,
        event_name: str,
        detail: str | None = None,
    ) -> str | None:
        self._record(
            activation, activity["activityId"], event_name, "Completion", detail
        )
        event = _event_on(activity, event_name)
        next_id = event.get("nextActivityId") if event else None
        if next_id is None:
            self._complete(activation, "end_of_path")
        return next_id

    def _complete(self, activation: JourneyActivation, how: str) -> None:
        activation.status = "Completed"
        activation.context = {**(activation.context or {}), "completedVia": how}
        self._deactivate_waiting(activation)
        self._maybe_finish_draining(activation.journey_id)

    def _maybe_finish_draining(self, journey_id: str) -> None:
        self.session.flush()  # the just-completed run must be visible to the count
        journey = self.session.execute(
            select(Journey).where(Journey.journey_id == journey_id)
        ).scalar_one_or_none()
        if journey is None or journey.status != "Stopping":
            return
        remaining = self.session.execute(
            select(JourneyActivation.id).where(
                JourneyActivation.journey_id == journey_id,
                JourneyActivation.status == "Active",
            )
        ).first()
        if remaining is None:
            journey.status = "Stopped"

    def _record(
        self,
        activation: JourneyActivation,
        activity_id: str,
        event_name: str,
        event_type: str,
        detail: str | None = None,
    ) -> None:
        history = list(activation.events_history or [])
        entry = {
            "activityId": activity_id,
            "eventName": event_name,
            "eventType": event_type,
            "occurredAt": utcnow().isoformat(),
        }
        if detail:
            entry["detail"] = detail
        history.append(entry)
        activation.events_history = history

    # ── activity handlers ────────────────────────────────────────────

    def _enter_activity(
        self,
        activation: JourneyActivation,
        journey: Journey,
        index: dict[str, dict],
        activity: dict,
    ) -> tuple:
        """Returns ("move", event_name[, detail]) | ("park", kind) |
        ("end", terminal). `detail` is the human-readable record of what
        the node actually did."""
        name = activity.get("activityName", "")
        spec = spec_for(name)
        if spec is None:
            raise EngineError("unknown-activity-type", name)
        kind = spec["kind"]
        init = activity.get("initializationData") or {}

        if kind == "source":
            # a source mid-graph just relays the token
            return "move", "PlayerAdded"
        if kind == "terminal":
            return "end", name
        if kind == "offer":
            return self._enter_offer(activation, activity, init)
        if kind == "comms":
            return self._enter_comms(activation, journey, activity, init, spec)
        if kind == "reward":
            return self._enter_reward(activation, journey, activity, init, spec)
        if kind == "split":
            return self._enter_split(activation, activity, init, name)
        if kind == "connector":
            return self._enter_connector(activation, activity, init)
        if kind == "parked":
            return self._enter_parked(activation, activity, init, name)
        raise EngineError("unknown-activity-kind", kind)

    # promotions ------------------------------------------------------

    def _enter_offer(
        self, activation: JourneyActivation, activity: dict, init: dict
    ) -> tuple[str, str]:
        offer = PromotionOffer(
            activation_id=activation.id,
            activity_id=activity["activityId"],
            player_id=activation.player_id,
            promotion_display_id=init.get("promotionDisplayId"),
            # significant terms travel with the offer so any front end
            # can show them next to the "free" (regulators require it)
            terms=init.get("terms") or init.get("termsAndConditions"),
        )
        self.session.add(offer)
        self.session.flush()
        self._record(
            activation,
            activity["activityId"],
            "PromotionOffered",
            "Boundary",
            f"offer #{offer.id} presented to {activation.player_id}",
        )

        if init.get("autoAccept"):
            offer.status = "Accepted"
            offer.resolved_at = utcnow()
            return "move", "PromotionAccepted", f"offer #{offer.id} auto-accepted"

        time_to_accept = init.get("timeToAccept")
        due = self._parse_window(time_to_accept)
        if due is not None:
            self.session.add(
                Timer(
                    activation_id=activation.id,
                    activity_id=activity["activityId"],
                    kind="offer_expiry",
                    due_at=utcnow() + due,
                    payload={"offerId": offer.id},
                )
            )
        return "park", "offer"

    def accept_offer(self, offer: PromotionOffer) -> JourneyActivation:
        if offer.status != "Offered":
            raise EngineError("offer-already-resolved", offer.status)
        activation = self.session.get(JourneyActivation, offer.activation_id)
        if activation is None or activation.status != "Active":
            raise EngineError("activation-not-active")
        offer.status = "Accepted"
        offer.resolved_at = utcnow()
        self._cancel_timers(activation, offer.activity_id)
        self._resume(
            activation,
            offer.activity_id,
            "PromotionAccepted",
            detail=f"offer #{offer.id} accepted by player",
        )
        return activation

    # comms -----------------------------------------------------------

    def _enter_comms(
        self,
        activation: JourneyActivation,
        journey: Journey,
        activity: dict,
        init: dict,
        spec: dict,
    ) -> tuple[str, str]:
        body: dict[str, Any] = {"activityDisplayName": activity.get("activityDisplayName")}
        raw_values = init.get("rawValues")
        if isinstance(raw_values, dict) and raw_values.get("messageText"):
            body["messageText"] = raw_values["messageText"]
        if init.get("templates"):
            body["templates"] = init["templates"]
        if init.get("emailSettings"):
            body["emailSettings"] = init["emailSettings"]
        if init.get("contract") is not None:
            # contract 1 = bell notification, 5 = pop-up
            body["contract"] = init["contract"]
        message = CommsMessage(
            activation_id=activation.id,
            player_id=activation.player_id,
            journey_id=journey.journey_id,
            activity_id=activity["activityId"],
            channel=spec.get("channel", "onsite"),
            status="Sent",
            is_test=activation.is_test,
            body=body,
        )
        self.session.add(message)
        self.session.flush()

        # compliance gates run before anything leaves the building
        exclusion = active_exclusion(self.session, message.player_id)
        if exclusion is not None:
            message.status = "Suppressed"
            message.delivery_detail = f"suppressed: player excluded ({exclusion.reason})"
            metrics.inc("journey_comms_suppressed_total")
            return (
                "move",
                spec["happy_path"],
                f"{message.channel} message #{message.id} suppressed — "
                f"player is on the exclusion list",
            )
        cap = frequency_cap_hit(
            self.session, message.player_id, message.channel,
            exclude_message_id=message.id,
        )
        if cap is not None:
            message.status = "Suppressed"
            message.delivery_detail = f"suppressed: frequency cap {cap}/24h on {message.channel}"
            metrics.inc("journey_comms_suppressed_total")
            return (
                "move",
                spec["happy_path"],
                f"{message.channel} message #{message.id} suppressed — "
                f"frequency cap ({cap} per 24h) reached",
            )
        release_at = quiet_hours_release(self.session, message.channel)
        if release_at is not None:
            message.status = "Held"
            message.delivery_detail = (
                f"held: quiet hours — release at {release_at.isoformat(timespec='minutes')}"
            )
            self.session.add(
                Timer(
                    activation_id=activation.id,
                    activity_id=message.activity_id,
                    kind="comms_release",
                    due_at=release_at,
                    payload={"messageId": message.id},
                )
            )
            metrics.inc("journey_comms_held_total")
            return (
                "move",
                spec["happy_path"],
                f"{message.channel} message #{message.id} held until quiet "
                f"hours end ({release_at.strftime('%H:%M')} UTC)",
            )
        if activation.is_test:
            message.delivery_detail = "test player — not delivered to platform"
            metrics.inc("journey_comms_delivered_total")
            return (
                "move",
                spec["happy_path"],
                f"{message.channel} message #{message.id} — test player, "
                "delivery skipped",
            )

        result = deliver_comms(
            message_id=message.id,
            channel=message.channel,
            player_id=message.player_id,
            journey_id=message.journey_id,
            activity_id=message.activity_id,
            body=body,
        )
        message.delivery_attempts = result.attempts
        message.delivery_detail = result.detail
        if not result.ok:
            message.status = "Failed"
            metrics.inc("journey_comms_failed_total")
            return (
                "move",
                spec.get("failure_path") or spec["happy_path"],
                f"{message.channel} delivery failed: {result.detail}",
            )
        metrics.inc("journey_comms_delivered_total")
        return (
            "move",
            spec["happy_path"],
            f"{message.channel} message #{message.id} — {result.detail}",
        )

    def engage_comms(self, message: CommsMessage, action: str) -> CommsMessage:
        ladder = ["Sent", "Shown", "Read", "Clicked"]
        target = {"show": "Shown", "read": "Read", "click": "Clicked"}.get(action)
        if target is None:
            raise EngineError("unknown-engagement-action", action)
        if message.status not in ladder:
            raise EngineError(
                "message-not-engageable",
                f"message #{message.id} is {message.status} — it was never delivered",
            )
        if ladder.index(target) > ladder.index(message.status):
            message.status = target
            message.engaged_at = utcnow()
        return message

    # rewards ---------------------------------------------------------

    def _enter_reward(
        self,
        activation: JourneyActivation,
        journey: Journey,
        activity: dict,
        init: dict,
        spec: dict,
    ) -> tuple[str, str]:
        name = activity["activityName"]
        detail: dict[str, Any] = {}
        expires_at = None
        if name == "freespin_bonus":
            freespin = init.get("freespinActivity") or {}
            detail = {
                "spins": freespin.get("spins"),
                "provider": freespin.get("provider"),
                "lobbyGameId": freespin.get("lobbyGameId"),
                "currenciesConfig": freespin.get("currenciesConfig"),
            }
            expiry_ms = freespin.get("spinsExpirationDuration")
            if isinstance(expiry_ms, (int, float)) and expiry_ms > 0:
                expires_at = utcnow() + timedelta(milliseconds=expiry_ms)
        elif name == "casino_bonus_v2":
            detail = {
                "bonusPercent": init.get("bonusPercent"),
                "wageringRequirement": init.get("wageringRequirement"),
                "productType": init.get("productType"),
                "currenciesConfig": init.get("currenciesConfig"),
            }
            expiry_ms = init.get("bonusExpirationTime")
            if isinstance(expiry_ms, (int, float)) and expiry_ms > 0:
                expires_at = utcnow() + timedelta(milliseconds=expiry_ms)
        elif name == "money_bonus":
            amounts = init.get("currencyAmounts") or []
            first = amounts[0] if amounts else {}
            detail = {
                "amount": first.get("amount"),
                "currencyCode": first.get("currencyCode"),
                "accrualType": init.get("amountAccrualType"),
                "transactionTitle": init.get("transactionTitle"),
            }
        else:  # freebet / sport_bonus
            detail = {"properties": init.get("properties")}

        grant = RewardGrant(
            activation_id=activation.id,
            player_id=activation.player_id,
            journey_id=journey.journey_id,
            activity_id=activity["activityId"],
            reward_type=name,
            detail=detail,
            is_test=activation.is_test,
            expires_at=expires_at,
        )
        self.session.add(grant)
        self.session.flush()

        # awarding a bonus to an excluded player is prohibited — the grant
        # is suppressed and the token takes the activity's failure path,
        # exactly as if the platform had rejected it
        exclusion = active_exclusion(self.session, grant.player_id)
        if exclusion is not None:
            grant.status = "Suppressed"
            grant.delivery_detail = f"suppressed: player excluded ({exclusion.reason})"
            metrics.inc("journey_rewards_suppressed_total")
            failed_boundary = {
                "freespin_bonus": "FreespinBonusAwardFailed",
                "casino_bonus_v2": "WageringBonusAwardFailed",
            }.get(name)
            if failed_boundary:
                self._record(
                    activation,
                    activity["activityId"],
                    failed_boundary,
                    "Boundary",
                    f"grant #{grant.id} suppressed — player is on the exclusion list",
                )
            return (
                "move",
                spec.get("failure_path") or "end_of_path",
                f"{name} suppressed: player excluded ({exclusion.reason})",
            )

        if activation.is_test:
            grant.delivery_detail = "test player — not delivered to platform"
            result = None
        else:
            result = deliver_reward(
                grant_id=grant.id,
                reward_type=name,
                player_id=grant.player_id,
                journey_id=grant.journey_id,
                activity_id=grant.activity_id,
                detail=detail,
                expires_at=expires_at.isoformat() if expires_at else None,
            )
            grant.delivery_attempts = result.attempts
            grant.delivery_detail = result.detail
            if not result.ok:
                grant.status = "Failed"
                metrics.inc("journey_rewards_failed_total")
                failed_boundary = {
                    "freespin_bonus": "FreespinBonusAwardFailed",
                    "casino_bonus_v2": "WageringBonusAwardFailed",
                }.get(name)
                if failed_boundary:
                    self._record(
                        activation,
                        activity["activityId"],
                        failed_boundary,
                        "Boundary",
                        f"platform rejected grant #{grant.id}: {result.detail}",
                    )
                return (
                    "move",
                    spec.get("failure_path") or "end_of_path",
                    f"{name} delivery failed: {result.detail}",
                )
        metrics.inc("journey_rewards_delivered_total")

        if name == "freespin_bonus":
            granted = f"granted {detail.get('spins')} free spins (grant #{grant.id})"
        elif name == "casino_bonus_v2":
            granted = f"granted {detail.get('bonusPercent')}% match bonus (grant #{grant.id})"
        elif name == "money_bonus":
            amount = detail.get("amount")
            money = f"{amount / 100:g} {detail.get('currencyCode') or ''}".strip() if amount else "cash"
            granted = f"accrued {money} money bonus (grant #{grant.id})"
        else:
            granted = f"granted {name} (grant #{grant.id})"
        if activation.is_test:
            granted += " — test player, delivery skipped"
        if spec.get("grant_boundary"):
            self._record(
                activation,
                activity["activityId"],
                spec["grant_boundary"],
                "Boundary",
                granted,
            )

        # follow the happy path if it is wired; otherwise the first wired
        # Completion event; otherwise the path simply ends here
        happy = spec.get("happy_path")
        if happy and _event_on(activity, happy) is not None:
            return "move", happy, granted
        for event in activity.get("events") or []:
            if event.get("eventType") == "Completion" and event.get("nextActivityId"):
                return "move", event["eventName"], granted
        return "move", happy or "end_of_path", granted

    # splits ----------------------------------------------------------

    def _enter_split(
        self, activation: JourneyActivation, activity: dict, init: dict, name: str
    ) -> tuple[str, str]:
        pathes_config = init.get("pathesConfig") or []

        if name == "ams_decision_split":
            player = self.session.get(Player, activation.player_id)
            attributes = dict(player.attributes or {}) if player else {}
            attributes.update(activation.context or {})
            rules = init.get("rules") or []
            for position, rule in enumerate(rules):
                if _matches_filter(rule.get("filter"), attributes):
                    return (
                        "move",
                        self._split_event(
                            pathes_config, position, f"DecisionSplitPassedPath{position + 1:02d}"
                        ),
                        f"rule '{rule.get('name', position + 1)}' matched",
                    )
            return (
                "move",
                "DecisionSplitPassedRemainderPath",
                "no rule matched — remainder path",
            )

        if name == "random_split":
            paths = init.get("paths") or []
            weights = [float(p.get("probability", 0)) for p in paths]
            if not paths or sum(weights) <= 0:
                raise EngineError("random-split-has-no-paths")
            position = random.choices(range(len(paths)), weights=weights, k=1)[0]
            return (
                "move",
                self._split_event(
                    pathes_config, position, f"RandomSplitPassedPath{position + 1}"
                ),
                f"rolled '{paths[position].get('pathName', position + 1)}' "
                f"({weights[position]:g}%)",
            )

        # engagement splits: branch on the delivery status of an upstream
        # comms activity for this same activation
        properties = init.get("properties") or {}
        target_activity = (
            properties.get("DextraNotificationCenterActivityId")
            or properties.get("DextraEmailActivityId")
            or properties.get("activityId")
        )
        status = "NotSent"
        query = select(CommsMessage).where(
            CommsMessage.activation_id == activation.id
        )
        if target_activity:
            query = query.where(CommsMessage.activity_id == target_activity)
        message = self.session.execute(
            query.order_by(CommsMessage.id.desc())
        ).scalars().first()
        if message is not None:
            status = message.status

        paths = properties.get("paths") or []
        for position, path in enumerate(paths):
            statuses = (
                path.get("notificationCenterEngagementStatuses")
                or path.get("engagementStatuses")
                or []
            )
            if status in statuses:
                config_position = self._path_position(pathes_config, path, position)
                default = (
                    f"NCEngagementSplitPassedPath{config_position + 1:02d}"
                    if name == "notification_center_engagement_split"
                    else f"Path{config_position + 1}"
                )
                return (
                    "move",
                    self._split_event(pathes_config, config_position, default),
                    f"message status was {status} — path '{path.get('pathName', config_position + 1)}'",
                )
        # nothing matched: last wired completion event acts as the remainder
        for event in reversed(activity.get("events") or []):
            if event.get("eventType") == "Completion":
                return "move", event["eventName"], f"message status was {status} (no matching path)"
        raise EngineError("engagement-split-has-no-paths")

    @staticmethod
    def _path_position(pathes_config: list, path: dict, fallback: int) -> int:
        path_id = path.get("pathId")
        for position, config in enumerate(pathes_config):
            if config.get("pathId") == path_id:
                return position
        return fallback

    @staticmethod
    def _split_event(pathes_config: list, position: int, default: str) -> str:
        if position < len(pathes_config):
            events = pathes_config[position].get("events") or []
            if events and events[0].get("eventName"):
                return events[0]["eventName"]
        return default

    # connector -------------------------------------------------------

    def _enter_connector(
        self, activation: JourneyActivation, activity: dict, init: dict
    ) -> tuple[str, str]:
        conditions = init.get("campaignConnectorConditions") or {}
        host_journey_id = (conditions.get("activityData") or {}).get("HostJourneyId")
        if not host_journey_id:
            return "move", "PlayerNotAddedToCampaign", "no journey linked"
        host = self.session.execute(
            select(Journey).where(Journey.journey_id == host_journey_id)
        ).scalar_one_or_none()
        if host is None or host.status != "Published":
            return (
                "move",
                "PlayerNotAddedToCampaign",
                f"{host_journey_id} is not published",
            )
        sources = entry_sources(host)
        if not sources:
            return "move", "PlayerNotAddedToCampaign", f"{host_journey_id} has no source"
        try:
            self.enter(
                host,
                sources[0]["activityId"],
                activation.player_id,
                context={"via": "campaign_connector", "fromJourney": activation.journey_id},
            )
        except EngineError as error:
            return "move", "PlayerNotAddedToCampaign", f"{host_journey_id}: {error.slug}"
        return "move", "PlayerAddedToCampaign", f"entered {host_journey_id}"

    # parked activities ----------------------------------------------

    def _enter_parked(
        self, activation: JourneyActivation, activity: dict, init: dict, name: str
    ) -> tuple[str, str]:
        activity_id = activity["activityId"]
        now = utcnow()

        if name == "wait_interval":
            wait = parse_iso_duration(init.get("waitPeriod", "P0Y0M0DT0H0M0S"))
            due_at = now + wait
            self._record(
                activation,
                activity_id,
                "WaitTimeStarted",
                "Boundary",
                f"waiting until {due_at.isoformat(timespec='seconds')}",
            )
            self.session.add(
                Timer(
                    activation_id=activation.id,
                    activity_id=activity_id,
                    kind="wait",
                    due_at=due_at,
                )
            )
            return "park", "wait"

        if name == "wait_date":
            wait_to = init.get("waitTo")
            due_at = max(parse_timestamp(wait_to) if wait_to else now, now)
            self._record(
                activation,
                activity_id,
                "WaitTimeStarted",
                "Boundary",
                f"waiting until {due_at.isoformat(timespec='seconds')}",
            )
            self.session.add(
                Timer(
                    activation_id=activation.id,
                    activity_id=activity_id,
                    kind="wait",
                    due_at=due_at,
                )
            )
            return "park", "wait"

        if name == "deposit":
            conditions = init.get("depositConditions") or {}
            minimums = conditions.get("minDepositAmounts") or []
            wanted = ", ".join(
                f"≥{(m.get('amount') or 0) / 100:g} {m.get('currencyCode', '')}"
                for m in minimums
            ) or "any amount"
            self._record(
                activation,
                activity_id,
                "DepositConditionAccepted",
                "Boundary",
                f"waiting for deposit {wanted}",
            )
            self.session.add(
                ParkedSubscription(
                    activation_id=activation.id,
                    activity_id=activity_id,
                    player_id=activation.player_id,
                    activity_name=name,
                    event_name="deposit.approved",
                    criteria=conditions,
                )
            )
            window = self._parse_window(conditions.get("expirationTimeout"))
            if window is not None:
                self.session.add(
                    Timer(
                        activation_id=activation.id,
                        activity_id=activity_id,
                        kind="deposit_window",
                        due_at=now + window,
                    )
                )
            return "park", "deposit"

        if name == "event_detector":
            properties = init.get("properties") or {}
            watched = ", ".join(
                (option.get("event") or {}).get("eventName", "?")
                for option in properties.get("subscriptionOptions") or []
            ) or "nothing"
            self._record(
                activation,
                activity_id,
                "DetectorStarted",
                "Boundary",
                f"watching for {watched}",
            )
            for option in properties.get("subscriptionOptions") or []:
                event = option.get("event") or {}
                self.session.add(
                    ParkedSubscription(
                        activation_id=activation.id,
                        activity_id=activity_id,
                        player_id=activation.player_id,
                        activity_name=name,
                        event_name=event.get("eventName", ""),
                        criteria={"filter": option.get("filter")},
                    )
                )
            duration = (properties.get("startingOptions") or {}).get("durationTime")
            window = self._parse_window(duration)
            if window is not None:
                self.session.add(
                    Timer(
                        activation_id=activation.id,
                        activity_id=activity_id,
                        kind="detector_window",
                        due_at=now + window,
                    )
                )
            return "park", "detector"

        if name == "sport_bet_condition":
            self._record(
                activation,
                activity_id,
                "Activated",
                "Boundary",
                f"waiting for bet ≥{(init.get('minBetAmount') or 0) / 100:g}, "
                f"odds ≥{init.get('minOdd') or 'any'}",
            )
            self.session.add(
                ParkedSubscription(
                    activation_id=activation.id,
                    activity_id=activity_id,
                    player_id=activation.player_id,
                    activity_name=name,
                    event_name="bet.settled",
                    criteria={
                        "minBetAmount": init.get("minBetAmount"),
                        "minOdd": init.get("minOdd"),
                    },
                )
            )
            expire_days = init.get("expireInDays")
            if expire_days:
                self.session.add(
                    Timer(
                        activation_id=activation.id,
                        activity_id=activity_id,
                        kind="bet_window",
                        due_at=now + timedelta(days=float(expire_days)),
                    )
                )
            return "park", "bet"

        if name == "sport_bet_insurance":
            # refunds a losing qualifying bet; the first condition carries the
            # per-currency minimum stake and the parlay minimum odds
            cond = (init.get("conditions") or [{}])[0] or {}
            min_bet = None
            for value in (cond.get("minBetAmount") or {}).values():
                try:
                    min_bet = float(value)
                    break
                except (TypeError, ValueError):
                    continue
            min_odd = cond.get("minOddParlay") or cond.get("minOdd")
            self._record(
                activation,
                activity_id,
                "Activated",
                "Boundary",
                f"bet insurance armed (≥{(min_bet or 0) / 100:g}, odds ≥{min_odd or 'any'})",
            )
            self.session.add(
                ParkedSubscription(
                    activation_id=activation.id,
                    activity_id=activity_id,
                    player_id=activation.player_id,
                    activity_name=name,
                    event_name="bet.settled",
                    criteria={"minBetAmount": min_bet, "minOdd": min_odd},
                )
            )
            expire_days = init.get("expireInDays")
            if expire_days:
                self.session.add(
                    Timer(
                        activation_id=activation.id,
                        activity_id=activity_id,
                        kind="bet_window",
                        due_at=now + timedelta(days=float(expire_days)),
                    )
                )
            return "park", "bet"

        raise EngineError("unknown-parked-activity", name)

    @staticmethod
    def _parse_window(value) -> timedelta | None:
        if value in (None, "", 0):
            return None
        if isinstance(value, (int, float)):
            return timedelta(milliseconds=value)
        try:
            return parse_iso_duration(str(value))
        except ValueError:
            return None

    # ── resuming a parked token ──────────────────────────────────────

    def _pinned_index(self, activation: JourneyActivation, journey: Journey) -> dict[str, dict]:
        """The activity graph this run walks: the revision it entered on.
        A live edit changes the journey for new entrants only."""
        if activation.journey_version and activation.journey_version != journey.version:
            revision = self.session.execute(
                select(JourneyRevision).where(
                    JourneyRevision.journey_id == journey.journey_id,
                    JourneyRevision.version == activation.journey_version,
                )
            ).scalar_one_or_none()
            if revision is not None:
                return {
                    a["activityId"]: a
                    for a in revision.body.get("activities", [])
                    if a.get("activityId")
                }
        return activity_index(journey)

    def _resume(
        self,
        activation: JourneyActivation,
        activity_id: str,
        event_name: str,
        detail: str | None = None,
    ) -> None:
        journey = self.session.execute(
            select(Journey).where(Journey.journey_id == activation.journey_id)
        ).scalar_one()
        index = self._pinned_index(activation, journey)
        activity = index.get(activity_id)
        if activity is None:
            raise EngineError("transition-target-not-found", activity_id)
        next_id = self._follow(activation, activity, event_name, detail)
        if next_id is not None:
            self._run(activation, journey, index, next_id)
        self.session.flush()

    def _release_held_message(self, timer: Timer) -> None:
        """Quiet hours ended: deliver a Held message — unless the player
        was excluded in the meantime (the wall wins, always)."""
        message_id = (timer.payload or {}).get("messageId")
        message = self.session.get(CommsMessage, message_id) if message_id else None
        if message is None or message.status != "Held":
            return
        exclusion = active_exclusion(self.session, message.player_id)
        if exclusion is not None:
            message.status = "Suppressed"
            message.delivery_detail = (
                f"suppressed at release: player excluded ({exclusion.reason})"
            )
            metrics.inc("journey_comms_suppressed_total")
            return
        if message.is_test:
            message.status = "Sent"
            message.delivery_detail = "released after quiet hours — test player, not delivered"
            metrics.inc("journey_comms_delivered_total")
            return
        result = deliver_comms(
            message_id=message.id,
            channel=message.channel,
            player_id=message.player_id,
            journey_id=message.journey_id,
            activity_id=message.activity_id,
            body=message.body or {},
        )
        message.delivery_attempts = result.attempts
        if result.ok:
            message.status = "Sent"
            message.delivery_detail = f"released after quiet hours — {result.detail}"
            metrics.inc("journey_comms_delivered_total")
        else:
            message.status = "Failed"
            message.delivery_detail = f"released after quiet hours — {result.detail}"
            metrics.inc("journey_comms_failed_total")

    def _deactivate_waiting(self, activation: JourneyActivation) -> None:
        for subscription in (
            self.session.execute(
                select(ParkedSubscription).where(
                    ParkedSubscription.activation_id == activation.id,
                    ParkedSubscription.active.is_(True),
                )
            )
            .scalars()
            .all()
        ):
            subscription.active = False
        for timer in (
            self.session.execute(
                select(Timer).where(
                    Timer.activation_id == activation.id,
                    Timer.fired.is_(False),
                    # a held message still goes out after the walk ends
                    Timer.kind != "comms_release",
                )
            )
            .scalars()
            .all()
        ):
            timer.fired = True

    def _cancel_timers(self, activation: JourneyActivation, activity_id: str) -> None:
        for timer in (
            self.session.execute(
                select(Timer).where(
                    Timer.activation_id == activation.id,
                    Timer.activity_id == activity_id,
                    Timer.fired.is_(False),
                )
            )
            .scalars()
            .all()
        ):
            timer.fired = True

    def _cancel_subscriptions(
        self, activation: JourneyActivation, activity_id: str
    ) -> None:
        for subscription in (
            self.session.execute(
                select(ParkedSubscription).where(
                    ParkedSubscription.activation_id == activation.id,
                    ParkedSubscription.activity_id == activity_id,
                    ParkedSubscription.active.is_(True),
                )
            )
            .scalars()
            .all()
        ):
            subscription.active = False

    # ── platform events ──────────────────────────────────────────────

    def ingest_platform_event(
        self,
        event_name: str,
        player_id: str,
        properties: dict | None = None,
        source_name: str = "platform",
        event_key: str | None = None,
    ) -> dict:
        properties = properties or {}
        if event_key:
            duplicate = self.session.execute(
                select(PlatformEvent.id).where(PlatformEvent.event_key == event_key)
            ).first()
            if duplicate is not None:
                metrics.inc("journey_events_duplicate_total")
                return {
                    "eventId": duplicate[0],
                    "duplicate": True,
                    "resolved": [],
                    "entered": [],
                }
        record = PlatformEvent(
            event_key=event_key,
            event_name=event_name,
            source_name=source_name,
            player_id=player_id,
            properties=properties,
        )
        self.session.add(record)
        self.session.flush()
        metrics.inc("journey_events_ingested_total")

        resolved: list[dict] = []
        subscriptions = (
            self.session.execute(
                select(ParkedSubscription).where(
                    ParkedSubscription.event_name == event_name,
                    ParkedSubscription.player_id == player_id,
                    ParkedSubscription.active.is_(True),
                )
            )
            .scalars()
            .all()
        )
        for subscription in subscriptions:
            activation = self.session.get(JourneyActivation, subscription.activation_id)
            if (
                activation is None
                or activation.status != "Active"
                or activation.current_activity_id != subscription.activity_id
            ):
                continue
            if not self._subscription_matches(subscription, properties):
                continue
            self._cancel_subscriptions(activation, subscription.activity_id)
            self._cancel_timers(activation, subscription.activity_id)
            amount = properties.get("amount")
            currency = properties.get("currencyCode") or properties.get("currency") or ""
            if subscription.activity_name == "deposit":
                completion = "DepositConditionSatisfied"
                detail = f"deposit {(amount or 0) / 100:g} {currency} qualified".strip()
            elif subscription.activity_name == "event_detector":
                self._record(
                    activation,
                    subscription.activity_id,
                    "EventReceived",
                    "Boundary",
                    f"{event_name} received",
                )
                completion = "DetectorSuccess"
                detail = f"{event_name} matched the filter"
            elif subscription.activity_name == "sport_bet_condition":
                completion = "Satisfied"
                detail = f"bet {(amount or 0) / 100:g} {currency} qualified".strip()
            elif subscription.activity_name == "sport_bet_insurance":
                completion = "SingleBetSatisfied"
                detail = f"insured bet {(amount or 0) / 100:g} {currency} settled".strip()
            else:
                continue
            self._resume(activation, subscription.activity_id, completion, detail)
            resolved.append(
                {
                    "activationId": activation.id,
                    "journeyId": activation.journey_id,
                    "activityId": subscription.activity_id,
                    "completion": completion,
                }
            )

        entered = self._maybe_enter_registration_sources(event_name, player_id, properties)
        return {"eventId": record.id, "resolved": resolved, "entered": entered}

    def _subscription_matches(
        self, subscription: ParkedSubscription, properties: dict
    ) -> bool:
        criteria = subscription.criteria or {}
        if subscription.activity_name == "deposit":
            amount = properties.get("amount")
            currency = properties.get("currencyCode") or properties.get("currency")
            minimums = criteria.get("minDepositAmounts") or []
            if not minimums:
                return True
            for minimum in minimums:
                required_currency = minimum.get("currencyCode")
                if currency and required_currency and required_currency != currency:
                    continue
                try:
                    if float(amount) >= float(minimum.get("amount", 0)):
                        return True
                except (TypeError, ValueError):
                    return False
            return False
        if subscription.activity_name == "event_detector":
            return _matches_filter(criteria.get("filter"), properties)
        if subscription.activity_name in ("sport_bet_condition", "sport_bet_insurance"):
            min_bet = criteria.get("minBetAmount")
            min_odd = criteria.get("minOdd")
            if min_bet is not None and not _compare(
                "gte", properties.get("amount"), min_bet
            ):
                return False
            if min_odd is not None and not _compare(
                "gte", properties.get("odd"), min_odd
            ):
                return False
            return True
        return True

    def _maybe_enter_registration_sources(
        self, event_name: str, player_id: str, properties: dict
    ) -> list[dict]:
        """`player.registered` events admit players through `registration`
        sources whose reference codes mention the event's refCode."""
        if event_name != "player.registered":
            return []
        ref_code = properties.get("refCode") or properties.get("promocode")
        entered: list[dict] = []
        journeys = (
            self.session.execute(select(Journey).where(Journey.status == "Published"))
            .scalars()
            .all()
        )
        for journey in journeys:
            for source in entry_sources(journey):
                if source.get("activityName") != "registration":
                    continue
                init = source.get("initializationData") or {}
                haystack = json.dumps(init.get("promocodeSettings") or {})
                if ref_code and ref_code not in haystack:
                    continue
                try:
                    activation = self.enter(
                        journey,
                        source["activityId"],
                        player_id,
                        context={"via": "registration", "refCode": ref_code},
                    )
                except EngineError:
                    continue
                entered.append(
                    {
                        "journeyId": journey.journey_id,
                        "activationId": activation.id,
                    }
                )
        return entered

    # ── timers ───────────────────────────────────────────────────────

    def run_due_timers(self, now: datetime | None = None) -> int:
        """Fire everything due, in passes: a resume may itself schedule a
        timer that is already due (zero-length waits), so sweep until a
        pass fires nothing."""
        total = 0
        for _ in range(100):
            fired = self._run_due_timers_once(now)
            total += fired
            if fired == 0:
                break
        return total

    def _run_due_timers_once(self, now: datetime | None = None) -> int:
        now = now or utcnow()
        timers = (
            self.session.execute(
                select(Timer)
                .where(Timer.fired.is_(False), Timer.due_at <= now)
                .order_by(Timer.due_at)
            )
            .scalars()
            .all()
        )
        fired = 0
        for timer in timers:
            # atomic claim: with several scheduler workers only one wins
            # this row; everyone else moves on
            claimed = self.session.execute(
                update(Timer)
                .where(Timer.id == timer.id, Timer.fired.is_(False))
                .values(fired=True)
            )
            if claimed.rowcount == 0:
                continue
            self.session.expire(timer, ["fired"])
            if timer.kind == "comms_release":
                # quiet-hours release is not a walk resume — the token has
                # long moved on (or completed); only the message goes out
                fired += 1
                metrics.inc("journey_timers_fired_total")
                try:
                    self._release_held_message(timer)
                except Exception as error:
                    print(
                        f"[timer-error] timer={timer.id} "
                        f"activation={timer.activation_id}: {error!r}",
                        flush=True,
                    )
                continue
            activation = self.session.get(JourneyActivation, timer.activation_id)
            if (
                activation is None
                or activation.status != "Active"
                or activation.current_activity_id != timer.activity_id
            ):
                continue
            fired += 1
            metrics.inc("journey_timers_fired_total")
            try:
                self._cancel_subscriptions(activation, timer.activity_id)
                self._cancel_timers(activation, timer.activity_id)
                if timer.kind == "wait":
                    self._resume(
                        activation, timer.activity_id, "WaitTimeCompleted", "wait elapsed"
                    )
                elif timer.kind == "offer_expiry":
                    offer_id = (timer.payload or {}).get("offerId")
                    offer = self.session.get(PromotionOffer, offer_id) if offer_id else None
                    if offer is not None and offer.status == "Offered":
                        offer.status = "Expired"
                        offer.resolved_at = utcnow()
                    self._resume(
                        activation,
                        timer.activity_id,
                        "PromotionExpired",
                        "accept window expired",
                    )
                elif timer.kind == "deposit_window":
                    self._resume(
                        activation,
                        timer.activity_id,
                        "DepositConditionUnsatisfied",
                        "deposit window expired",
                    )
                elif timer.kind == "detector_window":
                    self._record(
                        activation, timer.activity_id, "EventNotReceived", "Boundary"
                    )
                    self._resume(
                        activation,
                        timer.activity_id,
                        "DetectorFailed",
                        "window closed without a matching event",
                    )
                elif timer.kind == "bet_window":
                    self._resume(
                        activation, timer.activity_id, "Unsatisfied", "bet window expired"
                    )
            except Exception as error:  # one bad walk must not stall the rest
                print(f"[timer-error] timer={timer.id} activation={timer.activation_id}: {error!r}", flush=True)
        self.session.flush()
        return fired
