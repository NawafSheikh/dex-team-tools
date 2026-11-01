"""website-to-tools: URL and goal in; OpenAPI file, MCP server and a tested tool set out.

    python -m w2t run https://example.com --goal "..." --out runs/example [--headed] [--approve terminal]
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import discover, mcpgen, openapi, plan as planner, probe, report
from .approval import Approver, DenyAll, FileApprover, TerminalApprover
from .endpoints import group_calls

log = logging.getLogger("w2t")


def approver_for(kind: str, folder: str) -> Approver:
    if kind == "terminal":
        return TerminalApprover()
    if kind == "file":
        return FileApprover(Path(folder).expanduser(), source="website-to-tools")
    return DenyAll()


def run(args: argparse.Namespace) -> dict[str, Any]:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    clock = time.time()
    site_host = (urlsplit(args.url).hostname or "").removeprefix("www.")
    approver = approver_for(args.approve, args.approvals_dir)

    if args.reuse and (out / "discovery.json").exists():
        found = json.loads((out / "discovery.json").read_text(encoding="utf-8"))
        cost = 0.0
    else:
        d = discover.run(args.url, args.goal, approver, out, max_steps=args.max_steps, headed=args.headed,
                         channel=args.channel, model=args.model)
        found, cost = d.__dict__, d.cost_usd
    timings["discover"] = time.time() - clock

    t = time.time()
    endpoints, assets = group_calls(found["calls"], site_host)
    if args.keep_plan and (out / "plan.json").exists():
        data = mark_reads(json.loads((out / "plan.json").read_text(encoding="utf-8")), set(args.read_ok))
    else:
        plan = planner.make(args.goal, endpoints, assets, found.get("pages", {}), model=args.model)
        data = mark_reads(plan.data, set(args.read_ok))
        cost += plan.cost_usd
    (out / "plan.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    timings["plan"] = time.time() - t

    t = time.time()
    rest_tag = json.loads(args.rest_tag) if args.rest_tag else None
    spec = openapi.build(data, endpoints, tag=rest_tag)
    (out / "openapi.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    server_dir = mcpgen.write(data, out, name=args.name or site_host.replace(".", "-") + "-tools",
                              tag=json.loads(args.tag) if args.tag else None)
    timings["generate"] = time.time() - t

    results: list[probe.Result] = []
    if args.test:
        t = time.time()
        proc, port = probe.start_local(server_dir, args.port)
        try:
            results, test_cost = probe.run(f"http://127.0.0.1:{port}/mcp", data, model=args.model)
            cost += test_cost
        finally:
            proc.terminate()
        timings["test"] = time.time() - t
    timings["total"] = time.time() - clock
    summary = {"url": args.url, "tools": len(data["tools"]), "timings_s": {k: round(v, 1) for k, v in timings.items()},
               "cost_usd": round(cost, 3), "tests": [r.__dict__ for r in results]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "REPORT.md").write_text(report.markdown(args.url, data, summary), encoding="utf-8")
    return summary


def mark_reads(data: dict[str, Any], read_ok: set[str]) -> dict[str, Any]:
    """A person may declare that a non-GET call only reads (for example an estimate). Recorded in the plan."""
    tools = [{**t, "kind": "read", "read_ok_by_human": True} if t["operation_id"] in read_ok else t
             for t in data["tools"]]
    return {**data, "tools": tools}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="w2t")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="discover, plan, generate and test")
    r.add_argument("url")
    r.add_argument("--goal", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--name", default="")
    r.add_argument("--headed", action="store_true")
    r.add_argument("--channel", default=None, help="browser channel, e.g. chrome")
    r.add_argument("--max-steps", type=int, default=25)
    r.add_argument("--model", default="sonnet")
    r.add_argument("--approve", choices=["terminal", "file", "deny"], default="terminal")
    r.add_argument("--approvals-dir", default="~/.ai-os/harness/state/approvals")
    r.add_argument("--read-ok", nargs="*", default=[], help="operation ids a person declares read-only")
    r.add_argument("--tag", default="", help='JSON, e.g. {"body": {"src": "?utm_source=mcp"}}')
    r.add_argument("--rest-tag", default="", help="same as --tag, for the OpenAPI (REST tool) path")
    r.add_argument("--reuse", action="store_true", help="reuse discovery.json in --out")
    r.add_argument("--keep-plan", action="store_true",
                   help="reuse plan.json in --out (a reviewed, frozen plan) instead of planning again")
    r.add_argument("--test", action="store_true", help="start the generated server and test every tool")
    r.add_argument("--port", type=int, default=0, help="local test port (0 = any free port)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    summary = run(args)
    print(json.dumps({k: summary[k] for k in ("tools", "timings_s", "cost_usd")}, indent=2))
    failed = [t for t in summary["tests"] if not t["passed"]]
    return 1 if failed else 0
