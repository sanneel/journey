/* The canvas builder: palette -> nodes -> wired events -> draft.
 *
 * Rendering and layout follow docs/CANVAS_RULES.md — change the rule
 * first, then this file. Journeys flow TOP -> BOTTOM (rule 1.1).
 *
 * Faithful to the imitated wire format: on save the UI writes BOTH storage
 * copies — `activities[]` (runtime) and `rawJourneyData` (editor mirror
 * with canvas positions + activitiesConfiguration).
 */
import {
  api, errText, getPalette, specFor, CATEGORY_COLORS, h, toast,
} from "./app.js";

/* rule 5.4 — spacing constants live here */
const NODE_W = 220, NODE_H = 78;
const TERM_W = 148, TERM_H = 36;
const COL_GAP = 56, ROW_GAP = 104;
const GRID = 8, TOP = 48, AXIS_X = 640;
const ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2, 1.3];

/* rule 4.2 — category icons */
const ICONS = {
  "Input Source": "▶",
  "Flow control": "⇄",
  "Communication": "✉",
  "Delays": "◷",
  "Connectors": "∞",
  "Promotion type": "✦",
  "Conditions": "◈",
  "Reward type": "★",
  "Terminals": "■",
};

/* rule 3.4 — edge semantics derived from the event name */
const FAIL_RE = /Expired|Unsatisfied|Failed|NotSent|NotIssued|Canceled|Cancelled|Lost|Forfeited|Aborted|Terminated|NotAdded|NotReceived|NotUsed|NotComplied/;
const OK_RE = /Satisfied|Accepted|Success|Completed|Finished|Issued|Used|AddedToCampaign|PlayerAdded|WaitTimeCompleted|Sent$/;
function edgeSemantics(eventName) {
  if (FAIL_RE.test(eventName)) return "fail";
  if (OK_RE.test(eventName)) return "ok";
  return "neutral";
}

const snap = (value) => Math.round(value / GRID) * GRID;

/* starter initializationData per type, so a fresh node is runnable */
const STARTERS = {
  external_system_source: { targetSystem: "Randomizer", description: "" },
  dwh_source: { dataSourceName: "segment", filterDetails: {} },
  registration: { promocodeSettings: { refCodes: [] } },
  promotion: { autoAccept: true, timeToAccept: "P0Y0M1DT0H0M0S" },
  multipurpose_promotion: { autoAccept: true, timeToAccept: "P0Y0M1DT0H0M0S" },
  deposit: {
    depositConditions: {
      expirationTimeout: "P0Y0M1DT0H0M0S",
      minDepositAmounts: [{ brand: "JBCL", amount: 10000, currencyCode: "CLP" }],
      depositAccountingType: "Any",
    },
  },
  wait_interval: { waitPeriod: "P0Y0M1DT0H0M0S" },
  wait_date: { waitTo: "" },
  event_detector: {
    properties: {
      startingOptions: { durationTime: "P0Y0M1DT0H0M0S" },
      subscriptionOptions: [{
        event: { eventName: "deposit.approved", sourceName: "platform.orders" },
        filter: {
          property: { name: "amount", type: "number", value: "5000", operator: "greaterThanOrEqualCurrency" },
          variables: [{ name: "currency", type: "currency", value: "CLP" }],
        },
      }],
    },
  },
  freespin_bonus: {
    freespinActivity: { spins: 30, provider: "provider", lobbyGameId: "game-id", spinsExpirationDuration: 86400000 },
  },
  casino_bonus_v2: {
    activitySubtype: "deposit", productType: "slots", bonusPercent: 100,
    wageringRequirement: 25, bonusExpirationTime: 172800000,
  },
  freebet: { properties: {} },
  sport_bonus: { properties: {} },
  notification_center: { contract: 1, templates: {} },
  dextra_sms: { rawValues: { messageText: "" } },
  dextra_email: { emailSettings: {} },
  native_push: {},
  ams_decision_split: {
    rules: [{
      name: "rule 1",
      filter: { property: { name: "playerValue", type: "number", value: "100", operator: "gte" }, variables: [] },
    }],
    pathesConfig: [],
  },
  random_split: {
    paths: [
      { pathId: "path1", pathName: "Path 1", probability: 50 },
      { pathId: "path2", pathName: "Path 2", probability: 50 },
    ],
    pathesConfig: [],
  },
  notification_center_engagement_split: {
    properties: {
      paths: [
        { pathId: "path1", pathName: "Clicked", notificationCenterEngagementStatuses: ["Clicked"] },
        { pathId: "other", pathName: "Other", notificationCenterEngagementStatuses: ["NotSent", "Sent", "Shown", "Read"] },
      ],
      DextraNotificationCenterActivityId: "",
    },
    pathesConfig: [],
  },
  campaign_connector: {
    campaignConnectorConditions: { campaignId: "", activityData: { HostJourneyId: "" } },
  },
  sport_bet_condition: { minBetAmount: 1000, minOdd: 1.5, expireInDays: 7 },
};

