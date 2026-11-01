"""Step 1, discovery: Claude drives a real browser through the site toward a goal while every request is recorded.

Writes are gated: any same-site request that is not GET/HEAD/OPTIONS is held until a human approves it; refused
writes are aborted and still recorded (method, URL and body) so the planner knows the endpoint exists.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Request as PwRequest
from playwright.sync_api import Route, sync_playwright

from . import catalog, llm, page as pg
from .approval import Approver, Request
from .endpoints import in_scope

log = logging.getLogger(__name__)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_BODY = 20_000

STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string", "description": "one short sentence: what you are doing and why"},
        "action": {"type": "string", "enum": ["click", "type", "scroll_down", "scroll_up", "goto", "back", "done"]},
        "n": {"type": "integer", "description": "element number for click/type"},
        "text": {"type": "string", "description": "text to type"},
        "url": {"type": "string", "description": "same-site URL for goto"},
    },
    "required": ["thought", "action"],
}

SYSTEM = (
    "You explore a website like a curious first-time visitor so that every API the site's own pages call gets used "
    "at least once. You are given the goal, the current page (its text and numbered interactive elements), what "
    "you did so far and which API calls have been seen. Pick ONE next action. Prefer actions that make the page "
    "talk to its server: open sections and tools, use estimators, search boxes, filters, tabs, forms. When a form "
    "needs input, type realistic but clearly labelled test content (for a name use 'Test Visitor', for an email "
    "use test@example.com, for free text say it is a test). Submitting is allowed: writes are held for a human. Decline or close cookie and consent banners (never accept tracking). "
    "Stay on the same site. Say done when the goal's features have all been exercised or nothing new is left."
)


@dataclass
class Discovery:
    url: str
    goal: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    pages: dict[str, str] = field(default_factory=dict)
    cost_usd: float = 0.0
    seconds: float = 0.0

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / "discovery.json"
        out.write_text(json.dumps(self.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")
        return out


class _Recorder:
    def __init__(self, site_host: str, approver: Approver, record: list[dict[str, Any]]) -> None:
        self.site_host = site_host
        self.approver = approver
        self.record = record
        self.decided: dict[str, bool] = {}
        self.current_page = ""

    def route(self, route: Route, request: PwRequest) -> None:
        host = urlsplit(request.url).hostname or ""
        if request.method in SAFE_METHODS:
            route.continue_()
            return
        if not in_scope(host, self.site_host) or request.resource_type == "ping":
            route.abort()  # third-party or beacon writes are never sent during discovery
            return
        key = f"{request.method} {urlsplit(request.url).path}"
        if key not in self.decided:
            self.decided[key] = self.approver.ask(Request(
                slug="w2t-write-" + hashlib.sha1(key.encode()).hexdigest()[:10], title=f"The agent wants to send {key}",
                detail=f"Body: {(request.post_data or '')[:600]}",
                reason="This request may change data on the site, so a person decides."))
        if self.decided[key]:
            route.continue_()
            return
        self._add(request, blocked=True)
        route.abort()

    def finished(self, request: PwRequest) -> None:
        self._add(request, blocked=False)

    def _add(self, request: PwRequest, *, blocked: bool) -> None:
        entry: dict[str, Any] = {
            "method": request.method, "url": request.url, "resource_type": request.resource_type,
            "request_body": (request.post_data or "")[:MAX_BODY] or None, "page": self.current_page,
            "blocked": blocked, "at": time.time(),
        }
        response = None if blocked else request.response()
        if response is not None:
            entry["status"] = response.status
            entry["content_type"] = response.headers.get("content-type", "")
            if request.resource_type in {"xhr", "fetch"}:
                entry["response_body"] = _body(response)
            else:
                entry["response_bytes"] = int(response.headers.get("content-length") or 0)
        self.record.append(entry)


def _body(response: Any) -> str | None:
    try:
        return response.text()[:MAX_BODY]
    except Exception as exc:  # body can be gone after navigation; record why instead of failing the run
        log.debug("response body unavailable: %s", exc)
        return None


def run(url: str, goal: str, approver: Approver, out: Path, *, max_steps: int = 25, headed: bool = True,
        model: str = llm.DEFAULT_MODEL, channel: str | None = None, cdp: str = "") -> Discovery:
    found = Discovery(url=url, goal=goal)
    site_host = (urlsplit(url).hostname or "").removeprefix("www.")
    rec = _Recorder(site_host, approver, found.calls)
    started = time.time()
    with sync_playwright() as p:
        if cdp:
            # A browser someone else started (for example on a filmed desktop, reached through an SSH tunnel):
            # the model keys stay on this machine, only browser commands cross the tunnel.
            browser = p.chromium.connect_over_cdp(cdp)
        else:
            browser = p.chromium.launch(headless=not headed, channel=channel)
        ctx = browser.new_context(viewport=None if cdp else {"width": 1600, "height": 900},
                                  record_har_path=str(out / "network.har"))
        ctx.route("**/*", rec.route)
        ctx.on("requestfinished", rec.finished)
        page = ctx.new_page()
        found.calls.extend(catalog.probe(ctx.request, url, site_host))
        open_page(page, url)
        for step in range(max_steps):
            rec.current_page = page.url
            if not _step(page, found, step, site_host, model):
                break
        ctx.close()
        if not cdp:
            browser.close()  # never close a browser we did not start
    found.seconds = round(time.time() - started, 1)
    found.save(out)
    return found


def open_page(page: Any, url: str) -> None:
    """Navigate and wait until the document says it is complete. Playwright's own load and networkidle events
    can fail to arrive on real pages (analytics, consent scripts), so the document state is the signal."""
    page.goto(url, wait_until="commit")
    for _ in range(120):  # up to about a minute; polled through DevTools so a strict page CSP cannot block it
        try:
            if page.evaluate("() => document.readyState") == "complete":
                break
        except PlaywrightError:
            pass  # the document is being replaced; ask again
        page.wait_for_timeout(500)
    page.wait_for_timeout(1200)


def _step(page: Any, found: Discovery, step: int, site_host: str, model: str) -> bool:
    snap = pg.snapshot(page)
    found.pages.setdefault(snap["url"].split("#")[0], snap["text"])
    seen = sorted({f"{c['method']} {urlsplit(c['url']).path}" for c in found.calls
                   if c["resource_type"] in {"xhr", "fetch"}})
    prompt = json.dumps({"goal": found.goal, "step": step, "page": snap, "history": found.steps[-12:],
                         "api_calls_seen": seen}, ensure_ascii=False)
    result = llm.ask_json(prompt, STEP_SCHEMA, system=SYSTEM, model=model)
    found.cost_usd += result.cost_usd
    act = result.data
    found.steps.append({"step": step, "url": page.url, **act})
    log.info("step %d: %s %s", step, act["action"], act.get("thought", ""))
    if act["action"] == "done":
        return False
    try:
        _do(page, act, site_host)
    except Exception as exc:  # a stale element or a refused navigation is reported back to the model next step
        found.steps[-1]["error"] = str(exc)[:200]
        log.warning("action failed: %s", exc)
    page.wait_for_timeout(1200)
    return True


def _do(page: Any, act: dict[str, Any], site_host: str) -> None:
    kind = act["action"]
    if kind == "click":
        pg.glide_click(page, int(act["n"]))
    elif kind == "type":
        pg.human_type(page, int(act["n"]), act.get("text", ""))
    elif kind in {"scroll_down", "scroll_up"}:
        pg.scroll(page, kind.removeprefix("scroll_"))
    elif kind == "back":
        page.go_back()
    elif kind == "goto":
        target = act.get("url", "")
        if not in_scope((urlsplit(target).hostname or site_host).removeprefix("www."), site_host):
            raise ValueError(f"refused to leave the site: {target}")
        open_page(page, target if urlsplit(target).scheme else page.url.split("#")[0].rstrip("/") + "/" + target.lstrip("/"))
