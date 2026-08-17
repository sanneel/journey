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
  api, errText, getPalette, specFor, CATEGORY_COLORS, categoryIcon, h, toast,
} from "./app.js";

/* rule 5.4 — spacing constants live here */
const NODE_W = 232, NODE_H = 102;
const TERM_W = 148, TERM_H = 36;
const COL_GAP = 56, ROW_GAP = 116;
const GRID = 8, TOP = 48, AXIS_X = 640;
const ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2, 1.3];

/* rule 3.4 — edge semantics derived from the event name */
const FAIL_RE = /Expired|Unsatisfied|Failed|NotSent|NotIssued|Canceled|Cancelled|Lost|Forfeited|Aborted|Terminated|NotAdded|NotReceived|NotUsed|NotComplied/;
const OK_RE = /Satisfied|Accepted|Success|Completed|Finished|Issued|Used|AddedToCampaign|PlayerAdded|WaitTimeCompleted|Sent$/;
function edgeSemantics(eventName) {
  if (FAIL_RE.test(eventName)) return "fail";
  if (OK_RE.test(eventName)) return "ok";
  return "neutral";
}

const snap = (value) => Math.round(value / GRID) * GRID;

/* ── human-readable config summaries (rule 4.1: a node shows its
 *    decision content, not its JSON) ── */
function humanizeIso(iso) {
  if (!iso || typeof iso !== "string") return null;
  const match = iso.match(/P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?/);
  if (!match) return null;
  const [, years, months, days, hours, minutes, seconds] = match.map((v) => Number(v) || 0);
  const totalDays = years * 365 + months * 30 + days;
  if (totalDays >= 1) return `${totalDays} day${totalDays > 1 ? "s" : ""}`;
  if (hours >= 1) return `${hours} h`;
  if (minutes >= 1) return `${minutes} min`;
  if (seconds >= 1) return `${seconds} s`;
  return "instant";
}

function humanizeMs(ms) {
  if (typeof ms !== "number" || ms <= 0) return null;
  const hours = ms / 3600000;
  if (hours >= 48) return `${Math.round(hours / 24)} days`;
  if (hours >= 1) return `${Math.round(hours)} h`;
  return `${Math.round(ms / 60000)} min`;
}

const OP_SYMBOLS = { gte: "≥", gt: ">", lte: "≤", lt: "<", eq: "=", neq: "≠" };

