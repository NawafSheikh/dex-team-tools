"""Server wiring without Docker: the 26 tools are registered and the key gate rejects bad requests."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.mcpserver", reason="needs mcp>=2.3 (see requirements.txt)")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
_tmp = tempfile.mkdtemp()
os.environ.update(DEVTOOLS_API_KEY="a" * 40, DEVTOOLS_SUB_KEY="b" * 40, DEVTOOLS_STATE=_tmp, DEVTOOLS_LOGS=_tmp,
                  DEVTOOLS_CLAUDE_ENV=str(Path(_tmp) / "claude.env"))

import server  # noqa: E402

EXPECTED = {"bash", "powershell", "read_file", "write_file", "edit_file", "multi_edit", "glob", "grep", "list_dir",
            "git_status", "git_diff", "git_branch", "git_commit", "git_push", "create_pull_request", "run_tests",
            "run_build", "start_process", "process_output", "stop_process", "web_fetch", "web_search",
            "todo_write", "todo_read", "run_subagent", "get_subagent"}


def test_all_26_tools_registered():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == EXPECTED


def _status(headers: list[tuple[bytes, bytes]]) -> int:
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "path": "/mcp", "headers": headers, "method": "POST"}
    asyncio.run(server.ApiKeyGate(lambda *a: None)(scope, receive, send))
    return sent[0]["status"] if sent else 200


def test_key_gate():
    assert _status([]) == 401
    assert _status([(b"x-api-key", b"wrong")]) == 401
    assert _status([(b"x-api-key", b"a" * 40), (b"x-api-key", b"a" * 40)]) == 401  # two key headers


def test_subagent_auth_prefers_env_file(tmp_path, monkeypatch):
    env = tmp_path / "claude.env"
    monkeypatch.setattr(server, "CLAUDE_ENV_FILE", env)
    with pytest.raises(RuntimeError):
        server._claude_auth()
    env.write_text('OTHER=1\nANTHROPIC_API_KEY="test-value"\n')
    assert server._claude_auth() == {"ANTHROPIC_API_KEY": "test-value"}
