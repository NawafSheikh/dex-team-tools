"""Standalone host for the workday orchestrator.

Runs the workday package as a small FastAPI server: an X-API-Key gate for the Copilot Studio connector, and an
agent runner that starts Claude Code or Codex as a headless CLI process in the mission's work folder.

    python server.py        or        uvicorn server:create_app --factory --port 8091

Settings are environment variables; see .env.example.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import shlex
import subprocess
import threading
import time
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException

import workday

log = logging.getLogger("workday.server")

DEFAULT_COMMANDS = {
    # Prompt arrives on stdin. Both run unattended inside the mission's own work folder.
    "claude": "claude --print --permission-mode bypassPermissions",
    "codex": "codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -",
}
TAIL = 4000


def _api_key() -> str:
    key = os.environ.get("WORKDAY_API_KEY", "").strip()
    if len(key) < 32:
        raise SystemExit("WORKDAY_API_KEY must be set and at least 32 characters (try: openssl rand -hex 32)")
    return key


def agent_command(agent: str) -> list[str]:
    raw = os.environ.get(f"WORKDAY_{agent.upper()}_CMD", "").strip() or DEFAULT_COMMANDS.get(agent, "")
    if not raw:
        raise ValueError(f"unknown agent {agent!r}")
    return shlex.split(raw)  # POSIX quoting; on Windows write paths with forward slashes


def _create_time(pid: int) -> float | None:
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def _alive(record: dict) -> bool:
    """True if the job's own agent process still runs (same pid AND same start time, so a reused pid of an
    unrelated process never counts)."""
    pid, started = record.get("pid"), record.get("pid_started")
    if not pid or started is None:
        return False
    try:
        proc = psutil.Process(pid)
        return abs(proc.create_time() - started) < 1 and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


class AgentRunner:
    """Starts one CLI process per mission attempt and records its outcome in jobs/<id>.json."""

    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._close_orphans()

    def _close_orphans(self) -> None:
        """After a restart, a job still marked running either has a live agent process left over from the
        previous server (it keeps reading as running until that process exits, so nothing verifies or retries
        while it still writes) or is gone (marked finished with an error)."""
        for path in self.jobs_dir.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") != "running":
                continue
            if _alive(record):
                self._write(record["job_id"], {**record, "orphaned": True})
            else:
                self._write(record["job_id"], {**record, "status": "error", "exit_code": -1,
                                               "stderr_tail": "server restarted while the agent was running"})

    def _write(self, job_id: str, record: dict) -> None:
        tmp = self.jobs_dir / f"{job_id}.json.tmp"
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        tmp.replace(self.jobs_dir / f"{job_id}.json")

    def start(self, agent: str, prompt: str, work: Path, kind: str) -> str:
        argv = agent_command(agent)
        job_id = f"job-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{secrets.token_hex(3)}"
        work.mkdir(parents=True, exist_ok=True)
        record = {"job_id": job_id, "agent": agent, "kind": kind, "status": "running", "cwd": str(work),
                  "started_epoch": time.time(), "exit_code": None}
        with self._lock:
            self._write(job_id, record)
        threading.Thread(target=self._run, args=(job_id, argv, prompt, work, record), daemon=True).start()
        return job_id

    def _run(self, job_id: str, argv: list[str], prompt: str, work: Path, record: dict) -> None:
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=work, text=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            log.error("agent %s could not start: %s", record["agent"], exc)
            done = {**record, "status": "error", "exit_code": -1, "stderr_tail": f"could not start: {exc}",
                    "finished_epoch": time.time()}
            with self._lock:
                self._write(job_id, done)
            return
        record = {**record, "pid": proc.pid, "pid_started": _create_time(proc.pid)}
        with self._lock:
            self._write(job_id, record)
        out, err = proc.communicate(prompt)
        done = {**record, "status": "done" if proc.returncode == 0 else "error", "exit_code": proc.returncode,
                "result": (out or "")[-TAIL:], "stderr_tail": (err or "")[-TAIL:], "finished_epoch": time.time()}
        with self._lock:
            self._write(job_id, done)

    def get(self, job_id: str) -> dict:
        path = self.jobs_dir / f"{Path(job_id).name}.json"
        if not path.exists():
            # A job lost in a restart reads as finished: the verifier then judges what the worker left behind.
            return {"job_id": job_id, "status": "done", "exit_code": None, "result": "job record not found"}
        with self._lock:  # never read while _write swaps the file (Windows refuses the swap then)
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("orphaned") and record["status"] == "running" and not _alive(record):
                record = {**record, "status": "error", "exit_code": -1, "finished_epoch": time.time(),
                          "stderr_tail": "agent from before a server restart finished; its output was not captured"}
                self._write(job_id, record)
            return record


def create_app(root: Path | None = None) -> FastAPI:
    key = _api_key()
    # Absolute: agents run inside their own work folders, so every path in a prompt must be absolute.
    root = (root or Path(os.environ.get("WORKDAY_ROOT", "data"))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    runner = AgentRunner(root / "jobs")

    def check_auth(given: str | None) -> None:
        if not given or not hmac.compare_digest(given.encode(), key.encode()):
            raise HTTPException(401, "missing or invalid X-API-Key")

    app = FastAPI(title="Workday Orchestrator", version="1.0.0",
                  description="Plan a workday of missions for Claude Code and Codex, verify each one independently.")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    workday.install(app, root, check_auth, runner.start, runner.get)
    return app


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host=os.environ.get("WORKDAY_HOST", "127.0.0.1"),
                port=int(os.environ.get("WORKDAY_PORT", "8091")))
