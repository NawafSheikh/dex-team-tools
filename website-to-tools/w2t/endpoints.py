"""Turn the raw network log of a browsing session into a list of distinct API endpoints.

Input is the list of captured calls written by `discover` (one dict per finished request). Grouping is by method,
host and a templated path (ids and hashes in the path become {id}); everything observed for a group (query keys,
body samples, response samples, status codes) is kept as evidence for the planner and the schema writer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlsplit

API_TYPES = {"xhr", "fetch"}
DATA_TYPES = {"script", "document", "other"}
ID_SEGMENT = re.compile(r"^(\d+|[0-9a-f]{8,}|[0-9a-f-]{32,36}|[A-Za-z0-9_-]{22,})$", re.IGNORECASE)
MAX_SAMPLES = 3
MAX_SAMPLE_CHARS = 4000


@dataclass
class Endpoint:
    method: str
    host: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    request_samples: list[Any] = field(default_factory=list)
    response_samples: list[Any] = field(default_factory=list)
    statuses: list[int] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    calls: int = 0

    @property
    def key(self) -> str:
        return f"{self.method} {self.host}{self.path}"

    def summary(self) -> dict[str, Any]:
        """A compact, model-readable view of what was seen (samples trimmed)."""
        return {
            "key": self.key, "method": self.method, "host": self.host, "path": self.path,
            "query": {k: v[:3] for k, v in self.query.items()}, "calls": self.calls,
            "statuses": sorted(set(self.statuses)), "content_types": sorted(set(self.content_types)),
            "pages": self.pages[:5],
            "request_samples": [_trim(s) for s in self.request_samples],
            "response_samples": [_trim(s) for s in self.response_samples],
        }


def template_path(path: str) -> str:
    parts = [("{id}" if ID_SEGMENT.match(p) else p) for p in path.split("/")]
    return "/".join(parts) or "/"


def in_scope(host: str, site_host: str) -> bool:
    """Only the site's own hosts: the exact host or its subdomains. Third parties (analytics, ads) are out."""
    base = site_host.removeprefix("www.")
    return host == base or host.endswith("." + base)


def group_calls(calls: list[dict[str, Any]], site_host: str) -> tuple[list[Endpoint], list[dict[str, Any]]]:
    """Return (api endpoints, same-site data assets). Assets are scripts/documents the page loaded, kept so the
    planner can notice content that the page shows but that no API serves."""
    groups: dict[str, Endpoint] = {}
    assets: dict[str, dict[str, Any]] = {}
    for call in calls:
        url = urlsplit(call["url"])
        if not in_scope(url.hostname or "", site_host):
            continue
        rtype = call.get("resource_type", "")
        if rtype in DATA_TYPES and call.get("method") == "GET":
            assets.setdefault(url.path, {"path": url.path, "type": rtype, "bytes": call.get("response_bytes", 0)})
            continue
        if rtype not in API_TYPES:
            continue
        _add(groups, call, url)
    return list(groups.values()), list(assets.values())


def _add(groups: dict[str, Endpoint], call: dict[str, Any], url: Any) -> None:
    method = call["method"].upper()
    ep = groups.setdefault(f"{method} {url.hostname}{template_path(url.path)}",
                           Endpoint(method=method, host=url.hostname or "", path=template_path(url.path)))
    ep.calls += 1
    for k, v in parse_qsl(url.query, keep_blank_values=True):
        vals = ep.query.setdefault(k, [])
        if v not in vals:
            vals.append(v)
    _sample(ep.request_samples, call.get("request_body"))
    _sample(ep.response_samples, call.get("response_body"))
    if call.get("status") is not None:
        ep.statuses.append(int(call["status"]))
    if call.get("content_type"):
        ep.content_types.append(call["content_type"].split(";")[0].strip())
    if call.get("page") and call["page"] not in ep.pages:
        ep.pages.append(call["page"])


def _sample(bucket: list[Any], raw: Any) -> None:
    if raw in (None, "") or len(bucket) >= MAX_SAMPLES:
        return
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw[:MAX_SAMPLE_CHARS]
    if value not in bucket:
        bucket.append(value)


def _trim(value: Any) -> Any:
    text = json.dumps(value, ensure_ascii=False)
    return value if len(text) <= MAX_SAMPLE_CHARS else text[:MAX_SAMPLE_CHARS] + "...(trimmed)"
