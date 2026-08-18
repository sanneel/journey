# Journey Builder

A working imitation of a CRM **Journey Builder** — the automation engine
behind promo campaigns: journeys are node graphs that players move
through, assembled from a palette of activities (input sources,
promotions, deposit gates, waits, event detectors, splits, rewards,
comms, terminals).

This repo implements **both halves**:

1. **The builder backend** — the draft API a visual builder (or an
   automation script like `liveapi/journey-cloner`) talks to: identifier
   reservation, draft create/update, validation with the platform's real
   failure slugs, publish/stop/archive, and server-side duplication with
   correct ID-class handling.
2. **The runtime mechanism** — the part the real platform never shows
   you: a full execution engine that admits players through sources,
   walks them along `events[].nextActivityId` transitions, parks them on
   waits / deposit gates / event detectors / offers, wakes them with a
   timer scheduler or ingested platform events, grants rewards into a
   ledger and writes comms into an outbox.

The wire format (activity envelope, event vocabulary, config shapes,
dual-storage `rawJourneyData` mirror, ID classes, failure slugs) follows
the captured behaviour documented in `liveapi`'s
`journey-planner/REA_KNOWLEDGE_BASE.md` and `REA_BUILD_MECHANICS.md`.

## Quick start

```bash
pip install -r requirements.txt
python scripts/demo.py        # end-to-end campaign, no server needed
python server.py              # serve API + builder UI on :8000
pytest                        # 69 tests
```

To watch deliveries leave the building for real, run the stand-in
platform and point the connectors at it:

```bash
python scripts/mock_platform.py &          # receives wallet + comms calls on :9009
CONNECTOR_MODE=webhook \
CONNECTOR_REWARDS_URL=http://127.0.0.1:9009/wallet \
CONNECTOR_COMMS_URL=http://127.0.0.1:9009/comms \
python server.py
```

Open **http://localhost:8000/** for the visual builder (API docs at `/docs`).

## The builder UI

A zero-dependency single-page app served from `app/static/`, designed as
**"the bookmaker's ledger"** (`docs/DESIGN.md`): bond paper, ink, a
casino-felt rail, nodes as white tickets with perforated meta strips,
terminals as torn stubs, Zilla Slab (self-hosted, OFL) as the ledger
voice.

- **Journeys** — a campaign dashboard: search, status filters, live
  player counts, completion rate, and rewards paid per journey, plus the
  lifecycle actions (publish / stop / duplicate / archive / delete).
- **Builder** — a canvas editor governed by `docs/CANVAS_RULES.md`:
  journeys flow **top → bottom** (sources up, terminals down), layered
  auto-layout with barycenter crossing-reduction, bottom-edge fan-out
  ports, arrowed Bézier edges coloured by event semantics (success
  green / failure red / boundaries dashed) with mono label pills in the
  row gaps, category icon chips, terminal pills, zoom 50–130%, 8px grid
  snap. The inspector wires each Completion event through a dropdown and
  edits `initializationData` (each type starts with a runnable config
  skeleton). *Validate* runs the dry-run endpoint and shows problem slugs
  inline; *Save* writes **both storage copies** — `activities[]` and the
  `rawJourneyData` mirror (canvas positions in `elements`, display names
  in `activitiesConfiguration`) — exactly like the dual-storage rule
  demands. Editing is direct: **drag from a bottom port onto another
  activity to wire it** (an event picker opens when several events
  qualify), click a wire to select and disconnect it, drag activities in
  from the palette, pan the canvas, Delete/Escape/Ctrl+Z–Y with a
  50-step undo stack, and an "unsaved changes" guard. Everyday settings
  are **typed form fields** (amounts, duration presets, toggles) — raw
  `initializationData` JSON is demoted to Advanced.
  The **Templates ▾** menu drops in a ready-made campaign
  (`app/journey_templates.py`): *Promotion campaign* — offer with a
  1-day accept window, $100 deposit gate, player-value reward tiers
  (100/30 freespins), reward notification, next-day follow-up email,
  with SMS reminder and expiry pop-up on the failure paths — or the
  small *Welcome freespins* starter. Every instantiation mints fresh
  activity ids, so saved copies never collide.
- **Insights** — the paid-product half: on a published journey the
  canvas overlays live campaign numbers (`GET /runtime/v0/journeys/
  {jrn}/stats`) — players entered and currently parked on every node,
  traversal counts and percentages on every transition — so the funnel
  and its drop-offs read directly off the graph.
