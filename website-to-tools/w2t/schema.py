"""Infer a Swagger 2.0 JSON schema from observed JSON samples (requests or responses)."""
from __future__ import annotations

from typing import Any

MAX_DEPTH = 8
MAX_PROPS = 60


def infer(samples: list[Any]) -> dict[str, Any]:
    """Merge the shapes of every sample into one schema. Empty input gives a free-form object."""
    schema: dict[str, Any] | None = None
    for sample in samples:
        schema = merge(schema, of(sample))
    return schema or {"type": "object"}


def of(value: Any, depth: int = 0) -> dict[str, Any]:
    if depth > MAX_DEPTH:
        return {}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        items: dict[str, Any] | None = None
        for item in value[:20]:
            items = merge(items, of(item, depth + 1))
        return {"type": "array", "items": items or {}}
    if isinstance(value, dict):
        props = {str(k): of(v, depth + 1) for k, v in list(value.items())[:MAX_PROPS]}
        return {"type": "object", "properties": props}
    return {}


def merge(a: dict[str, Any] | None, b: dict[str, Any]) -> dict[str, Any]:
    if a is None:
        return b
    if not a or not b:
        return a or b
    if a.get("type") != b.get("type"):
        if {a.get("type"), b.get("type")} == {"integer", "number"}:
            return {"type": "number"}
        return {}  # mixed types: leave untyped rather than guess
    if a["type"] == "object":
        props = dict(a.get("properties", {}))
        for key, sub in b.get("properties", {}).items():
            props[key] = merge(props.get(key), sub)
        return {"type": "object", "properties": props}
    if a["type"] == "array":
        return {"type": "array", "items": merge(a.get("items") or None, b.get("items") or {})}
    return a
