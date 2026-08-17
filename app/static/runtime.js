/* Run view: enter players, feed platform events, tick timers, and watch
 * activations walk the graph — the whole mechanism, live. */
import { api, errText, h, toast, fmtTime } from "./app.js";

let refreshTimer = null;

export async function renderRun(view, journeyId) {
  clearInterval(refreshTimer);
  const journey = await api("GET", `/journey-builder/v0/journeys/${journeyId}`);
  const activityName = new Map(
    (journey.body.activities || []).map((activity) => [
      activity.activityId,
      activity.activityDisplayName || activity.activityName,
    ]),
  );
  const sources = (journey.body.activities || []).filter((activity) =>
    ["external_system_source", "dwh_source", "registration"].includes(activity.activityName),
  );

  view.innerHTML = "";
  const side = h("div", { class: "run-side" });
  const main = h("div", { class: "run-main" });
  view.append(h("div", { class: "run" }, side, main));

  /* ── left: controls ── */
  side.append(
    h("h2", {}, journey.journeyName),
    h("div", {},
      h("span", { class: "mono dim small" }, journey.journeyId), " ",
      h("span", { class: `badge ${journey.status}` }, journey.status), " ",
      h("button", {
        class: "btn ghost sm",
        onclick: () => (location.hash = `#/builder/${journey.journeyId}`),
      }, "<- Builder")),
  );

  if (journey.status !== "Published") {
    side.append(h("div", { class: "card", style: "margin-top:14px" },
      "This journey is not published — publish it to admit players."));
    return;
  }

  /* enter a player */
  side.append(h("h4", {}, "Enter a player"));
  const playerInput = h("input", { class: "input", placeholder: "player id", value: "player-1" });
  const attributesInput = h("input", { class: "input", placeholder: '{"playerValue": 100}  (optional attributes)' });
  const sourceSelect = h("select", { class: "input" });
  for (const source of sources) {
    sourceSelect.append(h("option", { value: source.activityId },
      `${source.activityDisplayName || source.activityName}`));
  }
  const enterBtn = h("button", { class: "btn primary", style: "width:100%; justify-content:center" }, "Enter journey");
  enterBtn.addEventListener("click", async () => {
    const playerId = playerInput.value.trim();
    if (!playerId) return toast("player id required", "err");
    try {
      const attributesRaw = attributesInput.value.trim();
      if (attributesRaw) {
        await api("POST", "/platform/v0/players", {
          playerId, attributes: JSON.parse(attributesRaw),
        });
      }
      await api("POST",
        `/journey-builder/v0/journeys/${journeyId}/activities/${sourceSelect.value}/enter`,
        { playerId });
      toast(`${playerId} entered`, "ok");
      refresh();
    } catch (error) {
      toast(errText(error), "err");
    }
  });
  side.append(h("div", { class: "card" },
    h("label", { class: "field" }, h("span", {}, "Player"), playerInput),
    h("label", { class: "field" }, h("span", {}, "Attributes (JSON, upserted first)"), attributesInput),
    h("label", { class: "field" }, h("span", {}, "Input source"), sourceSelect),
    enterBtn));

  /* platform event */
  side.append(h("h4", {}, "Platform event"));
  const eventName = h("input", { class: "input", list: "event-names", value: "deposit.approved" });
  const eventProps = h("textarea", { class: "input", rows: "3" });
  eventProps.value = '{"amount": 15000, "currencyCode": "CLP"}';
  const eventPlayer = h("input", { class: "input", placeholder: "player id", value: "player-1" });
  const sendEventBtn = h("button", { class: "btn", style: "width:100%; justify-content:center" }, "Send event");
  sendEventBtn.addEventListener("click", async () => {
    try {
      const result = await api("POST", "/platform/v0/events", {
        eventName: eventName.value.trim(),
        playerId: eventPlayer.value.trim(),
        properties: JSON.parse(eventProps.value || "{}"),
      });
      const resolved = result.resolved.length
        ? result.resolved.map((r) => r.completion).join(", ")
        : "nothing was waiting on it";
      toast(`Event sent — ${resolved}`, result.resolved.length ? "ok" : "");
      refresh();
    } catch (error) {
      toast(errText(error), "err");
    }
  });
  side.append(
    h("datalist", { id: "event-names" },
      h("option", { value: "deposit.approved" }),
      h("option", { value: "bet.settled" }),
      h("option", { value: "player.registered" })),
    h("div", { class: "card" },
      h("label", { class: "field" }, h("span", {}, "eventName"), eventName),
      h("label", { class: "field" }, h("span", {}, "playerId"), eventPlayer),
      h("label", { class: "field" }, h("span", {}, "properties"), eventProps),
      sendEventBtn));

  /* timers */
  side.append(h("h4", {}, "Scheduler"));
  const timersInfo = h("div", { class: "dim small", style: "margin-bottom:8px" }, "…");
  const runTimersBtn = h("button", { class: "btn", style: "width:100%; justify-content:center" }, "Run due timers now");
  runTimersBtn.addEventListener("click", async () => {
    const result = await api("POST", "/runtime/v0/timers/run");
    toast(`${result.fired} timer(s) fired`, result.fired ? "ok" : "");
    refresh();
  });
  side.append(h("div", { class: "card" }, timersInfo, runTimersBtn));

  /* player inspector */
  side.append(h("h4", {}, "Player ledger"));
  const ledgerPlayer = h("input", { class: "input", placeholder: "player id", value: "player-1" });
  const ledgerOut = h("div", { style: "margin-top:10px" });
  const ledgerBtn = h("button", { class: "btn sm" }, "Look up");
  ledgerBtn.addEventListener("click", () => renderLedger(ledgerOut, ledgerPlayer.value.trim()));
  side.append(h("div", { class: "card" },
    h("div", { class: "row" }, ledgerPlayer, ledgerBtn), ledgerOut));

  /* ── right: activations ── */
  const activationsBox = h("div");
  main.append(
    h("div", { class: "page-head" },
      h("h1", {}, "Activations"),
      h("div", { class: "spacer" }),
      h("span", { class: "dim small" }, "auto-refreshing")),
    activationsBox);

  async function refresh() {
    try {
      const [activations, timers] = await Promise.all([
        api("GET", `/runtime/v0/journeys/${journeyId}/activations`),
        api("GET", "/runtime/v0/timers"),
      ]);
      timersInfo.textContent = timers.items.length
        ? `${timers.items.length} pending timer(s); next due ${fmtTime(timers.items[0].dueAt)}`
        : "no pending timers";
      renderActivations(activationsBox, activations.items, activityName);
    } catch {
      /* keep the last good view on transient errors */
    }
  }

  await refresh();
  refreshTimer = setInterval(() => {
    if (!document.body.contains(main)) { clearInterval(refreshTimer); return; }
    refresh();
  }, 2500);
}

