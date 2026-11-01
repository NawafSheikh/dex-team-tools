"""Write the Workday Orchestrator agent's instructions, actions and connection reference into an agent
workspace (default copilot/agent, or the folder `pac copilot clone` made), ready for `pac copilot push`.

Usage: python build_agent.py [agent folder]
Environment (from your own tenant, after you import the connector and create its connection):
  WORKDAY_CONNECTOR_API   connector API name, e.g. shared_new-5fworkday-20orchestrator-5f<hash>
  WORKDAY_CONNECTION_REF  connection reference logical name the agent uses for that connector
Actions call the connector through the maker's shared connection (mode Maker), so chat users never see or
enter the server key.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "agent"
API = os.environ.get("WORKDAY_CONNECTOR_API", "shared_new-5fworkday-20orchestrator-5fYOURHASH")
REF = os.environ.get("WORKDAY_CONNECTION_REF", f"new_WorkdayOrchestrator.{API}.YOUR_CONNECTION_ID")

STARTER = ("Equipment loans are a mess. Today build us a loan app with approvals and overdue reminders, clean and "
           "analyse the loans export, turn the ops meeting into notes and a follow-up draft, and give me a manager "
           "deck and a one-page user guide.")
ACTIONS = [
    ("PlanWorkday", "Plan and start workday",
     "Use once per new workday: opens it for the user's request, adds every mission in order (M1, M2, ...) with "
     "the agent and why, dependencies, mode and failure policy, and starts it. Returns the plan and the live board link."),
    ("GetWorkday", "Get workday status",
     "Only when the user asks for status (status, how is it going, done?). Never right after planning: missions "
     "take minutes. Returns every mission (agent chain, best of both result, stopwatch, failed checks, retries and "
     "reroutes), the verified facts, deliverable links, the board link and the total workday clock. Use run_id latest."),
    ("GetMission", "Get mission detail",
     "One mission's packet, the worker's handoff note and every attempt with its verifier verdict. Use run_id latest."),
    ("ListMissionKinds", "List mission kinds",
     "The kinds of mission a workday can run and the checks that decide done for each."),
    ("StartWorkday", "Start workday",
     "Start a workday that was created but not started. Not needed after Plan and start workday."),
]


def block(text: str, indent: int = 2) -> str:
    pad = " " * indent
    return "\n".join(pad + line if line else "" for line in text.splitlines())


def main() -> None:
    instructions = (HERE / "instructions.md").read_text(encoding="utf-8").strip()
    assert "\u2014" not in instructions, "no em dashes"
    (AGENT / "agent.mcs.yml").write_text(
        "mcs.metadata:\n  componentName: Workday Orchestrator\nkind: GptComponentMetadata\n"
        f"displayName: Workday Orchestrator\ninstructions: |-\n{block(instructions)}\n"
        "conversationStarters:\n"
        "  - title: Run my workday\n"
        f"    text: {json.dumps(STARTER)}\n"
        "  - title: Status\n    text: status\n",
        encoding="utf-8")
    actions = AGENT / "actions"
    actions.mkdir(exist_ok=True)
    for op_id, name, desc in ACTIONS:
        (actions / f"Workday-{op_id}.mcs.yml").write_text(
            f"mcs.metadata:\n  componentName: Workday - {name}\nkind: TaskDialog\n"
            f"modelDisplayName: {name}\nmodelDescription: {json.dumps(desc)}\n"
            "action:\n  kind: InvokeConnectorTaskAction\n"
            f"  connectionReference: {REF}\n  connectionProperties:\n    mode: Maker\n\n"
            f"  operationId: {op_id}\n\noutputMode: All\n", encoding="utf-8")
    (AGENT / "connectionreferences.mcs.yml").write_text(
        f"connectionReferences:\n  - connectionReferenceLogicalName: {REF}\n"
        f"    connectorId: /providers/Microsoft.PowerApps/apis/{API}\n", encoding="utf-8")
    print(f"wrote instructions, {len(ACTIONS)} actions and the connection reference into {AGENT}")


if __name__ == "__main__":
    main()
