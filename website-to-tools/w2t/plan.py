"""Step 2, planning: Claude reads every endpoint seen (with real samples) and decides what becomes a tool.

For each tool it writes the operation id, a human-quality description (Copilot Studio's orchestrator chooses tools
by description), parameter descriptions and whether the call only reads or changes something. It also reports
gaps: things the pages show that no endpoint serves. The model judges; code only enforces the safety floor:
any method other than GET/HEAD is a write, whatever the model says.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import llm, schema as schema_mod
from .endpoints import Endpoint

PARAM = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "in": {"type": "string", "enum": ["query", "path", "body"]},
        "type": {"type": "string", "enum": ["string", "integer", "number", "boolean"]},
        "required": {"type": "boolean"}, "description": {"type": "string"},
        "enum": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "in", "type", "required", "description"],
}
TOOL = {
    "type": "object",
    "properties": {
        "endpoint": {"type": "string", "description": "the endpoint key exactly as given"},
        "operation_id": {"type": "string", "description": "PascalCase verb first, e.g. GetTeam"},
        "summary": {"type": "string", "description": "tool name a person reads, 2 to 6 words"},
        "description": {"type": "string", "description": "when to use it, what it returns, synonyms; 1 to 3 sentences"},
        "kind": {"type": "string", "enum": ["read", "write"]},
        "params": {"type": "array", "items": PARAM},
        "response_description": {"type": "string"},
    },
    "required": ["endpoint", "operation_id", "summary", "description", "kind", "params", "response_description"],
}
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "short API name, at most 30 characters"},
        "description": {"type": "string", "description": "what the whole API is for"},
        "tools": {"type": "array", "items": TOOL},
        "skipped": {"type": "array", "items": {"type": "object", "properties": {
            "endpoint": {"type": "string"}, "why": {"type": "string"}}, "required": ["endpoint", "why"]}},
        "gaps": {"type": "array", "items": {"type": "object", "properties": {
            "what": {"type": "string"}, "where": {"type": "string"}, "suggestion": {"type": "string"}},
            "required": ["what", "where", "suggestion"]}},
    },
    "required": ["title", "description", "tools", "skipped", "gaps"],
}
SYSTEM = (
    "You turn a website's own API calls into tools for an AI agent. You get the visitor goal, every endpoint the "
    "pages called with real request and response samples, the static files the pages loaded, and the text of the "
    "pages visited. Make a tool for each endpoint that serves the goal; skip static files, analytics and anything "
    "that only makes sense inside the page, and say why. Write descriptions for an orchestrator that picks tools "
    "by description: say when to use it and what comes back, with the words a user would actually say. A blocked "
    "call has no response sample: describe it from the request and the page. Mark kind=write for anything that "
    "sends, creates, changes or deletes. A body field that is empty in every sample while the page never shows it "
    "is usually a hidden form field (often an anti-spam trap): leave it out of the params. Then list gaps: information the pages show a visitor (quote where) that "
    "no endpoint returns, and what endpoint would serve it. Never invent endpoints as tools; gaps are only advice."
)


@dataclass(frozen=True)
class Plan:
    data: dict[str, Any]
    cost_usd: float

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self.data["tools"]


def make(goal: str, endpoints: list[Endpoint], assets: list[dict[str, Any]], pages: dict[str, str],
         *, model: str = llm.DEFAULT_MODEL) -> Plan:
    prompt = json.dumps({"goal": goal, "endpoints": [e.summary() for e in endpoints], "static_files": assets,
                         "pages": {u: t[:2500] for u, t in list(pages.items())[:8]}}, ensure_ascii=False)
    result = llm.ask_json(prompt, PLAN_SCHEMA, system=SYSTEM, model=model)
    return Plan(data=enforce(result.data, endpoints), cost_usd=result.cost_usd)


def enforce(data: dict[str, Any], endpoints: list[Endpoint]) -> dict[str, Any]:
    """Drop tools for endpoints that were never observed, de-duplicate operation ids and apply the write floor."""
    known = {e.key: e for e in endpoints}
    tools, ids = [], set()
    for tool in data.get("tools", []):
        ep = known.get(tool["endpoint"])
        if ep is None or tool["operation_id"] in ids:
            continue
        ids.add(tool["operation_id"])
        kind = "write" if ep.method not in {"GET", "HEAD"} else tool["kind"]
        tools.append({**tool, "kind": kind, "method": ep.method, "host": ep.host, "path": ep.path})
    return undash({**data, "tools": tools})


def undash(value: Any) -> Any:
    """No em or en dashes in anything we publish: they become a comma or a hyphen."""
    if isinstance(value, str):
        return value.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").replace("–", "-")
    if isinstance(value, list):
        return [undash(v) for v in value]
    if isinstance(value, dict):
        return {k: undash(v) for k, v in value.items()}
    return value


FIELDS_SCHEMA = {
    "type": "object",
    "properties": {"tools": {"type": "array", "items": {"type": "object", "properties": {
        "operation_id": {"type": "string"},
        "fields": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"}, "description": {"type": "string", "description": "one short sentence"}},
            "required": ["path", "description"]}}},
        "required": ["operation_id", "fields"]}}},
    "required": ["tools"],
}


def describe_fields(data: dict[str, Any], endpoints: list[Endpoint], *, model: str = llm.DEFAULT_MODEL
                    ) -> tuple[dict[str, Any], float]:
    """Give every response field a one-line description (Copilot Studio will not save a tool without them).
    One model call for the whole plan; tools that already have descriptions are left alone."""
    by_key = {e.key: e for e in endpoints}
    todo = []
    for tool in data["tools"]:
        ep = by_key.get(tool["endpoint"])
        if tool.get("response_fields") is not None or ep is None:
            continue
        shape = schema_mod.infer([s for s in ep.response_samples if isinstance(s, (dict, list))])
        paths = schema_mod.field_paths(shape)
        if paths:
            todo.append({"operation_id": tool["operation_id"], "tool": tool["description"], "paths": paths,
                         "sample": ep.summary()["response_samples"][:1]})
    if not todo:
        return data, 0.0
    result = llm.ask_json(json.dumps({"tools": todo}, ensure_ascii=False)[:60000], FIELDS_SCHEMA, model=model,
                          system=("Describe each response field of each tool in one short plain sentence for an AI "
                                  "agent that reads the answer: what the value is, using the sample to be specific. "
                                  "Use the paths exactly as given. No dashes."))
    found = {t["operation_id"]: {f["path"]: f["description"] for f in t["fields"]} for t in result.data["tools"]}
    tools = [{**t, "response_fields": found.get(t["operation_id"], t.get("response_fields"))} for t in data["tools"]]
    return undash({**data, "tools": tools}), result.cost_usd
