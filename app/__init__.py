"""Journey Builder — a self-contained imitation of a CRM journey engine.

App factory: wires the builder API, the runtime API, optional bearer-token
auth, and the background timer scheduler.
"""
from __future__ import annotations

import contextlib
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .db import SessionLocal, init_db

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
