"""Workday orchestrator: missions, handoffs, shared state, independent verification, retry and reroute.

Mount it into a FastAPI app with install(app, ...); server.py is a ready host."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import engine, store
from .routes import build_router


def install(app, root: Path, check_auth: Callable, start_agent: Callable, get_job: Callable) -> None:
    store.configure(root)
    app.include_router(build_router(check_auth))
    engine.install(start_agent, get_job)