function nodeSummary(node) {
  const init = node.init || {};
  switch (node.activityName) {
    case "external_system_source":
      return { headline: init.targetSystem || "External system", sub: "webhook entry" };
    case "dwh_source":
      return {
        headline: init.currentTemplate?.name || init.dataSourceName || "Segment",
        sub: "segment audience",
      };
    case "registration": {
      const codes = init.promocodeSettings?.refCodes || [];
      return {
        headline: codes.length ? codes.join(", ") : "Any reference code",
        sub: "registration entry",
      };
    }
    case "promotion":
    case "multipurpose_promotion": {
      const window = humanizeIso(init.timeToAccept);
      return {
        headline: init.autoAccept ? "Auto-accepted offer" : "Offer — manual accept",
        sub: !init.autoAccept && window ? `${window} to accept` : "granted on arrival",
      };
    }
    case "deposit": {
      const minimum = init.depositConditions?.minDepositAmounts?.[0];
      const window = humanizeIso(init.depositConditions?.expirationTimeout);
      return {
        headline: minimum
          ? `≥ $${Math.round((minimum.amount || 0) / 100)} ${minimum.currencyCode || ""}`.trim()
          : "Any deposit",
        sub: window ? `${window} window` : "no time limit",
      };
    }
    case "sport_bet_condition":
      return {
        headline: init.minBetAmount ? `Bet ≥ $${Math.round(init.minBetAmount / 100)}` : "Any bet",
        sub: init.minOdd ? `odds ≥ ${init.minOdd}` : "any odds",
      };
    case "wait_interval":
      return { headline: humanizeIso(init.waitPeriod) || "No delay", sub: "then continue" };
    case "wait_date":
      return {
        headline: init.waitTo ? init.waitTo.slice(0, 10) : "Date not set",
        sub: "wait until date",
      };
    case "event_detector": {
      const option = init.properties?.subscriptionOptions?.[0];
      const window = humanizeIso(init.properties?.startingOptions?.durationTime);
      return {
        headline: option?.event?.eventName || "No event chosen",
        sub: window ? `within ${window}` : "no window",
        mono: true,
      };
    }
    case "freespin_bonus": {
      const spins = init.freespinActivity?.spins;
      const expiry = humanizeMs(init.freespinActivity?.spinsExpirationDuration);
      return {
        headline: spins ? `${spins} free spins` : "Free spins",
        sub: [init.freespinActivity?.provider, expiry && `valid ${expiry}`]
          .filter(Boolean).join(" · "),
      };
    }
    case "casino_bonus_v2":
      return {
        headline: init.bonusPercent ? `${init.bonusPercent}% match bonus` : "Casino bonus",
        sub: [
          init.wageringRequirement && `x${init.wageringRequirement} wagering`,
          humanizeMs(init.bonusExpirationTime),
        ].filter(Boolean).join(" · "),
      };
    case "freebet":
      return { headline: "Sport freebet", sub: "issued to player" };
    case "sport_bonus":
      return { headline: "Sport bonus", sub: "wagering bonus" };
    case "notification_center":
      return {
        headline: init.contract === 5 ? "Pop-up message" : "Bell notification",
        sub: Object.keys(init.templates || {}).length
          ? `templates: ${Object.keys(init.templates).join(", ")}`
          : "on-site message",
      };
    case "dextra_sms": {
      const text = init.rawValues?.messageText;
      return {
        headline: text ? `“${text.length > 26 ? text.slice(0, 26) + "…" : text}”` : "SMS message",
        sub: "SMS",
      };
    }
    case "dextra_email":
      return {
        headline: init.emailSettings?.contentId || "Email",
        sub: "email send",
        mono: Boolean(init.emailSettings?.contentId),
      };
    case "native_push":
      return { headline: "Native push", sub: "push notification" };
    case "ams_decision_split": {
      const rule = init.rules?.[0];
      const property = rule?.filter?.property;
      return {
        headline: property
          ? `${property.name} ${OP_SYMBOLS[property.operator] || property.operator} ${property.value}`
          : "No rules yet",
        sub: `${init.rules?.length || 0} rule${(init.rules?.length || 0) === 1 ? "" : "s"} + remainder`,
        mono: Boolean(property),
      };
    }
    case "random_split": {
      const paths = init.paths || [];
      return {
        headline: paths.map((p) => `${p.probability}%`).join(" / ") || "No paths",
        bar: paths.map((p) => Number(p.probability) || 0),
      };
    }
    case "notification_center_engagement_split":
    case "email_engagement_split": {
      const paths = init.properties?.paths || [];
      return {
        headline: paths.map((p) => p.pathName).filter(Boolean).join(" / ") || "No paths",
        sub: node.activityName.startsWith("email") ? "email engagement" : "on-site engagement",
      };
    }
    case "campaign_connector": {
      const host = init.campaignConnectorConditions?.activityData?.HostJourneyId;
      return { headline: host || "No journey linked", sub: "sends player to journey", mono: Boolean(host) };
    }
    default:
      return { headline: node.activityName, sub: "" };
  }
}

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
  selection: null,       // selected node id
  edgeSelection: null,   // {nodeId, eventName} — a selected transition
  zoom: 1,
  els: {},               // canvas / edges / inspector / problems DOM refs
  insights: { on: true, data: null, timer: null },
  dirty: false,
  connect: null,         // live port-drag: {sourceId, ghost}
};

/* ── undo / redo (rule 5.6) ── */
const history = { stack: [], index: -1, limit: 50 };

function snapshotState() {
  return JSON.stringify({
    nodes: [...state.nodes.values()],
    name: state.meta?.name || "",
  });
}

function restoreSnapshot(raw) {
  const data = JSON.parse(raw);
  state.nodes = new Map(data.nodes.map((node) => [node.activityId, node]));
  if (state.meta) state.meta.name = data.name;
  if (state.selection && !state.nodes.has(state.selection)) state.selection = null;
  state.edgeSelection = null;
}

function resetHistory() {
  history.stack = [snapshotState()];
  history.index = 0;
  state.dirty = false;
  state.els.dirtyChip?.style.setProperty("display", "none");
}

function commit() {
  /* call after every structural mutation: it records undo state and
   * marks the draft dirty */
  history.stack = history.stack.slice(0, history.index + 1);
  history.stack.push(snapshotState());
  if (history.stack.length > history.limit) history.stack.shift();
  history.index = history.stack.length - 1;
  state.dirty = true;
  state.els.dirtyChip?.style.setProperty("display", "");
}

function undo() {
  if (history.index <= 0) return;
  history.index -= 1;
  restoreSnapshot(history.stack[history.index]);
  state.dirty = true;
  state.els.nameInput && (state.els.nameInput.value = state.meta.name);
  render();
}

function redo() {
  if (history.index >= history.stack.length - 1) return;
  history.index += 1;
  restoreSnapshot(history.stack[history.index]);
  state.dirty = true;
  state.els.nameInput && (state.els.nameInput.value = state.meta.name);
  render();
}

/* ── friendly config forms (rule 5.8): dot-path field schemas ── */
const DURATIONS = [
  ["P0Y0M0DT0H0M0S", "Instant"],
  ["P0Y0M0DT0H30M0S", "30 minutes"],
  ["P0Y0M0DT1H0M0S", "1 hour"],
  ["P0Y0M0DT6H0M0S", "6 hours"],
  ["P0Y0M1DT0H0M0S", "1 day"],
  ["P0Y0M3DT0H0M0S", "3 days"],
  ["P0Y0M7DT0H0M0S", "7 days"],
];

