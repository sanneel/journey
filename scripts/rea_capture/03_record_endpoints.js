// REA capture · 03 · Passive endpoint recorder  (READ-ONLY — observes, never calls)
//
// The reference data we still lack (the activity palette/metadata, the
// promotions list, player segments, content templates, game providers) lives
// behind endpoints whose paths we don't know. Rather than guess them, this
// records the paths the backoffice UI ITSELF calls while you navigate.
//
// 1. Paste this. It starts recording.
// 2. Now click through the UI: open the Journey Builder + its activity palette,
//    open a journey, open Promotions, Segments/Audiences, Content/Templates,
//    Games — anything whose structure we want.
// 3. Run  __REA_stop()  in the console. It prints a table of every distinct
//    API path the UI hit, with method + status + response top-level keys, and
//    downloads rea_endpoints.json.
//
// Nothing here creates or modifies anything — it only mirrors the browser's
// own requests.
(() => {
  'use strict';
  if (window.__REA_REC) { console.log('%cAlready recording. Navigate, then run __REA_stop().', 'color:#eab308'); return; }

  const seen = new Map();  // key "METHOD path" -> record
  const trim = (u) => { try { const x = new URL(u, location.origin); return x.pathname; } catch (e) { return String(u).split('?')[0]; } };
  const isApi = (p) => /\/api\/|\/ubo\/|\/crm\//.test(p);
  const keysOf = (txt) => { try { const d = JSON.parse(txt); if (Array.isArray(d)) return { shape: 'array[' + d.length + ']', keys: d[0] ? Object.keys(d[0]).slice(0, 20) : [] }; if (d && typeof d === 'object') return { shape: 'object', keys: Object.keys(d).slice(0, 25) }; return { shape: typeof d, keys: [] }; } catch (e) { return { shape: 'text', keys: [] }; } };
  const note = (method, url, status, sampleText) => {
    const path = trim(url); if (!isApi(path)) return;
    const key = method + ' ' + path;
    const rec = seen.get(key) || { method, path, count: 0, lastStatus: 0, shape: '', sampleKeys: [], example: '' };
    rec.count++; rec.lastStatus = status;
    if (sampleText && !rec.shape) { const k = keysOf(sampleText); rec.shape = k.shape; rec.sampleKeys = k.keys; rec.example = sampleText.slice(0, 300); }
    seen.set(key, rec);
  };

  const of = window.fetch;
  window.fetch = function (i, n) {
    const url = (typeof i === 'string') ? i : (i && i.url);
    const method = ((n && n.method) || (i && i.method) || 'GET').toUpperCase();
    const p = of.apply(this, arguments);
    p.then((res) => { try { res.clone().text().then((t) => note(method, url, res.status, t)).catch(() => note(method, url, res.status, '')); } catch (e) { note(method, url, res.status, ''); } }).catch(() => {});
    return p;
  };
  const oo = XMLHttpRequest.prototype.open, os = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__rea = { m: (m || 'GET').toUpperCase(), u }; return oo.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function () {
    this.addEventListener('load', function () { try { note(this.__rea.m, this.__rea.u, this.status, this.responseText || ''); } catch (e) {} });
    return os.apply(this, arguments);
  };

  window.__REA_REC = { of, oo, os };
  window.__REA_stop = () => {
    window.fetch = window.__REA_REC.of;
    XMLHttpRequest.prototype.open = window.__REA_REC.oo;
    XMLHttpRequest.prototype.send = window.__REA_REC.os;
    delete window.__REA_REC;
    const rows = [...seen.values()].sort((a, b) => a.path.localeCompare(b.path));
    console.table(rows.map((r) => ({ method: r.method, path: r.path, hits: r.count, status: r.lastStatus, shape: r.shape })));
    window.__REA_ENDPOINTS = rows;
    try { const b = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' }); const u = URL.createObjectURL(b); const a = document.createElement('a'); a.href = u; a.download = 'rea_endpoints.json'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000); console.log('%cDownloaded rea_endpoints.json (' + rows.length + ' distinct paths)', 'color:#22c55e'); } catch (e) { console.warn('Download blocked — copy(window.__REA_ENDPOINTS)', e); }
    return rows;
  };
  console.log('%cRecording API paths. Navigate the UI (palette, a journey, promotions, segments, content), then run  __REA_stop()', 'color:#22c55e;font-weight:bold');
})();