const state = {
  palette: null,
  nodes: new Map(),      // activityId -> node
  meta: null,            // {draftId, journeyId, status, name, brand, version}
  selection: null,
  zoom: 1,
  els: {},               // canvas / edges / inspector / problems DOM refs
};

function defaultMeta() {
  return { draftId: null, journeyId: null, status: "Draft", name: "", brand: "JBCL", version: 0 };
}

function editable() {
  return state.meta.status === "Draft" || state.meta.status === "Stopped";
}

function nodeSpec(node) {
  return specFor(state.palette, node.activityName);
}

/* rule 4.3 — terminals are pills */
function nodeSize(node) {
  return nodeSpec(node)?.kind === "terminal"
    ? { w: TERM_W, h: TERM_H }
    : { w: NODE_W, h: NODE_H };
}

/* ── node model ── */
function makeNode(activityName, x, y) {
  const spec = specFor(state.palette, activityName);
  const id = crypto.randomUUID();
  const events = [];
  if (spec.events.activation.length) {
    events.push({ eventName: "PlayerAdded", eventType: "Activation", nextActivityId: null });
  }
  for (const eventName of spec.events.completion) {
    events.push({ eventName, eventType: "Completion", nextActivityId: null });
  }
  return {
    activityId: id,
    activityName,
    displayName: spec.label,
    init: structuredClone(STARTERS[activityName] || {}),
    events,
    x, y,
  };
}

function wiredEvents(node) {
  return node.events.filter(
    (event) => event.nextActivityId && state.nodes.has(event.nextActivityId),
  );
}

/* ── serialization: body <-> canvas ── */
function buildBody() {
  const activities = [...state.nodes.values()].map((node) => ({
    activityId: node.activityId,
    activityName: node.activityName,
    activityDisplayName: node.displayName,
    events: node.events,
    dependencies: [],
    dataDependencies: [],
    initializationData: node.init,
  }));
  const elements = [...state.nodes.values()].map((node) => ({
    id: node.activityId,
    type: "node",
    activityName: node.activityName,
    position: { x: node.x, y: node.y },
  }));
  for (const node of state.nodes.values()) {
    for (const event of node.events) {
      if (event.nextActivityId) {
        elements.push({
          id: `edge-${node.activityId}-${event.eventName}`,
          type: "edge",
          source: node.activityId,
          target: event.nextActivityId,
          eventName: event.eventName,
        });
      }
    }
  }
  const activitiesConfiguration = {};
  for (const node of state.nodes.values()) {
    activitiesConfiguration[node.activityId] = { displayName: node.displayName };
  }
  return {
    journeyName: state.meta.name,
    brand: state.meta.brand,
    currencyCodes: ["CLP"],
    timeZoneId: "Chile/Continental",
    isImmediatelyAfterPublish: true,
    isUnlimited: true,
    reEntryRule: { reEntryMode: "Prohibited" },
    activities,
    rawJourneyData: {
      elements,
      activitiesConfiguration,
      infoValues: { journeyName: state.meta.name },
    },
  };
}

