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

/* ── promotion visuals ──
 * Every promotion carries a `visual` ({headerColor, accentColor, title,
 * subtitle, image}) — the promo card the player sees. One renderer serves
 * the builder's live preview and the run view's offer ledger. */
export function promoCard(visual, { sub, termsLine, foot } = {}) {
  const v = visual || {};
  const header = v.headerColor || "#175a41";
  const accent = v.accentColor || "#96752b";
  const banner = h("div", { class: "promo-card-banner" },
    h("div", { class: "promo-card-title" }, v.title || "Untitled promotion"));
  banner.style.background = v.image
    ? `url("${v.image}") center/cover no-repeat`
    : `linear-gradient(120deg, ${header} 0%, ${header} 55%, ${accent} 130%)`;
  const body = h("div", { class: "promo-card-body" });
  const subtitle = sub !== undefined ? sub : v.subtitle;
  if (subtitle) body.append(h("div", { class: "promo-card-sub" }, subtitle));
  if (termsLine) body.append(h("div", { class: "promo-card-terms" }, termsLine));
  if (foot) body.append(foot);
  return h("div", { class: "promo-card" }, banner, body);
}

export function termsLineOf(terms) {
  if (!terms || typeof terms !== "object") return null;
  const parts = [];
  if (terms.wageringRequirement) parts.push(`x${terms.wageringRequirement} wagering`);
  if (terms.expiryDays) parts.push(`expires in ${terms.expiryDays} days`);
  if (terms.maxWin) parts.push(`max win $${Math.round(terms.maxWin / 100)}`);
  for (const [key, value] of Object.entries(terms)) {
    if (!["wageringRequirement", "expiryDays", "maxWin"].includes(key)) parts.push(`${key}: ${value}`);
  }
  return parts.length ? `T&C — ${parts.join(" · ")}` : null;
}

/* In-place question anchored to the control that asked it — the ledger
 * never opens a browser prompt. Resolves the entered text, or null. */
export function askInline(anchor, { label, placeholder = "", value = "", submitLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    document.querySelector(".ask-pop")?.remove();
    const input = h("input", { class: "input", placeholder, value });
    const ok = h("button", { class: `btn sm ${danger ? "danger" : "primary"}` }, submitLabel);
    const pop = h("div", { class: "ask-pop" },
      h("div", { class: "ask-pop-label" }, label),
      h("div", { class: "row" }, input, ok));
    const close = (result) => {
      pop.remove();
      document.removeEventListener("pointerdown", outside, true);
      resolve(result);
    };
    const outside = (event) => { if (!pop.contains(event.target)) close(null); };
    ok.addEventListener("click", () => close(input.value.trim() || null));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") close(input.value.trim() || null);
      if (event.key === "Escape") close(null);
    });
    pop.addEventListener("click", (event) => event.stopPropagation());
    document.body.append(pop);
    const rect = anchor.getBoundingClientRect();
    pop.style.top = `${Math.min(rect.bottom + 6, innerHeight - pop.offsetHeight - 10)}px`;
    pop.style.left = `${Math.max(10, Math.min(rect.left, innerWidth - pop.offsetWidth - 10))}px`;
    document.addEventListener("pointerdown", outside, true);
    input.focus();
  });
}

/* Two-step destructive confirm: first press arms the button ("Sure?"),
 * second press within the window goes through. Returns true to proceed. */
