// REA capture · 01 · Journey inventory  (READ-ONLY — lists journeys, changes nothing)
//
// Paste into the DevTools console on a logged-in REA backoffice tab
// (pmi.rea-backoffice.gr8.tech). It captures the page's own auth token,
// auto-detects the API base + brand, lists every journey, prints a table,
// stashes the result on window.__REA_INV, and downloads rea_inventory.json.
//
// Run this FIRST — script 02 reuses the ids it finds.
(async () => {
  'use strict';

  // ── shared preamble: capture auth + brand + api root from the page ──
  const REA = await (async () => {
    const DEFAULT_ROOT = location.origin + '/api/ubo/api/v0/crm';
    const s = { auth: '', brand: '', crmRoot: '' };
    const decode = (t) => { try { return JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); } catch (e) { return null; } };
    const usable = (v) => { if (!v) return null; const b = /^bearer\s+/i.test(v) ? v : 'Bearer ' + v; const p = decode(b.replace(/^bearer\s+/i, '')); if (!p || (p.exp && p.exp - Date.now() / 1000 < 30)) return null; return b; };
    const rootOf = (url) => { try { const u = new URL(url, location.origin); const i = u.pathname.indexOf('/crm'); return i >= 0 ? u.origin + u.pathname.slice(0, i + 4) : ''; } catch (e) { return ''; } };
    await new Promise((resolve, reject) => {
      let done = false;
      const of = window.fetch, oh = XMLHttpRequest.prototype.setRequestHeader, oo = XMLHttpRequest.prototype.open;
      const clean = () => { window.fetch = of; XMLHttpRequest.prototype.setRequestHeader = oh; XMLHttpRequest.prototype.open = oo; };
      const finish = () => { if (done || !s.auth) return; done = true; clean(); clearTimeout(t); s.crmRoot = s.crmRoot || DEFAULT_ROOT; s.brand = s.brand || 'JBCL'; resolve(); };
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
  const dl = (name, obj) => { try { const b = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000); console.log('%cDownloaded ' + name, 'color:#22c55e'); } catch (e) { console.warn('Download blocked — copy(window.__REA_INV) instead', e); } };
  const asArray = (d) => Array.isArray(d) ? d : (d && (d.items || d.content || d.data || d.journeys || d.results || d.list)) || [];

  // the list contract is unknown — try a few shapes, keep the first that yields rows
  const candidates = [
    '/journeys',
    '/journeys?page=0&size=500',
    '/journeys?limit=500',
    '/journeys?pageSize=500&pageNumber=0',
    '/journeys?take=500&skip=0',
  ];
  let raw = null, used = '';
  for (const path of candidates) {
    const res = await get(jbase + path);
    console.log('GET', path, '→', res.status);
    if (res.ok && asArray(res.data).length) { raw = res.data; used = path; break; }
    if (res.ok && !raw) { raw = res.data; used = path; } // keep first 200 even if empty/odd
  }
  if (raw === null) { console.error('No journeys endpoint answered. Paste back the statuses above.'); return; }

  const rows = asArray(raw);
  console.log('%cGET ' + used + ' returned ' + rows.length + ' journeys', 'color:#22c55e');
  if (rows[0]) console.log('First raw item keys:', Object.keys(rows[0]));

  const mapped = rows.map((j) => ({
    id: j.journeyId || j.id || j.reservedJourneyId || '',
    name: j.journeyName || j.name || '',
    status: j.status || '',
    brand: j.brand || '',
    startAt: j.startAt || '',
    stopAt: j.stopAt || '',
  }));
  console.table(mapped);

  const ids = mapped.map((m) => m.id).filter(Boolean);
  window.__REA_INV = { crmRoot: REA.crmRoot, brand: REA.brand, endpoint: used, count: rows.length, ids, mapped, raw };
  console.log('%c' + ids.length + ' ids stashed on window.__REA_INV.ids — now run script 02.', 'color:#eab308;font-weight:bold');
  dl('rea_inventory.json', window.__REA_INV);
})();
