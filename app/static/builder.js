/* The canvas builder: palette -> nodes -> wired events -> draft.
 *
 * Faithful to the imitated wire format: on save the UI writes BOTH storage
 * copies — `activities[]` (runtime) and `rawJourneyData` (editor mirror
 * with canvas positions + activitiesConfiguration).
 */
import {
  api, errText, getPalette, specFor, CATEGORY_COLORS, h, toast,
} from "./app.js";

const NODE_W = 208;

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
  els: {},               // canvas / edges / inspector / problems DOM refs
};

function defaultMeta() {
  return { draftId: null, journeyId: null, status: "Draft", name: "", brand: "JBCL", version: 0 };
}

function editable() {
  return state.meta.status === "Draft" || state.meta.status === "Stopped";
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
  if (![...positions.keys()].length) autoLayout();
}

/* ── auto-layout: BFS layers from the sources ── */
function autoLayout() {
  const incoming = new Map([...state.nodes.keys()].map((id) => [id, 0]));
  for (const node of state.nodes.values()) {
    for (const event of node.events) {
      if (event.nextActivityId && incoming.has(event.nextActivityId)) {
        incoming.set(event.nextActivityId, incoming.get(event.nextActivityId) + 1);
      }
    }
  }
  const layer = new Map();
  const queue = [...state.nodes.values()]
    .filter((node) => incoming.get(node.activityId) === 0)
    .map((node) => node.activityId);
  queue.forEach((id) => layer.set(id, 0));
  while (queue.length) {
    const id = queue.shift();
    const node = state.nodes.get(id);
    for (const event of node.events) {
      const target = event.nextActivityId;
      if (!target || !state.nodes.has(target)) continue;
      const next = (layer.get(id) || 0) + 1;
      if (next > (layer.get(target) ?? -1)) {
        layer.set(target, next);
        queue.push(target);
      }
    }
  }
  const perLayer = new Map();
  for (const node of state.nodes.values()) {
    const l = layer.get(node.activityId) ?? 0;
    const index = perLayer.get(l) || 0;
    perLayer.set(l, index + 1);
    node.x = 50 + l * 300;
    node.y = 60 + index * 170 + (l % 2) * 40;
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
    const spec = specFor(state.palette, node.activityName);
    const color = CATEGORY_COLORS[spec?.category] || "var(--faint)";
    const wired = node.events.filter((event) => event.nextActivityId).length;
    const el = h("div", {
      class: `node${state.selection === node.activityId ? " selected" : ""}`,
      style: `left:${node.x}px; top:${node.y}px`,
      "data-id": node.activityId,
    },
      h("div", { class: "node-head" },
        h("span", { class: "dot", style: `background:${color}` }),
        h("span", { class: "node-title" }, node.displayName)),
      h("div", { class: "node-body" },
        h("div", { class: "node-type" }, node.activityName),
        h("div", { class: "node-hint" },
          spec?.kind === "terminal" ? "terminal" : `${wired}/${node.events.length} events wired`)),
      h("span", { class: "node-port in" }),
      spec?.kind === "terminal" ? null : h("span", { class: "node-port out" }),
    );
    attachNodeBehaviour(el, node);
    canvas.append(el);
  }
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
      const dx = move.clientX - startX, dy = move.clientY - startY;
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      if (!moved) return;
      node.x = Math.max(0, origX + dx);
      node.y = Math.max(0, origY + dy);
      el.style.left = `${node.x}px`;
      el.style.top = `${node.y}px`;
      el.classList.add("dragging");
      renderEdges();
    };
    const onUp = () => {
      el.classList.remove("dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
}

function renderEdges() {
  const svg = state.els.edges;
  svg.innerHTML = "";
  const ns = "http://www.w3.org/2000/svg";
  for (const node of state.nodes.values()) {
    for (const event of node.events) {
      const target = event.nextActivityId && state.nodes.get(event.nextActivityId);
      if (!target) continue;
      const x1 = node.x + NODE_W, y1 = node.y + 19;
      const x2 = target.x, y2 = target.y + 19;
      const bend = Math.max(40, Math.abs(x2 - x1) / 2);
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
      path.setAttribute("class", `edge-path${event.eventType === "Boundary" ? " boundary" : ""}`);
      svg.append(path);
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", (x1 + x2) / 2);
      label.setAttribute("y", (y1 + y2) / 2 - 6);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("class", "edge-label");
      label.textContent = event.eventName;
      svg.append(label);
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
  const spec = specFor(state.palette, node.activityName);
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
        h("span", { class: "evt", title: event.eventName }, event.eventName), select));
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

/* ── the sample journey (one click, runnable) ── */
function loadSample() {
  state.nodes = new Map();
  const source = makeNode("external_system_source", 0, 0);
  const promo = makeNode("promotion", 0, 0);
  const gate = makeNode("deposit", 0, 0);
  const spins = makeNode("freespin_bonus", 0, 0);
  const notify = makeNode("notification_center", 0, 0);
  const end = makeNode("end_of_journey", 0, 0);
  const sorry = makeNode("end_of_path", 0, 0);
  promo.displayName = "Welcome offer";
  gate.displayName = "Deposit $100+";
  spins.displayName = "30 freespins";
  notify.displayName = "You won!";
  const wire = (node, eventName, target) => {
    node.events.find((event) => event.eventName === eventName).nextActivityId = target.activityId;
  };
  wire(source, "PlayerAdded", promo);
  wire(promo, "PromotionAccepted", gate);
  wire(promo, "PromotionExpired", sorry);
  wire(gate, "DepositConditionSatisfied", spins);
  wire(gate, "DepositConditionUnsatisfied", sorry);
  wire(spins, "FreespinBonusCollectingFinished", notify);
  wire(notify, "NotificationSent", end);
  for (const node of [source, promo, gate, spins, notify, end, sorry]) {
    state.nodes.set(node.activityId, node);
  }
  autoLayout();
  if (!state.meta.name) state.meta.name = "JBCL | SAMPLE | welcome freespins";
  render();
}

/* ── main view ── */
export async function renderBuilder(view, journeyId) {
  state.palette = await getPalette();
  state.selection = null;

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
  const sampleBtn = h("button", { class: "btn ghost" }, "Load sample");
  const layoutBtn = h("button", { class: "btn ghost", title: "Re-layout the canvas" }, "Auto-layout");

  const toolbar = h("div", { class: "builder-toolbar" },
    nameInput, brandInput, h("span", { id: "meta-badge" }, statusBadge()),
    h("div", { class: "spacer", style: "flex:1" }),
    sampleBtn, layoutBtn, validateBtn, saveBtn, publishBtn, runLink,
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
        const node = makeNode(item.activityName, 80 + (state.nodes.size % 5) * 60, 80 + (state.nodes.size % 7) * 70);
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
    sampleBtn.style.display = state.nodes.size || state.meta.draftId ? "none" : "";
    publishBtn.disabled = !(state.meta.draftId && (state.meta.status === "Draft" || state.meta.status === "Stopped"));
    runLink.style.display = state.meta.status === "Published" ? "" : "none";
  };

  sampleBtn.addEventListener("click", () => { loadSample(); nameInput.value = state.meta.name; refreshMeta(); });
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
}