- **Run** — the live half: a KPI strip (entered / active / completed /
  completion rate / rewards + spins / comms / offer accept rate), player
  entry through any input source (with attribute upsert for decision
  splits), platform-event ingestion, timer firing, offer accepts, comms
  engagement, and each activation's event timeline — every event carries
  a human-readable detail of what the node actually did.

`DATABASE_URL` (default `sqlite:///./journey.db`) and
`JOURNEY_API_TOKEN` (default: auth off) configure persistence and auth.

## Delivery connectors (P3)

Rewards and comms don't stop at the ledger/outbox — each grant and each
message goes through a **delivery connector** (`app/connectors.py`):

- `CONNECTOR_MODE=log` (default) — deliveries are acknowledged locally
  and logged; nothing leaves the process. Right for demos and tests.
- `CONNECTOR_MODE=webhook` — the engine POSTs a self-describing JSON
  payload to the real platform: reward grants to
  `CONNECTOR_REWARDS_URL` (the wallet / game-aggregator side), comms to
  `CONNECTOR_COMMS_URL` (the gateway side), with optional
  `CONNECTOR_TOKEN` as a bearer header, `CONNECTOR_RETRIES` attempts
  (default 2 retries, exponential backoff) and `CONNECTOR_TIMEOUT`
  seconds per attempt.

Delivery outcome is part of the graph semantics: a failed reward
delivery marks the grant `Failed`, records the type's failed boundary
(`FreespinBonusAwardFailed` / `WageringBonusAwardFailed`) and routes the
token down the activity's **failure path** (`…Aborted`); a failed comms
delivery marks the message `Failed` and takes the comms failure event.
Attempts and the final detail are visible on every grant/message
(`deliveryAttempts`, `deliveryDetail`). `scripts/mock_platform.py` is a
stand-in platform for rehearsing both paths — including `POST
/fail-next {"times": N}` to force reds.

## Reliability (P4)

Built for more than one process and a flaky network:

- **Idempotent ingestion** — send `eventId` with a platform event and
  replays are detected (`{"duplicate": true}`) and processed exactly
  once, enforced by a unique key in storage.
- **Competing schedulers** — timer firing does an atomic claim
  (`UPDATE … WHERE fired = false`), so N workers never double-fire a
  wake-up; each timer resumes in its own error boundary, so one bad
  walk can't take down a sweep.
- **`GET /metrics`** — Prometheus counters: activations entered, events
  ingested/duplicate, timers fired, rewards and comms
  delivered/failed, journeys published.

## Versioning & live operations (P5)

- **Publish snapshots a revision.** Every publish (and every live edit)
  stores an immutable `JourneyRevision` of the full body.
