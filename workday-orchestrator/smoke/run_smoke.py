"""End-to-end smoke run without any AI: plan a one-mission workday through the HTTP API, let the engine dispatch
it to a stand-in agent, and wait for the independent verifier's verdict.

Usage: python smoke/run_smoke.py
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "fixtures"))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="workday-smoke-"))
    py = sys.executable.replace("\\", "/")
    agent = f'"{py}" "{(HERE / "fake_agent.py").as_posix()}"'
    os.environ.update(WORKDAY_API_KEY=secrets.token_hex(32), WORKDAY_INBOX=str(tmp / "inbox"),
                      WORKDAY_TRUTH_DIR=str(tmp / "truth"), WORKDAY_CLAUDE_CMD=agent, WORKDAY_CODEX_CMD=agent)
    import make_fixtures
    make_fixtures.main(str(tmp / "inbox"))
    make_fixtures.write_truth(str(tmp / "truth"))

    import importlib
    from workday import config
    importlib.reload(config)
    from workday import routes
    from workday.verifiers import docs
    routes.INBOX, docs.TRUTH_DIR = config.INBOX, config.TRUTH_DIR
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.create_app(tmp / "data"))
    headers = {"X-API-Key": os.environ["WORKDAY_API_KEY"]}
    missions = [{"kind": "notes", "title": "Ops meeting notes", "goal": "Notes, actions and a follow-up draft",
                 "agent": "claude", "why_agent": "writing and judgement", "depends_on": "", "mode": "single",
                 "on_fail": "retry_then_reroute"}]
    plan = client.post("/workday/plan", headers=headers, json={
        "request": "Turn the ops meeting into notes and a follow-up draft.", "title": "Smoke day",
        "missions_json": json.dumps(missions)})
    plan.raise_for_status()
    print("planned:", plan.json()["run_id"])
    for _ in range(60):
        run = client.get("/workday/runs/latest", headers=headers).json()
        if run["status"] not in ("planning", "running"):
            break
        time.sleep(2)
    m = run["missions"][0]
    print(f"run {run['status']}; mission {m['id']} {m['status']} by {m['agent_chain']} in {m['clock']}"
          f"{'; failed: ' + m['failed_checks'] if m['failed_checks'] else ''}")
    return 0 if run["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
