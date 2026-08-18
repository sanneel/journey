"""Journey Builder — a self-contained imitation of a CRM journey engine.

App factory: wires the builder API, the runtime API, optional bearer-token
auth, and the background timer scheduler.
"""
from __future__ import annotations

import contextlib
import os
import threading

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import SessionLocal, init_db

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

API_PREFIX = "/api/v0/crm"


def _scheduler_loop(stop_event: threading.Event) -> None:
    from .engine import Engine

    while not stop_event.wait(settings.scheduler_interval):
        session = SessionLocal()
        try:
            Engine(session).run_due_timers()
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()


def create_app() -> FastAPI:
    from .routes import identifiers, journeys, runtime

    app = FastAPI(
        title="Journey Builder",
        description=(
            "A working imitation of a CRM Journey Builder: node-graph journeys "
            "(sources, promotions, conditions, waits, splits, rewards, comms, "
            "terminals), draft lifecycle with server-minted identifiers, and a "
            "runtime engine that walks real players through published journeys."
        ),
        version="1.0.0",
    )

    init_db()

    @app.middleware("http")
    async def bearer_auth(request: Request, call_next):
        if settings.api_token and request.url.path.startswith("/api/"):
            header = request.headers.get("authorization", "")
            if header != f"Bearer {settings.api_token}":
                return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        return await call_next(request)

    app.include_router(journeys.router, prefix=API_PREFIX)
    app.include_router(identifiers.router, prefix=API_PREFIX)
    app.include_router(runtime.router, prefix=API_PREFIX)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    def metrics_endpoint():
        from fastapi.responses import PlainTextResponse

        from . import metrics

        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    # ── the builder UI ───────────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    if settings.scheduler_enabled:
        stop_event = threading.Event()

        @app.on_event("startup")
        def start_scheduler() -> None:
            thread = threading.Thread(
                target=_scheduler_loop, args=(stop_event,), daemon=True, name="timer-scheduler"
            )
            thread.start()
            app.state.scheduler_stop = stop_event

        @app.on_event("shutdown")
        def stop_scheduler() -> None:
            with contextlib.suppress(Exception):
                stop_event.set()

    return app
