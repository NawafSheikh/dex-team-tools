"""Build the Copilot Studio custom connector (Swagger 2.0) for the workday orchestrator.

Usage: python build_connector.py <host> [out.json]
  host  where server.py is reachable over HTTPS, e.g. workday.example.com (optionally with a base path:
        workday.example.com/api)
The API key is never written into the definition: it is a secure connection parameter (apiProperties.json),
entered once when the connection is created.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

KEY = {"$ref": "#/parameters/ApiKeyHeader"}
RUN_ID = {"name": "run_id", "in": "path", "required": True, "type": "string", "x-ms-summary": "Run ID",
          "description": "Workday run id from Create workday, or 'latest' for the most recent run"}

MISSION_ROW = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Mission id, e.g. M1"},
        "title": {"type": "string"},
        "kind": {"type": "string"},
        "status": {"type": "string", "description": "planned, running, verifying, retrying, rerouted, done, failed, blocked"},
        "agent_chain": {"type": "string", "description": "Agents that worked on it in order, e.g. codex > claude"},
        "why_agent": {"type": "string"},
        "depends_on": {"type": "string"},
        "clock": {"type": "string", "description": "Mission stopwatch m:ss"},
        "attempts": {"type": "integer"},
        "last_reason": {"type": "string", "description": "Why the last attempt was started (first attempt, retry, reroute)"},
        "failed_checks": {"type": "string", "description": "Verifier checks that failed on the last attempt"},
        "packet": {"type": "string", "description": "Path of the mission packet"},
        "mode": {"type": "string", "description": "single or best_of_both"},
        "best_of_both": {"type": "string", "description": "For best_of_both: how each candidate did, who the judge "
                                                           "picked and why, and the final result"},
    },
}
MISSION_FIELDS = {
    "kind": {"type": "string", "x-ms-summary": "Kind",
             "enum": ["pp_tables", "pp_app", "pp_flows", "excel", "deck", "notes", "guide"]},
    "title": {"type": "string", "x-ms-summary": "Title", "description": "Short mission title"},
    "goal": {"type": "string", "x-ms-summary": "Goal", "description": "What the mission must achieve, in your words"},
    "agent": {"type": "string", "x-ms-summary": "Agent", "enum": ["claude", "codex"],
              "description": "The agent you choose (for best_of_both: your first choice)"},
    "why_agent": {"type": "string", "x-ms-summary": "Why this agent", "description": "One sentence"},
    "depends_on": {"type": "string", "x-ms-summary": "Depends on",
                   "description": "Comma separated mission ids that must be verified first, e.g. M1, M2. Empty if none."},
    "notes": {"type": "string", "x-ms-summary": "Notes", "description": "Extra instructions for the worker"},
    "on_fail": {"type": "string", "x-ms-summary": "On failure", "enum": ["retry_then_reroute", "reroute", "retry"],
                "description": "retry_then_reroute: one retry by the same agent, then the other agent"},
    "mode": {"type": "string", "x-ms-summary": "Mode", "enum": ["single", "best_of_both"],
             "description": "best_of_both (excel, deck, notes, guide only): Claude and Codex both do it, the verifier "
                            "checks both, a blind judge picks the better one and the winner may merge in the other's strengths"},
}
RUN_SUMMARY = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "string", "description": "planning, running, done, finished_with_failures"},
        "workday_clock": {"type": "string", "description": "Total workday stopwatch"},
        "missions": {"type": "array", "items": MISSION_ROW},
        "facts": {"type": "object", "description": "Verified facts carried between missions", "additionalProperties": True},
        "deliverables": {"type": "array", "items": {"type": "string"}, "description": "Links to the deliverable files"},
        "board_url": {"type": "string", "description": "Live board for this workday"},
        "inbox": {"type": "array", "items": {"type": "string"}},
        "next": {"type": "string"},
    },
}


def op(op_id, summary, description, params, schema, body=None):
    o = {"summary": summary, "description": description, "operationId": op_id,
         "parameters": [KEY] + params,
         "responses": {"200": {"description": "OK", "schema": schema},
                       "401": {"$ref": "#/responses/Unauthorized"}}}
    if body:
        o["parameters"].append({"name": "body", "in": "body", "required": True, "schema": body})
    return o


PATHS = {
    "/workday/plan": {"post": op(
        "PlanWorkday", "Plan and start workday",
        "One call for the whole day: opens the workday for the user's request, adds every mission in order (M1, M2, "
        "...) and starts it. Missions run as soon as their dependencies are verified by the independent verifier. "
        "Returns the plan with the live board link.",
        [], RUN_SUMMARY,
        {"type": "object", "required": ["request", "missions_json"], "properties": {
            "request": {"type": "string", "x-ms-summary": "Request", "description": "The user's request, word for word"},
            "title": {"type": "string", "x-ms-summary": "Title", "description": "Short name for the workday"},
            "missions_json": {
                "type": "string", "x-ms-summary": "Missions (JSON list)",
                "description": "JSON list of missions, one per deliverable, in dependency order (M1, M2, ...). Each: "
                               "kind (pp_tables, pp_app, pp_flows, excel, deck, notes, guide), title, goal, "
                               "agent (claude or codex), why_agent, depends_on (e.g. \"M1, M2\" or \"\"), mode "
                               "(single or best_of_both; best_of_both only for excel, deck, notes, guide), on_fail "
                               "(retry_then_reroute). Example: [{\"kind\":\"notes\",\"title\":\"Ops meeting notes\","
                               "\"goal\":\"...\",\"agent\":\"claude\",\"why_agent\":\"...\",\"depends_on\":\"\","
                               "\"mode\":\"best_of_both\",\"on_fail\":\"retry_then_reroute\"}]"}}},
            )},
    "/workday/runs": {"post": op(
        "CreateWorkday", "Create workday",
        "Open a new workday run for a request typed by the user. Input files handed out for the day are copied in. "
        "Next: add one mission per task with Add mission, then Start workday.",
        [], RUN_SUMMARY,
        {"type": "object", "required": ["request"], "properties": {
            "request": {"type": "string", "x-ms-summary": "Request", "description": "The user's request, word for word"},
            "title": {"type": "string", "x-ms-summary": "Title", "description": "Short name for the workday"}}})},
    "/workday/runs/{run_id}/missions": {"post": op(
        "AddMission", "Add mission",
        "Add one mission to a workday. You choose the kind, the agent (claude or codex) and say why that agent, "
        "the missions it depends on, and what to do on failure. Each kind has a fixed deliverable and an independent "
        "verifier that decides done.",
        [RUN_ID], {"type": "object", "properties": {
            "mission_id": {"type": "string"}, "packet": {"type": "string"},
            "checks": {"type": "array", "items": {"type": "string"}}}},
        {"type": "object", "required": ["kind", "title", "goal", "agent", "why_agent"], "properties": {
            "kind": {"type": "string", "x-ms-summary": "Kind",
                     "enum": ["pp_tables", "pp_app", "pp_flows", "excel", "deck", "notes", "guide"],
                     "description": "pp_tables = Dataverse tables and sample data; pp_app = canvas app; pp_flows = approval "
                                    "and reminder flows; excel = clean and analyse the loans export; deck = manager "
                                    "PowerPoint; notes = meeting notes, actions and follow-up email draft; guide = one-page "
                                    "Word user guide"},
            "title": {"type": "string", "x-ms-summary": "Title"},
            "goal": {"type": "string", "x-ms-summary": "Goal", "description": "What this mission must achieve, in your words"},
            "agent": {"type": "string", "x-ms-summary": "Agent", "enum": ["claude", "codex"]},
            "why_agent": {"type": "string", "x-ms-summary": "Why this agent"},
            "depends_on": {"type": "string", "x-ms-summary": "Depends on",
                           "description": "Comma separated mission ids that must be verified first, e.g. M1, M2. Empty if none."},
            "notes": {"type": "string", "x-ms-summary": "Notes", "description": "Extra instructions for the worker"},
            "on_fail": {"type": "string", "x-ms-summary": "On failure",
                        "enum": ["retry_then_reroute", "reroute", "retry"],
                        "description": "retry_then_reroute: one retry by the same agent, then the other agent"},
            "mode": {"type": "string", "x-ms-summary": "Mode", "enum": ["single", "best_of_both"],
                     "description": "best_of_both (excel, deck, notes, guide only): Claude and Codex both do it, "
                                    "the verifier checks both, a blind judge picks the better one and the winner "
                                    "may merge in the other's strengths"}}})},
    "/workday/runs/{run_id}/start": {"post": op(
        "StartWorkday", "Start workday",
        "Start the workday after all missions are added. Missions run as soon as their dependencies are verified.",
        [RUN_ID], RUN_SUMMARY)},
    "/workday/runs/{run_id}": {"get": op(
        "GetWorkday", "Get workday status",
        "Status of every mission (agent chain, stopwatch, failed checks, retries and reroutes), the facts carried "
        "between missions, the deliverable links, the live board link and the total workday clock. Use run_id 'latest' "
        "for the most recent workday.",
        [RUN_ID], RUN_SUMMARY)},
    "/workday/runs/{run_id}/missions/{mission_id}": {"get": op(
        "GetMission", "Get mission detail",
        "The mission packet, the handoff note written by the worker, and every attempt with its verifier verdict.",
        [RUN_ID, {"name": "mission_id", "in": "path", "required": True, "type": "string", "x-ms-summary": "Mission ID"}],
        {"type": "object", "properties": {
            "packet_text": {"type": "string"}, "handoff_text": {"type": "string"},
            "attempts": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "mission": {"type": "object", "additionalProperties": True}}})},
    "/workday/kinds": {"get": op(
        "ListMissionKinds", "List mission kinds",
        "The kinds of mission the workday can run and the checks that decide done for each.",
        [], {"type": "object", "properties": {
            "kinds": {"type": "array", "items": {"type": "object", "properties": {
                "kind": {"type": "string"}, "label": {"type": "string"},
                "checks": {"type": "array", "items": {"type": "string"}}}}},
            "agents": {"type": "array", "items": {"type": "string"}}}})},
}


def build(host: str) -> dict:
    host, _, base = host.removeprefix("https://").partition("/")
    paths = copy.deepcopy(PATHS)
    for item in paths.values():  # the key lives in the connection, not in each operation
        for o in item.values():
            o["parameters"] = [p for p in o["parameters"] if p != KEY]
    return {
        "swagger": "2.0",
        "info": {"title": "Workday Orchestrator", "version": "1.0.0",
                 "description": "Plan a workday of missions for Claude Code and Codex, follow it live, and read "
                                "the verified results."},
        "host": host,
        "basePath": "/" + base.strip("/") if base.strip("/") else "/",
        "schemes": ["https"],
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "paths": paths,
        "definitions": {},
        "parameters": {},
        "responses": {"Unauthorized": {"description": "Missing or invalid X-API-Key"}},
        "securityDefinitions": {"api_key": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
        "security": [{"api_key": []}],
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "apiDefinition.swagger.json")
    spec = build(sys.argv[1])
    out.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"{len(spec['paths'])} workday paths written to {out} (the key goes in the connection)")


if __name__ == "__main__":
    main()
