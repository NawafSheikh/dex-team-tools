"""dev-tools: an MCP server that gives a Copilot Studio agent Claude Code's toolset.

Every tool runs inside the devbox sandbox container (shell, files, search, git,
tests, builds, processes, web). Sub-agents are headless Claude Code limited to
these same tools. Commands pass an allow-list; every call is audited.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Literal

import uvicorn
from pydantic import BaseModel, Field
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

import gitops
import policy
import sandbox_exec as sb
from subagents import SUBAGENT_DENIED, SubagentPool

API_KEY = os.environ["DEVTOOLS_API_KEY"].strip()
SUB_KEY = os.environ["DEVTOOLS_SUB_KEY"].strip()
if len(API_KEY) < 32 or len(SUB_KEY) < 32 or API_KEY == SUB_KEY:
    raise SystemExit("DEVTOOLS_API_KEY and DEVTOOLS_SUB_KEY must be set, at least 32 characters, and different")
CLAUDE_ENV_FILE = Path(os.environ.get("DEVTOOLS_CLAUDE_ENV", "/opt/devtools/claude.env"))
STATE = Path(os.environ.get("DEVTOOLS_STATE", "/opt/devtools/state"))
LOGS = Path(os.environ.get("DEVTOOLS_LOGS", "/opt/devtools/logs"))
PORT = int(os.environ.get("DEVTOOLS_PORT", "8095"))
SUBAGENT_WAIT_S = 20
# Minimum seconds per Copilot tool call; spreads its planner steps under Copilot Studio's burst rate limit.
MIN_CALL_S = float(os.environ.get("DEVTOOLS_MIN_CALL_S", "0"))  # long-poll: fewer calls against Copilot Studio's orchestration rate limit
PUBLIC_HOSTS = os.environ.get("DEVTOOLS_PUBLIC_HOSTS", "").split()  # your public host name(s), if proxied

audit = policy.AuditLog(LOGS)
pool = SubagentPool(SUB_KEY)
todo_lock = threading.Lock()

mcp = MCPServer(
    name="dev-tools",
    title="Dex Dev Tools",
    version="1.0.0",
    instructions=(
        "Developer tools on a sandboxed Linux machine. The workspace is /work; paths are relative to it. "
        "Shell commands pass an allow-list and every call is logged. Use read_file before edit_file, "
        "run_tests after a change, todo_write to keep a plan, run_subagent for a separate subtask."
    ),
)


def caller_of(ctx: Context) -> str:
    """Identify the caller. ApiKeyGate already admitted exactly one valid key header."""
    key = (ctx.headers or {}).get("x-api-key", "")
    if hmac.compare_digest(key, SUB_KEY):
        return "subagent"
    if hmac.compare_digest(key, API_KEY):
        return "copilot"
    raise ToolError("unauthenticated")


def audited(ctx: Context, tool: str, detail: str, fn: Callable[[], dict]) -> dict:
    caller = caller_of(ctx)
    started = time.monotonic()
    if caller == "subagent" and tool in SUBAGENT_DENIED:
        audit.write(caller, tool, detail, "DENIED", 0)
        raise ToolError(f"{tool} is not available to sub-agents")
    try:
        result = fn()
        if caller == "copilot" and MIN_CALL_S > 0:
            time.sleep(max(0.0, MIN_CALL_S - (time.monotonic() - started)))
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        audit.write(caller, tool, detail, f"ERROR {message.splitlines()[0][:80]}", time.monotonic() - started)
        raise ToolError(message) from exc
    outcome = "ok"
    if isinstance(result, dict) and "timed_out" in result:
        outcome = "timed out" if result.get("timed_out") else f"exit {result['exit_code']}"
    elif isinstance(result, dict) and "status" in result and "job_id" in result:
        outcome = result["status"]
    audit.write(caller, tool, detail, outcome, time.monotonic() - started)
    return result


def shell_tool(ctx: Context, tool: str, command: str, cwd: str, timeout_s: int,
               check: Callable[[str], policy.Verdict], run: Callable) -> dict:
    verdict = check(command)
    if not verdict.allowed:
        audit.write(caller_of(ctx), tool, command, f"BLOCKED {verdict.reason}", 0)
        raise ToolError(f"{verdict.reason}. The attempt was logged.")
    return audited(ctx, tool, command, lambda: {"command": command, "cwd": sb.workdir(cwd),
                                                **run(command, cwd, timeout_s).as_dict()})


# ----------------------------------------------------------------- shell --
@mcp.tool()
def bash(command: str, ctx: Context, cwd: str = ".", timeout_s: int = 25) -> dict:
    """Run a bash command in the sandbox and return its exit code and combined output.
    cwd is relative to /work. Use start_process for servers or anything longer than 25 s."""
    return shell_tool(ctx, "bash", command, cwd, timeout_s, policy.check_bash, sb.bash)


@mcp.tool()
def powershell(command: str, ctx: Context, cwd: str = ".", timeout_s: int = 25) -> dict:
    """Run a PowerShell 7 command in the sandbox and return its exit code and output."""
    return shell_tool(ctx, "powershell", command, cwd, timeout_s, policy.check_pwsh, sb.pwsh)


# ----------------------------------------------------------------- files --
class Edit(BaseModel):
    path: str = Field(description="File path relative to /work")
    old_string: str = Field(description="Exact text to replace")
    new_string: str = Field(description="Replacement text")
    replace_all: bool = False


@mcp.tool()
def read_file(path: str, ctx: Context, offset: int = 1, limit: int = 400) -> dict:
    """Read a text file with line numbers. offset is the first line (1-based), limit the number of lines."""
    return audited(ctx, "read_file", path, lambda: sb.op("read", {"path": path, "offset": offset, "limit": limit}))


@mcp.tool()
def write_file(path: str, content: str, ctx: Context) -> dict:
    """Create or overwrite a file with the full content given."""
    return audited(ctx, "write_file", path, lambda: sb.op("write", {"path": path, "content": content}))


@mcp.tool()
def edit_file(path: str, old_string: str, new_string: str, ctx: Context, replace_all: bool = False) -> dict:
    """Replace an exact string in a file. old_string must match once unless replace_all is true."""
    args = {"path": path, "old_string": old_string, "new_string": new_string, "replace_all": replace_all}
    return audited(ctx, "edit_file", path, lambda: sb.op("edit", args))


def _parse_edits(edits: str) -> list[Edit]:
    try:
        raw = json.loads(edits)
    except json.JSONDecodeError as exc:
        raise ToolError(f"edits must be a JSON array: {exc}") from exc
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ToolError("edits must be a non-empty JSON array")
    return [Edit.model_validate(item) for item in raw]


@mcp.tool()
def multi_edit(edits: str, ctx: Context) -> dict:
    """Apply several exact-string edits across one or more files in one step. All apply, or none do.
    edits is a JSON array, for example:
    [{"path": "repo/a.py", "old_string": "x = 1", "new_string": "x = 2"},
     {"path": "repo/b.py", "old_string": "round(v, 2)", "new_string": "round_money(v)", "replace_all": true}]"""
    parsed = _parse_edits(edits)
    detail = ", ".join(sorted({e.path for e in parsed}))
    return audited(ctx, "multi_edit", detail,
                   lambda: sb.op("multi_edit", {"edits": [e.model_dump() for e in parsed]}))


@mcp.tool()
def glob(pattern: str, ctx: Context, path: str = ".") -> dict:
    """Find files by name pattern, for example '*.py' or 'src/*/test_*.py'. Newest first."""
    return audited(ctx, "glob", pattern, lambda: sb.op("glob", {"pattern": pattern, "path": path}))


@mcp.tool()
def grep(pattern: str, ctx: Context, path: str = ".", include: str = "*", ignore_case: bool = False,
         context: int = 0, max_results: int = 100) -> dict:
    """Search file contents with a regular expression. include filters file names, e.g. '*.py'."""
    args = {"pattern": pattern, "path": path, "include": include, "ignore_case": ignore_case,
            "context": context, "max_results": max_results}
    return audited(ctx, "grep", pattern, lambda: sb.op("grep", args))


@mcp.tool()
def list_dir(ctx: Context, path: str = ".") -> dict:
    """List a folder: sub-folders first, then files with sizes."""
    return audited(ctx, "list_dir", path, lambda: sb.op("ls", {"path": path}))


# ------------------------------------------------------------------- git --
@mcp.tool()
def git_status(repo: str, ctx: Context) -> dict:
    """Show the branch and changed files of a git repo (path relative to /work)."""
    return audited(ctx, "git_status", repo, lambda: gitops.status(repo))


@mcp.tool()
def git_diff(repo: str, ctx: Context, staged: bool = False, path: str = "") -> dict:
    """Show the diff of uncommitted (or staged) changes, with a per-file summary."""
    return audited(ctx, "git_diff", repo, lambda: gitops.diff(repo, staged, path))


@mcp.tool()
def git_branch(repo: str, ctx: Context, name: str = "", checkout: bool = True) -> dict:
    """List branches, or create a branch and switch to it."""
    return audited(ctx, "git_branch", f"{repo} {name}", lambda: gitops.branch(repo, name, checkout))


@mcp.tool()
def git_commit(repo: str, message: str, ctx: Context, files: str = "") -> dict:
    """Stage files and commit with the message. files: space- or comma-separated paths; empty stages all changes."""
    paths = [p for p in re.split(r"[\s,]+", files) if p]
    return audited(ctx, "git_commit", message, lambda: gitops.commit(repo, message, paths))


@mcp.tool()
def git_push(repo: str, ctx: Context, branch: str = "") -> dict:
    """Push a branch (default: the current one) to origin on GitHub."""
    return audited(ctx, "git_push", f"{repo} {branch}", lambda: gitops.push(repo, branch))


@mcp.tool()
def create_pull_request(repo: str, title: str, body: str, ctx: Context, head: str = "",
                        base: str = "main") -> dict:
    """Open a GitHub pull request from head (default: current branch) into base."""
    return audited(ctx, "create_pull_request", title,
                   lambda: gitops.create_pull_request(repo, title, body, head, base))


# ---------------------------------------------------------- tests, build --
def detected_run(ctx: Context, tool: str, repo: str, command: str, kind: str, timeout_s: int) -> dict:
    chosen = command or gitops.detect(repo, kind)
    return shell_tool(ctx, tool, chosen, repo, timeout_s, policy.check_bash, sb.bash)


@mcp.tool()
def run_tests(repo: str, ctx: Context, command: str = "", timeout_s: int = 25) -> dict:
    """Run the repo's test suite (detected, or the command given) and return the result."""
    return detected_run(ctx, "run_tests", repo, command, "test", timeout_s)