const FORMS = {
  external_system_source: [
    { path: "targetSystem", label: "Target system", type: "text", hint: "Randomizer, PromoPage…" },
  ],
  dwh_source: [
    { path: "dataSourceName", label: "Segment name", type: "text" },
  ],
  registration: [
    { path: "promocodeSettings.refCodes", label: "Reference codes", type: "csv", hint: "comma-separated" },
  ],
  promotion: [
    { path: "autoAccept", label: "Auto-accept the offer", type: "bool" },
    { path: "timeToAccept", label: "Time to accept", type: "duration" },
  ],
  multipurpose_promotion: [
    { path: "autoAccept", label: "Auto-accept the offer", type: "bool" },
    { path: "timeToAccept", label: "Time to accept", type: "duration" },
  ],
  deposit: [
    { path: "depositConditions.minDepositAmounts.0.amount", label: "Minimum deposit (minor units)", type: "number", hint: "10000 = $100" },
    { path: "depositConditions.minDepositAmounts.0.currencyCode", label: "Currency", type: "text" },
    { path: "depositConditions.expirationTimeout", label: "Deposit window", type: "duration" },
  ],
  sport_bet_condition: [
    { path: "minBetAmount", label: "Minimum bet (minor units)", type: "number" },
    { path: "minOdd", label: "Minimum odds", type: "number" },
    { path: "expireInDays", label: "Window (days)", type: "number" },
  ],
  wait_interval: [
    { path: "waitPeriod", label: "Wait for", type: "duration" },
  ],
  wait_date: [
    { path: "waitTo", label: "Wait until (ISO timestamp)", type: "text", hint: "2026-09-01T04:00:00Z" },
  ],
  event_detector: [
    { path: "properties.subscriptionOptions.0.event.eventName", label: "Platform event", type: "text", hint: "deposit.approved" },
    { path: "properties.startingOptions.durationTime", label: "Watch window", type: "duration" },
    { path: "properties.subscriptionOptions.0.filter.property.value", label: "Filter value (amount)", type: "text" },
  ],
  freespin_bonus: [
    { path: "freespinActivity.spins", label: "Free spins", type: "number" },
    { path: "freespinActivity.provider", label: "Provider", type: "text" },
    { path: "freespinActivity.lobbyGameId", label: "Game id", type: "text" },
    { path: "freespinActivity.spinsExpirationDuration", label: "Validity (ms)", type: "number", hint: "86400000 = 24h" },
  ],
  casino_bonus_v2: [
    { path: "bonusPercent", label: "Match bonus %", type: "number" },
    { path: "wageringRequirement", label: "Wagering multiplier", type: "number", hint: "25 = x25" },
    { path: "bonusExpirationTime", label: "Expiry (ms)", type: "number", hint: "172800000 = 48h" },
  ],
  notification_center: [
    { path: "contract", label: "Message type", type: "select", options: [[1, "Bell notification"], [5, "Pop-up"]] },
  ],
  dextra_sms: [
    { path: "rawValues.messageText", label: "Message text", type: "textarea" },
  ],
  dextra_email: [
    { path: "emailSettings.contentId", label: "Content Studio id", type: "text", hint: "CSE-0-#####" },
  ],
  ams_decision_split: [
    { path: "rules.0.name", label: "Rule name", type: "text" },
    { path: "rules.0.filter.property.name", label: "Player attribute", type: "text", hint: "playerValue" },
    { path: "rules.0.filter.property.operator", label: "Operator", type: "select", options: [["gte", "≥"], ["gt", ">"], ["lte", "≤"], ["lt", "<"], ["eq", "="]] },
    { path: "rules.0.filter.property.value", label: "Value", type: "text" },
  ],
  campaign_connector: [
    { path: "campaignConnectorConditions.activityData.HostJourneyId", label: "Journey to link (JRN-…)", type: "text" },
  ],
};

function getPath(root, dotted) {
  let node = root;
  for (const part of dotted.split(".")) {
    if (node === null || node === undefined) return undefined;
    node = node[part];
  }
  return node;
}

