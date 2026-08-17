# Console scripts

The operators' journey-cloner workflow, reproduced by this sandbox: a
`*_console.js` file is pasted into the browser console of a Journey
Builder page and it reserves a journey id, POSTs the embedded draft
payload, publishes it, and prints `DONE` with the created `JRN-*` ids.

`promotion_campaign_console.js` is a generated example (from the
built-in *Promotion campaign* template — 14 activities). To try it:

1. `python server.py`, open http://localhost:8000/
2. F12 → Console (type `allow pasting` if Chrome warns)
3. Paste the whole file, press Enter
4. `DONE: JRN-0-… (Published)` — the journey appears in the dashboard

Generate one for any journey from the builder toolbar (**Console
script** button) or directly:

```
GET /api/v0/crm/journey-builder/v0/journeys/{JRN}/console-script[?publish=false]
```

Every download mints fresh internal activity ids and blanks the
promotion display ids (the server re-mints them), so the same file can
be pasted any number of times — each run creates a new copy, exactly
like the cloner's strip/regenerate rules require. `MANUAL_TOKEN` at the
top of the script adds a bearer token for deployments that need auth.
