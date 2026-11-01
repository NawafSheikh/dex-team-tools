"""Best of both: Claude and Codex do the same mission independently, the verifier checks both, a blind
judge picks the better result, and the winner may merge in the other's strengths.

Each candidate works in its own copy of the run's shared folder (cand/<mission>/r<round>-<agent>/), so the
two never touch each other's files. Only the final, verified result is promoted into the run's shared folder.
A merge that fails verification is dropped and the verified winner is promoted instead, so a mission never
ends worse than its best candidate. Missions that change the shared Power Platform environment are excluded
(two agents would edit the same tables and app).
"""
from __future__ import annotations

import json
import logging
import random
import shutil
import threading
from pathlib import Path
from typing import Callable

from . import bestof_prompts, prompts, store, verifiers
from .verifiers.common import sha
from .kinds import KINDS

log = logging.getLogger("workday.bestof")

AGENTS = ("claude", "codex")
FILE_KINDS = {"excel", "deck", "notes", "guide"}
JUDGE_AGENT = "claude"
TERMINAL = {"done", "failed", "blocked"}
_busy: set[tuple[str, str]] = set()
_guard = threading.Lock()


# ---------------------------------------------------------------- folders

def _cand_dir(run_id: str, mission_id: str, name: str) -> Path:
    return store.run_dir(run_id) / "cand" / mission_id / name


def _prepare(run_id: str, cdir: Path, seed: Path | None = None) -> None:
    """A candidate folder: its own shared/ (a copy of the run's, or of `seed`), the run inbox, its own work/."""
    rdir = store.run_dir(run_id)
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir(parents=True)
    shutil.copytree((seed or rdir) / "shared", cdir / "shared")
    shutil.copytree(rdir / "inbox", cdir / "inbox")
    if seed is not None and (seed / "work").exists():
        shutil.copytree(seed / "work", cdir / "work")
    (cdir / "work").mkdir(exist_ok=True)
    (cdir / "work" / "HANDOFF.md").unlink(missing_ok=True)


def _where(cdir: Path, note: str) -> dict:
    return {"shared": cdir / "shared", "inbox": cdir / "inbox", "work": cdir / "work", "note": note}


def output_hashes(kind: str, cdir: Path) -> dict:
    """Hashes of a result's deliverables, taken when it is verified, so a later change is caught."""
    files: list[Path] = []
    for out in KINDS[kind]["outputs"]:
        p = cdir / out
        files += sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else ([p] if p.exists() else [])
    return {f.relative_to(cdir).as_posix(): sha(f.read_bytes()) for f in files}


