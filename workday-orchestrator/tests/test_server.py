"""The standalone host: key gate, agent runner with a fake agent command, restart handling."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import server  # noqa: E402

KEY = "k" * 40
PY = sys.executable.replace("\\", "/")


def _wait(runner: server.AgentRunner, job_id: str) -> dict:
    for _ in range(100):
        job = runner.get(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_refuses_short_key(monkeypatch):
    monkeypatch.setenv("WORKDAY_API_KEY", "short")
    with pytest.raises(SystemExit):
        server.create_app()


def test_key_gate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKDAY_API_KEY", KEY)
    client = TestClient(server.create_app(tmp_path))
    assert client.get("/health").json() == {"ok": True}
    assert client.get("/workday/kinds").status_code == 401
    assert client.get("/workday/kinds", headers={"X-API-Key": "wrong" * 10}).status_code == 401
    ok = client.get("/workday/kinds", headers={"X-API-Key": KEY})
    assert ok.status_code == 200 and {k["kind"] for k in ok.json()["kinds"]} >= {"excel", "notes", "deck"}


def test_runner_passes_prompt_on_stdin(tmp_path: Path, monkeypatch):
    echo = f'"{PY}" -c "import sys; print(sys.stdin.read().upper())"'
    monkeypatch.setenv("WORKDAY_CLAUDE_CMD", echo)
    runner = server.AgentRunner(tmp_path / "jobs")
    job = _wait(runner, runner.start("claude", "hello mission", tmp_path / "work", "notes"))
    assert job["status"] == "done" and job["exit_code"] == 0 and "HELLO MISSION" in job["result"]


def test_runner_reports_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKDAY_CODEX_CMD", f'"{PY}" -c "import sys; sys.exit(3)"')
    runner = server.AgentRunner(tmp_path / "jobs")
    job = _wait(runner, runner.start("codex", "x", tmp_path / "work", "excel"))
    assert job["status"] == "error" and job["exit_code"] == 3


def test_unknown_job_reads_as_finished_and_orphans_close(tmp_path: Path):
    runner = server.AgentRunner(tmp_path / "jobs")
    assert runner.get("job-missing")["status"] == "done"
    runner._write("job-old", {"job_id": "job-old", "status": "running"})
    again = server.AgentRunner(tmp_path / "jobs")
    assert again.get("job-old")["status"] == "error"


def test_storage_root_is_absolute(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WORKDAY_API_KEY", KEY)
    monkeypatch.chdir(tmp_path)
    server.create_app(Path("relative-root"))
    from workday import store
    assert store.base().is_absolute() and store.base() == (tmp_path / "relative-root" / "workday").resolve()


def test_engine_error_releases_a_held_desk(tmp_path: Path, monkeypatch):
    from workday import desk, engine, store
    store.configure(tmp_path)
    state = store.new_run("x", "t")
    rid = state["run_id"]
    store.update(rid, lambda s: {**s, "status": "running", "missions": [{
        "id": "M1", "kind": "pp_app", "title": "app", "agent": "claude", "why_agent": "w", "depends_on": [],
        "status": "planned", "attempts": [], "mode": "single", "on_fail": "retry", "packet": "missing.md"}]})
    released = []
    monkeypatch.setattr(desk, "_helper", lambda *a: released.append(a[0]) or (0, "ok"))

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(engine, "dispatch", boom)
    engine.tick(rid)
    m = store.mission(store.load(rid), "M1")
    assert m["status"] == "failed" and m["desk"] == "released" and released == ["try", "release"]


def test_orphaned_worker_still_running_is_not_finished(tmp_path: Path):
    import subprocess as sp
    proc = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        runner = server.AgentRunner(tmp_path / "jobs")
        runner._write("job-live", {"job_id": "job-live", "status": "running", "pid": proc.pid,
                                   "pid_started": server._create_time(proc.pid)})
        again = server.AgentRunner(tmp_path / "jobs")          # a restart while the agent still runs
        assert again.get("job-live")["status"] == "running"
    finally:
        proc.kill()
        proc.wait()
    assert again.get("job-live")["status"] == "error"         # it ended: now it reads as finished


def test_failed_desk_release_keeps_the_desk_held(tmp_path: Path, monkeypatch):
    from workday import desk, store
    store.configure(tmp_path)
    rid = store.new_run("x", "t")["run_id"]
    store.update(rid, lambda s: {**s, "missions": [{"id": "M1", "title": "app", "agent": "claude", "status": "failed",
                                                       "attempts": [], "desk": "held"}]})
    monkeypatch.setattr(desk, "_helper", lambda *a: (1, "lock helper timed out"))
    desk.release(rid, {"id": "M1"})
    assert store.mission(store.load(rid), "M1")["desk"] == "held"