@mcp.tool()
def run_build(repo: str, ctx: Context, command: str = "", timeout_s: int = 25) -> dict:
    """Build the project (detected from pyproject, package.json or Makefile, or the command given)."""
    return detected_run(ctx, "run_build", repo, command, "build", timeout_s)


# ------------------------------------------------------------- processes --
@mcp.tool()
def start_process(name: str, command: str, ctx: Context, cwd: str = ".",
                  shell: Literal["bash", "powershell"] = "bash") -> dict:
    """Start a long-running command (a server, a watcher) in the background under a name.
    Read its output with process_output and end it with stop_process."""
    verdict = (policy.check_pwsh if shell == "powershell" else policy.check_bash)(command)
    if not verdict.allowed:
        audit.write(caller_of(ctx), "start_process", command, f"BLOCKED {verdict.reason}", 0)
        raise ToolError(verdict.reason)
    args = {"name": name, "command": command, "cwd": cwd, "shell": shell}
    return audited(ctx, "start_process", command, lambda: sb.op("spawn", args))


@mcp.tool()
def process_output(name: str, ctx: Context) -> dict:
    """Show whether a background process is still running and the latest lines of its output."""
    return audited(ctx, "process_output", name, lambda: sb.op("proc_output", {"name": name}))


@mcp.tool()
def stop_process(name: str, ctx: Context) -> dict:
    """Stop a background process started with start_process."""
    return audited(ctx, "stop_process", name, lambda: sb.op("proc_stop", {"name": name}))


