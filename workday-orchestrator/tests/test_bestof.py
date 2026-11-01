"""Best-of-both missions: both agents work, the verifier checks both, a blind judge picks, the winner may merge."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "fixtures"))
sys.path.insert(0, str(HERE))

import make_fixtures  # noqa: E402
from test_workday import _write_analysis  # noqa: E402
from workday import bestof, prompts, store  # noqa: E402
from workday.verifiers import excel  # noqa: E402


class FakeAgents:
    """Stands in for Claude and Codex: each 'job' writes its result at once and reports done."""

    def __init__(self, good: dict, judge: dict | None = None, merge_good: bool = True):
        self.good, self.judge, self.merge_good = good, judge, merge_good
        self.calls: list[tuple[str, str]] = []
        self.pending_judge: dict[str, Path] = {}

    def start(self, agent: str, prompt: str, cwd: Path, kind: str) -> str:
        role = "judge" if kind == "judge" else ("merge" if "Merge step" in prompt else "candidate")
        self.calls.append((agent, role))
        if role == "judge":  # the blind A/B mapping is saved after start, so answer when polled
            self.pending_judge[f"job-{len(self.calls)}"] = cwd
        else:
            cand = cwd.parent
            ok = self.merge_good if role == "merge" else self.good[agent]
            t = excel.truth(cand / "inbox" / "loans_export.xlsx")
            _write_analysis(cand, t if ok else {**t, "Clean loans": t["Clean loans"] + 3})
            (cwd / "HANDOFF.md").write_text(f"# Handoff\n\n{agent} {role}\n")
            (cwd / f"scratch-{len(self.calls)}.txt").write_text("working notes")
        return f"job-{len(self.calls)}"

    def job(self, job_id: str) -> dict:
        cwd = self.pending_judge.pop(job_id, None)
        if cwd is not None:
            state = json.loads((cwd.parents[2] / "STATE.json").read_text())
            blind = state["missions"][0]["bob"]["judge"]["blind"]
            letter = next(k for k, a in blind.items() if a == self.judge["winner"])
            (cwd / "judge.json").write_text(json.dumps({**self.judge, "winner": letter}))
        return {"status": "done", "exit_code": 0}

    def hooks(self) -> dict:
        return {"start": self.start, "job": self.job}


def _run(tmp_path: Path) -> tuple[str, str]:
    store.configure(tmp_path)
    state = store.new_run("Clean the loans export", "Test day")
    make_fixtures.main(str(store.run_dir(state["run_id"]) / "inbox"))
    mission = {"id": "M1", "kind": "excel", "title": "Clean and analyse loans", "goal": "clean it",
               "agent": "codex", "why_agent": "data work", "depends_on": [], "notes": "",
               "on_fail": "retry_then_reroute", "mode": "best_of_both", "status": "planned", "attempts": [],
               "started_epoch": None, "finished_epoch": None}
    mission["packet"] = prompts.write_packet(state, mission)
    store.update(state["run_id"], lambda s: {**s, "status": "running", "missions": [mission]})
    return state["run_id"], "M1"


def _drive(run_id: str, mid: str, hooks: dict) -> dict:
    bestof.start(run_id, mid, hooks)
    for _ in range(40):
        m = store.mission(store.load(run_id), mid)
        if m["status"] in ("done", "failed"):
            return m
        bestof.tick(run_id, m, hooks)
        deadline = time.time() + 30
        while bestof._busy and time.time() < deadline:
            time.sleep(0.05)
    raise AssertionError("mission did not finish")


def test_both_pass_judge_picks_without_merge(tmp_path: Path):
    run_id, mid = _run(tmp_path)
    fake = FakeAgents({"claude": True, "codex": True},
                      judge={"winner": "claude", "reasons": "clearer summary", "take_from_loser": [], "merge": False})
    m = _drive(run_id, mid, fake.hooks())
    assert m["status"] == "done" and m["bob"]["final"] == "claude"
    assert [r for _, r in fake.calls] == ["candidate", "candidate", "judge"]
    rdir = store.run_dir(run_id)
    assert (rdir / "shared" / "Loans_Analysis.xlsx").exists()
    assert "Best of both" in (rdir / "handoffs" / "M1.md").read_text()
    assert store.load(run_id)["facts"]["clean_loans"] > 0


def test_only_one_passes_takes_it_without_judge(tmp_path: Path):
    run_id, mid = _run(tmp_path)
    fake = FakeAgents({"claude": True, "codex": False})
    m = _drive(run_id, mid, fake.hooks())
    assert m["status"] == "done" and m["bob"]["final"] == "claude"
    assert "judge" not in [r for _, r in fake.calls]
    assert m["bob"]["candidates"]["codex"]["verdict"]["passed"] is False


def test_failed_merge_falls_back_to_verified_winner(tmp_path: Path):
    run_id, mid = _run(tmp_path)
    fake = FakeAgents({"claude": True, "codex": True}, merge_good=False,
                      judge={"winner": "codex", "reasons": "right numbers", "take_from_loser": ["chart colours"],
                             "merge": True})
    m = _drive(run_id, mid, fake.hooks())
    assert [c for c in fake.calls][-1] == ("codex", "merge")
    assert m["status"] == "done" and m["bob"]["final"] == "codex"
    t = excel.truth(store.run_dir(run_id) / "inbox" / "loans_export.xlsx")
    assert store.load(run_id)["facts"]["clean_loans"] == t["Clean loans"]  # the merge's wrong numbers never landed


def test_good_merge_is_promoted(tmp_path: Path):
    run_id, mid = _run(tmp_path)
    fake = FakeAgents({"claude": True, "codex": True},
                      judge={"winner": "claude", "reasons": "design", "take_from_loser": ["recount table"],
                             "merge": True})
    m = _drive(run_id, mid, fake.hooks())
    assert m["status"] == "done" and m["bob"]["final"] == "merge"


def test_both_fail_twice_fails_the_mission(tmp_path: Path):
    run_id, mid = _run(tmp_path)
    fake = FakeAgents({"claude": False, "codex": False})
    m = _drive(run_id, mid, fake.hooks())
    assert m["status"] == "failed" and m["bob"]["round"] == 2
    assert [r for _, r in fake.calls] == ["candidate"] * 4


def test_read_verdict_maps_blind_letters_and_falls_back(tmp_path: Path):
    path = tmp_path / "judge.json"
    path.write_text(json.dumps({"winner": "B", "reasons": "r", "take_from_loser": ["x"], "merge": True,
                                "scores": {"A": {"design": 6}, "B": {"design": 9}}}))
    v = bestof.read_verdict(path, {"A": "claude", "B": "codex"}, "claude")
    assert v["winner"] == "codex" and v["merge"] and v["scores"]["codex"]["design"] == 9
    path.write_text("not json")
    assert bestof.read_verdict(path, {"A": "claude", "B": "codex"}, "codex")["winner"] == "codex"


def test_route_rejects_best_of_both_for_power_platform(tmp_path: Path):
    from test_workday import _client
    c = _client(tmp_path)
    rid = c.post("/workday/runs", json={"request": "Do the day", "title": "T"}).json()["run_id"]
    body = {"kind": "pp_app", "title": "Canvas app", "goal": "build it", "agent": "claude",
            "why_agent": "design", "mode": "best_of_both"}
    assert c.post(f"/workday/runs/{rid}/missions", json=body).status_code == 400
    ok = c.post(f"/workday/runs/{rid}/missions", json={**body, "kind": "deck"})
    assert ok.status_code == 200
    assert "best of both" in (tmp_path / "workday" / rid / ok.json()["packet"]).read_text()


def test_stale_tick_does_not_rerun_a_step(tmp_path: Path):
    """A tick that read state before the previous step finished must not start a second judge."""
    run_id, mid = _run(tmp_path)
    fake = FakeAgents({"claude": True, "codex": True},
                      judge={"winner": "claude", "reasons": "r", "take_from_loser": [], "merge": False})
    hooks = fake.hooks()
    bestof.start(run_id, mid, hooks)
    stale = store.mission(store.load(run_id), mid)
    bestof._run_step(bestof._after_candidates, run_id, mid, hooks, bestof._token(stale))
    assert store.mission(store.load(run_id), mid)["status"] == "judging"
    bestof._run_step(bestof._after_candidates, run_id, mid, hooks, bestof._token(stale))
    assert [r for _, r in fake.calls].count("judge") == 1


def test_changed_files_are_never_promoted(tmp_path: Path):
    """If a verified result changes afterwards, the other verified result is promoted instead."""
    run_id, mid = _run(tmp_path)
    fake = FakeAgents({"claude": True, "codex": True},
                      judge={"winner": "claude", "reasons": "r", "take_from_loser": [], "merge": False})
    hooks = fake.hooks()
    bestof.start(run_id, mid, hooks)
    m = store.mission(store.load(run_id), mid)
    bestof._run_step(bestof._after_candidates, run_id, mid, hooks, bestof._token(m))
    rdir = store.run_dir(run_id)
    (rdir / "cand" / mid / "r1-claude" / "shared" / "Loans_Analysis.xlsx").write_bytes(b"garbage")
    m = store.mission(store.load(run_id), mid)
    hooks["job"](m["bob"]["judge"]["job_id"])
    bestof._run_step(bestof._after_judge, run_id, mid, hooks, bestof._token(m))
    m = store.mission(store.load(run_id), mid)
    assert m["status"] == "done" and m["bob"]["final"] == "codex"
    assert (rdir / "shared" / "Loans_Analysis.xlsx").read_bytes() != b"garbage"


def test_string_take_from_loser_is_ignored(tmp_path: Path):
    path = tmp_path / "judge.json"
    path.write_text(json.dumps({"winner": "A", "take_from_loser": "better chart", "merge": True}))
    v = bestof.read_verdict(path, {"A": "claude", "B": "codex"}, "claude")
    assert v["take"] == [] and v["merge"] is False


def test_round_two_starts_from_round_one_work(tmp_path: Path):
    run_id, mid = _run(tmp_path)
    fake = FakeAgents({"claude": False, "codex": False})
    _drive(run_id, mid, fake.hooks())
    r2 = store.run_dir(run_id) / "cand" / mid / "r2-claude" / "work"
    assert (r2 / "PROMPT.md").exists() and "attempt 2" in (r2 / "PROMPT.md").read_text()
    r1_notes = {f.name for f in (r2.parent.parent / "r1-claude" / "work").glob("scratch-*")}
    assert r1_notes and r1_notes <= {f.name for f in r2.glob("scratch-*")}


def test_desk_mission_waits_for_the_desk_and_gives_it_back(tmp_path: Path, monkeypatch):
    from workday import desk, engine
    store.configure(tmp_path)
    state = store.new_run("Build the app", "Desk day")
    rid = state["run_id"]
    m = {"id": "M1", "kind": "pp_app", "title": "Canvas app", "goal": "build it", "agent": "claude",
         "why_agent": "design", "depends_on": [], "notes": "", "on_fail": "retry", "status": "planned",
         "attempts": [], "started_epoch": None, "finished_epoch": None}
    m["packet"] = prompts.write_packet(state, m)
    store.update(rid, lambda s: {**s, "status": "running", "missions": [m]})
    free = {"now": False}
    calls = []
    monkeypatch.setattr(desk, "_helper", lambda *a: (calls.append(a[0]) or (0 if free["now"] else 1), "busy: another session"))
    started = []
    monkeypatch.setitem(engine._hooks, "start", lambda *a: started.append(a) or "job-1")
    monkeypatch.setitem(engine._hooks, "job", lambda j: {"status": "running"})
    engine.tick(rid)
    engine.tick(rid)
    assert not started and store.mission(store.load(rid), "M1")["desk"] == "waiting"
    assert [e["event"] for e in store.events(rid)].count("desk_waiting") == 1  # announced once, not every tick
    free["now"] = True
    engine.tick(rid)
    assert len(started) == 1 and store.mission(store.load(rid), "M1")["desk"] == "held"
    store.update_mission(rid, "M1", status="done")
    engine.tick(rid)
    assert store.mission(store.load(rid), "M1")["desk"] == "released" and calls[-1] == "release"