function loadBody(body, meta) {
  state.nodes = new Map();
  state.meta = meta;
  const positions = new Map();
  for (const element of body.rawJourneyData?.elements || []) {
    if (element.type === "node" && element.position) {
      positions.set(element.id, element.position);
    }
  }
  for (const activity of body.activities || []) {
    const position = positions.get(activity.activityId) || { x: 0, y: 0 };
    state.nodes.set(activity.activityId, {
      activityId: activity.activityId,
      activityName: activity.activityName,
      displayName: activity.activityDisplayName || activity.activityName,
      init: activity.initializationData || {},
      events: (activity.events || []).map((event) => ({ ...event })),
      x: position.x,
      y: position.y,
    });
  }
  /* rule 1.4 — only layout when there are no saved positions */
  if (![...positions.keys()].length) autoLayout();
}

/* ── auto-layout (rules 1.2–1.3): longest-path layers, barycenter order,
 *    each layer centered on the axis ── */
function autoLayout() {
  const nodes = [...state.nodes.values()];
  if (!nodes.length) return;

  const adjacency = new Map(nodes.map((node) => [node.activityId, []]));
  const indegree = new Map(nodes.map((node) => [node.activityId, 0]));
  for (const node of nodes) {
    for (const event of node.events) {
      const target = event.nextActivityId;
      if (target && state.nodes.has(target)) {
        adjacency.get(node.activityId).push(target);
        indegree.set(target, indegree.get(target) + 1);
      }
    }
  }

  const layerOf = new Map();
  const queue = nodes
    .filter((node) => indegree.get(node.activityId) === 0)
    .map((node) => node.activityId);
  queue.forEach((id) => layerOf.set(id, 0));
  const remaining = new Map(indegree);
  while (queue.length) {
    const id = queue.shift();
    for (const target of adjacency.get(id)) {
      layerOf.set(target, Math.max(layerOf.get(target) ?? 0, layerOf.get(id) + 1));
      remaining.set(target, remaining.get(target) - 1);
      if (remaining.get(target) === 0) queue.push(target);
    }
  }
  for (const node of nodes) {
    if (!layerOf.has(node.activityId)) layerOf.set(node.activityId, 0);
  }

  const layers = new Map();
  for (const node of nodes) {
    const layer = layerOf.get(node.activityId);
    if (!layers.has(layer)) layers.set(layer, []);
    layers.get(layer).push(node);
  }

  const parentsOf = new Map(nodes.map((node) => [node.activityId, []]));
  for (const node of nodes) {
    for (const target of adjacency.get(node.activityId)) {
      parentsOf.get(target).push(node);
    }
  }

  let y = TOP;
  for (const layer of [...layers.keys()].sort((a, b) => a - b)) {
    const row = layers.get(layer);
    if (layer > 0) {
      const barycenter = (node) => {
        const parents = parentsOf.get(node.activityId)
          .filter((parent) => (layerOf.get(parent.activityId) ?? 0) < layer);
        if (!parents.length) return Number.MAX_SAFE_INTEGER;
        return parents.reduce((sum, parent) => sum + parent.x + nodeSize(parent).w / 2, 0) / parents.length;
      };
      row.sort((a, b) => barycenter(a) - barycenter(b));
    }
    const total = row.reduce((sum, node) => sum + nodeSize(node).w, 0)
      + COL_GAP * (row.length - 1);
    let x = Math.max(24, AXIS_X - total / 2);
    const rowHeight = Math.max(...row.map((node) => nodeSize(node).h));
    for (const node of row) {
      const size = nodeSize(node);
      node.x = snap(x);
      node.y = snap(y + (rowHeight - size.h) / 2);
      x += size.w + COL_GAP;
    }
    y += rowHeight + ROW_GAP;
  }
}