# ------------------------------------------------------------------- web --
@mcp.tool()
def web_fetch(url: str, ctx: Context, offset: int = 0, max_chars: int = 12000) -> dict:
    """Fetch a web page (or a local server in the sandbox, e.g. http://localhost:8000) as readable text."""
    return audited(ctx, "web_fetch", url, lambda: sb.op("fetch", {"url": url, "offset": offset,
                                                                  "max_chars": max_chars}))


@mcp.tool()
def web_search(query: str, ctx: Context, max_results: int = 6) -> dict:
    """Search the web and return titles, links and snippets."""
    return audited(ctx, "web_search", query, lambda: sb.op("search", {"query": query,
                                                                      "max_results": max_results}))


# ------------------------------------------------------------- task list --
TODO_MARKS = {"[x]": "completed", "[>]": "in_progress", "[ ]": "pending"}


def _parse_tasks(tasks: str) -> list[dict]:
    items = []
    for line in tasks.splitlines():
        line = line.strip().lstrip("-*").strip()
        if not line:
            continue
        status = "pending"
        for mark, value in TODO_MARKS.items():
            if line.lower().startswith(mark):
                status, line = value, line[len(mark):].strip()
                break
        items.append({"content": line, "status": status})
    if not items:
        raise ToolError("tasks is empty: give one task per line")
    return items


