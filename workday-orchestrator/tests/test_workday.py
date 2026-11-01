"""Tests for the workday engine policy and the document/Excel verifiers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from docx import Document
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "fixtures"))

import make_fixtures  # noqa: E402
from workday import engine, store  # noqa: E402
from workday.verifiers import docs, excel  # noqa: E402


@pytest.fixture()
def rdir(tmp_path: Path) -> Path:
    for sub in ("inbox", "shared", "work", "handoffs", "verify"):
        (tmp_path / sub).mkdir()
    make_fixtures.main(str(tmp_path / "inbox"))
    return tmp_path


def test_policy_retry_then_reroute():
    a = [{"agent": "codex"}]
    assert engine.next_step("retry_then_reroute", a) == ("retry", "codex")
    assert engine.next_step("retry_then_reroute", a * 2) == ("reroute", "claude")
    assert engine.next_step("retry_then_reroute", a * 3) is None
    assert engine.next_step("reroute", [{"agent": "claude"}]) == ("reroute", "codex")
    assert engine.next_step("retry", a * 2) is None


def test_excel_truth_reconciles(rdir: Path):
    t = excel.truth(rdir / "inbox" / "loans_export.xlsx")
    assert t["Raw rows"] == t["Clean loans"] + t["Duplicates removed"] + t["Blank rows removed"]
    assert t["Duplicates removed"] > 0 and t["Blank rows removed"] > 0
    assert 0 < t["Overdue rate"] < 1


def _write_analysis(rdir: Path, values: dict, chart: bool = True) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Clean"
    top = wb.create_sheet("Top items")
    top.append(["Item", "Loans"])
    top.append([values["Top item"], 10])
    top.append(["Other", 5])
    if chart:
        c = BarChart()
        c.add_data(Reference(top, min_col=2, min_row=1, max_row=3), titles_from_data=True)
        top.add_chart(c, "D2")
    s = wb.create_sheet("Summary")
    for k in excel.LABELS:
        v = values[k]
        s.append([k, f"{v:.1%}" if k == "Overdue rate" else v])
    wb.save(rdir / "shared" / "Loans_Analysis.xlsx")
    (rdir / "shared" / "top_items.png").write_bytes(b"\x89PNG" + b"0" * 6000)


def test_excel_verifier_pass_and_fail(rdir: Path):
    t = excel.truth(rdir / "inbox" / "loans_export.xlsx")
    _write_analysis(rdir, t)
    ok = excel.verify(rdir, {}, {})
    assert ok["passed"], [c for c in ok["checks"] if not c["ok"]]
    assert ok["facts"]["overdue_rate"] == f"{t['Overdue rate']:.1%}"
    wrong = {**t, "Clean loans": t["Clean loans"] + 2}
    _write_analysis(rdir, wrong, chart=False)
    bad = excel.verify(rdir, {}, {})
    names = {c["name"] for c in bad["checks"] if not c["ok"]}
    assert "Clean loans matches recount" in names and "workbook has a chart" in names


def test_notes_verifier(rdir: Path, monkeypatch):
    truth_dir = rdir / "truth"
    truth_dir.mkdir()
    (truth_dir / "notes_truth.json").write_text(json.dumps(make_fixtures.TRUTH))
    monkeypatch.setattr(docs, "TRUTH_DIR", truth_dir)
    doc = Document()
    doc.add_heading("Decisions", 1)
    for d in make_fixtures.TRUTH["decisions"]:
        doc.add_paragraph(d, style="List Bullet")
    doc.add_heading("Actions", 1)
    table = doc.add_table(rows=1, cols=3)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text, table.rows[0].cells[2].text = "Action", "Owner", "Due"
    texts = {"access": "Set up app access", "label": "Label every item", "cost": "Pull hire costs",
             "brief": "Brief team leads", "tripod": "Remove broken tripods"}
    for a in make_fixtures.TRUTH["actions"]:
        row = table.add_row().cells
        row[0].text, row[1].text, row[2].text = texts[a["keywords"][0]], a["owner"], a["due"]
    for _ in range(6):
        doc.add_paragraph("")
    doc.save(rdir / "shared" / "Ops_Meeting_Notes.docx")
    to = ", ".join(f"{n} <{n.split()[0].lower()}@example.com>" for n in make_fixtures.TRUTH["attendees"])
    (rdir / "shared" / "Follow_up_email.eml").write_text(f"To: {to}\nSubject: Follow-up\nX-Unsent: 1\n\nBody\n")
    res = docs.verify_notes(rdir, {}, {})
    assert res["passed"], [c for c in res["checks"] if not c["ok"]]


def test_store_roundtrip(tmp_path: Path):
    store.configure(tmp_path)
    s = store.new_run("Build us an equipment-loan app", "Workday")
    s2 = store.update(s["run_id"], lambda x: {**x, "missions": [{"id": "M1", "title": "t", "agent": "codex",
                                                                    "status": "planned", "attempts": []}]})
    assert store.load(s["run_id"])["missions"][0]["id"] == "M1"
    assert "M1 t" in (tmp_path / "workday" / s["run_id"] / "STATE.md").read_text()
    assert s2["view_key"] == s["view_key"]


def _client(tmp_path: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from workday import routes

    store.configure(tmp_path)
    routes.INBOX = tmp_path / "no-inbox"
    app = FastAPI()
    app.include_router(routes.build_router(lambda key: None))
    return TestClient(app)


def test_routes_missions_and_file_guards(tmp_path: Path):
    c = _client(tmp_path)
    run = c.post("/workday/runs", json={"request": "Do the day", "title": "T"}).json()
    rid, key = run["run_id"], run["board_url"].split("k=")[1]
    m1 = c.post(f"/workday/runs/{rid}/missions", json={"kind": "excel", "title": "Excel", "goal": "do it",
                                                       "agent": "codex", "why_agent": "data"}).json()
    m2 = c.post(f"/workday/runs/{rid}/missions", json={"kind": "deck", "title": "Deck", "goal": "do it",
                                                       "agent": "claude", "why_agent": "design", "depends_on": "M1"}).json()
    assert (m1["mission_id"], m2["mission_id"]) == ("M1", "M2")
    bad = c.post(f"/workday/runs/{rid}/missions", json={"kind": "deck", "title": "Deck", "goal": "do it",
                                                        "agent": "claude", "why_agent": "xyz", "depends_on": "M9"})
    assert bad.status_code == 400
    assert c.get(f"/workday/runs/{rid}/missions/M7").status_code == 404
    rdir = tmp_path / "workday" / rid
    (rdir / "shared" / "ok.txt").write_text("fine")
    other = tmp_path / "workday" / "secret.txt"
    other.write_text("other run data")
    assert c.get(f"/workday/files/{rid}/shared/ok.txt?k={key}").text == "fine"
    assert c.get(f"/workday/files/{rid}/shared/ok.txt?k=wrong").status_code == 403
    assert c.get(f"/workday/files/{rid}/shared/../../secret.txt?k={key}").status_code == 404
    try:
        (rdir / "shared" / "link.txt").symlink_to(other)
    except OSError:
        pytest.skip("symlinks not permitted on this host")
    assert c.get(f"/workday/files/{rid}/shared/link.txt?k={key}").status_code == 404


def test_plan_workday_in_one_call(tmp_path: Path):
    c = _client(tmp_path)
    plan = {"request": "Do the day", "title": "Plan test", "missions": [
        {"kind": "excel", "title": "Excel", "goal": "do it", "agent": "codex", "why_agent": "data"},
        {"kind": "deck", "title": "Deck", "goal": "do it", "agent": "claude", "why_agent": "design",
         "depends_on": "M1", "mode": "best_of_both"}]}
    run = c.post("/workday/plan", json=plan).json()
    assert run["status"] == "running" and [m["id"] for m in run["missions"]] == ["M1", "M2"]
    assert run["missions"][1]["depends_on"] == "M1" and run["missions"][1]["mode"] == "best_of_both"
    before = len(list((tmp_path / "workday").iterdir()))
    bad = {**plan, "missions": [{**plan["missions"][1], "depends_on": "M3"}]}
    assert c.post("/workday/plan", json=bad).status_code == 400
    pp = {**plan, "missions": [{"kind": "pp_app", "title": "App", "goal": "do it", "agent": "claude",
                                "why_agent": "design", "mode": "best_of_both"}]}
    assert c.post("/workday/plan", json=pp).status_code == 400
    assert len(list((tmp_path / "workday").iterdir())) == before  # a rejected plan creates nothing


def test_plan_workday_accepts_missions_as_json_text(tmp_path: Path):
    """Copilot Studio connector actions cannot send a list of objects, so it sends the list as JSON text."""
    import json as _json
    c = _client(tmp_path)
    missions = [{"kind": "notes", "title": "Notes", "goal": "do it", "agent": "claude", "why_agent": "writing",
                 "mode": "best_of_both"}]
    run = c.post("/workday/plan", json={"request": "Do the day", "missions_json": _json.dumps(missions)}).json()
    assert run["status"] == "running" and run["missions"][0]["mode"] == "best_of_both"
    assert c.post("/workday/plan", json={"request": "Do the day", "missions_json": "not json"}).status_code == 400
    assert c.post("/workday/plan", json={"request": "Do the day", "missions_json": "[]"}).status_code == 400


def test_usage_limit_skips_the_retry_and_never_returns():
    limit = "ERROR: You've hit your usage limit. ... or try again at 1:51 PM."
    codex_out = {"agent": "codex", "worker_error": limit}
    # straight to the other agent instead of a pointless retry
    assert engine.next_step("retry_then_reroute", [codex_out]) == ("reroute", "claude")
    # the other agent gets one retry for an ordinary failure (a dropped connection)...
    drop = {"agent": "claude", "worker_error": "API Error: Connection closed mid-response."}
    assert engine.next_step("retry_then_reroute", [codex_out, drop]) == ("retry", "claude")
    # ...but the mission never goes back to the limited agent
    assert engine.next_step("retry_then_reroute", [codex_out, drop, drop]) is None
    # both agents out of usage, or a retry-only policy: stop
    assert engine.next_step("retry_then_reroute", [codex_out, {"agent": "claude", "worker_error": limit}]) is None
    assert engine.next_step("retry", [codex_out]) is None
    # ordinary failures keep the old policy
    assert engine.next_step("retry_then_reroute", [{"agent": "codex", "worker_error": "boom"}]) == ("retry", "codex")


def _desk_run(tmp_path: Path, monkeypatch, desk_free: bool) -> tuple[str, list]:
    """A pp_app mission whose first attempt just failed; the desk lock is free or held by another session."""
    from workday import desk
    store.configure(tmp_path)
    s = store.new_run("app", "Workday")
    m = {"id": "M1", "kind": "pp_app", "title": "app", "agent": "claude", "on_fail": "retry_then_reroute",
         "depends_on": [], "status": "running", "desk": "released", "packet": "",
         "attempts": [{"n": 1, "agent": "claude", "job_id": "j1"}]}
    store.update(s["run_id"], lambda x: {**x, "status": "running", "missions": [m]})
    started = []
    monkeypatch.setattr(engine, "_hooks", {"start": lambda *a: started.append(a[0]) or "j2",
                                            "job": lambda j: {"status": "running"}})
    monkeypatch.setattr(engine.prompts, "worker_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(desk, "_helper", lambda *a: (0, "acquired") if desk_free else (1, "busy: another session"))
    return s["run_id"], started


def test_retry_of_a_desk_mission_waits_for_the_desk(tmp_path: Path, monkeypatch):
    run_id, started = _desk_run(tmp_path, monkeypatch, desk_free=False)
    verdict = {"checks": [{"name": "app screenshots", "ok": False}]}
    engine._apply_policy(run_id, "M1", store.load(run_id)["missions"][0]["attempts"], verdict, "")
    assert started == []                                   # never dispatched without the desk
    m = store.load(run_id)["missions"][0]
    assert m["status"] == "waiting_desk" and m["pending"]["agent"] == "claude"
    engine.tick(run_id)
    assert started == [] and store.load(run_id)["missions"][0]["status"] == "waiting_desk"


def test_waiting_retry_dispatches_once_the_desk_is_free(tmp_path: Path, monkeypatch):
    run_id, started = _desk_run(tmp_path, monkeypatch, desk_free=False)
    verdict = {"checks": [{"name": "app screenshots", "ok": False}]}
    engine._apply_policy(run_id, "M1", store.load(run_id)["missions"][0]["attempts"], verdict, "")
    from workday import desk
    monkeypatch.setattr(desk, "_helper", lambda *a: (0, "acquired"))
    engine.tick(run_id)
    m = store.load(run_id)["missions"][0]
    assert started == ["claude"] and m["status"] == "retrying" and m["desk"] == "held" and not m.get("pending")


def test_retry_keeps_going_while_the_mission_holds_the_desk(tmp_path: Path, monkeypatch):
    run_id, started = _desk_run(tmp_path, monkeypatch, desk_free=False)
    store.update_mission(run_id, "M1", desk="held")
    verdict = {"checks": [{"name": "app screenshots", "ok": False}]}
    engine._apply_policy(run_id, "M1", store.load(run_id)["missions"][0]["attempts"], verdict, "")
    assert started == ["claude"] and store.load(run_id)["missions"][0]["status"] == "retrying"


def test_retry_reopens_a_failed_mission_and_what_it_blocked(tmp_path: Path):
    c = _client(tmp_path)
    plan = {"request": "Do the day", "title": "Retry test", "missions": [
        {"kind": "excel", "title": "Excel", "goal": "do it", "agent": "codex", "why_agent": "data"},
        {"kind": "pp_app", "title": "App", "goal": "do it", "agent": "claude", "why_agent": "screens"},
        {"kind": "deck", "title": "Deck", "goal": "do it", "agent": "claude", "why_agent": "design",
         "depends_on": "M1, M2"}]}
    run_id = c.post("/workday/plan", json=plan).json()["run_id"]
    old = [{"n": 1, "agent": "claude", "job_id": "j1", "verdict": {"passed": False}}]
    store.update(run_id, lambda s: {**s, "status": "finished_with_failures", "finished_epoch": 9.0, "missions": [
        {**s["missions"][0], "status": "done"},
        {**s["missions"][1], "status": "failed", "attempts": old, "desk": "released", "finished_epoch": 8.0},
        {**s["missions"][2], "status": "blocked", "finished_epoch": 8.0}]})
    assert c.post(f"/workday/runs/{run_id}/missions/M1/retry").status_code == 409   # done stays done
    out = c.post(f"/workday/runs/{run_id}/missions/M2/retry", json={"agent": "codex", "reason": "desk free",
                                                                      "notes": "The app already exists: finish it."})
    assert out.status_code == 200
    s = store.load(run_id)
    m1, m2, m3 = s["missions"]
    assert s["status"] == "running" and s.get("finished_epoch") is None
    assert m1["status"] == "done"
    assert m2["status"] == "planned" and m2["agent"] == "codex" and m2["attempts"] == []
    assert m2["earlier_attempts"] == old and m2.get("finished_epoch") is None and m2.get("desk") is None
    assert m3["status"] == "planned" and m3.get("finished_epoch") is None
    assert "The app already exists: finish it." in (tmp_path / "workday" / run_id / m2["packet"]).read_text()
    assert c.post(f"/workday/runs/{run_id}/missions/M9/retry").status_code == 404
    row = c.get(f"/workday/runs/{run_id}").json()["missions"][1]
    assert row["agent_chain"] == "claude" and row["attempts"] == 1 and row["reopened_after"].startswith("1 failed")


def test_waiting_retry_whose_desk_is_already_held_dispatches_after_a_restart(tmp_path: Path, monkeypatch):
    run_id, started = _desk_run(tmp_path, monkeypatch, desk_free=False)
    pending = {"agent": "codex", "failure": None, "status": "rerouted"}
    store.update_mission(run_id, "M1", status="waiting_desk", desk="held", pending=pending)
    engine.tick(run_id)                                    # helper says busy, but the desk is already ours
    m = store.load(run_id)["missions"][0]
    assert started == ["codex"] and m["status"] == "rerouted" and not m.get("pending")


def test_block_rechecks_fresh_state(tmp_path: Path):
    store.configure(tmp_path)
    run_id = store.new_run("x", "W")["run_id"]
    ms = [{"id": f"M{i}", "title": "t", "agent": "codex", "status": "planned", "attempts": [],
           "depends_on": ["M1"] if i == 2 else []} for i in (1, 2)]
    store.update(run_id, lambda s: {**s, "missions": ms})
    engine._block(run_id, "M2")                            # M1 was reopened after a stale tick saw it failed
    assert store.load(run_id)["missions"][1]["status"] == "planned"
    store.update_mission(run_id, "M1", status="failed")
    engine._block(run_id, "M2")
    assert store.load(run_id)["missions"][1]["status"] == "blocked"


def test_retry_releases_a_held_desk_and_resets_best_of_both(tmp_path: Path, monkeypatch):
    from workday import desk
    released = []
    monkeypatch.setattr(desk, "_helper", lambda *a: released.append(a) or (0, "released"))
    c = _client(tmp_path)
    plan = {"request": "Do the day", "title": "Desk test", "missions": [
        {"kind": "pp_app", "title": "App", "goal": "do it", "agent": "claude", "why_agent": "screens"},
        {"kind": "deck", "title": "Deck", "goal": "do it", "agent": "claude", "why_agent": "design",
         "mode": "best_of_both"}]}
    run_id = c.post("/workday/plan", json=plan).json()["run_id"]
    store.update(run_id, lambda s: {**s, "missions": [{**s["missions"][0], "status": "failed", "desk": "held"},
                                                      {**s["missions"][1], "status": "failed", "bob": {"round": 2}}]})
    assert c.post(f"/workday/runs/{run_id}/missions/M1/retry").status_code == 200
    assert released and released[0][0] == "release"
    assert store.load(run_id)["missions"][0].get("desk") is None
    assert c.post(f"/workday/runs/{run_id}/missions/M2/retry").status_code == 200
    assert "bob" not in store.load(run_id)["missions"][1]
    assert c.post(f"/workday/runs/{run_id}/missions/M2/retry").status_code == 409   # already reopened


def test_finish_decides_on_fresh_state(tmp_path: Path):
    store.configure(tmp_path)
    run_id = store.new_run("Do the day", "W")["run_id"]
    m = {"id": "M1", "title": "t", "agent": "codex", "status": "failed", "attempts": [], "depends_on": []}
    store.update(run_id, lambda s: {**s, "status": "running", "missions": [m]})
    store.update_mission(run_id, "M1", status="planned")   # a retry reopened it after the engine's last read
    engine._maybe_finish(run_id)
    assert store.load(run_id)["status"] == "running"
    store.update_mission(run_id, "M1", status="failed")
    engine._maybe_finish(run_id)
    assert store.load(run_id)["status"] == "finished_with_failures"