const expanded = new Set();

function renderActivations(container, items, activityName) {
  container.innerHTML = "";
  if (!items.length) {
    container.append(h("div", { class: "card empty" },
      "No activations yet — enter a player on the left."));
    return;
  }
  for (const activation of [...items].reverse()) {
    const isOpen = expanded.has(activation.activationId);
    const head = h("div", { class: "row", style: "cursor:pointer" },
      h("strong", { style: "flex:none" }, activation.playerId),
      h("span", { class: `badge ${activation.status}`, style: "flex:none" }, activation.status),
      h("span", { class: "dim small", style: "flex:1" },
        activation.status === "Active"
          ? `at: ${activityName.get(activation.currentActivityId) || activation.currentActivityId || "?"}`
          : `via ${activation.context?.completedVia || "-"}`),
      h("span", { class: "dim small", style: "flex:none" }, `#${activation.activationId} · ${fmtTime(activation.createdAt)}`),
    );
    const card = h("div", { class: "card" }, head);
    head.addEventListener("click", () => {
      if (expanded.has(activation.activationId)) expanded.delete(activation.activationId);
      else expanded.add(activation.activationId);
      renderActivations(container, items, activityName);
    });
    if (isOpen) {
      const timeline = h("div", { style: "margin-top:10px" });
      for (const event of activation.eventsHistory || []) {
        timeline.append(h("div", { class: "event-item" },
          h("span", { class: `etype ${event.eventType}` }, event.eventType),
          h("span", {},
            h("div", { class: "ename" }, event.eventName),
            h("div", { class: "enode" },
              `${activityName.get(event.activityId) || event.activityId} · ${fmtTime(event.occurredAt)}`))));
      }
      card.append(timeline);
    }
    container.append(card);
  }
}

async function renderLedger(container, playerId) {
  if (!playerId) return;
  container.innerHTML = "";
  try {
    const [rewards, comms, offers] = await Promise.all([
      api("GET", `/runtime/v0/players/${playerId}/rewards`),
      api("GET", `/runtime/v0/players/${playerId}/comms`),
      api("GET", `/runtime/v0/players/${playerId}/offers`),
    ]);

    container.append(h("h4", {}, `Rewards (${rewards.items.length})`));
    if (!rewards.items.length) container.append(h("div", { class: "dim small" }, "none yet"));
    for (const grant of rewards.items) {
      const spins = grant.detail?.spins ? ` · ${grant.detail.spins} spins` : "";
      const percent = grant.detail?.bonusPercent ? ` · ${grant.detail.bonusPercent}%` : "";
      container.append(h("div", { class: "event-item" },
        h("span", { class: "ename" }, grant.rewardType),
        h("span", { class: "dim small" }, `${grant.status}${spins}${percent}`)));
    }

    container.append(h("h4", {}, `Offers (${offers.items.length})`));
    for (const offer of offers.items) {
      const row = h("div", { class: "event-item" },
        h("span", { class: "ename" }, `#${offer.offerId}`),
        h("span", { class: `badge ${offer.status === "Offered" ? "Active" : offer.status === "Accepted" ? "Completed" : "Terminated"}` }, offer.status));
      if (offer.status === "Offered") {
        const accept = h("button", { class: "btn sm primary", style: "margin-left:auto" }, "Accept");
        accept.addEventListener("click", async () => {
          try {
            await api("POST", `/runtime/v0/offers/${offer.offerId}/accept`);
            toast("Offer accepted", "ok");
            renderLedger(container, playerId);
          } catch (error) { toast(errText(error), "err"); }
        });
        row.append(accept);
      }
      container.append(row);
    }

    container.append(h("h4", {}, `Comms (${comms.items.length})`));
    for (const message of comms.items) {
      const row = h("div", { class: "event-item" },
        h("span", { class: "ename" }, message.channel),
        h("span", { class: "dim small" }, message.status));
      if (message.status !== "Clicked") {
        for (const action of ["read", "click"]) {
          const btn = h("button", { class: "btn sm", style: action === "read" ? "margin-left:auto" : "" }, action);
          btn.addEventListener("click", async () => {
            await api("POST", `/runtime/v0/comms/${message.messageId}/${action}`);
            renderLedger(container, playerId);
          });
          row.append(btn);
        }
      }
      container.append(row);
    }
  } catch (error) {
    container.append(h("div", { class: "dim small" }, errText(error)));
  }
}
