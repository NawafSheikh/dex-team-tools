"""Sub-agents: headless Claude Code with ALL built-in tools switched off.

The only tools a sub-agent has are this server's sandboxed MCP tools, reached
with the sub-agent key, so it works in the same sandbox, under the same
allow-list, and every call it makes lands in the same audit log. Sub-agents
cannot start further sub-agents, push, or open pull requests.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from dataclasses import asdict, dataclass, field, replace

RUN_AS = os.environ.get("DEVTOOLS_SUBAGENT_USER", "devtools")  # an unprivileged host user that owns CONFIG_DIR
CLAUDE_BIN = os.environ.get("DEVTOOLS_CLAUDE_BIN", "claude")
MODEL = os.environ.get("DEVTOOLS_SUBAGENT_MODEL", "sonnet")
MCP_URL = os.environ.get("DEVTOOLS_SELF_URL", "http://127.0.0.1:8095/mcp")
CONFIG_DIR = os.environ.get("DEVTOOLS_SUBAGENT_CONFIG_DIR", "/opt/devtools/claude-sub")
JOBS_DIR = Path(os.environ.get("DEVTOOLS_STATE", "/opt/devtools/state")) / "subagents"
SUBAGENT_DENIED = ("run_subagent", "get_subagent", "git_push", "create_pull_request")

SYSTEM = (
    "You are a sub-agent working for a Copilot Studio agent. You can only act through the dev-tools MCP "
    "tools; they run in a sandbox whose workspace is /work. Do exactly the task you are given, keep "
    "changes minimal, and finish with a short plain report: what you did, what you found, file paths."
)


@dataclass(frozen=True)
class Job:
    job_id: str
    task: str
    status: str = "running"
    started: float = field(default_factory=time.time)
    finished: float | None = None
    report: str = ""
    exit_code: int | None = None

    def as_dict(self) -> dict:
        end = self.finished or time.time()
        return {"job_id": self.job_id, "status": self.status, "task": self.task[:300],
                "elapsed_s": round(end - self.started, 1), "exit_code": self.exit_code,
                "report": self.report[-12000:]}


class SubagentPool:
    def __init__(self, sub_key: str, max_running: int = 1) -> None:
        self.sub_key = sub_key
        self.max_running = max_running
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def _save(self, job: Job) -> None:
        """Keep every job on disk so a server restart does not lose it."""
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        (JOBS_DIR / f"{job.job_id}.json").write_text(json.dumps(asdict(job)), encoding="utf-8")

    def _set(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
        self._save(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None or not re.fullmatch(r"[0-9a-f]{10}", job_id or ""):
            return job
        path = JOBS_DIR / f"{job_id}.json"
        if not path.exists():
            return None
        job = Job(**json.loads(path.read_text(encoding="utf-8")))
        if job.status == "running":  # its process died with the previous server
            job = replace(job, status="failed", finished=job.finished or time.time(),
                          report=job.report or "the server restarted while this sub-agent was running; start it again")
        return job

    def start(self, task: str, auth_env: dict[str, str]) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:10], task=task)
        with self._lock:  # check and reserve under one lock, so two calls cannot both get the last slot
            if sum(1 for j in self._jobs.values() if j.status == "running") >= self.max_running:
                raise RuntimeError("a sub-agent is already running; check it with get_subagent first")
            self._jobs[job.job_id] = job
        self._save(job)
        threading.Thread(target=self._run, args=(job, auth_env), daemon=True).start()
        return job

    def _mcp_config(self) -> str:
        config = {"mcpServers": {"devtools": {"type": "http", "url": MCP_URL,
                                              "headers": {"x-api-key": self.sub_key}}}}
        fd, path = tempfile.mkstemp(prefix="sub-mcp-", suffix=".json", dir=CONFIG_DIR)
        with os.fdopen(fd, "w") as fh:
            json.dump(config, fh)
        subprocess.run(["chown", RUN_AS, path], check=False)
        os.chmod(path, 0o600)
        return path

    def _run(self, job: Job, auth_env: dict[str, str]) -> None:
        config_path = None
        # The credential travels in the environment, never in argv (argv is readable by other users via /proc).
        env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": f"/home/{RUN_AS}", "LANG": "C.UTF-8",
               "CLAUDE_CONFIG_DIR": CONFIG_DIR, **auth_env}
        try:
            config_path = self._mcp_config()
            argv = [
                "runuser", "-u", RUN_AS, "--",
                CLAUDE_BIN, "--print", job.task, "--model", MODEL, "--output-format", "text",
                "--tools", "", "--strict-mcp-config", "--mcp-config", config_path,
                "--allowedTools", "mcp__devtools", "--permission-mode", "bypassPermissions",
                "--append-system-prompt", SYSTEM,
            ]
            proc = subprocess.run(argv, cwd="/tmp", env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            out = proc.stdout.decode("utf-8", "replace").strip()[-200_000:]
            status = "done" if proc.returncode == 0 else "failed"
            self._set(replace(job, status=status, finished=time.time(), report=out, exit_code=proc.returncode))
        except Exception as exc:  # any setup or run failure must free the slot
            self._set(replace(job, status="failed", finished=time.time(), report=f"{type(exc).__name__}: {exc}"))
        finally:
            if config_path:
                try:
                    os.remove(config_path)
                except OSError:
                    pass
