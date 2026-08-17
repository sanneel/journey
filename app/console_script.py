"""Console-script export — the operator workflow from the source system.

The operators' journey-cloner ships `*_console.js` files: paste one into
the browser console of a logged-in Journey Builder backoffice and it
reserves an id, POSTs the embedded draft payloads in order, and prints
DONE with the created JRN ids. This module generates the same kind of
script from any journey stored here.

Each download regenerates internal ids (activityId graph, blanked
display ids), so the same script can be pasted repeatedly and against
any deployment that speaks `/journey-builder/v0` — this sandbox by
default, or an authenticated backoffice via MANUAL_TOKEN.
"""
from __future__ import annotations

import json

from .cloner import clone_journey_body
from .durations import utcnow
from .models import Journey

_TEMPLATE = """// Journey Builder console script — generated {generated}
// Journey: {name} (cloned from {source_id})
// Target: any deployment speaking /journey-builder/v0 (this sandbox by default)
//
// HOW TO RUN:
//   1. Open the Journey Builder UI in Chrome, logged in if the target needs it.
//   2. F12 -> Console tab (if Chrome warns, type: allow pasting).
//   3. Paste this whole script and press Enter.
//   4. Wait for "DONE" with the created JRN ids.
//
// Internal ids in the payload below are freshly minted for this download;
// promotion display ids are blank so the server re-mints them. Paste the
// same file twice and the second run simply creates another copy.
(async () => {{
  'use strict';
  // Optional: paste an access token here when the target requires auth.
  const MANUAL_TOKEN = '';
  const BASE = location.origin + '/api/v0/crm/journey-builder/v0';
  const PUBLISH = {publish};   // false -> leave the created journey as Draft

  const PAYLOADS = [
{payloads}
  ];

  const headers = (contentType) => {{
    const h = {{}};
    if (contentType) h['content-type'] = contentType;
    if (MANUAL_TOKEN.trim()) {{
      h['authorization'] = 'Bearer ' + MANUAL_TOKEN.trim().replace(/^Bearer\\s+/i, '');
    }}
    return h;
  }};

  async function reserveId() {{
    const r = await fetch(BASE + '/journeys/identifier', {{
      method: 'POST',
      headers: headers('application/json'),
      body: '{{}}',
      credentials: 'include',
    }});
    const raw = (await r.text()).trim();
    // Response may be a bare string ("JRN-...") or {{"journeyId": "JRN-..."}}.
    let id = raw.replace(/^"+|"+$/g, '');
    try {{
      const data = JSON.parse(raw);
      if (typeof data === 'string') id = data.trim();
      else if (data && typeof data === 'object') {{
        id = String(data.identifier || data.journeyId || data.id || data.value || '').trim();
      }}
    }} catch (e) {{ /* keep the raw text */ }}
    if (!r.ok || !id.startsWith('JRN-')) {{
      throw new Error('Failed to reserve journey ID: HTTP ' + r.status + ' ' + raw);
    }}
    return id;
  }}

  async function createDraft(payload) {{
    const r = await fetch(BASE + '/journey-drafts', {{
      method: 'POST',
      headers: headers('application/json'),
      body: JSON.stringify(payload),
      credentials: 'include',
    }});
    const data = await r.json().catch(() => null);
    if (!r.ok) {{
      throw new Error('Create failed: HTTP ' + r.status + ' ' + JSON.stringify(data));
    }}
    return data;
  }}

  async function publishJourney(journeyId) {{
    const r = await fetch(BASE + '/journeys/' + journeyId + '/publish', {{
      method: 'POST',
      headers: headers('application/json'),
      credentials: 'include',
    }});
    if (!r.ok) {{
      const raw = await r.text();
      throw new Error('Publish failed: HTTP ' + r.status + ' ' + raw);
    }}
    return r.json();
  }}

  const created = [];
  for (const payload of PAYLOADS) {{
    const journeyId = await reserveId();
    payload.journeyId = journeyId;
    payload.reservedJourneyId = journeyId;
    console.log('Reserved', journeyId, '->', payload.journeyName);
    const draft = await createDraft(payload);
    let status = draft.status;
    if (PUBLISH) {{
      const published = await publishJourney(journeyId);
      status = published.status;
      if (published.webhooks && published.webhooks.length) {{
        console.log('  webhooks:', published.webhooks.map((w) => w.webhookId).join(', '));
      }}
    }}
    created.push(journeyId + ' (' + status + ')');
    console.log('%cCreated ' + journeyId + ' — ' + status, 'color:#22c55e;font-weight:bold');
  }}
  console.log('%cDONE: ' + created.join(', '), 'color:#22c55e;font-weight:bold;font-size:14px');
}})();
"""


def render_console_script(journey: Journey, *, publish: bool = True) -> str:
    body, _ = clone_journey_body(
        journey.body,
        new_journey_id="",
        new_name=journey.journey_name,
        source_journey_id=journey.journey_id,
        source_version=journey.version,
    )
    # the script reserves its own id at run time
    body.pop("journeyId", None)
    body.pop("reservedJourneyId", None)
    body.pop("duplicatedFromId", None)
    payload = json.dumps(body, indent=2, ensure_ascii=False)
    indented = "\n".join(f"    {line}" for line in payload.splitlines())
    return _TEMPLATE.format(
        generated=utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        name=journey.journey_name,
        source_id=journey.journey_id,
        publish="true" if publish else "false",
        payloads=indented,
    )