- **Live edit** — `PUT /journey-drafts/{id}` is allowed on a
  **Published** journey: the change goes live instantly as version
  N+1. In-flight players are **pinned to the version they entered**
  (their walk resolves transitions against their revision's snapshot);
  new entries get the new version. No stop-the-world, no stranded
  tokens.
- **Drain stop** — `POST /journeys/{jrn}/stop` with
  `{"mode": "drain"}` closes the doors (new entries → 409), flips the
  journey to `Stopping`, lets everyone in flight finish, and the
  journey moves itself to `Stopped` when the last active walk
  completes. `{"mode": "terminate"}` (default) keeps the old
  hard-stop.

## The mental model

```
 PROMO FRONT DOOR (wheel / promo page — not part of this repo)
        │  routes a player via { journeyId, activityId }
        ▼
 ┌──────────────────────── JOURNEY ───────────────────────────┐
 │  input source ──PlayerAdded──▶ promotion ──Accepted──▶ ... │
 │       ▲                            │Expired                │
 │   webhook /                        ▼                       │
 │   segment /                deposit gate ──Satisfied──▶ reward
 │   registration                     │Unsatisfied      (ledger)
 │                                    ▼                       │
 │                              notification ──▶ end          │
 └────────────────────────────────────────────────────────────┘
```

- The graph is encoded **entirely** in `events[].nextActivityId` on each
  activity — there is no separate edges array.
- `eventType: "Completion"` events are transitions; `"Boundary"` events
  mark moments (offer shown, bonus awarded) and are recorded on the
  activation's history without moving the token.
- Every source fires `PlayerAdded` into the first real activity.

## API surface (prefix `/api/v0/crm`)

### Builder — `/journey-builder/v0`

| Method | Path | Purpose |
|---|---|---|
| POST | `/journeys/identifier` | reserve a `JRN-0-*` before drafting |
| POST | `/journey-drafts` | create a draft (201; missing `promotionDisplayId`s re-minted) |
| POST | `/journey-drafts/validate` | dry-run validation, nothing persisted |
| PUT | `/journey-drafts/{draft_id}` | update a draft (numeric id from create) |
| DELETE | `/journey-drafts/{draft_id}` | delete a Draft/Archived journey (frees its activity ids) |
| GET | `/journeys` · `/journeys/{jrn}` | list / read |
| POST | `/journeys/{jrn}/publish` | compile + register webhooks + go live |
| POST | `/journeys/{jrn}/stop` · `/archive` | lifecycle |
| POST | `/journeys/{jrn}/duplicate` | server-side clone (see ID classes) |
| GET | `/activities/catalog` | the Tools palette with event vocabulary |
| GET | `/journey-templates` | ready-made campaign shapes |
| GET | `/journey-templates/{key}` | instantiate a template (fresh activity ids per call) |

### Promo — `/promo/v0`

| POST | `/promotion-display-identifier` | pre-mint a display id |
|---|---|---|

### Runtime — entry, events, observability

| Method | Path | Purpose |
|---|---|---|
| POST | `/journey-builder/v0/webhooks/{webhookId}` | `external_system_source` entry (the wheel-prize hand-off) |
| POST | `/journey-builder/v0/journeys/{jrn}/activities/{id}/enter` | direct `{journeyId, activityId}` entry |
| POST | `/journey-builder/v0/journeys/{jrn}/players` | bulk segment injection (`dwh_source`) |
| POST | `/platform/v0/players` | upsert a player + attributes (decision splits read these) |
| POST | `/platform/v0/events` | ingest `deposit.approved`, `player.registered`, `bet.settled`, … (optional `eventId` → idempotent replay detection) |
| POST | `/runtime/v0/offers/{id}/accept` | player accepts a promotion |
| POST | `/runtime/v0/comms/{id}/{show\|read\|click}` | engagement (feeds engagement splits) |
| POST | `/runtime/v0/timers/run` | fire due timers now (scheduler also runs in-process) |
| GET | `/runtime/v0/activations/{id}` | one run: current node + full event history |
| GET | `/runtime/v0/journeys/{jrn}/activations` | all runs of a journey |
| GET | `/runtime/v0/players/{id}/rewards` · `/comms` · `/offers` | the ledger / outbox (with `deliveryAttempts` / `deliveryDetail`) |
| GET | `/runtime/v0/journeys/{jrn}/stats` | per-node/per-edge live funnel numbers |
| GET | `/runtime/v0/timers` | pending wake-ups |
| GET | `/metrics` | Prometheus counters (no `/api/v0/crm` prefix) |

## The activity palette

Wire names and event vocabulary match the captured objects:

| Category | Activities |
|---|---|
| Input Source | `dwh_source`, `external_system_source`, `registration` |
| Flow control | `ams_decision_split`, `random_split`, `notification_center_engagement_split`, `email_engagement_split` |
| Communication | `notification_center` (contract 1 = bell, 5 = pop-up), `dextra_sms`, `dextra_email`, `native_push` |
| Delays | `wait_interval` (ISO-8601 `waitPeriod`), `wait_date`, `event_detector` |
| Connectors | `campaign_connector` (`activityData.HostJourneyId`) |
| Promotion | `promotion`, `multipurpose_promotion` |
| Conditions | `deposit` (`depositConditions`), `sport_bet_condition` |
| Rewards | `freespin_bonus`, `casino_bonus_v2`, `freebet`, `sport_bonus` |
| Terminals | `end_of_path`, `end_of_journey` |

Money is minor units (`12000` = $120 CLP); bonus expiries are
milliseconds; waits/windows are ISO-8601 durations
(`P0Y0M1DT0H0M0S` = 1 day). Both timestamp flavours are accepted
(.NET `…T04:00:00.0000000Z` and plain `…T04:00:00Z`).

## Validation & the failure playbook

Draft failures return the platform's error shape —
`aggregatedError.journeyActivityError[].problemDetails[].type` carries a
stable slug:

| Slug | Cause |
|---|---|
| `journey-with-same-identifier-already-exists` | lineage (`duplicatedFromId`) not stripped, or JRN reuse |
| `activities-with-same-identifier-already-exist` | activityIds reused (un-regenerated clone) — enforced **brand-wide** |
| `already-existing-promotion-display-id` | display id reuse (**HTTP 422**) |
| `transition-target-not-found` / `unknown-event-for-activity` | broken graph wiring |
| `raw-journey-data-out-of-sync` | editor mirror disagrees with `activities[]` |
| `journey-has-no-input-source` / `activity-has-no-outgoing-transition` | unreachable structure |

## Cloning (the ID classes)

`POST /journeys/{jrn}/duplicate` applies the same rules a correct
external cloner must:

- **KEEP** external references (`promotionId`, `contentId`, `frontId`, templates)
- **REGENERATE** structural ids — UUID values of `activityId`/`id` keys,
  string-replaced across the serialized payload so every embedded
  reference (transitions, `activitiesConfiguration` keys, canvas edges)
  renames together
- **STRIP** server-minted `promotionDisplayId` (re-minted on create)
- **BLANK** `campaignConnectorConditions.campaignId`
- **REMOVE** lineage fields

## How execution works

- **Publish** registers a webhook per `external_system_source` and opens
  the journey.
- **Entry** creates a `JourneyActivation` (the token) and fires
  `PlayerAdded`. `reEntryRule.reEntryMode: "Prohibited"` blocks second
  runs.
- **Instant activities** (comms, rewards, splits, connectors) do their
  work and follow their happy-path completion in the same request.
- **Parked activities** stop the token and register timers and/or
  platform-event subscriptions:
  - `wait_interval` / `wait_date` → timer → `WaitTimeCompleted`
  - `promotion` (no `autoAccept`) → accept API or `timeToAccept` expiry
  - `deposit` → `deposit.approved` matching `minDepositAmounts`, or
    `expirationTimeout` → `DepositConditionUnsatisfied`
  - `event_detector` → any `subscriptionOptions` event whose filter
    matches (`amount greaterThanOrEqualCurrency CLP 5000`), or the
    `durationTime` window closes → `DetectorFailed`
- A background scheduler thread fires due timers (interval
  `JOURNEY_SCHEDULER_INTERVAL`, default 1s).
- `ams_decision_split` evaluates its `rules[].filter.property`
  (`lt/lte/gt/gte/eq/…`) against player attributes; `random_split` rolls
  weighted `paths[].probability`; engagement splits read the outbox
  status (`Sent/Shown/Read/Clicked`) of the comms activity referenced by
  `properties.DextraNotificationCenterActivityId`.
- `campaign_connector` enters the player into
  `activityData.HostJourneyId`'s first source (`PlayerAddedToCampaign` /
  `PlayerNotAddedToCampaign`).
