# Canvas design rules

The builder canvas follows these rules. Every rendering / layout change
must respect them — change the rule first, then the code.

## 1. Direction

1.1 A journey flows **top → bottom**. Time advances downward: sources at
    the top, terminals at the bottom.
1.2 A node's **layer** is its longest path from a source (layer 0 =
    sources). Auto-layout places layer *L* at
    `y = TOP + L * (NODE_H + ROW_GAP)`.
1.3 Within a layer, nodes are ordered by the **barycenter** (average
    horizontal position) of their parents — fewer edge crossings — and
    the whole layer is centered on the canvas axis.
1.4 Manual drags are respected: auto-layout never runs implicitly on a
    journey that already has saved positions. It is a button.

## 2. Ports

2.1 Every node has **one in-port**: center of its top edge.
2.2 Wired transitions leave through the **bottom edge**. When a node has
    *k* wired events, their exits fan out at `x = W * (i+1)/(k+1)` so
    parallel branches separate immediately and labels never stack.
2.3 Ports are visual anchors only — wiring happens in the inspector.

## 3. Edges

3.1 An edge is an **orthogonal connector** — a plain flowchart line, no
    curves: straight down out of the out-port, one horizontal run, then
    straight down into the in-port (`M x1,y1 V ym H x2 V y2`). Corners
    are square. The horizontal run sits at the vertical midpoint of the
    gap; sibling edges leaving the same node stagger their runs by 12px
    so horizontals never overlap.
3.2 An edge that must travel **upward** (a loop back) routes
    orthogonally around the left side of both nodes instead of cutting
    through them.
3.3 Every edge ends in an **arrowhead** at the in-port.
3.4 Edge colour is **semantic**, derived from the event name:
    - *success* (`Satisfied|Accepted|Success|Sent(?!.*Not)|Completed|
      Finished|Issued|Used|AddedToCampaign|PlayerAdded|WaitTimeCompleted`)
      → green;
    - *failure* (`Expired|Unsatisfied|Failed|NotSent|NotIssued|Canceled|
      Cancelled|Lost|Forfeited|Aborted|Terminated|NotAdded|NotReceived|
      NotUsed|NotComplied`) → red;
    - anything else (splits' paths, boundaries) → neutral slate.
3.5 `Boundary` edges are dashed; `Completion`/`Activation` are solid.
3.6 Every edge carries a **label pill** with the exact wire event name
    (the platform's vocabulary, never a paraphrase), in mono type,
    background-filled. The pill sits **just below the source port**, in
    the row gap (never over an intermediate node); sibling labels from
    the same node stagger alternately (+0 / +20px) so they cannot
    collide.

## 4. Nodes

4.1 A node is a 220px card: colour-coded **icon chip** + display name in
    the header; wire `activityName` + wiring status in the body.
4.2 The chip colour and icon come from the palette **category** (the
    single source of truth in `app.js`). Icons are **drawn SVGs** in one
    family — 16px grid, 1.5px rounded stroke, `currentColor` — never
    unicode glyphs or emoji.
4.3 **Terminals are pills**, not cards — `end_of_path` / `end_of_journey`
    carry no config and render as compact 148px capsules.
4.4 A non-terminal node with **zero wired completions** shows an amber
    warning dot — the draft will fail validation, say so before save.
4.5 Selection = accent ring + soft glow. Exactly one node selectable.

## 5. Interaction

5.1 Dragging snaps to an **8px grid**.
5.2 Clicking empty canvas clears the selection.
5.3 Zoom: 50–130% in 10% steps via toolbar buttons; drag math is
    zoom-corrected. Reset shows 100%.
5.4 Spacing constants live in one place (`builder.js` top):
    `NODE_W 220, NODE_H 78, TERM_W 148, TERM_H 36, COL_GAP 56,
    ROW_GAP 104, GRID 8`.

## 6. Colour

6.1 Category colours are defined once in `app.js` (`CATEGORY_COLORS`)
    and reused everywhere (palette, chips, ports) — never hard-coded per
    view.
6.2 Edge semantics (3.4) use dimmed strokes (`--edge-ok/--edge-fail/
    --edge-neutral`) so the canvas stays calm; full-saturation colour is
    reserved for selection and status badges.