/* ── rendering ── */
function render() {
  renderNodes();
  renderEdges();
  renderInspector();
}

function renderNodes() {
  const canvas = state.els.canvas;
  canvas.querySelectorAll(".node").forEach((el) => el.remove());
  for (const node of state.nodes.values()) {
    const spec = nodeSpec(node);
    const color = CATEGORY_COLORS[spec?.category] || "var(--faint)";
    const icon = ICONS[spec?.category] || "●";
    const size = nodeSize(node);
    const selected = state.selection === node.activityId ? " selected" : "";

    let el;
    if (spec?.kind === "terminal") {
      el = h("div", {
        class: `node terminal${selected}`,
        style: `left:${node.x}px; top:${node.y}px`,
        "data-id": node.activityId,
      },
        h("span", { class: "chip", style: `color:${color}` }, icon),
        h("span", { class: "node-title" },
          node.activityName === "end_of_journey" ? "End of journey" : "End of path"),
        h("span", { class: "node-port in", style: `left:${size.w / 2 - 5}px` }),
      );
    } else {
      const wired = wiredEvents(node).length;
      const completions = node.events.filter((event) => event.eventType !== "Boundary").length;
      /* rule 4.4 — warn when nothing is wired */
      const warn = wired === 0 && completions > 0;
      el = h("div", {
        class: `node${selected}`,
        style: `left:${node.x}px; top:${node.y}px`,
        "data-id": node.activityId,
      },
        h("div", { class: "node-head" },
          h("span", { class: "chip", style: `color:${color}; background:color-mix(in srgb, ${color} 16%, transparent)` }, icon),
          h("span", { class: "node-title" }, node.displayName),
          warn ? h("span", { class: "warn-dot", title: "no outgoing transition wired" }) : null),
        h("div", { class: "node-body" },
          h("div", { class: "node-type" }, node.activityName),
          h("div", { class: "node-hint" }, `${wired}/${completions} events wired`)),
        h("span", { class: "node-port in", style: `left:${size.w / 2 - 5}px` }),
        ...portDots(node, color),
      );
    }
    attachNodeBehaviour(el, node);
    canvas.append(el);
  }
}

/* rule 2.2 — bottom-edge fan-out anchors */
function outAnchors(node) {
  const wired = wiredEvents(node);
  const size = nodeSize(node);
  return wired.map((event, index) => ({
    event,
    x: node.x + size.w * ((index + 1) / (wired.length + 1)),
    y: node.y + size.h,
  }));
}

function portDots(node, color) {
  const anchors = outAnchors(node);
  const size = nodeSize(node);
  if (!anchors.length) {
    return [h("span", { class: "node-port out", style: `left:${size.w / 2 - 5}px; border-color:${color}` })];
  }
  return anchors.map((anchor) =>
    h("span", {
      class: "node-port out",
      style: `left:${anchor.x - node.x - 5}px; border-color:${color}`,
      title: anchor.event.eventName,
    }));
}

