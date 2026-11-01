# Workday orchestrator (Episode 3)

Copilot Studio plans a day of work. Claude Code and Codex do it. An independent verifier decides when each
piece is really done.

Episode 3: "Copilot Studio orchestrates Claude Code and Codex" (video coming).

## What it does

1. Someone types a day of work into a Copilot Studio agent ("build us a loan app, clean the loans export, turn
   the ops meeting into notes, give me a manager deck").
2. The agent splits it into **missions**, one per deliverable. For each it picks the agent (Claude Code or
   Codex) and says why, sets the dependencies, the failure policy, and optionally **best of both**. It sends the
   whole plan in one call (`PlanWorkday`).
3. This server runs the plan. A mission starts as soon as the missions it depends on are verified. Each worker
   gets a mission packet, the shared state of the day (`STATE.md`) and the handoff notes of the missions before
   it, and must leave its own `HANDOFF.md`.
4. An **independent verifier** per mission kind decides done. It never trusts the worker's word: it recounts
   the spreadsheet from the raw export, opens the deck and checks the chart is byte-identical, checks every
   action owner against the meeting attendees, queries Dataverse for the tables and flows.
5. On a failed check: retry with the failed checks attached, then reroute to the other agent with the
   handoff and the failure report. An agent that hit its usage limit is never given that mission again.
6. **Best of both** (file missions): Claude and Codex each do the mission in their own copy, the verifier
   checks both, a blind judge (A/B in random order) picks the better one and lists what the loser does better,
   and the winner may merge that in. The merge must pass the verifier again or the verified winner stands.
7. A live board (`/workday/board/<run>`) shows every mission, agent, stopwatch, verdict, retry and reroute.

Copilot is the orchestrator: it plans the day, picks the agent for every mission and sets the rules. The engine
runs that plan and the verifier decides done. Copilot does not watch, retry or verify by itself; it reports
status when you ask.

## Mission kinds

| Kind | Deliverable | Verified by |
|---|---|---|
| `excel` | Clean and analyse a messy loans export: workbook with Clean, Top items (with chart) and Summary sheets | independent recount from the raw file |
| `notes` | Meeting notes (decisions, actions table) and an unsent follow-up email draft | owners are attendees, dates are real, every agreed action present |
| `deck` | 8 to 10 slide manager deck | slide count, chart and screenshots byte-identical, numbers match the verified analysis |
| `guide` | One-page user guide | renders to exactly one page, covers borrow/return/approve/overdue, real screenshot |
| `pp_tables` | Dataverse tables and fictional sample data | Dataverse Web API: tables, columns, counts, lookups, overdue rows |
| `pp_flows` | Approval and overdue reminder cloud flows | both on; a test loan really starts an approval run |
| `pp_app` | Canvas app on those tables | Power Apps API: created and published this run, uses the table, 3 screenshots |

The file kinds run anywhere. The `pp_` kinds need a Power Platform environment (use a demo or sandbox one).

## Let your agent set this up

The [Dex Kit](https://mcpforwork.com/kit?utm_source=github&utm_medium=readme&utm_content=workday-orchestrator) includes this tool as a learned skill: your Claude Code or Codex installs it, configures it, tests it and runs it for you, end to end. You bring your own keys, host and Microsoft environment. The code here stays free as proof; the kit is the version your agent can follow step by step.

## Run it

```bash
pip install -r requirements.txt
python -m pytest -q                      # 39 tests, no AI calls
python smoke/run_smoke.py                # end to end through the HTTP API with a stand-in agent
```

Real run:

```bash
cp .env.example .env                     # set WORKDAY_API_KEY (openssl rand -hex 32) and the rest
python fixtures/make_fixtures.py inbox --truth truth
set -a; . ./.env; set +a
python server.py                         # http://127.0.0.1:8091, docs at /docs
```

The agents run as headless CLIs in each mission's work folder, with the mission prompt on stdin
(`WORKDAY_CLAUDE_CMD`, `WORKDAY_CODEX_CMD`). Install and sign in to Claude Code and Codex on that machine first.
They work unattended with full permissions inside the run folder, so run the server on a machine or VM you are
happy for them to work on, never on one with secrets they could read.

### Power Platform missions

- `tools/dv.js`: a small Dataverse / Flow / Power Apps REST helper the workers and verifiers share
  (`cd tools && npm install && npm link`, then `dv login` once). Workers call `dv`; they never see the token cache.
- `tools/pa_apps.py`: lists canvas apps with their ids (install it on PATH as `pa-apps`).
- `tools/reset_demo.py --since <time>`: lists (and with `--apply` removes) only what the missions created.
- `pp_app` also needs Microsoft's Canvas Authoring MCP, Microsoft's canvas-apps skill references
  (`WORKDAY_CANVAS_SKILLS`) and a `desk` command that lets the worker see and click a browser running Power Apps
  Studio. That desktop-control part is not in this repo. It is the least reliable mission (see limits).

### Copilot Studio side

1. Build the connector: `python connector/build_connector.py your-host.example.com connector/apiDefinition.swagger.json`,
   then create it with `pac connector create --api-definition-file ... --api-properties-file connector/apiProperties.json`
   (or import it in the maker portal). Create a connection and paste your `WORKDAY_API_KEY`; it is stored
   encrypted in the connection, never in the definition.
2. Create an agent (`pac copilot init` or the portal), set `WORKDAY_CONNECTOR_API` and `WORKDAY_CONNECTION_REF`
   to your connector and connection reference, run `python copilot/build_agent.py <agent folder>`, then
   `pac copilot push` and publish. `copilot/instructions.md` is the agent's whole brief.
3. Ask it: "Equipment loans are a mess. Today build us a loan app with approvals and overdue reminders, clean
   and analyse the loans export, turn the ops meeting into notes and a follow-up draft, and give me a manager
   deck and a one-page user guide."

## API

All under `/workday`, key in `X-API-Key` (board and files use the per-run view key in the link instead).

| Method | Path | Use |
|---|---|---|
| POST | `/plan` | Create, add every mission, start: one call |
| POST | `/runs`, `/runs/{id}/missions`, `/runs/{id}/start` | The same in steps |
| GET | `/runs/{id}` (`latest` works) | Status, stopwatch, agent chain, failed checks, facts, deliverable links |
| GET | `/runs/{id}/missions/{mid}` | Packet, handoff and every attempt with its verdict |
| POST | `/runs/{id}/missions/{mid}/retry` | Reopen a failed mission (optionally another agent, extra notes) |
| GET | `/kinds` | Mission kinds and their checks |
| GET | `/board/{id}?k=`, `/files/{id}/{path}?k=` | Live board, deliverables |

## Honest limits

- What we saw on our runs: the file missions (excel, notes, deck, guide) usually pass first time. Tables and
  flows passed after at most one retry. The canvas app mission failed three attempts in the filmed run and
  passed when reopened with a "finish the existing app" note. The app it built works, but its layout was rough.
  The verifier checks that the app exists, is published, uses the table and has screenshots. It does not judge
  polish.
- Copilot Studio throttles bursts of tool calls, which is why planning is one `PlanWorkday` call. Its connector
  actions cannot send a list of objects, so the plan travels as `missions_json` text.
- Claude Code and Codex hit usage limits and drop connections mid-response. The engine handles that with retry
  and reroute, but a day can still end with failures. They are reported, never hidden.
- The runner starts real agents with broad permissions. Keep it on an isolated machine.
- Known gaps (open): the Excel verifier recounts the Summary numbers from the raw export and checks the chart,
  but does not yet reconcile the `Clean` sheet row by row. A retry or reroute gets the failed checks and the
  earlier work folder, but the failed attempt's `HANDOFF.md` is cleared rather than archived for it.
- All data is fictional.
