// REA capture · 02 · Journey bodies + per-activity-type catalog  (READ-ONLY)
//
// Fetches the FULL body of each journey and distills the one thing we need to
// complete our imitation: for every activityName that exists anywhere in your
// backoffice, a real initializationData sample + the union of its event
// vocabulary (Activation / Boundary / Completion) + its rawJourneyData config
// shape.
//
// ids come from (in order): window.__REA_IDS (edit below), else the inventory
// script's window.__REA_INV.ids. Run script 01 first, or paste ids into IDS.
//
// Downloads TWO files:
//   rea_activity_catalog.json  — small, this is the deliverable to send back
//   rea_journey_bodies.json    — the raw full bodies (backup / deep reference)
(async () => {
  'use strict';

  const MAX_JOURNEYS = 60;     // cap the fetch; raise if you want everything
  const DELAY_MS = 120;        // be gentle on the API between requests
  const IDS = window.__REA_IDS || (window.__REA_INV && window.__REA_INV.ids) || [
    // 'JRN-0-577417', 'JRN-0-222272',   // <- or hardcode ids here
  ];

  const REA = await (async () => {
    const DEFAULT_ROOT = location.origin + '/api/ubo/api/v0/crm';
    const s = { auth: '', brand: '', crmRoot: (window.__REA_INV && window.__REA_INV.crmRoot) || '' };
    const decode = (t) => { try { return JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); } catch (e) { return null; } };
    const usable = (v) => { if (!v) return null; const b = /^bearer\s+/i.test(v) ? v : 'Bearer ' + v; const p = decode(b.replace(/^bearer\s+/i, '')); if (!p || (p.exp && p.exp - Date.now() / 1000 < 30)) return null; return b; };
    const rootOf = (url) => { try { const u = new URL(url, location.origin); const i = u.pathname.indexOf('/crm'); return i >= 0 ? u.origin + u.pathname.slice(0, i + 4) : ''; } catch (e) { return ''; } };
    await new Promise((resolve, reject) => {
      let done = false;
      const of = window.fetch, oh = XMLHttpRequest.prototype.setRequestHeader, oo = XMLHttpRequest.prototype.open;
      const clean = () => { window.fetch = of; XMLHttpRequest.prototype.setRequestHeader = oh; XMLHttpRequest.prototype.open = oo; };
      const finish = () => { if (done || !s.auth) return; done = true; clean(); clearTimeout(t); s.crmRoot = s.crmRoot || DEFAULT_ROOT; s.brand = s.brand || (window.__REA_INV && window.__REA_INV.brand) || 'JBCL'; resolve(); };
      const grabAuth = (v) => { const a = usable(v); if (a) s.auth = a; };
      const grabBrand = (v) => { if (v && !s.brand) s.brand = v; };
      window.fetch = function (i, n) {
        try {
          const url = (typeof i === 'string') ? i : (i && i.url); if (url && !s.crmRoot) { const r = rootOf(url); if (r) s.crmRoot = r; }
          const h = (n && n.headers) || (i && i.headers);
          if (h) { const g = (k) => typeof h.get === 'function' ? h.get(k) : (h[k] || h[k.toLowerCase()]); grabAuth(g('authorization')); grabBrand(g('x-brand')); }
        } catch (e) {}
        const p = of.apply(this, arguments); finish(); return p;
      };
      XMLHttpRequest.prototype.open = function (m, url) { try { if (url && !s.crmRoot) { const r = rootOf(url); if (r) s.crmRoot = r; } } catch (e) {} return oo.apply(this, arguments); };
      XMLHttpRequest.prototype.setRequestHeader = function (k, v) { try { if (/^authorization$/i.test(k)) grabAuth(v); if (/^x-brand$/i.test(k)) grabBrand(v); } catch (e) {} const r = oh.apply(this, arguments); finish(); return r; };
      const t = setTimeout(() => { if (!done) { done = true; clean(); reject(new Error('No auth token seen in 3 min — click around the UI and rerun.')); } }, 180000);
      console.log('%cWaiting for the backoffice to make a request — click anything in the UI…', 'color:#eab308');
    });
    console.log('%cReady', 'color:#22c55e;font-weight:bold', { crmRoot: s.crmRoot, brand: s.brand });
    return s;
  })();

  const H = () => ({ accept: 'application/json, text/plain, */*', authorization: REA.auth, 'x-brand': REA.brand });
  const jbase = REA.crmRoot + '/journey-builder/v0';
  const get = async (url) => { const r = await fetch(url, { headers: H(), credentials: 'include' }); const txt = await r.text(); let data; try { data = JSON.parse(txt); } catch (e) { data = txt; } return { ok: r.ok, status: r.status, data }; };
  const dl = (name, obj) => { try { const b = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000); console.log('%cDownloaded ' + name, 'color:#22c55e'); } catch (e) { console.warn('Download blocked — copy(window.__REA_CAT) / window.__REA_BODIES', e); } };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  if (!IDS.length) { console.error('No ids. Run script 01 first, or paste ids into the IDS array at the top.'); return; }
  const targets = IDS.slice(0, MAX_JOURNEYS);
  console.log('Fetching', targets.length, 'journey bodies (of', IDS.length, 'known)…');

  const bodies = [];
  for (let i = 0; i < targets.length; i++) {
    const id = targets[i];
    try {
      const res = await get(jbase + '/journeys/' + encodeURIComponent(id));
      if (res.ok && res.data && typeof res.data === 'object') { bodies.push(res.data); console.log('  [' + (i + 1) + '/' + targets.length + ']', id, '✓'); }
      else console.warn('  [' + (i + 1) + '/' + targets.length + ']', id, 'HTTP', res.status);
    } catch (e) { console.warn('  ', id, 'failed', e.message); }
    await sleep(DELAY_MS);
  }
  if (!bodies.length) { console.error('No bodies fetched.'); return; }

  // some GETs wrap the journey as { body: {...} } — normalise to the graph object
  const graphOf = (b) => (b && b.activities) ? b : (b && b.body && b.body.activities) ? b.body : b;

  // ── distill the per-activity-type catalog ──
  const cat = {};
  const bump = (name) => cat[name] || (cat[name] = {
    count: 0, journeys: new Set(),
    events: { Activation: new Set(), Boundary: new Set(), Completion: new Set(), other: new Set() },
    initKeys: new Set(), sampleInit: null, sampleInitSize: -1, sampleConfig: null,
  });
  for (const raw of bodies) {
    const g = graphOf(raw);
    const jid = g.journeyId || g.reservedJourneyId || raw.journeyId || '';
    const cfg = (g.rawJourneyData && g.rawJourneyData.activitiesConfiguration) || {};
    for (const a of (g.activities || [])) {
      const name = a.activityName; if (!name) continue;
      const c = bump(name); c.count++; c.journeys.add(jid);
      for (const e of (a.events || [])) {
        const bucket = c.events[e.eventType] || c.events.other;
        if (e.eventName) bucket.add(e.eventName);
      }
      const init = a.initializationData || {};
      for (const k of Object.keys(init)) c.initKeys.add(k);
      const size = JSON.stringify(init).length;              // keep the richest example
      if (size > c.sampleInitSize) { c.sampleInitSize = size; c.sampleInit = init; c.sampleConfig = cfg[a.activityId] || c.sampleConfig; }
    }
  }
  const catalog = {};
  for (const [name, c] of Object.entries(cat)) {
    catalog[name] = {
      count: c.count,
      inJourneys: c.journeys.size,
      events: {
        activation: [...c.events.Activation].sort(),
        boundary: [...c.events.Boundary].sort(),
        completion: [...c.events.Completion].sort(),
        ...(c.events.other.size ? { other: [...c.events.other].sort() } : {}),
      },
      initKeys: [...c.initKeys].sort(),
      sampleInit: c.sampleInit,
      sampleConfig: c.sampleConfig,
    };
  }

  const summary = Object.entries(catalog).map(([name, c]) => ({
    activityName: name, seen: c.count, journeys: c.inJourneys,
    completionEvents: c.events.completion.length, initFields: c.initKeys.length,
  })).sort((a, b) => a.activityName.localeCompare(b.activityName));
  console.table(summary);
  console.log('%c' + Object.keys(catalog).length + ' distinct activity types captured.', 'color:#22c55e;font-weight:bold');

  window.__REA_CAT = { crmRoot: REA.crmRoot, brand: REA.brand, journeysScanned: bodies.length, activityTypes: Object.keys(catalog).length, catalog };
  window.__REA_BODIES = bodies;
  dl('rea_activity_catalog.json', window.__REA_CAT);   // <-- send me THIS one
  dl('rea_journey_bodies.json', bodies);               //     (bodies = backup)
})();
