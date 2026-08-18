#!/usr/bin/env python3
"""A stand-in casino platform: the other side of the delivery connectors.

Receives what the journey engine sends in webhook mode — reward grants
(the wallet / game-aggregator side) and comms messages (the gateway
side) — remembers everything, and can be told to fail so red paths can
be rehearsed.

  POST /wallet      reward grants land here
  POST /comms       sms / email / push / on-site messages land here
  GET  /received    everything received so far
  POST /fail-next   {"times": N} -> answer 500 to the next N calls

Run: python scripts/mock_platform.py   (port 9009, override with PORT)
"""
from __future__ import annotations

import os

import uvicorn
from fastapi import Body, FastAPI, Response

app = FastAPI(title="Mock casino platform")
received: list[dict] = []
fail_budget = {"times": 0}


def _accept(kind: str, payload: dict) -> Response | dict:
    if fail_budget["times"] > 0:
        fail_budget["times"] -= 1
        return Response(status_code=500, content="platform says no")
    entry = {"kind": kind, **payload}
    received.append(entry)
    print(f"[mock-platform] {kind}: {payload.get('rewardType') or payload.get('channel')} "
          f"-> {payload.get('playerId')} (journey {payload.get('journeyId')})", flush=True)
    return {"accepted": True}


@app.post("/wallet")
def wallet(payload: dict = Body(...)):
    return _accept("wallet", payload)


@app.post("/comms")
def comms(payload: dict = Body(...)):
    return _accept("comms", payload)


@app.get("/received")
def all_received():
    return {"items": received, "count": len(received)}


@app.post("/fail-next")
def fail_next(payload: dict = Body(...)):
    fail_budget["times"] = int(payload.get("times", 1))
    return {"failingNext": fail_budget["times"]}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "9009")))