def _todo_path() -> Path:
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE / "todos.json"


@mcp.tool()
def todo_write(tasks: str, ctx: Context) -> dict:
    """Replace the task list. One task per line, each starting with [x] done, [>] in progress or [ ] pending.
    Example: "[x] Reproduce the failing tests
[>] Fix the rounding
[ ] Commit and push" """
    items = _parse_tasks(tasks)

    def run() -> dict:
        with todo_lock:
            _todo_path().write_text(json.dumps(items, indent=1))
        done = sum(1 for t in items if t["status"] == "completed")
        return {"todos": items, "summary": f"{done} of {len(items)} done"}
    return audited(ctx, "todo_write", f"{len(items)} items", run)


@mcp.tool()
def todo_read(ctx: Context) -> dict:
    """Show the current task list."""
    def run() -> dict:
        path = _todo_path()
        return {"todos": json.loads(path.read_text()) if path.exists() else []}
    return audited(ctx, "todo_read", "", run)


# ------------------------------------------------------------ sub-agents --
CLAUDE_AUTH_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


def _claude_auth() -> dict[str, str]:
    """Sub-agent credential, read from a root-only env file at call time (never kept in this process's env).
    Prefer ANTHROPIC_API_KEY (commercial API); CLAUDE_CODE_OAUTH_TOKEN works for a personal Claude Code login."""
    if CLAUDE_ENV_FILE.exists():
        for line in CLAUDE_ENV_FILE.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() in CLAUDE_AUTH_VARS and value.strip():
                return {name.strip(): value.strip().strip('"')}
    raise RuntimeError("sub-agent sign-in is not configured (set ANTHROPIC_API_KEY in DEVTOOLS_CLAUDE_ENV)")


@mcp.tool()
def run_subagent(task: str, ctx: Context) -> dict:
    """Hand a self-contained subtask to a sub-agent that works in the same sandbox with the same tools.
    Returns a job_id at once; check progress and the final report with get_subagent."""
    return audited(ctx, "run_subagent", task, lambda: pool.start(task, _claude_auth()).as_dict())


@mcp.tool()
def get_subagent(job_id: str, ctx: Context) -> dict:
    """Get a sub-agent's status (running, done, failed), elapsed time and its report.
    Waits up to 20 s for the job to finish before answering, so call it again only if still running."""
    def run() -> dict:
        deadline = time.monotonic() + SUBAGENT_WAIT_S
        job = pool.get(job_id)
        if job is None:
            raise KeyError(f"no sub-agent job {job_id}")
        while job.status == "running" and time.monotonic() < deadline:
            time.sleep(1)
            job = pool.get(job_id)
        return job.as_dict()
    return audited(ctx, "get_subagent", job_id, run)


# ------------------------------------------------------------------ app --
class ApiKeyGate:
    """Reject any request to /mcp without a valid x-api-key header."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            keys = [v.decode("latin-1") for k, v in scope["headers"] if k.decode("latin-1").lower() == "x-api-key"]
            key = keys[0] if len(keys) == 1 else ""  # zero or several key headers: reject
            if not key or not (hmac.compare_digest(key, API_KEY) or hmac.compare_digest(key, SUB_KEY)):
                audit.write("unknown", "auth", scope["path"], "REJECTED bad or missing key", 0)
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"invalid api key"}'})
                return
        await self.app(scope, receive, send)


def build_app():
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1", f"127.0.0.1:{PORT}", "localhost", f"localhost:{PORT}", *PUBLIC_HOSTS],
        allowed_origins=[],
    )
    app = mcp.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
    return ApiKeyGate(app)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=PORT, log_level="warning")
