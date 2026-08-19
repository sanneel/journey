// REA capture · 04 · Single journey body  (READ-ONLY)
//
// Dump the full body of ONE journey by id. Use this after you build one of the
// activity types we still lack (native push, web push, WhatsApp, random split,
// email-engagement split, outgoing API request, bet insurance / collection,
// deposit collection, sport bonus, money bonus, coins bonus, standalone
// choosable flows) — build it in the UI, save the journey, then run this with
// its JRN id to capture that activity's real object + its rawJourneyData mirror.
//
// Edit JOURNEY_ID below, then paste.
(async () => {
  'use strict';
  const JOURNEY_ID = 'JRN-0-000000';   // <- put the journey id here

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
  const url = REA.crmRoot + '/journey-builder/v0/journeys/' + encodeURIComponent(JOURNEY_ID);
  const r = await fetch(url, { headers: H(), credentials: 'include' });
  const txt = await r.text();
  if (!r.ok) { console.error('HTTP ' + r.status, txt.slice(0, 400)); return; }
  const body = JSON.parse(txt);
  window.__REA_ONE = body;
  const g = body.activities ? body : (body.body || body);
  console.log('%c' + (g.journeyName || JOURNEY_ID), 'color:#22c55e;font-weight:bold');
  console.log('activities:', (g.activities || []).map((a) => a.activityName));
  try { const b = new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = 'rea_journey_' + JOURNEY_ID + '.json'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000); console.log('%cDownloaded rea_journey_' + JOURNEY_ID + '.json', 'color:#22c55e'); } catch (e) { console.warn('Download blocked — copy(window.__REA_ONE)', e); }
})();
