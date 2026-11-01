"""HTTP surface of the workday orchestrator (called by the Copilot Studio connector)."""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from . import bestof, board, config, desk, store
from .kinds import KINDS, describe_kinds
from .prompts import write_packet

PUBLIC_BASE = config.PUBLIC_BASE
INBOX = config.INBOX
VIEWABLE = ("shared/", "missions/", "handoffs/", "verify/", "STATE.md", "REQUEST.md", "work/")


class RunBody(BaseModel):
    request: str = Field(..., min_length=3, description="The job exactly as the requester typed it")
    title: str = Field("Workday", max_length=80)


class MissionBody(BaseModel):
    kind: Literal["pp_tables", "pp_app", "pp_flows", "excel", "deck", "notes", "guide"]
    title: str = Field(..., min_length=3, max_length=80)
    goal: str = Field(..., min_length=3)
    agent: Literal["claude", "codex"]
    why_agent: str = Field(..., min_length=3, description="Why this agent suits this mission")
    depends_on: str = Field("", description="Comma separated mission ids, e.g. 'M1, M2'")
    notes: str = ""
    on_fail: Literal["retry_then_reroute", "reroute", "retry"] = "retry_then_reroute"
    mode: Literal["single", "best_of_both"] = Field(
        "single", description="best_of_both: Claude and Codex both do it, the verifier checks both, a blind judge "
                              "picks the better one and the winner may merge in the other's strengths")


class RetryBody(BaseModel):
    agent: Literal["claude", "codex"] | None = None
    reason: str = ""
    notes: str = Field("", description="Added to the mission packet, e.g. what earlier attempts already built")


class PlanBody(BaseModel):
    request: str = Field(..., min_length=3, description="The job exactly as the requester typed it")
    title: str = Field("Workday", max_length=80)
    missions: list[MissionBody] | None = Field(None, max_length=12,
                                               description="One per deliverable, in dependency order (M1, M2, ...)")
    missions_json: str | None = Field(None, description="The same list as JSON text. Copilot Studio connector "
                                                        "actions cannot send a list of objects, so it sends this.")

    def mission_list(self) -> list[MissionBody]:
        if self.missions:
            return self.missions
        try:
            raw = json.loads(self.missions_json or "")
        except ValueError as exc:
            raise HTTPException(400, f"missions_json is not valid JSON: {exc}") from exc
        if isinstance(raw, dict):
            raw = raw.get("missions", [])
        if not isinstance(raw, list) or not 1 <= len(raw) <= 12:
            raise HTTPException(400, "missions_json must be a JSON list of 1 to 12 missions")
        try:
            return [MissionBody(**m) for m in raw]
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"a mission in missions_json is invalid: {exc}") from exc


