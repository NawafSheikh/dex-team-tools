"""Workday run storage: one folder per run, STATE.json as the single source of truth.

Layout of a run folder (ROOT/workday/<run_id>/):
  REQUEST.md            the job as typed in Teams
  STATE.json, STATE.md  shared state (machine and human readable)
  missions/<id>.md      one mission packet per task, written when the orchestrator adds it
  handoffs/<id>.md      the worker's handoff note, copied in once the mission is verified
  verify/<id>-a<n>.json verifier report per attempt
  work/<id>/            the worker's own folder
  shared/               deliverables shared between missions (screens, chart, workbook, deck, docs)
  inbox/                input files handed out for the day
  events.jsonl          append-only event log
"""
from __future__ import annotations

import copy
import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_ROOT: Path | None = None


def configure(root: Path) -> None:
    global _ROOT
    _ROOT = Path(root).resolve() / "workday"  # absolute: workers run in their own folders
    _ROOT.mkdir(parents=True, exist_ok=True)


def base() -> Path:
    if _ROOT is None:
        raise RuntimeError("workday store not configured")
    return _ROOT


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def now_epoch() -> float:
    return time.time()


def slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (cleaned or "item")[:limit].strip("-")


def run_dir(run_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{3,64}", run_id or ""):
        raise ValueError(f"invalid run id: {run_id!r}")
    path = base() / run_id
    if not path.exists():
        raise FileNotFoundError(f"no workday run {run_id}")
    return path


def new_run(request: str, title: str) -> dict:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    run_id = f"wd-{stamp}-{secrets.token_hex(2)}"
    rdir = base() / run_id
    for sub in ("missions", "handoffs", "verify", "work", "shared", "inbox"):
        (rdir / sub).mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": run_id,
        "title": title or "Workday",
        "request": request,
        "status": "planning",
        "created_at": now_iso(),
        "created_epoch": now_epoch(),
        "started_epoch": None,
        "finished_epoch": None,
        "view_key": secrets.token_urlsafe(18),
        "missions": [],
    }
    (rdir / "REQUEST.md").write_text(f"# Request\n\n{request.strip()}\n", encoding="utf-8")
    save(state)
    event(run_id, "run_created", {"title": state["title"]})
    return state


def load(run_id: str) -> dict:
    with _LOCK:
        return json.loads((run_dir(run_id) / "STATE.json").read_text(encoding="utf-8"))


def save(state: dict) -> None:
    with _LOCK:
        rdir = base() / state["run_id"]
        tmp = rdir / "STATE.json.tmp"
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(rdir / "STATE.json")
        (rdir / "STATE.md").write_text(render_state_md(state), encoding="utf-8")


def update(run_id: str, fn) -> dict:
    """Load, apply fn to a deep copy, save, return the new state."""
    with _LOCK:
        current = load(run_id)
        nxt = fn(copy.deepcopy(current))
        save(nxt)
        return nxt


def update_mission(run_id: str, mission_id: str, **fields: Any) -> dict:
    def apply(state: dict) -> dict:
        state["missions"] = [
            {**m, **fields} if m["id"] == mission_id else m for m in state["missions"]
        ]
        return state
    return update(run_id, apply)


def mission(state: dict, mission_id: str) -> dict:
    for m in state["missions"]:
        if m["id"] == mission_id:
            return m
    raise KeyError(f"no mission {mission_id}")


def event(run_id: str, kind: str, data: dict | None = None) -> None:
    line = json.dumps({"t": now_iso(), "epoch": now_epoch(), "event": kind, **(data or {})})
    with _LOCK:
        with (base() / run_id / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def events(run_id: str, limit: int = 200) -> list[dict]:
    path = run_dir(run_id) / "events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(x) for x in lines if x.strip()]


def list_runs(limit: int = 20) -> list[dict]:
    runs = sorted((p for p in base().iterdir() if (p / "STATE.json").exists()), reverse=True)
    out = []
    for p in runs[:limit]:
        s = json.loads((p / "STATE.json").read_text(encoding="utf-8"))
        out.append({"run_id": s["run_id"], "title": s["title"], "status": s["status"],
                    "missions": len(s["missions"])})
    return out


def elapsed(start: float | None, end: float | None) -> float | None:
    if not start:
        return None
    return round((end or now_epoch()) - start, 1)


def fmt_secs(secs: float | None) -> str:
    if secs is None:
        return "-"
    secs = int(secs)
    return f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}" if secs >= 3600 else f"{secs // 60}:{secs % 60:02d}"


def render_state_md(state: dict) -> str:
    lines = [
        f"# Workday state: {state['title']}",
        "",
        f"- Run: `{state['run_id']}`",
        f"- Status: **{state['status']}**",
        f"- Workday clock: {fmt_secs(elapsed(state.get('started_epoch'), state.get('finished_epoch')))}",
        "",
        "| Mission | Agent | Status | Attempts | Clock | Depends on |",
        "|---|---|---|---|---|---|",
    ]
    for m in state["missions"]:
        agents = " > ".join(a["agent"] for a in m.get("attempts", [])) or m["agent"]
        lines.append(
            f"| {m['id']} {m['title']} | {agents} | {m['status']} | {len(m.get('attempts', []))} | "
            f"{fmt_secs(elapsed(m.get('started_epoch'), m.get('finished_epoch')))} | "
            f"{', '.join(m.get('depends_on', [])) or '-'} |"
        )
    shared = state.get("shared_outputs", {})
    if shared:
        lines += ["", "## Shared outputs", ""] + [f"- {k}: `{v}`" for k, v in sorted(shared.items())]
    facts = state.get("facts", {})
    if facts:
        lines += ["", "## Facts carried between missions", ""] + [f"- {k}: {v}" for k, v in sorted(facts.items())]
    return "\n".join(lines) + "\n"
