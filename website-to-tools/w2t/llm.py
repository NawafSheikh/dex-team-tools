"""Structured calls to Claude through the Claude Code CLI (runs on the user's own Claude subscription login).

No API key is read here. Every call is a fresh, tool-less, settings-less headless session that must return JSON
matching a schema; the CLI enforces the schema and we validate the shape again on the way out.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "sonnet"


class LLMError(RuntimeError):
    """The model call failed or returned something we cannot use."""


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    cost_usd: float


def _cli() -> str:
    path = shutil.which("claude")
    if not path:
        raise LLMError("The Claude Code CLI (`claude`) is not on PATH. Install it and sign in first.")
    return path


def ask_json(prompt: str, schema: dict[str, Any], *, system: str = "", model: str = DEFAULT_MODEL) -> LLMResult:
    """Send one prompt, get back one JSON object that matches `schema`."""
    cmd = [
        _cli(), "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
        "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
        "--model", model,
    ]
    if system:
        cmd += ["--system-prompt", system]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise LLMError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:500]}")
    return _parse(proc.stdout)


def _parse(stdout: str) -> LLMResult:
    try:
        events = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise LLMError(f"claude printed non-JSON output: {stdout[:300]}") from exc
    records = events if isinstance(events, list) else [events]
    result = next((e for e in records if isinstance(e, dict) and e.get("type") == "result"), None)
    if result is None or result.get("is_error"):
        raise LLMError(f"claude returned no usable result: {str(result)[:300]}")
    data = result.get("structured_output")
    if not isinstance(data, dict):
        raise LLMError("claude result had no structured output")
    cost = float(result.get("total_cost_usd") or 0.0)
    log.debug("llm call ok, cost %.4f", cost)
    return LLMResult(data=data, cost_usd=cost)