export function armConfirm(button, armedLabel = "Sure?") {
  if (button.dataset.armed) {
    delete button.dataset.armed;
    return true;
  }
  button.dataset.armed = "1";
  const original = button.textContent;
  button.textContent = armedLabel;
  button.classList.add("confirming");
  setTimeout(() => {
    if (!button.isConnected || !button.dataset.armed) return;
    delete button.dataset.armed;
    button.textContent = original;
    button.classList.remove("confirming");
  }, 2600);
  return false;
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

/* ── journeys list: the campaign dashboard ── */
const listFilter = { query: "", status: "" };

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

  /* search + status filters */
  const search = h("input", {
    class: "input", placeholder: "Search by name or id…",
    style: "width:260px", value: listFilter.query,
  });
  search.addEventListener("input", () => {
    listFilter.query = search.value;
    renderRows();
  });
  const filterRow = h("div", { class: "filter-row" }, search);
  for (const status of ["", "Published", "Draft", "Stopped", "Archived"]) {
    const chip = h("button", {
      class: `filter-chip${listFilter.status === status ? " active" : ""}`,
    }, status || "All");
    chip.addEventListener("click", () => {
      listFilter.status = status;
      filterRow.querySelectorAll(".filter-chip").forEach((el) => el.classList.remove("active"));
      chip.classList.add("active");
      renderRows();
    });
    filterRow.append(chip);
  }
  page.append(filterRow);

  const pct = (value) => (value == null ? "—" : `${Math.round(value * 100)}%`);
  const table = h("table", { class: "list" },
    h("thead", {}, h("tr", {},
      h("th", {}, "Journey"), h("th", {}, "Id"),
      h("th", {}, "Status"), h("th", {}, "Players"), h("th", {}, "Completion"),
      h("th", {}, "Rewards"), h("th", {}, "Changed"), h("th", {}, ""))),
  );
  const tbody = h("tbody");
  table.append(tbody);
  page.append(h("div", { class: "card", style: "padding:0" }, table));

  function renderRows() {
    tbody.innerHTML = "";
    const query = listFilter.query.trim().toLowerCase();
    const rows = data.items.filter((journey) =>
      (!listFilter.status || journey.status === listFilter.status)
      && (!query
        || journey.journeyName.toLowerCase().includes(query)
        || journey.journeyId.toLowerCase().includes(query)));
    if (!rows.length) {
      tbody.append(h("tr", {}, h("td", { colspan: "8", class: "empty" },
        "Nothing matches — clear the search or filters.")));
      return;
    }
    for (const journey of rows) buildRow(journey);
  }

  function buildRow(journey) {
    const actions = h("td", { style: "text-align:right; white-space:nowrap" });
    const players = h("td", {},
      String(journey.allJourneyActivationsCount),
      journey.activeActivationsCount
        ? h("span", { class: "live small" }, ` · ${journey.activeActivationsCount} live`)
        : null);
    const row = h("tr", { class: "rowlink" },
      h("td", {},
        h("strong", {}, journey.journeyName || "(unnamed)"),
        h("div", { class: "dim small" }, journey.brand)),
      h("td", { class: "mono dim" }, journey.journeyId),
      h("td", {},
        h("div", { class: "stamp-stack" },
          h("span", { class: `badge ${journey.status}` }, journey.status),
          journey.approvalState
            ? h("span", { class: `badge ${journey.approvalState}` },
                journey.approvalState === "InReview" ? "In review" : journey.approvalState)
            : null)),
      players,
      h("td", { class: "dim" }, pct(journey.completionRate)),
      h("td", { class: "dim" }, String(journey.rewardGrantsCount)),
      h("td", { class: "dim small" }, fmtTime(journey.changedAt)),
      actions,
    );
    row.addEventListener("click", () => (location.hash = `#/builder/${journey.journeyId}`));

    const act = (label, cls, handler, title) => {
      const btn = h("button", { class: `btn sm ${cls || ""}`, title: title || label }, label);
      btn.addEventListener("click", async (event) => {
        event.stopPropagation();
        try {
          // a handler returns false when nothing happened (cancelled ask,
          // first press of a two-step confirm) — keep the row as it is
          const result = await handler(btn);
          if (result !== false) renderJourneys(view);
        } catch (error) { toast(errText(error), "err"); }
      });
      actions.append(btn, " ");
      return btn;
    };
    if (journey.status === "Published") {
      act("Run", "primary", async () => { location.hash = `#/run/${journey.journeyId}`; });
      act("Stop", "", () => api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/stop`));
    } else if (journey.status === "Draft" || journey.status === "Stopped") {
      if (journey.approvalState === "InReview") {
        act("Approve", "primary", async (btn) => {
          const approver = await askInline(btn, {
            label: `Approve ${journey.journeyId} — countersign as`,
            placeholder: journey.submittedBy ? `anyone but ${journey.submittedBy}` : "your name",
            submitLabel: "Approve",
          });
          if (!approver) return false;
          await api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/approve`,
            { approvedBy: approver });
          toast(`${journey.journeyId} approved by ${approver}`, "ok");
        });
        act("Reject", "danger", async (btn) => {
          const reason = await askInline(btn, {
            label: `Send ${journey.journeyId} back — because`,
            placeholder: "what needs to change",
            submitLabel: "Reject",
            danger: true,
          });
          if (!reason) return false;
          await api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/reject`,
            { rejectedBy: "reviewer", reason });
          toast(`${journey.journeyId} sent back`, "");
        });
      } else {
        act("Submit review", "", async (btn) => {
          const author = await askInline(btn, {
            label: `Hand ${journey.journeyId} to a reviewer — signed`,
            placeholder: "your name",
            submitLabel: "Submit",
          });
          if (!author) return false;
          await api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/submit-review`,
            { requestedBy: author });
          toast(`${journey.journeyId} waiting for a second pair of eyes`, "ok");
        }, "Four-eyes: a second person approves before publish");
      }
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
      act("Delete", "danger", async (btn) => {
        if (!armConfirm(btn)) return false;
        await api("DELETE", `/journey-builder/v0/journey-drafts/${journey.id}`);
        toast(`${journey.journeyId} deleted`, "ok");
      });
    } else if (journey.status !== "Archived") {
      act("Archive", "", () => api("POST", `/journey-builder/v0/journeys/${journey.journeyId}/archive`));
    }
    tbody.append(row);
  }

  renderRows();
}

