"""Step 5, layer 1: call every generated tool through the generated MCP server with sample inputs.

Read tools are called for real. Write tools are only called without confirm, which must return a preview and send
nothing; a write is never confirmed by the tester. Results say pass or fail with the reason, for the fix loop.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import llm

log = logging.getLogger(__name__)

SAMPLES_SCHEMA = {
    "type": "object",
    "properties": {"cases": {"type": "array", "items": {"type": "object", "properties": {
        "tool": {"type": "string"}, "arguments": {"type": "object"},
        "expect": {"type": "string", "description": "what a correct answer must contain, in words"}},
        "required": ["tool", "arguments", "expect"]}}},
    "required": ["cases"],
}
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["pass", "why"],
}


@dataclass(frozen=True)
class Result:
    tool: str
    arguments: dict[str, Any]
    passed: bool
    why: str
    ms: int


class McpClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.next_id = 1

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}).encode()
        self.next_id += 1
        req = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "User-Agent": "website-to-tools-tester"})
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_local(server_dir: Path, port: int = 0) -> tuple[subprocess.Popen[bytes], int]:
    """Start the generated server on a free local port; returns the process and the port."""
    if not (server_dir / "node_modules").exists():
        subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=server_dir, check=True, shell=True)
    port = port or free_port()
    proc = subprocess.Popen(["node", "serve.mjs", str(port)], cwd=server_dir,
                            env={**os.environ, "HOST": "127.0.0.1"})
    for _ in range(50):
        if proc.poll() is not None:
            raise RuntimeError(f"the generated MCP server exited with code {proc.returncode}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health")
            return proc, port
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("the generated MCP server did not start")


def run(url: str, plan: dict[str, Any], *, model: str = llm.DEFAULT_MODEL) -> tuple[list[Result], float]:
    client = McpClient(url)
    client.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "website-to-tools-tester", "version": "1"}})
    listed = {t["name"]: t for t in client.call("tools/list")["result"]["tools"]}
    cost = 0.0
    samples = llm.ask_json(json.dumps({"tools": list(listed.values())}), SAMPLES_SCHEMA, model=model, system=(
        "Write one realistic test case per tool: the arguments a real user's request would produce, and what a "
        "correct answer must contain. For tools with a confirm argument never set confirm."))
    cost += samples.cost_usd
    results = []
    for case in samples.data["cases"]:
        if case["tool"] not in listed:
            continue
        args = {k: v for k, v in case["arguments"].items() if k != "confirm"}
        started = time.time()
        out = client.call("tools/call", {"name": case["tool"], "arguments": args})
        ms = int((time.time() - started) * 1000)
        verdict = llm.ask_json(json.dumps({"tool": listed[case["tool"]], "arguments": args, "expect": case["expect"],
                                           "answer": out.get("result", out)}, ensure_ascii=False)[:30000],
                               VERDICT_SCHEMA, model=model, system=(
            "Judge one tool call. Pass if the answer is what the tool promises (for a write tool without confirm, "
            "a preview that sends nothing is correct). Fail on errors, empty or wrong data, and say why."))
        cost += verdict.cost_usd
        results.append(Result(case["tool"], args, bool(verdict.data["pass"]), verdict.data["why"], ms))
    return results, cost
