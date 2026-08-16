#!/usr/bin/env python3
"""Entry point: `python server.py` (or `uvicorn server:app --reload`)."""
from __future__ import annotations

import os

import uvicorn

from app import create_app

app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("RELOAD")),
    )
