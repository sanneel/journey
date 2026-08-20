# Big Promo September — Fiestas Patrias

| | |
|---|---|
| **Name** | Big Promo September |
| **Description** | Casino. Every day, all visitors to the site can take part in the promo through the promo page. Every day, 4 free-spin bonuses are available. Making at least 2 deposits (claiming 2 of 4 bonuses) grants an entry to the **Special Card**. Plan-B scratch card (fewer free bonuses) for players who didn't participate in the main offer. Fiestas Patrias theming ("La Gran Promo del Dieciocho"). |
| **Start date** | 18.09.26 (Friday — Fiestas Patrias) |
| **End date** | 19.09.26 (Saturday — Día de las Glorias del Ejército) |
| **Promo days** | 2 (both national holidays) |
| **Product type** | CS & SP |
| **Client segments** | All players · Communication: Actives, sleeps, churned last open 1 month, 1 month ret |

## Communications Casino

| | Friday | Saturday |
|---|---|---|
| **Date** | 18.09.26 | 19.09.26 |
| NC | Yes | Yes |
| Email | Yes | Yes |
| Sms | Yes | No |
| App | Yes | Yes |

## Bonus N1 — Free spins | For deposit

| | | | |
|---|---|---|---|
| Bonus | 20 | | |
| Bet | 400 | Bonus amount | 8.000 |
| Max bonus amount | 200.000 | Contribution | 0.8 |
| Cashout | 20 | | |
| Max win | 4.000.000 | | |
| Provider | Jugabet Games | | |
| Game | La Gran Copa Jugabet *(September rotation)* | | |
| Days to activate bonus | 1 | | |
| **Min dep** | **10.000** | Days to make deposit | 1 |
| Wager | 30 | Days for wagering | 3 |

## Bonus N2 — Free spins | For deposit

| | | | |
|---|---|---|---|
| Bonus | 20 | | |
| Bet | 600 | Bonus amount | 12.000 |
| Max bonus amount | 200.000 | Contribution | 0.8 |
| Cashout | 20 | | |
| Max win | 4.000.000 | | |
| Provider | Tada | | |
| Game | Fortune Gems 2 | | |
| Days to activate bonus | 1 | | |
| **Min dep** | **15.000** | Days to make deposit | 1 |
| Wager | 30 | Days for wagering | 3 |

## Bonus N3 — Free spins | For deposit

| | | | |
|---|---|---|---|
| Bonus | 40 | | |
| Bet | 600 | Bonus amount | 24.000 |
| Max bonus amount | 200.000 | Contribution | 0.8 |
| Cashout | 20 | | |
| Max win | 4.000.000 | | |
| Provider | Endorphina | | |
| Game | Fortune Chests | | |
| Days to activate bonus | 1 | | |
| **Min dep** | **30.000** | Days to make deposit | 1 |
| Wager | 30 | Days for wagering | 3 |

## Bonus N4 — Free spins | For deposit

| | | | |
|---|---|---|---|
| Bonus | 60 | | |
| Bet | 800 | Bonus amount | 48.000 |
| Max bonus amount | 200.000 | Contribution | 0.96 |
| Cashout | 20 | | |
| Max win | 4.000.000 | | |
| Provider | Playson | | |
| Game | 4 Pots Riches: Hold and Win | | |
| Days to activate bonus | 1 | | |
| **Min dep** | **50.000** | Days to make deposit | 1 |
| Wager | 30 | Days for wagering | 3 |

## Special Card (2 deposits made)

| Prize | Chance |
|---|---|
| Free spins with deposit | 10% |
| Casino deposit bonus | 10% |
| Free spins without deposit | 80% |

No-dep free spins spec: 20 FS · bet 60 · max bonus 50.000 · cashout 5 ·
max win 250.000 · Tada, Fortune Gems 2 · 1 day to activate · wager 0.

## Plan-B scratch card (didn't participate in main offer)

| Prize | Chance |
|---|---|
| Free spins with deposit | 48% |
| Casino deposit bonus | 48% |
| Free spins without deposit | 4% |
| Empty prize | 0% |

## Journeys (Grand Total)

| Journey | Template key |
|---|---|
| JBCL \| CS \| Big Promo - September \| Bonuses - 18.09 | `big_promo_day` |
| JBCL \| CS \| Big Promo - September \| Bonuses - 19.09 | duplicate of the 18.09 journey |
| JBCL \| CS \| Big Promo - September \| Special Card - 18.09 | `big_promo_special_card` |
| JBCL \| CS \| Big Promo - September \| Special Card - 19.09 | duplicate |
| JBCL \| CS \| Big Promo - September \| Scratch Card Plan B - 18.09 | `big_promo_plan_b` |
| JBCL \| CS \| Big Promo - September \| Scratch Card Plan B - 19.09 | duplicate |

## Build order

1. Instantiate `big_promo_special_card` and `big_promo_plan_b`, publish,
   note their `JRN-0-*` ids.
2. Instantiate `big_promo_day`, set the two campaign connectors'
   `campaignConnectorConditions.activityData.HostJourneyId` to those ids,
   publish.
3. Duplicate all three for day 2 (`POST /journeys/{jrn}/duplicate`
   regenerates every activity id and blanks the connector `campaignId`
   automatically — re-link `HostJourneyId` to the day-2 scratch journeys),
   rename to `- 19.09`.
4. The promo page routes visitors in with the player attribute
   `bonusOption` (1–4, the bonus tier the player picked); the decision
   split defaults to N1 when the attribute is missing.

## Mechanic notes

- Two deposits are counted **inside the journey**: bonus deposit at the
  gate, then an `event_detector` waits the rest of the day for a second
  `deposit.approved` of $10.000+; success feeds the Special Card via
  campaign connector, failure sends a "one more deposit" pop-up.
- Non-depositors get the reminder SMS and flow into the plan-B scratch
  card journey — nobody leaves the promo without a next step.
- Scratch prizes are weighted `random_split` paths, so the odds live in
  the journey (auditable), not in the front end.