def _readonly_copy(src: Path, dst: Path) -> Path:
    """Judge and merge workers get copies of the other results, never the verified originals."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src / "shared", dst)
    return dst


# ---------------------------------------------------------------- state helpers

def _set(run_id: str, mission_id: str, fn: Callable[[dict], dict]) -> None:
    """Apply fn to the mission (a copy) inside one atomic state update."""
    def apply(s: dict) -> dict:
        s["missions"] = [fn(dict(m)) if m["id"] == mission_id else m for m in s["missions"]]
        return s
    store.update(run_id, apply)


def _attempt(m: dict, agent: str, role: str, job_id: str, reason: str) -> dict:
    return {"n": len(m.get("attempts", [])) + 1, "agent": agent, "role": role, "job_id": job_id,
            "started_epoch": store.now_epoch(), "finished_epoch": None, "verdict": None, "reason": reason}


def _finish_attempt(m: dict, job_id: str, **fields) -> dict:
    m["attempts"] = [{**a, "finished_epoch": store.now_epoch(), **fields} if a["job_id"] == job_id else a
                     for a in m["attempts"]]
    return m


# ---------------------------------------------------------------- phases

def start(run_id: str, mission_id: str, hooks: dict, failures: dict | None = None) -> None:
    """Dispatch both candidates (round 1, or round 2 with each one's failed checks attached)."""
    state = store.load(run_id)
    m = store.mission(state, mission_id)
    rdir = store.run_dir(run_id)
    rnd = (m.get("bob") or {}).get("round", 0) + 1
    _set(run_id, mission_id, lambda x: {
        **x, "status": "running" if rnd == 1 else "retrying",
        "started_epoch": x.get("started_epoch") or store.now_epoch(),
        "bob": {"round": rnd, "phase": "starting", "candidates": {}, "judge": None, "merge": None, "final": None}})
    for agent in AGENTS:
        cdir = _cand_dir(run_id, mission_id, f"r{rnd}-{agent}")
        seed = _cand_dir(run_id, mission_id, f"r{rnd - 1}-{agent}") if failures else None
        _prepare(run_id, cdir, seed=seed if seed and seed.exists() else None)
        failure = (failures or {}).get(agent)
        prompt = prompts.worker_prompt(state, m, agent, rdir, failure, _where(cdir, bestof_prompts.CANDIDATE_NOTE))
        (cdir / "work" / "PROMPT.md").write_text(prompt, encoding="utf-8")
        job_id = hooks["start"](agent, prompt, cdir / "work", m["kind"])
        reason = f"best of both, round {rnd}: {agent}'s candidate"

        def record(x: dict, agent=agent, job_id=job_id, cdir=cdir, reason=reason) -> dict:
            # recorded the moment the job starts, so no job runs untracked if the next start fails
            x["attempts"] = x["attempts"] + [_attempt(x, agent, "candidate", job_id, reason)]
            x["bob"] = {**x["bob"], "candidates": {**x["bob"]["candidates"], agent: {
                "job_id": job_id, "dir": str(cdir.relative_to(rdir)), "verdict": None}}}
            return x
        _set(run_id, mission_id, record)
        store.event(run_id, "mission_dispatched", {"mission": mission_id, "agent": agent, "job_id": job_id,
                                                   "reason": reason, "mode": "best_of_both"})
    _set(run_id, mission_id, lambda x: {**x, "bob": {**x["bob"], "phase": "candidates"}})


def tick(run_id: str, m: dict, hooks: dict) -> None:
    bob = m.get("bob") or {}
    phase = bob.get("phase")
    if phase == "candidates":
        jobs = [c["job_id"] for c in bob["candidates"].values()]
    elif phase == "judging":
        jobs = [bob["judge"]["job_id"]]
    elif phase == "merging":
        jobs = [bob["merge"]["job_id"]]
    else:
        return
    if not all(hooks["job"](j).get("status") in ("done", "error") for j in jobs):
        return
    key = (run_id, m["id"])
    with _guard:
        if key in _busy:
            return
        _busy.add(key)
    step = {"candidates": _after_candidates, "judging": _after_judge, "merging": _after_merge}[phase]
    token = _token(m)
    threading.Thread(target=_run_step, args=(step, run_id, m["id"], hooks, token), daemon=True).start()


def _token(m: dict) -> tuple:
    """Identifies the exact step a tick saw: phase, round and the job ids it waited for."""
    bob = m.get("bob") or {}
    jobs = tuple(sorted(c["job_id"] for c in bob.get("candidates", {}).values()))
    return (m["status"] in TERMINAL, bob.get("phase"), bob.get("round"), jobs,
            (bob.get("judge") or {}).get("job_id"), (bob.get("merge") or {}).get("job_id"))


def _run_step(step: Callable, run_id: str, mission_id: str, hooks: dict, token: tuple) -> None:
    try:
        # the tick may have read state from before the previous step finished: act only if nothing moved on
        fresh = store.mission(store.load(run_id), mission_id)
        if _token(fresh) != token or token[0]:
            return
        step(run_id, mission_id, hooks)
    except Exception as exc:
        log.exception("best-of-both step failed")
        store.update_mission(run_id, mission_id, status="failed", finished_epoch=store.now_epoch())
        store.event(run_id, "mission_engine_error", {"mission": mission_id, "error": str(exc)[:300]})
    finally:
        with _guard:
            _busy.discard((run_id, mission_id))


def _verify(run_id: str, m: dict, cdir: Path, label: str, job: dict) -> dict:
    state = store.load(run_id)
    verdict = verifiers.run(m["kind"], cdir, state, m)
    handoff = cdir / "work" / "HANDOFF.md"
    verdict["checks"].append({"name": "handoff note written", "ok": handoff.exists(), "detail": "HANDOFF.md"})
    verdict["passed"] = verdict["passed"] and handoff.exists()
    worker_error = ""
    if job.get("status") == "error" or job.get("exit_code") not in (0, None):
        worker_error = (job.get("stderr") or job.get("stderr_tail") or job.get("result") or "")[-600:]
    (store.run_dir(run_id) / "verify" / f"{m['id']}-{label}.json").write_text(
        json.dumps({**verdict, "worker_error": worker_error}, indent=2), encoding="utf-8")
    failed = [c for c in verdict["checks"] if not c["ok"]]
    verdict = {**verdict, "hashes": output_hashes(m["kind"], cdir)}
    store.event(run_id, "mission_verified", {"mission": m["id"], "agent": label.split("-")[-1],
                                             "passed": verdict["passed"], "failed": [c["name"] for c in failed]})
    return {**verdict, "failed": failed, "worker_error": worker_error}


def _after_candidates(run_id: str, mission_id: str, hooks: dict) -> None:
    m = store.mission(store.load(run_id), mission_id)
    bob, rdir = m["bob"], store.run_dir(run_id)
    store.update_mission(run_id, mission_id, status="verifying")
    results = {}
    for agent, c in bob["candidates"].items():
        job = hooks["job"](c["job_id"])
        store.event(run_id, "worker_finished", {"mission": mission_id, "agent": agent,
                                                "exit_code": job.get("exit_code")})
        results[agent] = _verify(run_id, m, rdir / c["dir"], f"r{bob['round']}-{agent}", job)

    def record(x: dict) -> dict:
        for agent, v in results.items():
            short = {"passed": v["passed"], "failed": v["failed"], "total": len(v["checks"]), "hashes": v["hashes"]}
            x["bob"]["candidates"][agent]["verdict"] = short
            x = _finish_attempt(x, x["bob"]["candidates"][agent]["job_id"], verdict=short,
                                worker_error=v["worker_error"][-300:])
        return x
    _set(run_id, mission_id, record)

    passed = [a for a in AGENTS if results[a]["passed"]]
    if len(passed) == 2:
        _start_judge(run_id, mission_id, hooks)
    elif len(passed) == 1:
        winner = passed[0]
        store.event(run_id, "best_of_both_pick", {"mission": mission_id, "agent": winner,
                                                  "why": f"only {winner}'s result passed the verifier"})
        _promote(run_id, mission_id, rdir / bob["candidates"][winner]["dir"], results[winner], winner,
                 f"Only {winner}'s result passed the verifier.", results[winner]["hashes"])
    elif bob["round"] == 1:
        failures = {a: {"attempt": 2, "agent": a, "checks": results[a]["checks"],
                        "worker_error": results[a]["worker_error"], "reason": "both candidates failed"}
                    for a in AGENTS}
        store.event(run_id, "mission_retry", {"mission": mission_id, "to": "both",
                                              "failed": sorted({c["name"] for a in AGENTS for c in results[a]["failed"]})})
        start(run_id, mission_id, hooks, failures)
    else:
        store.update_mission(run_id, mission_id, status="failed", finished_epoch=store.now_epoch())
        store.event(run_id, "mission_failed", {"mission": mission_id})


def _start_judge(run_id: str, mission_id: str, hooks: dict) -> None:
    m = store.mission(store.load(run_id), mission_id)
    rdir = store.run_dir(run_id)
    order = list(AGENTS)
    random.shuffle(order)  # blind: the judge sees A and B in a random order, never the agent names
    blind = {"A": order[0], "B": order[1]}
    work = _cand_dir(run_id, mission_id, f"r{m['bob']['round']}-judge")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    cands = m["bob"]["candidates"]
    copies = {k: _readonly_copy(rdir / cands[a]["dir"], work / k / "shared").parent for k, a in blind.items()}
    prompt = bestof_prompts.judge_prompt(m, rdir / m["packet"], copies["A"], copies["B"], work)
    (work / "PROMPT.md").write_text(prompt, encoding="utf-8")
    job_id = hooks["start"](JUDGE_AGENT, prompt, work, "judge")
    reason = "both passed the verifier: blind judge compares them"

    def apply(x: dict) -> dict:
        x["attempts"] = x["attempts"] + [_attempt(x, "judge", "judge", job_id, reason)]
        x["status"] = "judging"
        x["bob"] = {**x["bob"], "phase": "judging",
                    "judge": {"job_id": job_id, "blind": blind, "dir": str(work.relative_to(rdir))}}
        return x
    _set(run_id, mission_id, apply)
    store.event(run_id, "best_of_both_judging", {"mission": mission_id, "agent": "judge"})


def read_verdict(path: Path, blind: dict, default: str) -> dict:
    """The judge's verdict mapped back to agent names; falls back to the orchestrator's agent if unreadable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        letter = str(raw.get("winner", "")).strip().upper()[:1]
        winner = blind[letter]
        raw_take = raw.get("take_from_loser")
        take = [str(t) for t in raw_take if str(t).strip()][:6] if isinstance(raw_take, list) else []
        scores = {blind[k]: v for k, v in (raw.get("scores") or {}).items() if k in blind}
        return {"winner": winner, "reasons": str(raw.get("reasons", ""))[:600], "take": take,
                "merge": bool(raw.get("merge")) and bool(take), "scores": scores, "valid": True}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"winner": default, "reasons": "The judge gave no readable verdict, so the orchestrator's first "
                "choice of agent stands.", "take": [], "merge": False, "scores": {}, "valid": False}


def _after_judge(run_id: str, mission_id: str, hooks: dict) -> None:
    m = store.mission(store.load(run_id), mission_id)
    bob, rdir = m["bob"], store.run_dir(run_id)
    v = read_verdict(rdir / bob["judge"]["dir"] / "judge.json", bob["judge"]["blind"], m["agent"])
    winner = v["winner"]
    loser = next(a for a in AGENTS if a != winner)
    store.event(run_id, "best_of_both_pick", {"mission": mission_id, "agent": winner, "why": v["reasons"],
                                              "take": v["take"]})

    def record(x: dict) -> dict:
        x = _finish_attempt(x, x["bob"]["judge"]["job_id"], verdict={"passed": True, "failed": [], "total": 0},
                            reason=f"judge picked {winner}: {v['reasons']}")
        x["bob"] = {**x["bob"], "judge": {**x["bob"]["judge"], **{k: v[k] for k in
                                                                   ("winner", "reasons", "take", "merge", "scores")}}}
        return x
    _set(run_id, mission_id, record)
    win_dir = rdir / bob["candidates"][winner]["dir"]
    if not v["merge"]:
        _promote_verified(run_id, mission_id, winner, f"Judge picked {winner}: {v['reasons']}")
        return
    cdir = _cand_dir(run_id, mission_id, f"r{bob['round']}-merge")
    _prepare(run_id, cdir, seed=win_dir)
    other = _readonly_copy(rdir / bob["candidates"][loser]["dir"], cdir / "other" / "shared").parent
    state = store.load(run_id)
    note = bestof_prompts.merge_note(other, v["take"])
    prompt = prompts.worker_prompt(state, m, winner, rdir, None, _where(cdir, note))
    (cdir / "work" / "PROMPT-merge.md").write_text(prompt, encoding="utf-8")
    job_id = hooks["start"](winner, prompt, cdir / "work", m["kind"])
    reason = f"{winner} merges the best of {loser}'s result"

    def apply(x: dict) -> dict:
        x["attempts"] = x["attempts"] + [_attempt(x, winner, "merge", job_id, reason)]
        x["status"] = "merging"
        x["bob"] = {**x["bob"], "phase": "merging",
                    "merge": {"job_id": job_id, "agent": winner, "dir": str(cdir.relative_to(rdir))}}
        return x
    _set(run_id, mission_id, apply)
    store.event(run_id, "best_of_both_merging", {"mission": mission_id, "agent": winner, "take": v["take"]})


def _after_merge(run_id: str, mission_id: str, hooks: dict) -> None:
    m = store.mission(store.load(run_id), mission_id)
    bob, rdir = m["bob"], store.run_dir(run_id)
    winner = bob["judge"]["winner"]
    store.update_mission(run_id, mission_id, status="verifying")
    job = hooks["job"](bob["merge"]["job_id"])
    v = _verify(run_id, m, rdir / bob["merge"]["dir"], f"r{bob['round']}-merge-{winner}", job)
    short = {"passed": v["passed"], "failed": v["failed"], "total": len(v["checks"])}
    _set(run_id, mission_id, lambda x: _finish_attempt(x, bob["merge"]["job_id"], verdict=short))
    if v["passed"]:
        _promote(run_id, mission_id, rdir / bob["merge"]["dir"], v, "merge",
                 f"Judge picked {winner}, then {winner} merged in the other's strengths: "
                 + "; ".join(bob["judge"]["take"]), v["hashes"])
        return
    store.event(run_id, "best_of_both_merge_rejected", {"mission": mission_id, "agent": winner,
                                                        "failed": [c["name"] for c in v["failed"]]})
    _promote_verified(run_id, mission_id, winner,
                      f"Judge picked {winner}; the merge failed the verifier, so {winner}'s verified result stands.")


def _promote_verified(run_id: str, mission_id: str, agent: str, why: str) -> None:
    """Promote a candidate verified earlier, only if its files are unchanged and it still passes; otherwise
    fall back to the other passed candidate, otherwise fail the mission. Nothing unverified is ever promoted."""
    m = store.mission(store.load(run_id), mission_id)
    rdir = store.run_dir(run_id)
    for a in (agent, *[x for x in AGENTS if x != agent]):
        c = m["bob"]["candidates"][a]
        cdir = rdir / c["dir"]
        verdict = c.get("verdict") or {}
        if not verdict.get("passed") or output_hashes(m["kind"], cdir) != verdict.get("hashes"):
            continue
        fresh = verifiers.run(m["kind"], cdir, store.load(run_id), m)
        if fresh["passed"]:
            note = why if a == agent else f"{why} But {agent}'s files changed after verification, so {a}'s stands."
            _promote(run_id, mission_id, cdir, fresh, a, note, verdict["hashes"])
            return
    store.update_mission(run_id, mission_id, status="failed", finished_epoch=store.now_epoch())
    store.event(run_id, "mission_failed", {"mission": mission_id, "why": "no verified result was left unchanged"})


def _promote(run_id: str, mission_id: str, cdir: Path, verdict: dict, final: str, why: str,
             hashes: dict) -> None:
    """Copy the chosen, verified result's outputs into the run, then mark the mission done with its facts."""
    m = store.mission(store.load(run_id), mission_id)
    rdir = store.run_dir(run_id)
    if not verdict.get("passed") or output_hashes(m["kind"], cdir) != hashes:
        raise RuntimeError(f"refusing to promote {cdir.name}: not verified as it is now")
    for out in KINDS[m["kind"]]["outputs"]:
        src, dst = cdir / out, rdir / out
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    work = rdir / "work" / mission_id
    work.mkdir(parents=True, exist_ok=True)
    handoff = (cdir / "work" / "HANDOFF.md").read_text(encoding="utf-8")
    note = f"\n\n## Best of both\n\n{why}\n"
    (work / "HANDOFF.md").write_text(handoff + note, encoding="utf-8")
    shutil.copyfile(work / "HANDOFF.md", rdir / "handoffs" / f"{mission_id}.md")

    def apply(s: dict) -> dict:
        s["facts"] = {**s.get("facts", {}), **verdict.get("facts", {})}
        s["missions"] = [{**x, "status": "done", "finished_epoch": store.now_epoch(),
                          "bob": {**x["bob"], "phase": "final", "final": final, "why": why}}
                         if x["id"] == mission_id else x for x in s["missions"]]
        return s
    store.update(run_id, apply)
    store.event(run_id, "best_of_both_final", {"mission": mission_id, "agent": final, "why": why})
