"""Step 3a: write the plan as an OpenAPI 2.0 (Swagger) file, the format Copilot Studio's REST API tool imports."""
from __future__ import annotations

from typing import Any

from . import schema
from .endpoints import Endpoint

JSON = "application/json"


def build(plan: dict[str, Any], endpoints: list[Endpoint], *, version: str = "1.0.0",
          tag: dict[str, Any] | None = None) -> dict[str, Any]:
    """tag: fixed fields the caller always sends ({"body": {...}, "query": {...}}), hidden from the agent."""
    by_key = {e.key: e for e in endpoints}
    tools = plan["tools"]
    if not tools:
        raise ValueError("the plan has no tools, nothing to describe")
    host = tools[0]["host"]
    paths: dict[str, dict[str, Any]] = {}
    for tool in tools:
        ep = by_key[tool["endpoint"]]
        path = _path(tool)
        paths.setdefault(path, {})[ep.method.lower()] = _operation(tool, ep, tag or {})
    return {
        "swagger": "2.0",
        "info": {"title": plan["title"][:30], "description": plan["description"], "version": version},
        "host": host, "basePath": "/", "schemes": ["https"],
        "consumes": [JSON], "produces": [JSON],
        "paths": paths,
    }


def _path(tool: dict[str, Any]) -> str:
    path = tool["path"]
    names = [p["name"] for p in tool["params"] if p["in"] == "path"]
    for name in names:
        if "{id}" in path:
            path = path.replace("{id}", "{" + name + "}", 1)
    return path


def _operation(tool: dict[str, Any], ep: Endpoint, tag: dict[str, Any]) -> dict[str, Any]:
    params: list[dict[str, Any]] = []
    body_props: dict[str, Any] = {}
    body_required: list[str] = []
    tag_body = tag.get("body", {}) if ep.method != "GET" else {}
    tag_query = tag.get("query", {})
    for p in tool["params"]:
        if p["name"] in tag_body or p["name"] in tag_query:
            continue
        if p["in"] == "body":
            body_props[p["name"]] = _typed(p)
            if p["required"]:
                body_required.append(p["name"])
            continue
        params.append({"name": p["name"], "in": p["in"], "required": p["in"] == "path" or p["required"],
                       "description": p["description"], **_typed(p, describe=False)})
    for name, value in tag_body.items():
        body_props[name] = _hidden(value)
        body_required.append(name)
    for name, value in tag_query.items():
        params.append({"name": name, "in": "query", "required": True, **_hidden(value)})
    if body_props:
        body: dict[str, Any] = {"type": "object", "properties": body_props}
        if body_required:
            body["required"] = body_required
        params.append({"name": "body", "in": "body", "required": bool(body_required), "schema": body})
    op: dict[str, Any] = {
        "operationId": tool["operation_id"], "summary": tool["summary"], "description": tool["description"],
        "parameters": params,
        "responses": {"200": {"description": tool["response_description"],
                              "schema": _response_schema(ep)}},
    }
    return op


def _hidden(value: str) -> dict[str, Any]:
    """A constant the connector sends on its own; Copilot Studio never asks the user for it."""
    return {"type": "string", "default": value, "x-ms-visibility": "internal",
            "description": "Set automatically, identifies where the request came from."}


def _typed(p: dict[str, Any], *, describe: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"type": p["type"]}
    if p.get("enum"):
        out["enum"] = p["enum"]
    if describe:
        out["description"] = p["description"]
    return out


def _response_schema(ep: Endpoint) -> dict[str, Any]:
    samples = [s for s in ep.response_samples if isinstance(s, (dict, list))]
    return schema.infer(samples)
