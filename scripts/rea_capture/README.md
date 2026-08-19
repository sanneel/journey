# REA / GR8 backoffice capture scripts

Two browser-console scripts that pull the **real GR8 Journey Builder structure**
out of the REA backoffice (`pmi.rea-backoffice.gr8.tech`) so we can complete our
imitation against ground truth — **built to leave no unusual footprint.**

## The footprint question

The server only ever sees HTTP requests. So the safety of a script is entirely
"does it make requests a normal user wouldn't?"

| Script | Extra API calls it makes | Footprint |
|--------|--------------------------|-----------|
| `03_record_endpoints.js` | **none** — it only observes the UI's own traffic | **none** (indistinguishable from browsing) |
| `04_one_journey.js` | one `GET /journeys/{id}` | same as opening one journey in the UI |

**Recommended: use `03` alone.** It issues no requests of its own; it just
mirrors what the UI already fetches as you click. You open a few journeys
normally and it captures their full bodies + the endpoint map + the distilled
activity catalog — all passively.

> An earlier version had an inventory script and a bulk-fetch script. The
> bulk-fetch looped ~60 `GET /journeys/{id}` in a few seconds — the one thing
> that *does* look anomalous (no human opens 60 journeys in 7 seconds). Both
> were removed. `03` gets the same result by riding on normal navigation.

## How to run `03` (the recorder)

1. Log into the REA backoffice, open the Console (DevTools → Console).
2. Paste the whole `03_record_endpoints.js` file, press Enter. It starts
   recording (no requests yet).
3. **Navigate the UI normally.** Opening a journey in the builder makes the UI
   fetch that journey's full body — which the recorder keeps. So open a handful
   of **varied** journeys (a promo one, a casino one, a comms one, a sport one)
   to cover the activity types. Optionally open the activity palette, Promotions,
   Segments/Audiences, Content/Templates, Games — to capture those endpoints too.
4. Run `__REA_stop()` in the console.

It downloads:

- **`rea_activity_catalog.json`** ← send me this (real `initializationData`
  sample + full Activation/Boundary/Completion event vocabulary for every
  `activityName` the UI loaded)
- `rea_endpoints.json` — every distinct API path the UI called (this is how we
  learn the real paths for palette/metadata, promotions, segments, content)
- `rea_journey_bodies.json` — the raw full bodies it captured (backup)

If a download is blocked, `copy(window.__REA_CAT)` in the console instead.

## `04_one_journey.js` (optional, one request)

For capturing a **specific** activity type we still lack: build one in the UI,
save the journey, then run `04` with that journey's `JRN-…` id (edit
`JOURNEY_ID` at the top). One GET — same as opening it in the UI.

## What we most want (the gaps)

Common activity types are already captured. Still uncaptured — if any journey
you open uses one, `03` grabs it automatically; otherwise build one and capture
it with `04`:

- Input sources: `CSV` upload, `Events` (real-time)
- Flow control: `Random split`, `Email engagement split`, `Native-push engagement split`
- Communication: `Native push`, `Web push`, `WhatsApp`
- Connectors: `Outgoing API request`
- Conditions: `Bet Insurance`, `Bet Collection`, `Casino Bet Collection`, `Deposit Collection`
- Rewards: `Sport Bonus`, `Money Bonus`, `Coins Bonus`
- `Choosable flows` standalone (we only have it nested in `multipurpose_promotion`)

Reference data to surface from `rea_endpoints.json`: the activity
**palette/metadata**, **promotions** list, player **segments**,
**content/email templates**, **games/providers** registry.

## Reference (already reverse-engineered)

- Journey Builder base: `https://<host>/api/ubo/api/v0/crm/journey-builder/v0`
- Auth: short-lived Bearer JWT (the recorder never needs it — it reads the UI's
  own responses); brand via `x-brand`
- One journey: `GET /journeys/{JRN-…}`
- Full wire-format notes: liveapi's
  `journey-cloner/REA_BACKOFFICE_AND_JOURNEYS.md`.