function setPath(root, dotted, value) {
  const parts = dotted.split(".");
  let node = root;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    if (node[key] === undefined || node[key] === null) {
      node[key] = /^\d+$/.test(parts[i + 1]) ? [] : {};
    }
    node = node[key];
  }
  node[parts[parts.length - 1]] = value;
}

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
  const sorted = [...layers.keys()].sort((a, b) => a - b);
  for (const layer of sorted) {
    const row = layers.get(layer);
    const parentCenter = (node) => {
      const parents = parentsOf.get(node.activityId)
        .filter((parent) => (layerOf.get(parent.activityId) ?? 0) < layer);
      if (!parents.length) return null;
      return parents.reduce((sum, parent) => sum + parent.x + nodeSize(parent).w / 2, 0) / parents.length;
    };
    if (layer > 0) {
      row.sort((a, b) =>
        (parentCenter(a) ?? Number.MAX_SAFE_INTEGER) - (parentCenter(b) ?? Number.MAX_SAFE_INTEGER));
    }
    const rowHeight = Math.max(...row.map((node) => nodeSize(node).h));
    if (layer === sorted[0]) {
      /* first layer: center the row on the axis */
      const total = row.reduce((sum, node) => sum + nodeSize(node).w, 0)
        + COL_GAP * (row.length - 1);
      let x = Math.max(24, AXIS_X - total / 2);
      for (const node of row) {
        node.x = snap(x);
        node.y = snap(y + (rowHeight - nodeSize(node).h) / 2);
        x += nodeSize(node).w + COL_GAP;
      }
    } else {
      /* deeper layers: place each node under the mean of its parents so
       * single chains run straight; sweep right to resolve overlaps,
       * then shift the row back by the average drift so siblings
       * straddle their parent instead of staircasing rightward */
      let minX = 24;
      const drifts = [];
      for (const node of row) {
        const size = nodeSize(node);
        const center = parentCenter(node);
        const desired = center === null ? minX : center - size.w / 2;
        node.x = Math.max(desired, minX);
        node.y = snap(y + (rowHeight - size.h) / 2);
        if (center !== null) drifts.push(node.x - desired);
        minX = node.x + size.w + COL_GAP;
      }
      if (drifts.length) {
        const shift = Math.min(
          drifts.reduce((a, b) => a + b, 0) / drifts.length,
          row[0].x - 24,
        );
        if (shift > 0) for (const node of row) node.x -= shift;
      }
      for (const node of row) node.x = snap(node.x);
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
  canvas.querySelector(".canvas-empty")?.remove();
  if (!state.nodes.size) {
    canvas.append(h("div", { class: "canvas-empty" },
      h("strong", {}, "Empty canvas"),
      h("div", {}, "Pick a shape from Templates, or add an Input Source from the palette to admit players.")));
  }
  for (const node of state.nodes.values()) {
    const spec = nodeSpec(node);
    const color = CATEGORY_COLORS[spec?.category] || "var(--faint)";
    const size = nodeSize(node);
    const selected = state.selection === node.activityId ? " selected" : "";

    let el;
    if (spec?.kind === "terminal") {
      const chip = h("span", { class: "chip", style: `color:${color}` });
      chip.append(categoryIcon(spec?.category));
      el = h("div", {
        class: `node terminal${selected}`,
        style: `left:${node.x}px; top:${node.y}px`,
        "data-id": node.activityId,
      },
        chip,
        h("span", { class: "node-title" },
          node.activityName === "end_of_journey" ? "End of journey" : "End of path"),
        h("span", { class: "node-port in", style: `left:${size.w / 2 - 5}px` }),
      );
    } else {
      const wired = wiredEvents(node).length;
      const completions = node.events.filter((event) => event.eventType !== "Boundary").length;
      /* rule 4.4 — warn when nothing is wired */
      const warn = wired === 0 && completions > 0;
      const chip = h("span", {
        class: "chip",
        style: `color:${color}; background:color-mix(in srgb, ${color} 16%, transparent)`,
      });
      chip.append(categoryIcon(spec?.category));

      const summary = nodeSummary(node);
      const body = h("div", { class: "node-body" },
        h("div", { class: `node-headline${summary.mono ? " mono-line" : ""}` }, summary.headline));
      if (summary.bar) {
        const bar = h("div", { class: "node-bar" });
        summary.bar.forEach((weight, index) => {
          bar.append(h("span", {
            style: `flex:${Math.max(weight, 1)}; background:${color}; opacity:${[0.9, 0.55, 0.32][index % 3]}`,
          }));
        });
        body.append(bar);
      } else if (summary.sub) {
        body.append(h("div", { class: "node-sub" }, summary.sub));
      }

      /* insights overlay: live player counts instead of wiring status */
      const nodeStats =
        state.insights.on && state.insights.data?.activities?.[node.activityId];
      const metaRight = nodeStats
        ? h("span", {},
            `${nodeStats.entered} in`,
            nodeStats.activeHere
              ? h("span", { class: "live" }, ` · ${nodeStats.activeHere} here`)
              : null)
        : h("span", {}, `${wired}/${completions} wired`);

      el = h("div", {
        class: `node${selected}`,
        style: `left:${node.x}px; top:${node.y}px`,
        "data-id": node.activityId,
      },
        h("div", { class: "node-head" },
          chip,
          h("span", { class: "node-title" }, node.displayName),
          warn ? h("span", { class: "warn-dot", title: "No outgoing transition wired — validation will fail" }) : null),
        body,
        h("div", { class: "node-meta" },
          h("span", { class: "node-type" }, node.activityName),
          metaRight),
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

function canvasPoint(clientX, clientY) {
  const rect = state.els.canvas.getBoundingClientRect();
  return {
    x: (clientX - rect.left) / state.zoom,
    y: (clientY - rect.top) / state.zoom,
  };
}

function attachNodeBehaviour(el, node) {
  el.addEventListener("pointerdown", (down) => {
    if (down.button !== 0) return;
    /* rule 5.2 — dragging an out-port starts a connection */
    if (down.target.classList?.contains("node-port")
        && down.target.classList.contains("out")
        && editable()) {
      down.preventDefault();
      down.stopPropagation();
      startConnectDrag(node, down);
      return;
    }
    down.preventDefault();
    state.selection = node.activityId;
    state.edgeSelection = null;
    renderNodes(); renderEdges(); renderInspector();
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
      if (moved) { commit(); renderNodes(); }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
}

/* ── drag-to-connect (rule 5.2) ── */
function startConnectDrag(sourceNode, down) {
  const ns = "http://www.w3.org/2000/svg";
  const ghost = document.createElementNS(ns, "path");
  ghost.setAttribute("class", "edge-path neutral ghost");
  state.els.edges.append(ghost);
  const from = canvasPoint(down.clientX, down.clientY);

  const onMove = (move) => {
    const to = canvasPoint(move.clientX, move.clientY);
    const dip = Math.max(30, (to.y - from.y) / 2);
    ghost.setAttribute("d",
      `M ${from.x} ${from.y} C ${from.x} ${from.y + dip}, ${to.x} ${to.y - dip}, ${to.x} ${to.y}`);
  };
  const onUp = (up) => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    ghost.remove();
    const hit = document.elementFromPoint(up.clientX, up.clientY)?.closest?.(".node[data-id]");
    const targetId = hit?.dataset.id;
    if (!targetId || targetId === sourceNode.activityId) return;
    const candidates = sourceNode.events.filter((event) => event.eventType !== "Boundary");
    if (!candidates.length) return toast("This activity has no outgoing events", "err");
    const unwired = candidates.filter((event) => !event.nextActivityId);
    if (unwired.length === 1) {
      wireEvent(sourceNode, unwired[0], targetId);
    } else if (!unwired.length && candidates.length === 1) {
      wireEvent(sourceNode, candidates[0], targetId);  // re-point the only event
    } else {
      openEventPicker(sourceNode, targetId, up.clientX, up.clientY,
        unwired.length ? unwired : candidates);
    }
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

function wireEvent(sourceNode, event, targetId) {
  event.nextActivityId = targetId;
  commit();
  render();
}

function openEventPicker(sourceNode, targetId, clientX, clientY, events) {
  closeEventPicker();
  const menu = h("div", { class: "event-picker", id: "event-picker" });
  menu.append(h("div", { class: "event-picker-title" },
    `Which event leads to ${state.nodes.get(targetId)?.displayName || "this node"}?`));
  for (const event of events) {
    const item = h("button", { class: "event-picker-item" },
      h("span", { class: `evt ${edgeSemantics(event.eventName)}` }, event.eventName),
      event.nextActivityId ? h("span", { class: "dim small" }, " · rewires") : null);
    item.addEventListener("click", () => {
      closeEventPicker();
      wireEvent(sourceNode, event, targetId);
    });
    menu.append(item);
  }
  document.body.append(menu);
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(clientX, window.innerWidth - rect.width - 12)}px`;
  menu.style.top = `${Math.min(clientY + 6, window.innerHeight - rect.height - 12)}px`;
  setTimeout(() => {
    document.addEventListener("pointerdown", closeEventPickerOnOutside, { once: true });
  });
}

function closeEventPickerOnOutside(event) {
  if (!event.target.closest?.("#event-picker")) closeEventPicker();
  else document.addEventListener("pointerdown", closeEventPickerOnOutside, { once: true });
}

function closeEventPicker() {
  document.getElementById("event-picker")?.remove();
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
    const anchors = outAnchors(node);
    for (const [anchorIndex, anchor] of anchors.entries()) {
      const event = anchor.event;
      const target = state.nodes.get(event.nextActivityId);
      const targetSize = nodeSize(target);
      const p0 = { x: anchor.x, y: anchor.y };
      const p3 = { x: target.x + targetSize.w / 2, y: target.y };  /* rule 2.1 */
      const semantics = edgeSemantics(event.eventName);

      let d;
      if (p3.y > p0.y + 20) {
        /* rule 3.1 — orthogonal connector; sibling runs staggered 12px */
        let ym = p0.y + (p3.y - p0.y) / 2
          + (anchorIndex - (anchors.length - 1) / 2) * 12;
        ym = Math.max(p0.y + 14, Math.min(ym, p3.y - 12));
        d = `M ${p0.x} ${p0.y} V ${ym} H ${p3.x} V ${p3.y}`;
      } else {
        /* rule 3.2 — upward edge routes around the left side */
        const side = Math.min(node.x, target.x) - 60;
        d = `M ${p0.x} ${p0.y} V ${p0.y + 16} H ${side} V ${p3.y - 20} H ${p3.x} V ${p3.y}`;
      }

      const isSelected =
        state.edgeSelection?.nodeId === node.activityId
        && state.edgeSelection?.eventName === event.eventName;
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      path.setAttribute("class",
        `edge-path ${semantics}${event.eventType === "Boundary" ? " boundary" : ""}${isSelected ? " selected" : ""}`);
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
      let label = event.eventName;
      const sourceStats =
        state.insights.on && state.insights.data?.activities?.[node.activityId];
      if (sourceStats?.entered) {
        const taken = sourceStats.events?.[event.eventName] || 0;
        label += ` · ${taken} (${Math.round((taken / sourceStats.entered) * 100)}%)`;
      }
      text.textContent = label;
      group.append(text);
      if (isSelected) group.classList.add("selected");
      /* rule 5.5 — clicking the pill selects the transition */
      group.addEventListener("pointerdown", (click) => {
        click.stopPropagation();
        state.edgeSelection = { nodeId: node.activityId, eventName: event.eventName };
        state.selection = null;
        render();
      });
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
function removeSelectedNode() {
  const node = state.selection && state.nodes.get(state.selection);
  if (!node || !editable()) return;
  state.nodes.delete(node.activityId);
  for (const other of state.nodes.values()) {
    for (const event of other.events) {
      if (event.nextActivityId === node.activityId) event.nextActivityId = null;
    }
  }
  state.selection = null;
  commit();
  render();
}

function disconnectSelectedEdge() {
  const selected = state.edgeSelection;
  if (!selected || !editable()) return;
  const node = state.nodes.get(selected.nodeId);
  const event = node?.events.find((entry) => entry.eventName === selected.eventName);
  if (event) {
    event.nextActivityId = null;
    commit();
  }
  state.edgeSelection = null;
  render();
}

function formField(node, field, locked) {
  const current = getPath(node.init, field.path);
  const apply = (value) => {
    setPath(node.init, field.path, value);
    commit();
    renderNodes();
  };
  let control;
  if (field.type === "bool") {
    control = h("label", { class: "switch-row" });
    const box = h("input", { type: "checkbox" });
    box.checked = Boolean(current);
    box.disabled = locked;
    box.addEventListener("change", () => apply(box.checked));
    control.append(box, h("span", {}, field.label));
    return h("div", { class: "field" }, control,
      field.hint ? h("div", { class: "hint" }, field.hint) : null);
  }
  if (field.type === "select" || field.type === "duration") {
    const options = field.type === "duration" ? DURATIONS : field.options;
    control = h("select", { class: "input" });
    let matched = false;
    for (const [value, label] of options) {
      const option = h("option", { value: String(value) }, label);
      if (String(current) === String(value)) { option.selected = true; matched = true; }
      control.append(option);
    }
    if (current !== undefined && current !== null && current !== "" && !matched) {
      const custom = h("option", { value: String(current) }, `custom: ${current}`);
      custom.selected = true;
      control.append(custom);
    }
    control.disabled = locked;
    control.addEventListener("change", () => {
      const raw = control.value;
      apply(field.type === "select" && field.options.some(([v]) => typeof v === "number")
        ? Number(raw) : raw);
    });
  } else if (field.type === "textarea") {
    control = h("textarea", { class: "input", rows: "3" });
    control.value = current ?? "";
    control.disabled = locked;
    control.addEventListener("change", () => apply(control.value));
  } else {
    control = h("input", { class: "input", value: current ?? "" });
    control.disabled = locked;
    control.addEventListener("change", () => {
      apply(field.type === "number" ? Number(control.value) : control.value);
    });
  }
  return h("label", { class: "field" },
    h("span", {}, field.label), control,
    field.hint ? h("div", { class: "hint" }, field.hint) : null);
}

function renderInspector() {
  const panel = state.els.inspector;
  panel.innerHTML = "";
  const locked = !editable();

  /* a selected transition gets its own panel (rule 5.5) */
  if (state.edgeSelection) {
    const { nodeId, eventName } = state.edgeSelection;
    const source = state.nodes.get(nodeId);
    const event = source?.events.find((entry) => entry.eventName === eventName);
    const target = event?.nextActivityId && state.nodes.get(event.nextActivityId);
    panel.append(
      h("h2", {}, "Transition"),
      h("div", { class: "type-line" },
        h("span", { class: `evt mono small ${edgeSemantics(eventName)}` }, eventName)),
      h("div", { class: "small", style: "margin-bottom:14px" },
        `${source?.displayName || "?"} → ${target?.displayName || "?"}`),
    );
    if (!locked) {
      const disconnect = h("button", { class: "btn danger sm" }, "Disconnect");
      disconnect.addEventListener("click", disconnectSelectedEdge);
      panel.append(disconnect,
        h("div", { class: "hint", style: "margin-top:10px" }, "or press Delete"));
    }
    return;
  }

  const node = state.selection && state.nodes.get(state.selection);
  if (!node) {
    panel.append(h("div", { class: "inspector-empty" },
      "Select an activity on the canvas,", h("br"),
      "or drag one in from the palette.", h("br"), h("br"),
      h("span", { class: "small" },
        "Wire activities by dragging from a bottom port onto another activity.")));
    return;
  }
  const spec = nodeSpec(node);

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
  nameField.addEventListener("change", () => commit());
  panel.append(h("label", { class: "field" }, h("span", {}, "Display name"), nameField));

  /* rule 5.8 — friendly settings first */
  const fields = FORMS[node.activityName];
  if (fields?.length) {
    panel.append(h("h4", {}, "Settings"));
    for (const field of fields) panel.append(formField(node, field, locked));
  }

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
        commit();
        renderNodes(); renderEdges();
      });
      panel.append(h("div", { class: "wire-row" },
        h("span", { class: `evt ${edgeSemantics(event.eventName)}`, title: event.eventName },
          event.eventName),
        select));
    }
  }

  /* the raw wire format stays available, demoted to Advanced */
  if (spec?.kind !== "terminal") {
    const textarea = h("textarea", { class: "input", rows: "10" });
    textarea.value = JSON.stringify(node.init, null, 2);
    textarea.disabled = locked;
    textarea.addEventListener("change", () => {
      try {
        node.init = JSON.parse(textarea.value || "{}");
        textarea.style.borderColor = "";
        commit();
        renderNodes();
        renderInspector();
      } catch {
        textarea.style.borderColor = "var(--wax)";
        toast("initializationData is not valid JSON", "err");
      }
    });
    panel.append(h("details", { class: "advanced" },
      h("summary", {}, "Advanced · initializationData"),
      textarea));
  }

  if (!locked) {
    const remove = h("button", { class: "btn danger sm", style: "margin-top:14px" }, "Remove activity");
    remove.addEventListener("click", removeSelectedNode);
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
    commit();
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
  const dirtyChip = h("span", {
    class: "dirty-chip",
    style: state.dirty ? "" : "display:none",
    title: "There are changes that are not saved yet",
  }, "unsaved changes");

  const problems = h("div", { class: "problems", style: "position:absolute; right:336px; top:66px; width:360px; z-index:20" });

  const validateBtn = h("button", { class: "btn" }, "Validate");
  const saveBtn = h("button", { class: "btn primary" }, "Save draft");
  const publishBtn = h("button", { class: "btn" }, "Publish");
  const runLink = h("button", { class: "btn ghost" }, "Run view ->");
  const layoutBtn = h("button", { class: "btn ghost", title: "Re-layout top to bottom" }, "Auto-layout");
  const insightsBtn = h("button", {
    class: "btn ghost",
    title: "Live player counts on nodes and transitions",
  }, "Insights");

  /* live campaign numbers over the canvas (published journeys only) */
  clearInterval(state.insights.timer);
  state.insights.data = null;
  const pollInsights = async () => {
    if (!document.body.contains(view) || state.meta.status !== "Published") return;
    try {
      state.insights.data = await api(
        "GET", `/runtime/v0/journeys/${state.meta.journeyId}/stats`
      );
      if (state.insights.on) { renderNodes(); renderEdges(); }
    } catch { /* transient */ }
  };
  const syncInsights = () => {
    insightsBtn.style.display = state.meta.status === "Published" ? "" : "none";
    insightsBtn.classList.toggle("pressed", state.insights.on);
    clearInterval(state.insights.timer);
    if (state.meta.status === "Published") {
      pollInsights();
      state.insights.timer = setInterval(pollInsights, 3000);
    }
  };
  insightsBtn.addEventListener("click", () => {
    state.insights.on = !state.insights.on;
    insightsBtn.classList.toggle("pressed", state.insights.on);
    renderNodes(); renderEdges();
  });

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
    nameInput, brandInput, h("span", { id: "meta-badge" }, statusBadge()), dirtyChip,
    h("div", { class: "spacer", style: "flex:1" }),
    h("span", { class: "zoom-group" }, zoomOut, zoomLabel, zoomIn),
    insightsBtn, templatesWrap, layoutBtn, validateBtn, saveBtn, publishBtn, runLink,
  );

  const paletteEl = h("div", { class: "palette" });
  for (const group of state.palette) {
    paletteEl.append(h("h3", {}, group.category));
    const grid = h("div", { class: "palette-grid" });
    for (const item of group.activities) {
      const color = CATEGORY_COLORS[group.category];
      const chip = h("span", {
        class: "palette-chip",
        style: `color:${color}; background:color-mix(in srgb, ${color} 13%, transparent)`,
      });
      chip.append(categoryIcon(group.category));
      const button = h("button", {
        class: "palette-item",
        title: `${item.activityName} · ${item.kind}`,
      }, chip, h("span", { class: "palette-label" }, item.label));
      const addNode = (x, y) => {
        if (!editable()) return toast("Stop the journey to edit it", "err");
        const node = makeNode(item.activityName, snap(x), snap(y));
        state.nodes.set(node.activityId, node);
        state.selection = node.activityId;
        state.edgeSelection = null;
        commit();
        render();
      };
      button.addEventListener("click", () =>
        addNode(AXIS_X - NODE_W / 2 + ((state.nodes.size % 3) - 1) * 40,
                TOP + state.nodes.size * (NODE_H + 28)));
      /* drag from the palette straight onto the canvas */
      button.draggable = true;
      button.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/activity", item.activityName);
        event.dataTransfer.effectAllowed = "copy";
      });
      grid.append(button);
    }
    paletteEl.append(grid);
  }

  const edges = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  edges.setAttribute("class", "edges");
  const canvas = h("div", { class: "canvas" });
  canvas.append(edges);
  const canvasWrap = h("div", { class: "canvas-wrap" }, canvas, problems);
  const inspector = h("div", { class: "inspector" });

  /* empty-canvas press: deselect on click, pan on drag (rule 5.9) */
  canvas.addEventListener("pointerdown", (down) => {
    if (down.target !== canvas) return;
    down.preventDefault();
    const startX = down.clientX, startY = down.clientY;
    const scrollLeft = canvasWrap.scrollLeft, scrollTop = canvasWrap.scrollTop;
    let moved = false;
    const onMove = (move) => {
      const dx = move.clientX - startX, dy = move.clientY - startY;
      if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
      if (!moved) return;
      canvas.classList.add("panning");
      canvasWrap.scrollLeft = scrollLeft - dx;
      canvasWrap.scrollTop = scrollTop - dy;
    };
    const onUp = () => {
      canvas.classList.remove("panning");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (!moved) {
        state.selection = null;
        state.edgeSelection = null;
        renderNodes(); renderEdges(); renderInspector();
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });

  /* palette drop target */
  canvas.addEventListener("dragover", (event) => {
    if (event.dataTransfer.types.includes("text/activity")) event.preventDefault();
  });
  canvas.addEventListener("drop", (event) => {
    const activityName = event.dataTransfer.getData("text/activity");
    if (!activityName) return;
    event.preventDefault();
    if (!editable()) return toast("Stop the journey to edit it", "err");
    const point = canvasPoint(event.clientX, event.clientY);
    const node = makeNode(activityName,
      snap(Math.max(0, point.x - NODE_W / 2)), snap(Math.max(0, point.y - 20)));
    state.nodes.set(node.activityId, node);
    state.selection = node.activityId;
    state.edgeSelection = null;
    commit();
    render();
  });

  view.append(h("div", { class: "builder" }, toolbar, paletteEl, canvasWrap, inspector));
  state.els = { canvas, edges, inspector, problems, nameInput, dirtyChip };

  /* rule 5.5 / 5.6 — keyboard: Delete, Escape, undo/redo */
  const onKeyDown = (event) => {
    if (!document.body.contains(view)) {
      document.removeEventListener("keydown", onKeyDown);
      return;
    }
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      event.shiftKey ? redo() : undo();
    } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
      event.preventDefault();
      redo();
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      if (state.edgeSelection) disconnectSelectedEdge();
      else if (state.selection) removeSelectedNode();
    } else if (event.key === "Escape") {
      closeEventPicker();
      state.selection = null;
      state.edgeSelection = null;
      renderNodes(); renderEdges(); renderInspector();
    }
  };
  document.addEventListener("keydown", onKeyDown);

  /* rule 5.7 — never lose work silently */
  window.onbeforeunload = () =>
    state.dirty && editable() ? "There are unsaved changes." : undefined;

  const refreshMeta = () => {
    const holder = document.getElementById("meta-badge");
    holder.innerHTML = "";
    holder.append(statusBadge());
    const locked = !editable();
    saveBtn.disabled = locked;
    templatesBtn.disabled = locked;
    publishBtn.disabled = !(state.meta.draftId && (state.meta.status === "Draft" || state.meta.status === "Stopped"));
    runLink.style.display = state.meta.status === "Published" ? "" : "none";
    syncInsights();
  };

  layoutBtn.addEventListener("click", () => { autoLayout(); commit(); render(); });

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
      resetHistory();
      render();
      showProblems(problems, null);
      toast(`Saved ${saved.journeyId} (v${saved.version})`, "ok");
      refreshMeta();
      window.history.replaceState(null, "", `#/builder/${saved.journeyId}`);
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

  resetHistory();
  refreshMeta();
  render();
  applyZoom();
}