function attachNodeBehaviour(el, node) {
  el.addEventListener("pointerdown", (down) => {
    if (down.button !== 0) return;
    down.preventDefault();
    state.selection = node.activityId;
    renderNodes(); renderInspector();
    const startX = down.clientX, startY = down.clientY;
    const origX = node.x, origY = node.y;
    let moved = false;
    const onMove = (move) => {
      const dx = (move.clientX - startX) / state.zoom;
      const dy = (move.clientY - startY) / state.zoom;
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      if (!moved) return;
      node.x = Math.max(0, snap(origX + dx));   /* rule 5.1 — grid snap */
      node.y = Math.max(0, snap(origY + dy));
      el.style.left = `${node.x}px`;
      el.style.top = `${node.y}px`;
      el.classList.add("dragging");
      renderEdges();
    };
    const onUp = () => {
      el.classList.remove("dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (moved) renderNodes();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
}

function renderEdges() {
  const svg = state.els.edges;
  svg.innerHTML = "";
  const ns = "http://www.w3.org/2000/svg";

  /* rule 3.3 — arrowheads, one marker per semantic colour */
  const defs = document.createElementNS(ns, "defs");
  for (const kind of ["neutral", "ok", "fail"]) {
    const marker = document.createElementNS(ns, "marker");
    marker.setAttribute("id", `arr-${kind}`);
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", "8");
    marker.setAttribute("refY", "5");
    marker.setAttribute("markerWidth", "7");
    marker.setAttribute("markerHeight", "7");
    marker.setAttribute("orient", "auto-start-reverse");
    const tip = document.createElementNS(ns, "path");
    tip.setAttribute("d", "M0 0 L10 5 L0 10 z");
    tip.setAttribute("class", `arrow-tip ${kind}`);
    marker.append(tip);
    defs.append(marker);
  }
  svg.append(defs);

  for (const node of state.nodes.values()) {
    for (const [anchorIndex, anchor] of outAnchors(node).entries()) {
      const event = anchor.event;
      const target = state.nodes.get(event.nextActivityId);
      const targetSize = nodeSize(target);
      const p0 = { x: anchor.x, y: anchor.y };
      const p3 = { x: target.x + targetSize.w / 2, y: target.y };  /* rule 2.1 */
      const semantics = edgeSemantics(event.eventName);

      let p1, p2;
      if (p3.y > p0.y + 20) {
        /* rule 3.1 — vertical bezier, straight out / straight in */
        const d = Math.min(120, Math.max(40, (p3.y - p0.y) / 2));
        p1 = { x: p0.x, y: p0.y + d };
        p2 = { x: p3.x, y: p3.y - d };
      } else {
        /* rule 3.2 — upward edge bows around the side */
        const side = Math.min(p0.x, p3.x) - 180;
        p1 = { x: side, y: p0.y + 80 };
        p2 = { x: side, y: p3.y - 80 };
      }

      const path = document.createElementNS(ns, "path");
      path.setAttribute("d",
        `M ${p0.x} ${p0.y} C ${p1.x} ${p1.y}, ${p2.x} ${p2.y}, ${p3.x} ${p3.y}`);
      path.setAttribute("class",
        `edge-path ${semantics}${event.eventType === "Boundary" ? " boundary" : ""}`);
      path.setAttribute("marker-end", `url(#arr-${semantics})`);
      svg.append(path);

      /* rule 3.6 — label pill in the row gap below the source port,
       * siblings staggered so they never collide */
      const at = { x: p0.x, y: p0.y + 26 + (anchorIndex % 2) * 20 };
      const group = document.createElementNS(ns, "g");
      group.setAttribute("class", `edge-pill ${semantics}`);
      const text = document.createElementNS(ns, "text");
      text.setAttribute("x", at.x);
      text.setAttribute("y", at.y);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("dominant-baseline", "middle");
      text.textContent = event.eventName;
      group.append(text);
      svg.append(group);
      const box = text.getBBox();
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", box.x - 7);
      rect.setAttribute("y", box.y - 3);
      rect.setAttribute("width", box.width + 14);
      rect.setAttribute("height", box.height + 6);
      rect.setAttribute("rx", 8);
      group.insertBefore(rect, text);
    }
  }
}

/* ── inspector ── */
function renderInspector() {
  const panel = state.els.inspector;
  panel.innerHTML = "";
  const node = state.selection && state.nodes.get(state.selection);
  if (!node) {
    panel.append(h("div", { class: "inspector-empty" },
      "Select an activity on the canvas,", h("br"), "or add one from the palette."));
    return;
  }
  const spec = nodeSpec(node);
  const locked = !editable();

  panel.append(
    h("h2", {}, node.displayName),
    h("div", { class: "type-line" },
      h("span", { class: "mono dim small" }, node.activityName),
      " ", h("span", { class: "dim small" }, `· ${spec?.category || ""}`)),
  );

  const nameField = h("input", { class: "input", value: node.displayName });
  nameField.disabled = locked;
  nameField.addEventListener("input", () => {
    node.displayName = nameField.value;
    renderNodes();
  });
  panel.append(h("label", { class: "field" }, h("span", {}, "Display name"), nameField));

  /* wiring */
  const wireable = node.events.filter((event) => event.eventType !== "Boundary");
  if (wireable.length) {
    panel.append(h("h4", {}, "Transitions (events -> next activity)"));
    for (const event of wireable) {
      const select = h("select", { class: "input" });
      select.append(h("option", { value: "" }, "— none —"));
      for (const other of state.nodes.values()) {
        if (other.activityId === node.activityId) continue;
        const option = h("option", { value: other.activityId }, other.displayName);
        if (event.nextActivityId === other.activityId) option.selected = true;
        select.append(option);
      }
      select.disabled = locked;
      select.addEventListener("change", () => {
        event.nextActivityId = select.value || null;
        renderNodes(); renderEdges();
      });
      panel.append(h("div", { class: "wire-row" },
        h("span", { class: `evt ${edgeSemantics(event.eventName)}`, title: event.eventName },
          event.eventName),
        select));
    }
  }

  /* initializationData */
  if (spec?.kind !== "terminal") {
    panel.append(h("h4", {}, "initializationData"));
    const textarea = h("textarea", { class: "input", rows: "12" });
    textarea.value = JSON.stringify(node.init, null, 2);
    textarea.disabled = locked;
    textarea.addEventListener("change", () => {
      try {
        node.init = JSON.parse(textarea.value || "{}");
        textarea.style.borderColor = "";
      } catch {
        textarea.style.borderColor = "var(--danger)";
        toast("initializationData is not valid JSON", "err");
      }
    });
    panel.append(textarea);
  }

  if (!locked) {
    const remove = h("button", { class: "btn danger sm", style: "margin-top:14px" }, "Remove activity");
    remove.addEventListener("click", () => {
      state.nodes.delete(node.activityId);
      for (const other of state.nodes.values()) {
        for (const event of other.events) {
          if (event.nextActivityId === node.activityId) event.nextActivityId = null;
        }
      }
      state.selection = null;
      render();
    });
    panel.append(h("div", {}, remove));
  }
}

/* ── problems panel ── */
function showProblems(container, detail, okMessage) {
  container.innerHTML = "";
  if (!detail) {
    if (okMessage) container.append(h("div", { class: "problem okline" }, okMessage));
    return;
  }
  const entries = detail.aggregatedError?.journeyActivityError || [];
  for (const entry of entries) {
    for (const problem of entry.problemDetails) {
      const node = entry.activityId && state.nodes.get(entry.activityId);
      container.append(h("div", { class: "problem" },
        h("div", { class: "slug" }, problem.type),
        h("div", {}, problem.title, node ? ` — ${node.displayName}` : ""),
        problem.detail ? h("div", { class: "dim small" }, problem.detail) : null));
    }
  }
}

/* ── templates: server-provided campaign shapes, fresh ids per call ── */
async function loadTemplate(key, nameInput, refreshMeta) {
  if (state.nodes.size &&
      !confirm("Replace the current canvas with this template?")) return;
  try {
    const { body } = await api("GET", `/journey-builder/v0/journey-templates/${key}`);
    const meta = state.meta;
    loadBody(body, meta);            // no saved positions -> auto-layout
    if (!meta.name) meta.name = body.journeyName;
    nameInput.value = meta.name;
    state.selection = null;
    render();
    refreshMeta();
    toast(`Template loaded — ${body.activities.length} activities`, "ok");
  } catch (error) {
    toast(errText(error), "err");
  }
}

/* ── main view ── */
export async function renderBuilder(view, journeyId) {
  state.palette = await getPalette();
  state.selection = null;
  state.zoom = 1;

  if (journeyId) {
    const data = await api("GET", `/journey-builder/v0/journeys/${journeyId}`);
    loadBody(data.body, {
      draftId: data.id, journeyId: data.journeyId, status: data.status,
      name: data.journeyName, brand: data.brand, version: data.version,
    });
  } else {
    state.nodes = new Map();
    state.meta = defaultMeta();
  }

  view.innerHTML = "";
  const nameInput = h("input", { class: "input name", placeholder: "Journey name (BRAND | TYPE | name)", value: state.meta.name });
  nameInput.addEventListener("input", () => (state.meta.name = nameInput.value));
  const brandInput = h("input", { class: "input brand", value: state.meta.brand, title: "brand" });
  brandInput.addEventListener("input", () => (state.meta.brand = brandInput.value));

  const statusBadge = () => h("span", { class: `badge ${state.meta.status}` },
    state.meta.journeyId ? `${state.meta.journeyId} · ${state.meta.status}` : "unsaved");

  const problems = h("div", { class: "problems", style: "position:absolute; right:336px; top:66px; width:360px; z-index:20" });

  const validateBtn = h("button", { class: "btn" }, "Validate");
  const saveBtn = h("button", { class: "btn primary" }, "Save draft");
  const publishBtn = h("button", { class: "btn" }, "Publish");
  const runLink = h("button", { class: "btn ghost" }, "Run view ->");
  const layoutBtn = h("button", { class: "btn ghost", title: "Re-layout top to bottom" }, "Auto-layout");

  /* templates menu */
  const templatesBtn = h("button", { class: "btn ghost" }, "Templates ▾");
  const templatesMenu = h("div", { class: "tpl-menu", style: "display:none" });
  const templatesWrap = h("span", { class: "tpl-wrap" }, templatesBtn, templatesMenu);
  let templatesLoaded = false;
  templatesBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (!editable()) return toast("Stop the journey to edit it", "err");
    if (!templatesLoaded) {
      const data = await api("GET", "/journey-builder/v0/journey-templates");
      templatesMenu.innerHTML = "";
      for (const template of data.items) {
        const item = h("button", { class: "tpl-item" },
          h("strong", {}, template.name),
          h("span", { class: "dim small" }, ` · ${template.activities} activities`),
          h("div", { class: "dim small" }, template.description));
        item.addEventListener("click", () => {
          templatesMenu.style.display = "none";
          loadTemplate(template.key, nameInput, refreshMeta);
        });
        templatesMenu.append(item);
      }
      templatesLoaded = true;
    }
    templatesMenu.style.display = templatesMenu.style.display === "none" ? "" : "none";
  });
  document.addEventListener("click", () => (templatesMenu.style.display = "none"));

  /* rule 5.3 — zoom controls */
  const zoomLabel = h("span", { class: "zoom-label" }, "100%");
  const applyZoom = () => {
    state.els.canvas.style.transform = `scale(${state.zoom})`;
    zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
  };
  const zoomStep = (direction) => {
    const index = ZOOM_STEPS.indexOf(state.zoom);
    const next = ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, index + direction))];
    state.zoom = next;
    applyZoom();
  };
  const zoomOut = h("button", { class: "btn ghost sm", title: "Zoom out" }, "−");
  const zoomIn = h("button", { class: "btn ghost sm", title: "Zoom in" }, "+");
  zoomOut.addEventListener("click", () => zoomStep(-1));
  zoomIn.addEventListener("click", () => zoomStep(1));
  zoomLabel.addEventListener("click", () => { state.zoom = 1; applyZoom(); });

  const toolbar = h("div", { class: "builder-toolbar" },
    nameInput, brandInput, h("span", { id: "meta-badge" }, statusBadge()),
    h("div", { class: "spacer", style: "flex:1" }),
    h("span", { class: "zoom-group" }, zoomOut, zoomLabel, zoomIn),
    templatesWrap, layoutBtn, validateBtn, saveBtn, publishBtn, runLink,
  );

  const paletteEl = h("div", { class: "palette" });
  for (const group of state.palette) {
    paletteEl.append(h("h3", {}, group.category));
    for (const item of group.activities) {
      const button = h("button", { class: "palette-item", title: item.activityName },
        h("span", { class: "dot", style: `background:${CATEGORY_COLORS[group.category]}` }),
        item.label,
        h("span", { class: "wire" }, item.kind));
      button.addEventListener("click", () => {
        if (!editable()) return toast("Stop the journey to edit it", "err");
        const node = makeNode(
          item.activityName,
          snap(AXIS_X - NODE_W / 2 + ((state.nodes.size % 3) - 1) * 40),
          snap(TOP + state.nodes.size * 48),
        );
        state.nodes.set(node.activityId, node);
        state.selection = node.activityId;
        render();
      });
      paletteEl.append(button);
    }
  }

  const edges = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  edges.setAttribute("class", "edges");
  const canvas = h("div", { class: "canvas" });
  canvas.append(edges);
  canvas.addEventListener("pointerdown", (event) => {
    if (event.target === canvas) { state.selection = null; renderNodes(); renderInspector(); }
  });
  const canvasWrap = h("div", { class: "canvas-wrap" }, canvas, problems);
  const inspector = h("div", { class: "inspector" });

  view.append(h("div", { class: "builder" }, toolbar, paletteEl, canvasWrap, inspector));
  state.els = { canvas, edges, inspector, problems };

  const refreshMeta = () => {
    const holder = document.getElementById("meta-badge");
    holder.innerHTML = "";
    holder.append(statusBadge());
    const locked = !editable();
    saveBtn.disabled = locked;
    templatesBtn.disabled = locked;
    publishBtn.disabled = !(state.meta.draftId && (state.meta.status === "Draft" || state.meta.status === "Stopped"));
    runLink.style.display = state.meta.status === "Published" ? "" : "none";
  };

  layoutBtn.addEventListener("click", () => { autoLayout(); render(); });

  validateBtn.addEventListener("click", async () => {
    const body = buildBody();
    if (state.meta.journeyId) body.journeyId = state.meta.journeyId;
    const result = await api("POST", "/journey-builder/v0/journey-drafts/validate", body);
    showProblems(problems, result.valid ? null : result, "Draft is valid — ready to save.");
    setTimeout(() => (problems.innerHTML = ""), 6000);
  });

  saveBtn.addEventListener("click", async () => {
    if (!state.meta.name.trim()) return toast("Give the journey a name first", "err");
    const body = buildBody();
    try {
      let saved;
      if (state.meta.draftId) {
        body.journeyId = state.meta.journeyId;
        body.reservedJourneyId = state.meta.journeyId;
        saved = await api("PUT", `/journey-builder/v0/journey-drafts/${state.meta.draftId}`, body);
      } else {
        saved = await api("POST", "/journey-builder/v0/journey-drafts", body);
      }
      state.meta.draftId = saved.id;
      state.meta.journeyId = saved.journeyId;
      state.meta.status = saved.status;
      state.meta.version = saved.version;
      loadBody(saved.body, state.meta);
      render();
      showProblems(problems, null);
      toast(`Saved ${saved.journeyId} (v${saved.version})`, "ok");
      refreshMeta();
      history.replaceState(null, "", `#/builder/${saved.journeyId}`);
    } catch (error) {
      if (error.detail?.aggregatedError) showProblems(problems, error.detail);
      else toast(errText(error), "err");
    }
  });

  publishBtn.addEventListener("click", async () => {
    try {
      const result = await api("POST", `/journey-builder/v0/journeys/${state.meta.journeyId}/publish`);
      state.meta.status = result.status;
      toast(`${state.meta.journeyId} is live${result.webhooks.length ? ` — ${result.webhooks.length} webhook(s)` : ""}`, "ok");
      refreshMeta();
      renderInspector();
    } catch (error) {
      toast(errText(error), "err");
    }
  });

  runLink.addEventListener("click", () => (location.hash = `#/run/${state.meta.journeyId}`));

  refreshMeta();
  render();
  applyZoom();
}
