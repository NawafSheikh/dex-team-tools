# Dex team tools

The working tools behind the "Dex and her team" videos: AI agents in Microsoft Copilot Studio doing real jobs
with Claude Code and Codex. Every tool here ran on camera. This repo is the proof, with the code, the tests, and
the honest limits.

Built by Dex's AI team, reviewed by Nawaf.

| Tool | What it does | Episode |
|---|---|---|
| [workday-orchestrator](workday-orchestrator/) | Copilot Studio plans a day of work into missions. Claude Code and Codex do them. An independent verifier decides when each one is done, failures are retried or rerouted, and handoff notes carry state between missions. A live board shows it all. | Episode 3 (video coming) |
| [copilot-dev-tools](copilot-dev-tools/) | An MCP server that gives a Copilot Studio agent Claude Code's toolset: bash, PowerShell, files and edits, glob and grep, git, tests and builds, processes, web, a task list and sub-agents. Every call runs in a firewalled sandbox, passes an allow-list and is logged. | Episode 4 (video coming) |
| [training-video-generator](training-video-generator/) | A Copilot Studio agent turns an SOP or procedure document into a narrated, captioned training video. The agent writes a scene plan; a small service compiles it to a HyperFrames composition and renders the MP4. No video model, no GPU. | Episode 5 (video coming) |

Earlier episode: [Episode 2 on YouTube](https://www.youtube.com/watch?v=wKeOZ57zS4w). More at
[mcpforwork.com](https://mcpforwork.com).

## The team

The commits in this repo are made by the team's own bot accounts, so you can see who did what. They are AI
agents, not people, and their accounts are clearly marked as bots.

| Bot | Role |
|---|---|
| Dex (`dex-ai-developer-team-lead[bot]`) | AI developer and team lead: scopes the job, writes the top-level README, ships the release |
| Lyra (`lyra-ai-copilot-engineer[bot]`) | AI Copilot engineer: builds the Copilot Studio agents and the orchestrator |
| Theo (`theo-ai-f-o-developer[bot]`) | AI F&O developer: architecture notes and the questions nobody else asks |
| Quinn (`quinn-ai-data-analyst[bot]`) | AI data analyst: tests, checks, numbers against the source |
| Rook (`rook-ai-admin[bot]`) | AI admin: security, sandboxing, the open-source audit |

Nawaf reviews everything before it is published.

## Let your agent set this up

Each tool is also in the [Dex Kit](https://mcpforwork.com/kit?utm_source=github&utm_medium=readme&utm_content=top-level) as a learned skill: your Claude Code or Codex installs it, configures it, tests it and runs it for you, end to end. The code in this repo stays free as proof. The kit is the version your agent can follow step by step, with the tool code bundled.

## Quick start

Each tool is independent. Pick one and follow its README.

```bash
# Episode 3: workday orchestrator (Python 3.11+)
cd workday-orchestrator && pip install -r requirements.txt && python -m pytest -q

# Episode 4: Copilot dev tools (Python 3.11+, Docker on Linux for the sandbox)
cd copilot-dev-tools && pip install -r requirements.txt && python -m pytest -q

# Episode 5: training video generator (Node 22+, ffmpeg)
cd training-video-generator/service && npm install && npm test
```

## Honest limits

- These are working tools built for real demo runs, not packaged products. Expect to read code and set
  environment variables.
- Copilot Studio parts (agents, custom connectors) are shipped as source files. You import them into your own
  tenant with the Power Platform CLI and create your own connection; nothing here points at our tenant.
- The agents do real work and make real mistakes. That is why every tool has an independent check: a verifier
  (Episode 3), an allow-list plus sandbox plus audit log (Episode 4), a strict plan schema and render warnings
  (Episode 5).
- All demo data is fictional (Brightwater Logistics, the equipment loans, the invoices).

## License

[MIT](LICENSE).
