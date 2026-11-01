"""Verifier registry: one independent done-check per mission kind."""
from __future__ import annotations

from pathlib import Path

from . import docs, excel, pp

VERIFIERS = {
    "pp_tables": pp.verify_tables,
    "pp_app": pp.verify_app,
    "pp_flows": pp.verify_flows,
    "excel": excel.verify,
    "deck": docs.verify_deck,
    "notes": docs.verify_notes,
    "guide": docs.verify_guide,
}


def run(kind: str, rdir: Path, state: dict, mission: dict) -> dict:
    fn = VERIFIERS[kind]
    try:
        return fn(rdir, state, mission)
    except Exception as exc:  # a crashing verifier is a failed check, never a pass
        return {"passed": False, "checks": [{"name": "verifier ran", "ok": False,
                                             "detail": f"{type(exc).__name__}: {exc}"}],
                "facts": {}, "outputs": {}}
