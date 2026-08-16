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
pytest                        # 29 tests
```

Open **http://localhost:8000/** for the visual builder (API docs at `/docs`).

## The builder UI

A zero-dependency single-page app served from `app/static/`:

- **Journeys** — list with lifecycle actions (publish / stop / duplicate /
  archive / delete) and live activation counts.
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
  demands. "Load sample" drops in a runnable welcome-freespins flow.
- **Run** — the live half: enter players through any input source
  (with attribute upsert for decision splits), ingest platform events,
  fire due timers, accept offers, mark comms read/clicked, and watch each
  activation's event timeline (Activation / Boundary / Completion
  colour-coded) refresh in real time next to the player's reward ledger.

`DATABASE_URL` (default `sqlite:///./journey.db`) and
`JOURNEY_API_TOKEN` (default: auth off) configure persistence and auth.

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
| POST | `/platform/v0/events` | ingest `deposit.approved`, `player.registered`, `bet.settled`, … |
| POST | `/runtime/v0/offers/{id}/accept` | player accepts a promotion |
| POST | `/runtime/v0/comms/{id}/{show\|read\|click}` | engagement (feeds engagement splits) |
| POST | `/runtime/v0/timers/run` | fire due timers now (scheduler also runs in-process) |
| GET | `/runtime/v0/activations/{id}` | one run: current node + full event history |
| GET | `/runtime/v0/journeys/{jrn}/activations` | all runs of a journey |
| GET | `/runtime/v0/players/{id}/rewards` · `/comms` · `/offers` | the ledger / outbox |
| GET | `/runtime/v0/timers` | pending wake-ups |

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
  ids.py         JRN / display-id sequences, structural-id regeneration
  durations.py   ISO-8601 durations + both timestamp flavours
  models.py      journeys, activations, timers, subscriptions, ledger, outbox
  routes/        journeys.py (builder), identifiers.py, runtime.py
scripts/demo.py  three-journey birthday-style campaign, end to end
tests/           23 tests: units, builder API, full engine walks
```

## What's deliberately simplified

- No visual canvas: `rawJourneyData.elements` is stored and
  consistency-checked, never rendered or generated.
- Single-token walks (no parallel/choosable flow fan-out).
- Comms are an outbox, not real SMS/email delivery.
- Reward outcomes follow the happy path after granting; the full
  reject/cancel/expiry sub-state machines of bonuses are not modelled.
- `registration` source matching is a promocode substring check.
