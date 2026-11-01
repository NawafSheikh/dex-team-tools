"""Read the site's published API catalog (RFC 9727, /.well-known/api-catalog), GET only, same site only.

A site can say which APIs it offers without a visitor clicking anything. The catalog is a linkset; every same-site
link in it is fetched once, and if that answer is a JSON index whose entries carry same-site "url" fields, those
are fetched too (one level). Every response is recorded exactly like a browser call so the rest of the pipeline
treats both the same.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import APIRequestContext

from .endpoints import in_scope

log = logging.getLogger(__name__)
WELL_KNOWN = "/.well-known/api-catalog"
MAX_FETCHES = 25
MAX_BODY = 20_000


def probe(request: APIRequestContext, site_url: str, site_host: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    root = urljoin(site_url, WELL_KNOWN)
    catalog = _get(request, root, calls)
    if catalog is None:
        log.info("no api catalog at %s", root)
        return calls
    queue = [u for u in _links(catalog, root) if in_scope(urlsplit(u).hostname or "", site_host)]
    seen = {root}
    for depth in range(2):
        nxt: list[str] = []
        for url in queue:
            if url in seen or len(seen) > MAX_FETCHES:
                continue
            seen.add(url)
            body = _get(request, url, calls)
            if depth == 0 and body is not None:
                nxt += [u for u in _index_urls(body, url) if in_scope(urlsplit(u).hostname or "", site_host)]
        queue = nxt
    return calls


def _get(request: APIRequestContext, url: str, calls: list[dict[str, Any]]) -> Any | None:
    try:
        resp = request.get(url, headers={"Accept": "application/linkset+json, application/json"})
    except Exception as exc:  # network failure on one link must not end discovery
        log.warning("catalog fetch failed %s: %s", url, exc)
        return None
    text = resp.text()[:MAX_BODY]
    calls.append({"method": "GET", "url": url, "resource_type": "fetch", "request_body": None, "page": "api-catalog",
                  "blocked": False, "at": time.time(), "status": resp.status,
                  "content_type": resp.headers.get("content-type", ""), "response_body": text})
    if not resp.ok:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _links(catalog: Any, base: str) -> Iterable[str]:
    """Hrefs from an RFC 9264 linkset: {"linkset": [{"anchor": ..., "service-desc": [{"href": ...}], ...}]}."""
    for entry in (catalog.get("linkset", []) if isinstance(catalog, dict) else []):
        if entry.get("anchor"):
            yield urljoin(base, entry["anchor"])
        for key, targets in entry.items():
            if isinstance(targets, list):
                for t in targets:
                    if isinstance(t, dict) and t.get("href"):
                        yield urljoin(base, t["href"])


def _index_urls(body: Any, base: str, depth: int = 0) -> Iterable[str]:
    """Any "url" or "href" string anywhere in a JSON index (a few levels deep)."""
    if depth > 4:
        return
    if isinstance(body, dict):
        for key, value in body.items():
            if key in {"url", "href"} and isinstance(value, str):
                yield urljoin(base, value)
            else:
                yield from _index_urls(value, base, depth + 1)
    elif isinstance(body, list):
        for item in body[:50]:
            yield from _index_urls(item, base, depth + 1)