/* ── compliance: exclusion list, marketing policy, audit trail ── */
async function renderCompliance(view) {
  view.innerHTML = "";
  const page = h("div", { class: "page" });
  page.append(h("div", { class: "page-head" },
    h("h1", {}, "Compliance"),
    h("div", { class: "spacer" }),
    h("span", { class: "dim small" }, "enforced by the engine on every entry and every send")));
  view.append(page);

  const [exclusions, policy, audit] = await Promise.all([
    api("GET", "/compliance/v0/exclusions"),
    api("GET", "/compliance/v0/policy"),
    api("GET", "/compliance/v0/audit?limit=30"),
  ]);

  /* one ledger page, three ruled sections */
  const sheet = h("div", { class: "sheet" });
  page.append(sheet);

  /* exclusion register */
  const exclusionSection = h("section", { class: "sheet-section" },
    h("h3", {}, "Exclusion register",
      h("span", { class: "count" }, String(exclusions.items.length))),
    h("p", { class: "section-note" },
      "A listed player cannot enter any journey or receive any message or reward — in-flight runs included."));
  for (const row of exclusions.items) {
    const line = h("div", { class: "event-item" },
      h("strong", { class: "mono" }, row.playerId),
      h("span", { class: `badge ${row.active ? "Terminated" : "Draft"}` },
        row.active ? row.reason.replace("_", "-") : "expired"),
      h("span", { class: "dim small", style: "flex:1" },
        row.expiresAt ? `until ${fmtTime(row.expiresAt)}` : "indefinite",
        row.note ? ` · ${row.note}` : ""),
    );
    const remove = h("button", { class: "btn sm danger" }, "Remove");
    remove.addEventListener("click", async () => {
      if (!armConfirm(remove)) return;
      await api("DELETE", `/compliance/v0/exclusions/${encodeURIComponent(row.playerId)}`);
      renderCompliance(view);
    });
    line.append(remove);
    exclusionSection.append(line);
  }
  const exPlayer = h("input", { class: "input", placeholder: "player id", style: "flex:1" });
  const exReason = h("select", { class: "input", style: "width:150px" },
    h("option", { value: "self_exclusion" }, "self-exclusion"),
    h("option", { value: "vulnerable" }, "vulnerable"),
    h("option", { value: "cool_off" }, "cool-off (24h)"));
  const exAdd = h("button", { class: "btn" }, "Exclude");
  exAdd.addEventListener("click", async () => {
    const playerId = exPlayer.value.trim();
    if (!playerId) return toast("player id required", "err");
    const payload = { playerId, reason: exReason.value };
    if (exReason.value === "cool_off") {
      payload.expiresAt = new Date(Date.now() + 24 * 3600 * 1000).toISOString();
    }
    try {
      await api("POST", "/compliance/v0/exclusions", payload);
      toast(`${playerId} excluded`, "ok");
      renderCompliance(view);
    } catch (error) { toast(errText(error), "err"); }
  });
  exclusionSection.append(h("div", { class: "row", style: "margin-top:12px" }, exPlayer, exReason, exAdd));
  sheet.append(exclusionSection);

  /* marketing policy */
  const quiet = policy.quietHours || {};
  const caps = policy.frequencyCaps || {};
  const qStart = h("input", { class: "input", placeholder: "21:00", value: quiet.start || "", style: "width:90px" });
  const qEnd = h("input", { class: "input", placeholder: "09:00", value: quiet.end || "", style: "width:90px" });
  const capInputs = {};
  const capRow = h("div", { class: "row", style: "flex-wrap:wrap; gap:10px" });
  for (const channel of ["sms", "email", "push", "onsite"]) {
    capInputs[channel] = h("input", {
      class: "input", type: "number", min: "0", placeholder: "no cap",
      value: caps[channel] ?? "", style: "width:80px",
    });
    capRow.append(h("label", { class: "field", style: "margin:0" },
      h("span", {}, channel), capInputs[channel]));
  }
  const saveBtn = h("button", { class: "btn primary" }, "Save policy");
  saveBtn.addEventListener("click", async () => {
    const quietHours = qStart.value.trim() && qEnd.value.trim()
      ? { start: qStart.value.trim(), end: qEnd.value.trim() }
      : null;
    const frequencyCaps = {};
    for (const [channel, input] of Object.entries(capInputs)) {
      if (input.value !== "" && Number(input.value) > 0) frequencyCaps[channel] = Number(input.value);
    }
    try {
      await api("PUT", "/compliance/v0/policy", {
        quietHours,
        frequencyCaps: Object.keys(frequencyCaps).length ? frequencyCaps : null,
      });
      toast("Policy saved", "ok");
    } catch (error) { toast(errText(error), "err"); }
  });
  sheet.append(h("section", { class: "sheet-section" },
    h("h3", {}, "Marketing policy"),
    h("p", { class: "section-note" },
      "Quiet hours hold sms / email / push until the window ends; caps bound sends per player per rolling 24 hours."),
    h("div", { class: "row", style: "align-items:flex-end; gap:10px" },
      h("label", { class: "field", style: "margin:0" }, h("span", {}, "quiet from (UTC)"), qStart),
      h("label", { class: "field", style: "margin:0" }, h("span", {}, "until"), qEnd),
      h("span", { style: "flex:2" })),
    h("div", { class: "row", style: "align-items:flex-end; gap:10px; margin-top:12px" },
      capRow,
      h("span", { style: "flex:1" }),
      saveBtn)));

  /* audit trail */
  const auditSection = h("section", { class: "sheet-section" },
    h("h3", {}, "Audit trail",
      h("span", { class: "count" }, "latest 30")));
  if (!audit.items.length) auditSection.append(h("div", { class: "dim small" }, "nothing yet"));
  for (const row of audit.items) {
    auditSection.append(h("div", { class: "event-item" },
      h("span", { class: "ename" }, row.action),
      h("span", { class: "dim small", style: "flex:1" },
        `${row.actor}${row.journeyId ? ` · ${row.journeyId}` : ""}${row.detail ? ` · ${row.detail}` : ""}`),
      h("span", { class: "dim small" }, fmtTime(row.at))));
  }
  sheet.append(auditSection);
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
    } else if (parts[0] === "compliance") {
      setNav("compliance");
      await renderCompliance(view);
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
