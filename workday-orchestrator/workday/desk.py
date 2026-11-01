"""The shared desk screen: missions that work on it wait for the desk lock and give it back when they end.

Other sessions may share the same screen, so the lock is taken only when a desk mission is about to start
(never held while it waits for its dependencies) and released as soon as the mission is done or failed.
"""
from __future__ import annotations

import logging
import subprocess

from . import config, store

log = logging.getLogger("workday.desk")

DESK_KINDS = {"pp_app"}
HELPER = config.DESK_LOCK_CMD.split() if config.DESK_LOCK_CMD else []


def _helper(*args: str) -> tuple[int, str]:
    if not HELPER:
        return 0, "no desk lock configured"
    try:
        proc = subprocess.run(HELPER + list(args), capture_output=True, text=True, timeout=60)
        return proc.returncode, (proc.stdout or proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"desk lock helper failed: {exc}"


def take(run_id: str, m: dict) -> bool:
    """True when the mission holds the desk and may start; otherwise it keeps waiting (shown on the board)."""
    code, out = _helper("try", f"{run_id} {m['id']}")
    if code == 0:
        store.update_mission(run_id, m["id"], desk="held")
        store.event(run_id, "desk_acquired", {"mission": m["id"]})
        return True
    if m.get("desk") != "waiting":
        store.update_mission(run_id, m["id"], desk="waiting")
        store.event(run_id, "desk_waiting", {"mission": m["id"], "why": out[:120]})
    return False


def release(run_id: str, m: dict) -> None:
    code, out = _helper("release", f"{run_id} {m['id']}")  # a no-op when a whole rehearsal holds the desk
    if code != 0:
        # Keep it marked held: the engine retries the release on its next tick for a finished mission.
        log.warning("desk release failed for %s %s: %s", run_id, m["id"], out)
        return
    store.update_mission(run_id, m["id"], desk="released")
    store.event(run_id, "desk_released", {"mission": m["id"]})
