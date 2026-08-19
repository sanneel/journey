# REA / GR8 backoffice capture scripts

Browser-console scripts that pull the **real GR8 Journey Builder structure** out
of the REA backoffice (`pmi.rea-backoffice.gr8.tech`) so we can complete our
imitation against ground truth.

**All of these are READ-ONLY.** They only issue `GET`s (or passively observe the
UI's own traffic). Nothing is created, edited, published, or deleted. They
capture the page's own bearer token — no token copy/paste — and auto-detect the
API base and `x-brand` from the page, so the same scripts work for JBCL and
PMCL without editing.

## How to run one

1. Log into the REA backoffice, open any Journey Builder page.
2. Open DevTools → Console.
3. Paste the whole script file, press Enter.
4. If it says *"Waiting for a token…"*, click anything in the UI once — it grabs
   the token from the next request the page makes.
5. It prints a table, stashes the result on a `window.__REA*` variable, and
   downloads a `.json` file. Send me the downloaded file (or `copy(window.__REA…)`
   if a download is blocked).

## Run order

| # | File | What it gets | Send me |
|---|------|--------------|---------|
| 1 | `01_inventory.js` | every journey: id, name, status, dates | `rea_inventory.json` |
| 2 | `02_bodies_and_catalog.js` | full journey bodies + a distilled **per-activity-type catalog** (real `initializationData` sample + full event vocabulary for every `activityName` that exists) | **`rea_activity_catalog.json`** ← the main one |
| 3 | `03_record_endpoints.js` | discovers the endpoints we don't know yet (activity palette/metadata, promotions, segments, content templates, games) by recording the UI's own calls | `rea_endpoints.json` |
| 4 | `04_one_journey.js` | one journey's full body — for capturing a specific newly-built activity type | `rea_journey_<id>.json` |

Script 2 reads the ids that script 1 stashes on `window.__REA_INV`, so run 1
then 2 in the same tab. (Or paste ids into the `IDS`/`JOURNEY_ID` array at the
top of 2/4.)

### Script 3 (endpoint recorder) — how to use

Paste it, then **navigate the UI** through everything whose structure we want:
open the Journey Builder and its activity palette, open a journey, open
Promotions, open Segments/Audiences, open Content/Templates, open Games. Then
run `__REA_stop()` in the console. It prints and downloads the list of every
distinct API path the UI called, with method, status, and response shape — that
tells us the real paths for the reference data below.

## What we most want (the gaps)

We already have solid captures of the common activity types. From the REA
capture backlog, these activity types are **still uncaptured** — if any live
journey uses one, script 2 will grab it automatically; otherwise build one in
the UI and capture it with script 4:

- Input sources: `CSV` upload, `Events` (real-time)
- Flow control: `Random split`, `Email engagement split`, `Native-push engagement split`
- Communication: `Native push`, `Web push`, `WhatsApp`
- Connectors: `Outgoing API request`
- Conditions: `Bet Insurance`, `Bet Collection`, `Casino Bet Collection`, `Deposit Collection`
- Rewards: `Sport Bonus`, `Money Bonus`, `Coins Bonus`
- `Choosable flows` as a standalone (we only have it nested inside `multipurpose_promotion`)

And the reference data script 3 should surface the endpoints for:
the activity **palette/metadata** (schemas the UI renders forms from),
**promotions** list, player **segments**, **content/email templates**, and the
**games/providers** registry.

## Reference (already reverse-engineered)

- Journey Builder base: `https://<host>/api/ubo/api/v0/crm/journey-builder/v0`
- Promo base: `…/crm/promo/v2`
- Auth: short-lived Bearer JWT (captured from the page); brand via `x-brand`
- List journeys: `GET /journeys` · one journey: `GET /journeys/{JRN-…}`
- The full wire-format notes live in liveapi's
  `journey-cloner/REA_BACKOFFICE_AND_JOURNEYS.md` and
  `journey-planner/REA_KNOWLEDGE_BASE.md`.
