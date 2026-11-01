"""Step 3b: generate a small Node MCP server (streamable HTTP) from the same plan the OpenAPI file came from."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMPLATES = Path(__file__).resolve().parent / "templates"
SDK_VERSION = "1.32.2"


def tools_for_server(plan: dict[str, Any], tag: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Tool definitions for the server. Fields the server fills itself (the tag) are never offered to the agent."""
    tagged = set((tag or {}).get("body", {})) | set((tag or {}).get("query", {}))
    return [{
        "name": t["operation_id"], "summary": t["summary"], "description": t["description"], "kind": t["kind"],
        "method": t["method"], "path": _path(t), "params": [
            {k: p[k] for k in ("name", "in", "type", "required", "description", "enum") if p.get(k) is not None}
            for p in t["params"] if p["name"] not in tagged],
    } for t in plan["tools"]]


def _path(tool: dict[str, Any]) -> str:
    path = tool["path"]
    for p in tool["params"]:
        if p["in"] == "path" and "{id}" in path:
            path = path.replace("{id}", "{" + p["name"] + "}", 1)
    return path


def instructions(plan: dict[str, Any]) -> str:
    writes = [t["operation_id"] for t in plan["tools"] if t["kind"] == "write"]
    text = plan["description"]
    if writes:
        text += (f" Tools that send or change something ({', '.join(writes)}) return a preview first; show it to the "
                 "user and only call again with confirm=true after the user explicitly agrees.")
    return text


def render(plan: dict[str, Any], *, name: str, version: str = "1.0.0", tag: dict[str, Any] | None = None) -> str:
    host = plan["tools"][0]["host"]
    src = (TEMPLATES / "mcp_server.mjs").read_text(encoding="utf-8")
    values = {
        "__TITLE__": plan["title"].replace("\n", " "),
        "__ORIGIN__": json.dumps(f"https://{host}"),
        "__TOOLS__": json.dumps(tools_for_server(plan, tag), indent=2, ensure_ascii=False),
        "__TAG__": json.dumps(tag or {}),
        "__NAME__": json.dumps(name),
        "__VERSION__": json.dumps(version),
        "__INSTRUCTIONS__": json.dumps(instructions(plan), ensure_ascii=False),
    }
    for key, value in values.items():
        src = src.replace(key, value)
    return src


def write(plan: dict[str, Any], out: Path, *, name: str, tag: dict[str, Any] | None = None) -> Path:
    folder = out / "mcp-server"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mcp-server.mjs").write_text(render(plan, name=name, tag=tag), encoding="utf-8")
    (folder / "serve.mjs").write_text((TEMPLATES / "serve.mjs").read_text(encoding="utf-8"), encoding="utf-8")
    (folder / "package.json").write_text(json.dumps({
        "name": name, "private": True, "type": "module", "scripts": {"start": "node serve.mjs"},
        "dependencies": {"@modelcontextprotocol/sdk": SDK_VERSION},
    }, indent=2) + "\n", encoding="utf-8")
    return folder