- Rewards land in `reward_grants` (spins/provider/game, bonus %/wagering,
  expiry computed from ms durations); comms land in `comms_messages`.
- Every event — activation, boundary, completion — is appended to the
  activation's `eventsHistory`, so a run's full path is auditable.

## Layout

```
app/
  catalog.py     the palette + event vocabulary (from captures)
  validation.py  draft checks -> aggregatedError slugs
  cloner.py      ID-class clone mechanism
  drafts.py      draft persistence, display-id minting, registries
  engine.py      the runtime: entry, walk, park/resume, timers, events
  connectors.py  reward/comms delivery: log or webhook + retries
  metrics.py     Prometheus counters behind GET /metrics
  ids.py         JRN / display-id sequences, structural-id regeneration
  durations.py   ISO-8601 durations + both timestamp flavours
  models.py      journeys, revisions, activations, timers, ledger, outbox
  routes/        journeys.py (builder), identifiers.py, runtime.py
scripts/demo.py            three-journey birthday-style campaign, end to end
scripts/mock_platform.py   stand-in casino platform for webhook mode
tests/           69 tests: units, builder API, engine walks, per-type
                 coverage, real captured journeys, production hardening
```

## What's deliberately simplified

- No visual canvas: `rawJourneyData.elements` is stored and
  consistency-checked, never rendered or generated.
- Single-token walks (no parallel/choosable flow fan-out).
- In `CONNECTOR_MODE=log`, comms and rewards stop at the outbox/ledger;
  webhook mode delivers them to a real endpoint but the payload shape is
  ours, not a specific gateway's.
- Reward sub-state machines beyond award success/failure (player-side
  cancel, wagering progress, withdrawal-confirmed reverts) are recorded
  as vocabulary but not simulated.
- `registration` source matching is a promocode substring check.
