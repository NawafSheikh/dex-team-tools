"""Workday engine: runs the mission graph the orchestrator planned.

A background thread ticks every few seconds. A mission starts when all its dependencies are verified.
When its worker finishes, the independent verifier decides done. On a failed verdict the engine applies
the orchestrator's on_fail policy (retry with the failed checks attached, then reroute to the other
agent with the handoff and the failure report). Everything is written to the run folder as it happens.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from . import bestof, desk, prompts, store, verifiers
from .kinds import other_agent

log = logging.getLogger("workday.engine")

TERMINAL = {"done", "failed", "blocked"}
ACTIVE_JOB = {"running", "retrying", "rerouted"}

_hooks: dict[str, Callable] = {}
_verifying: set[tuple[str, str]] = set()
_guard = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None


def install(start_agent: Callable[[str, str, Path, str], str], get_job: Callable[[str], dict]) -> None:
    if _hooks:
        return  # one engine loop per process
    _hooks["start"] = start_agent
    _hooks["job"] = get_job
    _recover()
    global _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="workday-engine", daemon=True)
    _thread.start()


def shutdown(timeout: float = 10.0) -> None:
    """Stop the background loop (used by tests so one test's loop never ticks the next test's run)."""
    global _thread
    _stop.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout)
    _thread = None


def _recover() -> None:
    """After a restart, missions caught mid-verify go back to polling; their lost job reads as finished,
    so the verifier runs again on whatever the worker left."""
    for run in store.list_runs(limit=50):
        if run["status"] != "running":
            continue
        for m in store.load(run["run_id"])["missions"]:
            if m["status"] == "verifying":
                store.update_mission(run["run_id"], m["id"], status="running")
                store.event(run["run_id"], "mission_recovered", {"mission": m["id"]})


def _loop() -> None:
    while not _stop.is_set():
        try:
            runs = store.list_runs(limit=50)
        except Exception:
            log.exception("workday run listing failed")
            runs = []
        for run in runs:
            if run["status"] != "running":
                continue
            try:
                tick(run["run_id"])
            except Exception:
                log.exception("workday tick failed for %s", run["run_id"])
        _stop.wait(4)


def tick(run_id: str) -> None:
    state = store.load(run_id)
    by_id = {m["id"]: m for m in state["missions"]}
    for m in state["missions"]:
        if m["status"] in TERMINAL and m.get("desk") == "held":
            desk.release(run_id, m)
        if m["status"] in TERMINAL or m["status"] == "verifying":
            continue
        deps = [by_id[d] for d in m.get("depends_on", []) if d in by_id]
        if any(d["status"] in ("failed", "blocked") for d in deps):
            _block(run_id, m["id"])
            continue
        try:
            if m.get("mode") == "best_of_both":
                if m["status"] == "planned" and all(d["status"] == "done" for d in deps):
                    bestof.start(run_id, m["id"], _hooks)
                elif m["status"] != "planned":
                    bestof.tick(run_id, m, _hooks)
            elif m["status"] == "planned" and all(d["status"] == "done" for d in deps):
                if m["kind"] in desk.DESK_KINDS and m.get("desk") != "held" and not desk.take(run_id, m):
                    continue  # another session is filming on the desk; try again next tick
                dispatch(run_id, m["id"], m["agent"], failure=None, status="running")
            elif m["status"] == "waiting_desk":
                # desk already "held": a restart came between taking the desk and recording the dispatch
                if m.get("desk") == "held" or desk.take(run_id, m):
                    p = m["pending"]
                    dispatch(run_id, m["id"], p["agent"], failure=p["failure"], status=p["status"])
                    store.update_mission(run_id, m["id"], pending=None)  # only once the attempt is recorded
            elif m["status"] in ACTIVE_JOB:
                _check_job(run_id, m)
        except Exception as exc:
            log.exception("mission %s failed in the engine", m["id"])
            store.update_mission(run_id, m["id"], status="failed", finished_epoch=store.now_epoch())
            store.event(run_id, "mission_engine_error", {"mission": m["id"], "error": str(exc)[:300]})
            fresh = store.mission(store.load(run_id), m["id"])
            if fresh.get("desk") == "held":  # never leave the shared desk locked by a mission that failed here
                desk.release(run_id, fresh)
    _maybe_finish(run_id)


def _block(run_id: str, mission_id: str) -> None:
    """Block a mission whose dependency failed, re-checked on fresh state: a retry may have reopened it since."""
    blocked: list[str] = []

    def apply(s: dict) -> dict:
        by_id = {x["id"]: x for x in s["missions"]}
        me = by_id[mission_id]
        deps = [by_id[d] for d in me.get("depends_on", []) if d in by_id]
        if me["status"] in TERMINAL or not any(d["status"] in ("failed", "blocked") for d in deps):
            return s
        blocked.append(mission_id)
        return {**s, "missions": [{**x, "status": "blocked", "finished_epoch": store.now_epoch()}
                                  if x["id"] == mission_id else x for x in s["missions"]]}

    store.update(run_id, apply)
    if blocked:
        store.event(run_id, "mission_blocked", {"mission": mission_id})


def dispatch(run_id: str, mission_id: str, agent: str, failure: dict | None, status: str) -> None:
    state = store.load(run_id)
    m = store.mission(state, mission_id)
    rdir = store.run_dir(run_id)
    work = rdir / "work" / mission_id
    work.mkdir(parents=True, exist_ok=True)
    (work / "HANDOFF.md").unlink(missing_ok=True)
    prompt = prompts.worker_prompt(state, m, agent, rdir, failure)
    (work / f"PROMPT-a{len(m['attempts']) + 1}.md").write_text(prompt, encoding="utf-8")
    job_id = _hooks["start"](agent, prompt, work, m["kind"])
    attempt = {"n": len(m["attempts"]) + 1, "agent": agent, "job_id": job_id,
               "started_epoch": store.now_epoch(), "finished_epoch": None, "verdict": None,
               "reason": failure["reason"] if failure else "first attempt"}
    store.update_mission(run_id, mission_id, status=status, attempts=m["attempts"] + [attempt],
                         started_epoch=m.get("started_epoch") or store.now_epoch())
    store.event(run_id, "mission_dispatched", {"mission": mission_id, "agent": agent, "attempt": attempt["n"],
                                               "job_id": job_id, "reason": attempt["reason"]})


def _check_job(run_id: str, m: dict) -> None:
    attempt = m["attempts"][-1]
    job = _hooks["job"](attempt["job_id"])
    if job.get("status") not in ("done", "error"):
        return
    key = (run_id, m["id"])
    with _guard:
        if key in _verifying:
            return
        _verifying.add(key)
    store.update_mission(run_id, m["id"], status="verifying")
    store.event(run_id, "worker_finished", {"mission": m["id"], "agent": attempt["agent"],
                                            "exit_code": job.get("exit_code")})
    threading.Thread(target=_verify, args=(run_id, m["id"], job), daemon=True).start()


def _verify(run_id: str, mission_id: str, job: dict) -> None:
    try:
        state = store.load(run_id)
        m = store.mission(state, mission_id)
        rdir = store.run_dir(run_id)
        worker_error = ""
        if job.get("status") == "error" or job.get("exit_code") not in (0, None):
            worker_error = (job.get("stderr") or job.get("stderr_tail") or job.get("result") or "")[-600:]
        verdict = verifiers.run(m["kind"], rdir, state, m)
        handoff = rdir / "work" / mission_id / "HANDOFF.md"
        verdict["checks"].append({"name": "handoff note written", "ok": handoff.exists(),
                                  "detail": f"work/{mission_id}/HANDOFF.md"})
        verdict["passed"] = verdict["passed"] and handoff.exists()
        n = len(m["attempts"])
        (rdir / "verify" / f"{mission_id}-a{n}.json").write_text(
            json.dumps({**verdict, "worker_error": worker_error}, indent=2), encoding="utf-8")
        attempts = [dict(a) for a in m["attempts"]]
        attempts[-1].update(finished_epoch=store.now_epoch(), worker_error=worker_error[-300:],
                            verdict={"passed": verdict["passed"],
                                     "failed": [c for c in verdict["checks"] if not c["ok"]],
                                     "total": len(verdict["checks"])})
        store.event(run_id, "mission_verified", {"mission": mission_id, "attempt": n,
                                                 "passed": verdict["passed"],
                                                 "failed": [c["name"] for c in verdict["checks"] if not c["ok"]]})
        if verdict["passed"]:
            shutil.copyfile(handoff, rdir / "handoffs" / f"{mission_id}.md")
            def apply(s: dict) -> dict:
                s["facts"] = {**s.get("facts", {}), **verdict.get("facts", {})}
                s["missions"] = [{**x, "status": "done", "attempts": attempts, "finished_epoch": store.now_epoch()}
                                 if x["id"] == mission_id else x for x in s["missions"]]
                return s
            store.update(run_id, apply)
            return
        store.update_mission(run_id, mission_id, attempts=attempts)
        _apply_policy(run_id, mission_id, attempts, verdict, worker_error)
    except Exception as exc:
        log.exception("verify failed")
        store.update_mission(run_id, mission_id, status="failed", finished_epoch=store.now_epoch())
        store.event(run_id, "verify_crashed", {"mission": mission_id, "error": str(exc)})
    finally:
        with _guard:
            _verifying.discard((run_id, mission_id))


LIMIT_MARKERS = ("usage limit", "rate limit", "quota", "try again at")


def hit_limit(attempt: dict) -> bool:
    """The agent's account is out of usage: retrying the same agent now cannot work."""
    return any(k in (attempt.get("worker_error") or "").lower() for k in LIMIT_MARKERS)


