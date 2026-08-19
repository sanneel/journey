// REA capture · 03 · Passive recorder  (ZERO extra API calls — pure observation)
//
// This is the safe one. It makes NO requests of its own — it only mirrors the
// requests the backoffice UI already makes as you navigate. To the server it is
// indistinguishable from normal browsing. It does two things at once:
//
//   1. records every distinct API path the UI calls (method + status + shape),
//   2. keeps the full body of every journey the UI loads, and — on stop —
//      distills the per-activity-type catalog we actually need.
//
// USE:
//   1. Paste this. It starts recording.
//   2. Navigate the UI normally: open the activity palette, open a handful of
//      VARIED journeys (a promo one, a casino one, a comms one, a sport one —
//      opening a journey makes the UI fetch its full body, which we capture),
//      and open Promotions / Segments / Content / Games if you want their
//      endpoints too.
//   3. Run  __REA_stop()  in the console.
//
// Downloads:
//   rea_activity_catalog.json  <- send me this (the deliverable)
//   rea_endpoints.json            (the endpoint map it saw)
//   rea_journey_bodies.json       (raw full bodies it captured, backup)
(() => {
  'use strict';
  if (window.__REA_REC) { console.log('%cAlready recording. Navigate, then run __REA_stop().', 'color:#eab308'); return; }

  const seen = new Map();          // "METHOD path" -> endpoint record
  const bodies = new Map();        // journeyId -> full body (deduped)

  const trim = (u) => { try { return new URL(u, location.origin).pathname; } catch (e) { return String(u).split('?')[0]; } };
  const isApi = (p) => /\/api\/|\/ubo\/|\/crm\//.test(p);
  const graphOf = (d) => (d && d.activities) ? d : (d && d.body && d.body.activities) ? d.body : null;

  const keysOf = (txt) => { try { const d = JSON.parse(txt); if (Array.isArray(d)) return { shape: 'array[' + d.length + ']', keys: d[0] ? Object.keys(d[0]).slice(0, 20) : [] }; if (d && typeof d === 'object') return { shape: 'object', keys: Object.keys(d).slice(0, 25) }; return { shape: typeof d, keys: [] }; } catch (e) { return { shape: 'text', keys: [] }; } };

  const capture = (method, url, status, txt) => {
    const path = trim(url); if (!isApi(path)) return;
    const key = method + ' ' + path;
    const rec = seen.get(key) || { method, path, count: 0, lastStatus: 0, shape: '', sampleKeys: [] };
    rec.count++; rec.lastStatus = status;
    if (txt && !rec.shape) { const k = keysOf(txt); rec.shape = k.shape; rec.sampleKeys = k.keys; }
    seen.set(key, rec);
    // keep any journey body the UI loaded
    if (txt) { try { const g = graphOf(JSON.parse(txt)); if (g) { const id = g.journeyId || g.reservedJourneyId || ('seen-' + bodies.size); if (!bodies.has(id)) { bodies.set(id, g); console.log('%ccaptured journey ' + id + ' — ' + (g.activities || []).length + ' activities', 'color:#22c55e'); } } } catch (e) {} }
  };

  const of = window.fetch;
  window.fetch = function (i, n) {
    const url = (typeof i === 'string') ? i : (i && i.url);
    const method = ((n && n.method) || (i && i.method) || 'GET').toUpperCase();
    const p = of.apply(this, arguments);
    p.then((res) => { try { res.clone().text().then((t) => capture(method, url, res.status, t)).catch(() => capture(method, url, res.status, '')); } catch (e) { capture(method, url, res.status, ''); } }).catch(() => {});
    return p;
  };
  const oo = XMLHttpRequest.prototype.open, os = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__rea = { m: (m || 'GET').toUpperCase(), u }; return oo.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function () { this.addEventListener('load', function () { try { capture(this.__rea.m, this.__rea.u, this.status, this.responseText || ''); } catch (e) {} }); return os.apply(this, arguments); };

  const dl = (name, obj) => { try { const b = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000); console.log('%cDownloaded ' + name, 'color:#22c55e'); } catch (e) { console.warn('Download blocked for ' + name, e); } };

  const buildCatalog = () => {
    const cat = {};
    const bump = (name) => cat[name] || (cat[name] = { count: 0, journeys: new Set(), events: { Activation: new Set(), Boundary: new Set(), Completion: new Set(), other: new Set() }, initKeys: new Set(), sampleInit: null, sampleInitSize: -1, sampleConfig: null });
    for (const g of bodies.values()) {
      const jid = g.journeyId || g.reservedJourneyId || '';
      const cfg = (g.rawJourneyData && g.rawJourneyData.activitiesConfiguration) || {};
      for (const a of (g.activities || [])) {
        const name = a.activityName; if (!name) continue;
        const c = bump(name); c.count++; c.journeys.add(jid);
        for (const e of (a.events || [])) { const bkt = c.events[e.eventType] || c.events.other; if (e.eventName) bkt.add(e.eventName); }
        const init = a.initializationData || {}; for (const k of Object.keys(init)) c.initKeys.add(k);
        const size = JSON.stringify(init).length; if (size > c.sampleInitSize) { c.sampleInitSize = size; c.sampleInit = init; c.sampleConfig = cfg[a.activityId] || c.sampleConfig; }
      }
    }
    const out = {};
    for (const [name, c] of Object.entries(cat)) out[name] = { count: c.count, inJourneys: c.journeys.size, events: { activation: [...c.events.Activation].sort(), boundary: [...c.events.Boundary].sort(), completion: [...c.events.Completion].sort(), ...(c.events.other.size ? { other: [...c.events.other].sort() } : {}) }, initKeys: [...c.initKeys].sort(), sampleInit: c.sampleInit, sampleConfig: c.sampleConfig };
    return out;
  };

  window.__REA_REC = { of, oo, os };
  window.__REA_stop = () => {
    window.fetch = window.__REA_REC.of;
    XMLHttpRequest.prototype.open = window.__REA_REC.oo;
    XMLHttpRequest.prototype.send = window.__REA_REC.os;
    delete window.__REA_REC;

    const endpoints = [...seen.values()].sort((a, b) => a.path.localeCompare(b.path));
    console.log('%c── endpoints seen ──', 'font-weight:bold');
    console.table(endpoints.map((r) => ({ method: r.method, path: r.path, hits: r.count, status: r.lastStatus, shape: r.shape })));

    const catalog = buildCatalog();
    console.log('%c── activity types captured: ' + Object.keys(catalog).length + ' (from ' + bodies.size + ' journeys) ──', 'font-weight:bold;color:#22c55e');
    console.table(Object.entries(catalog).map(([name, c]) => ({ activityName: name, seen: c.count, journeys: c.inJourneys, completionEvents: c.events.completion.length, initFields: c.initKeys.length })).sort((a, b) => a.activityName.localeCompare(b.activityName)));

    window.__REA_ENDPOINTS = endpoints;
    window.__REA_BODIES = [...bodies.values()];
    window.__REA_CAT = { journeysScanned: bodies.size, activityTypes: Object.keys(catalog).length, catalog };
    dl('rea_activity_catalog.json', window.__REA_CAT);
    dl('rea_endpoints.json', endpoints);
    if (bodies.size) dl('rea_journey_bodies.json', window.__REA_BODIES);
    if (!bodies.size) console.log('%cNo journey bodies captured yet — open a few journeys in the builder, then run __REA_stop() again.', 'color:#eab308');
    return { endpoints: endpoints.length, activityTypes: Object.keys(catalog).length, journeys: bodies.size };
  };
  console.log('%cRecording (no extra requests). Open the palette + a few varied journeys, then run  __REA_stop()', 'color:#22c55e;font-weight:bold');
})();