def build_router(check_auth) -> APIRouter:
    r = APIRouter(prefix="/workday", tags=["workday"])

    def auth(key: str | None) -> None:
        check_auth(key)

    def links(state: dict) -> dict:
        k = state["view_key"]
        return {"board_url": f"{PUBLIC_BASE}/workday/board/{state['run_id']}?k={k}",
                "files_base": f"{PUBLIC_BASE}/workday/files/{state['run_id']}/"}

    def summary(state: dict) -> dict:
        missions = []
        for m in state["missions"]:
            last = (m.get("attempts") or [{}])[-1]
            verdict = last.get("verdict") or {}
            every = m.get("earlier_attempts", []) + m.get("attempts", [])  # a reopened mission keeps its history
            earlier = (m.get("earlier_attempts") or [{}])[-1].get("verdict") or {}
            missions.append({
                "id": m["id"], "title": m["title"], "kind": m["kind"], "status": m["status"],
                "agent_chain": " > ".join(a["agent"] for a in every) or m["agent"],
                "why_agent": m["why_agent"], "depends_on": ", ".join(m.get("depends_on", [])),
                "clock": store.fmt_secs(store.elapsed(m.get("started_epoch"), m.get("finished_epoch"))),
                "attempts": len(every),
                "reopened_after": (f"{len(m['earlier_attempts'])} failed attempts, last failed: "
                                   + "; ".join(c["name"] for c in earlier.get("failed", []))
                                   if m.get("earlier_attempts") else ""),
                "last_reason": last.get("reason", ""),
                "failed_checks": "; ".join(f"{c['name']} ({c['detail']})" for c in verdict.get("failed", [])),
                "packet": m.get("packet", ""),
                "mode": m.get("mode", "single"),
                "best_of_both": _bob_summary(m),
            })
        return {"run_id": state["run_id"], "title": state["title"], "status": state["status"],
                "workday_clock": store.fmt_secs(store.elapsed(state.get("started_epoch"), state.get("finished_epoch"))),
                "missions": missions, "facts": state.get("facts", {}),
                "deliverables": [f"{links(state)['files_base']}{p}?k={state['view_key']}" for p in _shared(state)],
                **links(state)}

    def _bob_summary(m: dict) -> str:
        bob = m.get("bob") or {}
        if not bob:
            return ""
        parts = [f"{a}: " + {True: "passed", False: "failed", None: "working"}[(c.get("verdict") or {}).get("passed")]
                 for a, c in bob.get("candidates", {}).items()]
        judge = bob.get("judge") or {}
        if judge.get("winner"):
            parts.append(f"judge picked {judge['winner']}: {judge.get('reasons', '')}")
        if bob.get("final"):
            parts.append(f"final: {bob['final']}")
        return "; ".join(parts)

    def _shared(state: dict) -> list[str]:
        sdir = store.base() / state["run_id"] / "shared"
        return sorted(str(p.relative_to(sdir.parent)).replace("\\", "/") for p in sdir.rglob("*") if p.is_file())

    @r.get("/kinds")
    def kinds(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        auth(x_api_key)
        return {"kinds": describe_kinds(), "agents": ["claude", "codex"]}

    @r.post("/runs")
    def create_run(body: RunBody, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        auth(x_api_key)
        state = store.new_run(body.request, body.title)
        if INBOX.exists():
            for f in INBOX.iterdir():
                if f.is_file():
                    shutil.copy2(f, store.base() / state["run_id"] / "inbox" / f.name)
        inbox = sorted(p.name for p in (store.base() / state["run_id"] / "inbox").iterdir())
        return {**summary(state), "inbox": inbox, "next": "Add one mission per task with AddMission, then StartWorkday."}

    def _check_mission(body: MissionBody, known: set[str]) -> list[str]:
        if body.mode == "best_of_both" and body.kind not in bestof.FILE_KINDS:
            raise HTTPException(400, f"{body.title}: best_of_both is for file missions (excel, deck, notes, guide); "
                                     "Power Platform missions change one shared environment, so one agent does them")
        deps = [d.upper() for d in re.findall(r"[Mm]\d+", body.depends_on)]
        unknown = [d for d in deps if d not in known]
        if unknown:
            raise HTTPException(400, f"{body.title}: unknown dependencies {unknown}; list those missions first")
        return deps

    def _append_mission(run_id: str, body: MissionBody) -> dict:
        added: dict = {}

        def append(s: dict) -> dict:
            if s["status"] not in ("planning", "running"):
                raise HTTPException(409, f"run is {s['status']}")
            deps = _check_mission(body, {m["id"] for m in s["missions"]})
            mission = {"id": f"M{len(s['missions']) + 1}", "kind": body.kind, "title": body.title.strip(),
                       "goal": body.goal, "agent": body.agent, "why_agent": body.why_agent, "depends_on": deps,
                       "notes": body.notes, "on_fail": body.on_fail, "mode": body.mode, "status": "planned", "attempts": [],
                       "started_epoch": None, "finished_epoch": None}
            mission["packet"] = write_packet(s, mission)
            added.update(mission)
            return {**s, "missions": s["missions"] + [mission]}

        store.update(run_id, append)
        store.event(run_id, "mission_added", {"mission": added["id"], "kind": body.kind, "agent": body.agent,
                                              "why": body.why_agent, "depends_on": added["depends_on"]})
        return added

    def _start(run_id: str) -> dict:
        state = _load(run_id)
        if not state["missions"]:
            raise HTTPException(400, "add missions first")
        if state["status"] == "planning":
            state = store.update(run_id, lambda s: {**s, "status": "running", "started_epoch": store.now_epoch()})
            store.event(run_id, "run_started", {"missions": len(state["missions"])})
        return state

    @r.post("/runs/{run_id}/missions")
    def add_mission(run_id: str, body: MissionBody, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        auth(x_api_key)
        _load(run_id)
        mission = _append_mission(run_id, body)
        return {"mission_id": mission["id"], "packet": mission["packet"], "checks": KINDS[body.kind]["checks"]}

    @r.post("/runs/{run_id}/start")
    def start(run_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        auth(x_api_key)
        return summary(_start(run_id))

    @r.post("/runs/{run_id}/missions/{mission_id}/retry")
    def retry_mission(run_id: str, mission_id: str, body: RetryBody | None = None,
                      x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        """Reopen a failed mission (fresh retry and reroute budget, optionally another agent) and the missions it
        blocked; the run goes back to running. Earlier attempts stay on record for the board."""
        auth(x_api_key)
        body = body or RetryBody()
        mid = mission_id.upper()
        before: dict = {}

        def reopen(m: dict) -> dict:
            if m["id"] == mid:
                notes = "\n\n".join(x for x in (m.get("notes", ""), body.notes.strip()) if x)
                return {**{k: v for k, v in m.items() if k not in ("desk", "pending", "bob")}, "status": "planned",
                        "agent": body.agent or m["agent"], "attempts": [], "finished_epoch": None, "notes": notes,
                        "earlier_attempts": m.get("earlier_attempts", []) + m.get("attempts", [])}
            if m["status"] == "blocked":
                return {**m, "status": "planned", "finished_epoch": None}
            return m

        def apply(s: dict) -> dict:
            target = next((m for m in s["missions"] if m["id"] == mid), None)
            if target is None:
                raise HTTPException(404, f"no mission {mission_id}")
            if target["status"] != "failed":  # checked inside the update: two retries cannot both reopen it
                raise HTTPException(409, f"{mid} is {target['status']}; only a failed mission can be retried")
            before.update(target)
            return {**s, "status": "running", "finished_epoch": None, "missions": [reopen(m) for m in s["missions"]]}

        _load(run_id)
        state = store.update(run_id, apply)
        if before.get("desk") == "held":  # the failed attempt still held the desk: give it back before reopening
            desk.release(run_id, before)
            state = store.update_mission(run_id, mid, desk=None)
        target = before
        write_packet(state, store.mission(state, target["id"]))
        store.event(run_id, "mission_reopened", {"mission": target["id"], "agent": body.agent or target["agent"],
                                                 "why": body.reason[:200]})
        return summary(state)

    @r.post("/plan")
    def plan_workday(body: PlanBody, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        """One call for the whole day: create the run, add every mission in order, start it. The plan is checked
        before anything is created, so a bad plan never leaves a half-made run."""
        auth(x_api_key)
        missions = body.mission_list()
        for i, mb in enumerate(missions):
            _check_mission(mb, {f"M{n + 1}" for n in range(i)})
        state = create_run(RunBody(request=body.request, title=body.title), x_api_key)
        for mb in missions:
            _append_mission(state["run_id"], mb)
        return {**summary(_start(state["run_id"])), "inbox": state["inbox"],
                "next": "The workday has started and runs by itself for many minutes. Reply to the user NOW with "
                        "the numbered plan (agent and why, what each waits for) and the board_url. Do not call "
                        "Get workday status in this turn; check status only when the user asks."}

    @r.get("/runs/{run_id}")
    def get_run(run_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        auth(x_api_key)
        return summary(_load(run_id if run_id != "latest" else _latest()))

    @r.get("/runs/{run_id}/missions/{mission_id}")
    def get_mission(run_id: str, mission_id: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")):
        auth(x_api_key)
        rid = run_id if run_id != "latest" else _latest()
        state = _load(rid)
        try:
            m = store.mission(state, mission_id.upper())
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        rdir = store.run_dir(rid)
        handoff = rdir / "handoffs" / f"{m['id']}.md"
        return {"mission": {k: v for k, v in m.items() if k != "attempts"}, "attempts": m.get("attempts", []),
                "packet_text": (rdir / m["packet"]).read_text(encoding="utf-8"),
                "handoff_text": handoff.read_text(encoding="utf-8") if handoff.exists() else ""}

    @r.get("/board/{run_id}", response_class=HTMLResponse)
    def board_page(run_id: str, k: str = ""):
        state = _load(run_id if run_id != "latest" else _latest())
        _view(state, k)
        return board.page(state["run_id"], k)

    @r.get("/board/{run_id}/data")
    def board_data(run_id: str, k: str = ""):
        state = _load(run_id)
        _view(state, k)
        return board.data(state, store.events(run_id, 60), _shared(state))

    @r.get("/files/{run_id}/{path:path}")
    def files(run_id: str, path: str, k: str = ""):
        state = _load(run_id)
        _view(state, k)
        if not path.startswith(VIEWABLE) or ".." in path or chr(0) in path:
            raise HTTPException(404)
        rdir = (store.base() / run_id).resolve()
        raw = store.base() / run_id / path
        try:
            target = raw.resolve()
        except (OSError, ValueError) as exc:
            raise HTTPException(404) from exc
        if raw.is_symlink() or not target.is_file() or rdir not in target.parents:
            raise HTTPException(404)
        return FileResponse(target, filename=target.name)

    return r


def _latest() -> str:
    runs = store.list_runs(limit=1)
    if not runs:
        raise HTTPException(404, "no workday runs yet")
    return runs[0]["run_id"]


def _load(run_id: str) -> dict:
    try:
        return store.load(run_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc


def _view(state: dict, key: str) -> None:
    if not secrets.compare_digest(key.encode(), state["view_key"].encode()):
        raise HTTPException(403, "invalid view key")