def next_step(on_fail: str, attempts: list[dict]) -> tuple[str, str] | None:
    """Return (action, agent) for the next attempt, or None when the policy is exhausted.

    An agent that hit its usage limit is never given this mission again: the mission goes straight to the other
    agent (when the policy allows any reroute), which then gets one retry of its own for an ordinary failure."""
    n, last = len(attempts), attempts[-1]["agent"]
    limited = {a["agent"] for a in attempts if hit_limit(a)}
    if limited:
        if on_fail == "retry" or len(limited) == 2:
            return None
        other = other_agent(next(iter(limited)))
        tries = sum(a["agent"] == other for a in attempts)
        if tries == 0:
            return ("reroute", other)
        return ("retry", other) if tries == 1 else None
    if on_fail == "retry_then_reroute":
        return {1: ("retry", last), 2: ("reroute", other_agent(last))}.get(n)
    if on_fail == "reroute":
        return ("reroute", other_agent(last)) if n == 1 else None
    if on_fail == "retry":
        return ("retry", last) if n == 1 else None
    return None


def _apply_policy(run_id: str, mission_id: str, attempts: list[dict], verdict: dict, worker_error: str) -> None:
    m = store.mission(store.load(run_id), mission_id)
    step = next_step(m["on_fail"], attempts)
    if step is None:
        store.update_mission(run_id, mission_id, status="failed", finished_epoch=store.now_epoch())
        store.event(run_id, "mission_failed", {"mission": mission_id})
        return
    action, agent = step
    failed = [c["name"] for c in verdict["checks"] if not c["ok"]]
    reason = (f"{action}: attempt {len(attempts)} by {attempts[-1]['agent']} failed "
              f"{', '.join(failed) or 'the worker run'}")
    failure = {"attempt": len(attempts) + 1, "agent": attempts[-1]["agent"], "checks": verdict["checks"],
               "worker_error": worker_error, "reason": reason}
    store.event(run_id, f"mission_{action}", {"mission": mission_id, "to": agent, "failed": failed})
    if m["kind"] in desk.DESK_KINDS and m.get("desk") != "held" and not desk.take(run_id, m):
        # The desk went to another session between attempts: queue the step, tick dispatches it with the lock.
        pending = {"agent": agent, "failure": failure, "status": "retrying" if action == "retry" else "rerouted"}
        store.update_mission(run_id, mission_id, status="waiting_desk", pending=pending)
        return
    dispatch(run_id, mission_id, agent, failure, status="retrying" if action == "retry" else "rerouted")


def _maybe_finish(run_id: str) -> None:
    finished: list[bool] = []

    def apply(s: dict) -> dict:  # decided on fresh state: a retry may have reopened a mission since the last read
        if s["status"] != "running" or not s["missions"] or any(m["status"] not in TERMINAL for m in s["missions"]):
            return s
        ok = all(m["status"] == "done" for m in s["missions"])
        finished.append(ok)
        return {**s, "status": "done" if ok else "finished_with_failures", "finished_epoch": store.now_epoch()}

    store.update(run_id, apply)
    if finished:
        store.event(run_id, "run_finished", {"all_verified": finished[0]})
