"""A short human report of one run: tools made, gaps found, test results and the stopwatch."""
from __future__ import annotations

from typing import Any


def markdown(url: str, plan: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [f"# {plan['title']}", "", f"Site: {url}", "", plan["description"], "", "## Tools", "",
             "| Tool | Kind | Call | What it is for |", "|---|---|---|---|"]
    for t in plan["tools"]:
        kind = t["kind"] + (" (set by a person)" if t.get("read_ok_by_human") else "")
        lines.append(f"| {t['operation_id']} | {kind} | `{t['method']} {t['path']}` | {t['description']} |")
    if plan.get("skipped"):
        lines += ["", "## Skipped", ""] + [f"- `{s['endpoint']}`: {s['why']}" for s in plan["skipped"]]
    if plan.get("gaps"):
        lines += ["", "## Gaps (shown on the site, no API serves it)", ""]
        lines += [f"- {g['what']} ({g['where']}). Suggestion: {g['suggestion']}" for g in plan["gaps"]]
    if summary["tests"]:
        lines += ["", "## Tests", "", "| Tool | Result | ms | Why |", "|---|---|---|---|"]
        for r in summary["tests"]:
            lines.append(f"| {r['tool']} | {'pass' if r['passed'] else 'FAIL'} | {r['ms']} | {r['why']} |")
    lines += ["", "## Stopwatch (seconds)", ""] + [f"- {k}: {v}" for k, v in summary["timings_s"].items()]
    lines += ["", f"Model cost: about USD {summary['cost_usd']}", ""]
    return "\n".join(lines)
