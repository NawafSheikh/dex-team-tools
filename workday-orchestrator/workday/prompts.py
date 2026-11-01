"""Mission packets and worker prompts."""
from __future__ import annotations

from pathlib import Path

from . import config, store
from .kinds import KINDS

POLICY_TEXT = {
    "retry_then_reroute": "If the verifier fails it: one retry by the same agent with the failed checks attached, "
                          "then reroute to the other agent with the handoff and the failure report.",
    "reroute": "If the verifier fails it: reroute straight to the other agent with the failure report.",
    "retry": "If the verifier fails it: one retry by the same agent with the failed checks attached.",
}


def mission_packet(state: dict, m: dict) -> str:
    kind = KINDS[m["kind"]]
    deps = m.get("depends_on", [])
    lines = [
        f"# Mission {m['id']}: {m['title']}",
        "",
        f"- Workday: {state['title']} (`{state['run_id']}`)",
        f"- Kind: {kind['label']}",
        (f"- Mode: **best of both**. Claude and Codex each do this mission independently; the verifier checks "
         f"both, a blind judge picks the better one, and the winner may merge in the other's strengths. "
         f"Orchestrator's first choice: {m['agent']} ({m['why_agent']})"
         if m.get("mode") == "best_of_both" else
         f"- Assigned to: **{m['agent']}**. Why (orchestrator): {m['why_agent']}"),
        f"- Depends on: {', '.join(deps) if deps else 'nothing, can start at once'}",
        "",
        "## Goal (from the orchestrator)",
        "",
        m["goal"].strip(),
        "",
        "## Deliverable",
        "",
        *[f"- {x}" for x in kind["deliverable"]],
        "",
        "## Done when (checked by the independent verifier, not by the worker)",
        "",
        *[f"- [ ] {x}" for x in kind["checks"]],
    ]
    if m.get("notes"):
        lines += ["", "## Orchestrator's notes", "", m["notes"].strip()]
    policy = (POLICY_TEXT[m["on_fail"]] if m.get("mode") != "best_of_both" else
              "If only one result passes the verifier, that one is used. If both fail: one more round for both, "
              "each with its own failed checks attached.")
    lines += ["", "## On failure", "", policy, ""]
    return "\n".join(lines)


def worker_prompt(state: dict, m: dict, agent: str, rdir: Path, failure: dict | None,
                  where: dict | None = None) -> str:
    """`where` overrides the inbox/shared/work folders (best-of-both candidates work in their own copies)
    and may carry an extra `note` placed right after the introduction."""
    where = where or {}
    packet = rdir / m["packet"]
    handoffs = [rdir / "handoffs" / f"{d}.md" for d in m.get("depends_on", [])]
    work = where.get("work", rdir / "work" / m["id"])
    inbox, shared = where.get("inbox", rdir / "inbox"), where.get("shared", rdir / "shared")
    parts = [
        f"You are {agent}, one of two AI coding agents on a team run by an orchestrator. You are doing ONE "
        f"mission of today's workday.",
        *([where["note"]] if where.get("note") else []),
        f"Read your mission packet first: {packet}",
        f"Shared state of the whole workday (read only): {rdir / 'STATE.md'}",
    ]
    if handoffs:
        parts.append("Handoff notes from the missions you depend on (names, ids, paths you need): "
                     + ", ".join(str(h) for h in handoffs))
    parts += [
        f"Input files: {inbox}. Shared deliverables folder: {shared} (save deliverables "
        f"there with the exact names in the packet; insert shared images into documents as they are, do not "
        f"re-encode them). Your own working folder: {work}.",
        f"Tools: Python with pandas, openpyxl, python-pptx, python-docx and matplotlib is "
        f"{config.PYTHON}. LibreOffice is `soffice --headless`. The Power Platform "
        "demo environment is reached with the `dv` command (run `dv --help`; it handles sign-in).",
        "Rules: never use em dashes (the long dash character) in anything you write; fictional data only; never send email, post, share, or delete anything you did not create "
        "in this mission; do not touch other missions' tables or files.",
        f"When you are finished, write {work / 'HANDOFF.md'} with these sections: What I did; Outputs (exact "
        "paths); Names and ids the next missions need; How I checked it; Open issues. Keep it short and exact.",
    ]
    if failure:
        parts += [
            "",
            f"This is attempt {failure['attempt']}. The previous attempt by {failure['agent']} FAILED "
            f"verification. Failed checks:",
            *[f"- {c['name']}: {c['detail']}" for c in failure["checks"] if not c["ok"]],
        ]
        if failure.get("worker_error"):
            parts.append(f"Worker error: {failure['worker_error']}")
        parts.append(f"Earlier work is in {work}. Fix exactly what failed, then update HANDOFF.md.")
    return "\n".join(parts)


def write_packet(state: dict, m: dict) -> str:
    rel = f"missions/{m['id']}-{store.slug(m['title'])}.md"
    (store.base() / state["run_id"] / rel).write_text(mission_packet(state, m), encoding="utf-8")
    return rel
