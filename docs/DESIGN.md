# DESIGN.md — The bookmaker's ledger

The visual world of this Journey Builder. Every surface derives from it;
the previous dark console is an anti-reference.

## The world

An operator's desk at a betting house: **bond paper, ink, table felt,
tickets**. The tool reads like a well-kept ledger — calm, precise,
matter-of-fact about money — executed as a modern instrument, not a
costume. Light, because the use scene is an operator working a normal
day, not a gamer in the dark.

## Signature

Two things carry the identity; everything else stays quiet:

1. **The felt rail** — the deep table-felt green top bar with the brass
   mark. The one saturated surface in the product.
2. **Ticket anatomy on the canvas** — nodes are white tickets whose meta
   strip sits below a dashed perforation rule; terminals are torn
   **stubs** (dashed-border pills). The graph reads as a pinned-up chain
   of betting slips.

## Tokens

| Role | Value |
|---|---|
| paper (app ground) | `#F2F0E9` |
| card / ticket | `#FFFFFF`, panel `#FAF8F3` |
| ink | `#20261F` · muted `#5A6156` · faint `#83897B` |
| rule lines | `#E0DCCE` · strong `#C9C4B0` |
| felt (primary, success) | `#175A41`, hover `#1D6B4E` |
| wax (failure, danger) | `#B0452F` |
| brass (rewards) | `#96752B` |
| edge strokes | pencil `#8A8574` · ok `#2E7D5B` · fail `#C05E45` |
| categories | source `#1C7A4E` · flow `#A67716` · comms `#2D6C9E` · delay `#6B5AA8` · connector `#AD4A77` · promo `#BC6425` · condition `#B0452F` · reward `#96752B` · terminal `#83897B` |

## Type

- **Zilla Slab** (self-hosted, OFL) is the voice — a print-flavoured
  slab that reads like ledger type: brand, page titles, node headlines,
  template names, the journey-name field. Weights 500/600 only.
- System sans for body/controls (Operate-mode familiarity).
- `ui-monospace` strictly for the wire vocabulary (event names, ids,
  activityName) with tabular numerals.

## Conduct

- Colour states meaning: felt = go/success, wax = failure, brass =
  reward. Category colour appears only in chips, ports, and the palette.
- Depth is paper depth: small offset, soft blur, never glows.
- Motion 150–250ms, state-conveying only.
- Canvas rules in `docs/CANVAS_RULES.md` are unchanged by the skin.
