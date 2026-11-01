"""Human approval for anything that might change data.

Two ways to ask: a terminal prompt (default, for anyone running the tool) or an approval file that a dashboard or
another person answers by adding `"decision": "approve" | "deny"` to the same JSON file. Silence is never consent:
the file backend waits for a written decision, and the terminal backend treats anything but "y" as no.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)
POLL_SECONDS = 5


@dataclass(frozen=True)
class Request:
    slug: str
    title: str
    detail: str
    reason: str


class Approver(Protocol):
    def ask(self, req: Request) -> bool: ...


class TerminalApprover:
    def ask(self, req: Request) -> bool:
        print(f"\nAPPROVAL NEEDED: {req.title}\n{req.detail}\nWhy: {req.reason}")
        answer = input("Allow this? [y/N] ").strip().lower()
        return answer == "y"


class DenyAll:
    """Unattended runs: every write is refused and recorded."""

    def ask(self, req: Request) -> bool:
        log.info("write refused (unattended): %s", req.title)
        return False


class FileApprover:
    def __init__(self, folder: Path, source: str) -> None:
        self.folder = folder
        self.source = source

    def ask(self, req: Request) -> bool:
        path = self.folder / f"{req.slug}.json"
        self.folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "title": req.title, "detail": req.detail, "reason": req.reason, "source": self.source,
            "created_at": datetime.now(timezone.utc).isoformat(), "cost_note": "none",
        }, indent=2), encoding="utf-8")
        log.info("waiting for a decision in %s", path)
        while True:
            decision = _decision(path)
            if decision is not None:
                return decision
            time.sleep(POLL_SECONDS)


def _decision(path: Path) -> bool | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("approval file unreadable, still waiting: %s", exc)
        return None
    value = str(data.get("decision", "")).lower()
    if value in {"approve", "approved", "yes", "allow"}:
        return True
    if value in {"deny", "denied", "no", "reject"}:
        return False
    return None
