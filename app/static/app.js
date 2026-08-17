/* Journey Builder UI — router, API client, journeys list. */
import { renderBuilder } from "./builder.js";
import { renderRun } from "./runtime.js";

export const API = "/api/v0/crm";

export async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(API + path, options);
  let data = null;
  try { data = await response.json(); } catch { /* no body */ }
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`);
    error.status = response.status;
    error.detail = data ? data.detail : null;
    throw error;
  }
  return data;
}

export function toast(message, kind = "") {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

export function errText(error) {
  const detail = error.detail;
  if (!detail) return error.message;
  if (typeof detail === "string") return detail;
  if (detail.aggregatedError) {
    const problems = detail.aggregatedError.journeyActivityError
      .flatMap((entry) => entry.problemDetails)
      .map((problem) => problem.type);
    return problems.join(", ");
  }
  return detail.type ? `${detail.type}: ${detail.detail || ""}` : JSON.stringify(detail);
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (value !== null && value !== undefined) el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    el.append(child.nodeType ? child : document.createTextNode(child));
  }
  return el;
}

export function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/* ── activity catalog (shared cache) ── */
let paletteCache = null;
export async function getPalette() {
  if (!paletteCache) {
    const data = await api("GET", "/journey-builder/v0/activities/catalog");
    paletteCache = data.palette;
  }
  return paletteCache;
}
export function specFor(palette, activityName) {
  for (const group of palette) {
    for (const item of group.activities) {
      if (item.activityName === activityName) return { ...item, category: group.category };
    }
  }
  return null;
}
export const CATEGORY_COLORS = {
  "Input Source": "var(--cat-source)",
  "Flow control": "var(--cat-flow)",
  "Communication": "var(--cat-comms)",
  "Delays": "var(--cat-delay)",
  "Connectors": "var(--cat-connector)",
  "Promotion type": "var(--cat-promo)",
  "Conditions": "var(--cat-condition)",
  "Reward type": "var(--cat-reward)",
  "Terminals": "var(--cat-terminal)",
};

/* One drawn icon per palette category — single 1.5px stroke family,
 * 16px grid, currentColor. */
const ICON_PATHS = {
  "Input Source": '<path d="M5 3.5 12.5 8 5 12.5z"/>',
  "Flow control": '<path d="M3 8h4m0 0 3-4.5H14M7 8l3 4.5H14"/><path d="M11.5 2 14 3.5 11.5 5M11.5 11 14 12.5 11.5 14"/>',
  "Communication": '<rect x="2.5" y="4" width="11" height="8.5" rx="1.5"/><path d="m3 4.8 5 4 5-4"/>',
  "Delays": '<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.2l2.2 1.4"/>',
  "Connectors": '<path d="M6.5 9.5 9.5 6.5M5 11l-1.2 1.2a2.4 2.4 0 0 1-3.4-3.4L3.6 5.6M12.4 10.4l3.2-3.2a2.4 2.4 0 0 0-3.4-3.4L11 5" transform="translate(0 0.5)"/>',
  "Promotion type": '<path d="M2.5 8.5 8 3h5v5l-5.5 5.5a1.4 1.4 0 0 1-2 0l-3-3a1.4 1.4 0 0 1 0-2z"/><circle cx="10.5" cy="5.5" r="0.9"/>',
  "Conditions": '<path d="M8 2.5 13.5 8 8 13.5 2.5 8z"/>',
  "Reward type": '<path d="m8 2.8 1.6 3.3 3.6.5-2.6 2.5.6 3.6L8 11l-3.2 1.7.6-3.6L2.8 6.6l3.6-.5z"/>',
  "Terminals": '<rect x="4" y="4" width="8" height="8" rx="1.2"/>',
};

export function categoryIcon(category) {
  const paths = ICON_PATHS[category] || ICON_PATHS["Terminals"];
  const span = document.createElement("span");
  span.className = "icon";
  span.innerHTML =
    `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" ` +
    `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  return span;
}

/* ── journeys list ── */
async function renderJourneys(view) {
  view.innerHTML = "";
  const page = h("div", { class: "page" });
  const head = h("div", { class: "page-head" },
    h("h1", {}, "Journeys"),
    h("div", { class: "spacer" }),
    h("button", { class: "btn primary", onclick: () => (location.hash = "#/builder") }, "+ New journey"),
  );
  page.append(head);
  view.append(page);

  let data;
  try {
    data = await api("GET", "/journey-builder/v0/journeys");
  } catch (error) {
    page.append(h("div", { class: "card empty" }, `Failed to load: ${errText(error)}`));
    return;
  }
  if (!data.items.length) {
    page.append(h("div", { class: "card empty" },
      "No journeys yet. Create one in the builder — or run scripts/demo.py for a sample campaign."));
    return;
  }

  const table = h("table", { class: "list" },
    h("thead", {}, h("tr", {},
      h("th", {}, "Journey"), h("th", {}, "Id"), h("th", {}, "Brand"),
      h("th", {}, "Status"), h("th", {}, "Runs"), h("th", {}, "Changed"), h("th", {}, ""))),
  );
  const tbody = h("tbody");
  for (const journey of data.items) {
    const actions = h("td", { style: "text-align:right; white-space:nowrap" });
    const row = h("tr", { class: "rowlink" },
      h("td", {}, h("strong", {}, journey.journeyName || "(unnamed)")),
      h("td", { class: "mono dim" }, journey.journeyId),
      h("td", { class: "dim" }, journey.brand),
      h("td", {}, h("span", { class: `badge ${journey.status}` }, journey.status)),
      h("td", { class: "dim" }, String(journey.allJourneyActivationsCount)),
      h("td", { class: "dim small" }, fmtTime(journey.changedAt)),
      actions,
    );
    row.addEventListener("click", () => (location.hash = `#/builder/${journey.journeyId}`));

    const act = (label, cls, handler, title) => {
      const btn = h("button", { class: `btn sm ${cls || ""}`, title: title || label }, label);
      btn.addEventListener("click", async (event) => {
        event.stopPropagation();
        try { await handler(); renderJourneys(view); } catch (error) { toast(errText(error), "err"); }
      });
      actions.append(btn, " ");
      return btn;
    };
    if (journey.status === "Published") {
      act("Run", "primary", async () => { location.hash = `#/run/${journey.journeyId}`; });
      act("Stop", "", () => api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/stop`));
    } else if (journey.status === "Draft" || journey.status === "Stopped") {
      act("Publish", "", async () => {
        await api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/publish`);
        toast(`${journey.journeyId} published`, "ok");
      });
    }
    act("Duplicate", "", async () => {
      const copy = await api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/duplicate`, {});
      toast(`Duplicated as ${copy.journeyId}`, "ok");
    });
    if (journey.status === "Draft" || journey.status === "Archived") {
      act("Delete", "danger", async () => {
        if (!confirm(`Delete ${journey.journeyId} "${journey.journeyName}"?`)) return;
        await api("DELETE", `/journey-builder/v0/journey-drafts/${journey.id}`);
        toast(`${journey.journeyId} deleted`, "ok");
      });
    } else if (journey.status !== "Archived") {
      act("Archive", "", () => api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/archive`));
    }
    tbody.append(row);
  }
  table.append(tbody);
  page.append(h("div", { class: "card", style: "padding:0" }, table));
}

/* ── router ── */
function setNav(active) {
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === active);
  });
}

async function route() {
  const view = document.getElementById("view");
  const hash = location.hash || "#/";
  const parts = hash.slice(2).split("/").filter(Boolean);
  document.getElementById("topbar-status").textContent = "";
  try {
    if (parts[0] === "builder") {
      setNav("builder");
      await renderBuilder(view, parts[1] || null);
    } else if (parts[0] === "run" && parts[1]) {
      setNav("");
      await renderRun(view, parts[1]);
    } else {
      setNav("journeys");
      await renderJourneys(view);
    }
  } catch (error) {
    view.innerHTML = "";
    view.append(h("div", { class: "page" },
      h("div", { class: "card empty" }, `Something broke: ${errText(error)}`)));
  }
}

window.addEventListener("hashchange", route);
route();
