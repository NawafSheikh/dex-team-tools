# Website to tools (Episode 6)

Give it a website you own and a goal. An AI agent opens the site in a real browser, clicks through it like a
visitor while recording every API call the pages make, decides which calls matter, writes the descriptions, and
builds the same tools two ways:

- **A. An OpenAPI 2.0 file** you import into Copilot Studio as a REST API tool (standard harness, no server).
- **B. A small MCP server** (streamable HTTP) generated from the same plan, for Copilot Studio's MCP tool, Claude,
  VS Code or any other MCP client.

Then it tests every tool through the generated server and writes a report with a stopwatch.

Episode 6: "I gave an AI agent a website. It built its own Copilot tools." (video coming). The live result is the
public mcpforwork MCP server: `https://mcpforwork.com/mcp`, OpenAPI file at `https://mcpforwork.com/openapi.json`.

Want to see how the team built it? Open the commit history: each bot commits its own part.

## How it works

| Step | What happens | Who decides |
|---|---|---|
| Discover | Playwright drives a real browser. Claude reads the page (text plus numbered buttons, links and fields) and picks one action at a time toward the goal. Every request is recorded, and the network log is saved as `network.har`. If the site publishes an RFC 9727 API catalog (`/.well-known/api-catalog`), its links are read too (GET only). | Claude |
| Group | Calls are grouped into endpoints (method, host, path with ids turned into `{id}`). Third-party hosts are dropped. | Code |
| Plan | Claude gets every endpoint with real request and response samples and the visited pages' text. It picks the tools, names them, writes descriptions for an orchestrator, sorts read from write, and lists gaps: things the pages show that no API serves. | Claude |
| Generate | `openapi.json` (Swagger 2.0) and `mcp-server/` (Node, `@modelcontextprotocol/sdk`) are written from the same plan. | Code |
| Test | The generated server is started locally. Claude writes one realistic case per tool, every tool is called, and a second Claude call judges each answer. | Claude |

## Safety rails

- **Writes wait for a person.** During discovery, any same-site request that is not GET, HEAD or OPTIONS is held
  until a person approves it (terminal prompt or approval file). Refused writes are aborted and still recorded, so
  the planner knows the endpoint exists.
- **The write floor is code, not a model.** Anything that is not GET or HEAD is a write, whatever the model says.
  Only a person can mark a POST as read-only (`--read-ok EstimateJob`), and that is recorded in the plan.
- **Generated write tools need confirm.** Called without `confirm=true`, a write tool returns a preview and sends
  nothing. The server instructions tell the agent to set it only after the user agreed.
- **Rate limits.** Every non-GET call is limited per caller (3 per hour by default).
- **Only the site's own hosts.** Third-party requests are never turned into tools; third-party and beacon writes
  are aborted during discovery, and cookie banners are declined.
- **Hidden form fields stay hidden.** Fields that are always empty and never shown (often anti-spam traps) are left
  out of the tool parameters.
- **Lead tagging.** `--tag` adds fixed fields the server fills itself (for example a source tag) and the agent
  never sees. `--rest-tag` does the same in the OpenAPI file as `x-ms-visibility: internal` defaults.

Only run it on sites you own or APIs whose terms allow it.

## Setup

Needs Python 3.11+, Node 20+, Google Chrome or Playwright's Chromium, and the Claude Code CLI signed in
(`claude`). The model calls run through the CLI on your own Claude login; no API key is read.

```bash
cd website-to-tools
pip install -r requirements.txt
python -m pytest -q
```

## Run

```bash
python -m w2t run https://example.com \
  --goal "Use everything a visitor can do: search, filter, open a product, ask for a quote" \
  --out runs/example --headed --channel chrome --test
```

| Option | Meaning |
|---|---|
| `--headed` | Show the browser (good for filming) |
| `--approve terminal\|file\|deny` | How writes are approved during discovery (default terminal) |
| `--read-ok OpId ...` | Operation ids a person declares read-only |
| `--tag JSON` / `--rest-tag JSON` | Fixed fields for the MCP server / the OpenAPI file |
| `--reuse` | Reuse `discovery.json` in `--out` |
| `--keep-plan` | Reuse a reviewed `plan.json` instead of planning again (no model call) |
| `--test` | Start the generated server and test every tool |

Output in `--out`: `discovery.json`, `network.har`, `plan.json`, `openapi.json`, `mcp-server/`, `summary.json`,
`REPORT.md`.

### Run the generated server

```bash
cd runs/example/mcp-server && npm install && node serve.mjs 8080   # POST http://localhost:8080/mcp
```

`mcp-server.mjs` also exports a default `(req, res)` handler, so it runs as a Vercel or other Node function as is.

### Add it to Copilot Studio

- **REST API tool**: Tools, Add a tool, New tool, REST API, upload `openapi.json`. Turn on the tool's user
  confirmation for any write tool: this path calls the site directly, so the server's confirm step does not apply.
- **MCP tool**: Tools, Add a tool, New tool, Model Context Protocol, then the server URL.

## On mcpforwork.com

| Run | What it found | Tools |
|---|---|---|
| 1 | Only `POST /api/estimate` and `POST /api/job` (both held as writes). It reported on its own that the team, the work record and the pricing have no API: they live in the page's script. | 2 |
| 2 | After the team added a read-only `/api/site` and an API catalog, the agent found them through the catalog. | 6, all tests pass |

Run 2 took about 7 minutes end to end (about 5 of them clicking through the site) and about USD 0.37 of Claude
usage.

## Honest limits

- Discovery only finds what the pages call while the agent is there. Features behind sign-in, or not reached in
  `--max-steps`, are missed; the gap list says what looks missing.
- A refused write has no response sample, so its response schema is a free-form object until someone approves one
  real call.
- Plans differ a little between runs (names, wording). Review `plan.json` once, then use `--keep-plan`.
- The rate limit lives in memory per server instance: on serverless platforms each warm instance counts on its
  own. Put a shared store behind it for heavy traffic.
- The judge in the test step is a model. It catches wrong or empty answers well, but it is not a contract test.
