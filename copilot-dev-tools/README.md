# Copilot dev tools (Episode 4)

An MCP server that gives a Microsoft Copilot Studio agent Claude Code's toolset, on a sandboxed Linux machine,
behind an allow-list, with every call logged.

Episode 4: "I gave Copilot Studio Claude Code's full toolset" (video coming).

## The 26 tools

| Group | Tools |
|---|---|
| Shell | `bash`, `powershell` |
| Files | `read_file`, `write_file`, `edit_file`, `multi_edit`, `list_dir` |
| Search | `glob`, `grep` |
| Git and GitHub | `git_status`, `git_diff`, `git_branch`, `git_commit`, `git_push`, `create_pull_request` |
| Tests and builds | `run_tests`, `run_build` |
| Processes | `start_process`, `process_output`, `stop_process` |
| Web | `web_fetch`, `web_search` |
| Planning | `todo_write`, `todo_read` |
| Sub-agents | `run_subagent`, `get_subagent` |

Sub-agents are headless Claude Code with all of its own built-in tools switched off. They only get these same
MCP tools (with a separate key), so they work in the same sandbox, under the same allow-list, and land in the
same audit log. They cannot push, open pull requests or start further sub-agents.

## The rails

- **Sandbox**: every tool runs in a Docker container (`devbox`) as a non-root user, no Linux capabilities,
  `no-new-privileges`, 1.2 GB memory, 1.5 CPU, 256 processes, its own network that is firewalled from the host and
  from private address ranges. The workspace is `/work`; paths outside it are refused, symlinks included.
- **No credentials in the sandbox**: `git_push` runs a one-shot broker container that alone mounts the deploy key,
  copies only the branch into a clean mirror and pushes to an allow-listed repo. Pull requests are opened
  host-side with a token the sandbox never sees.
- **Allow-list**: only listed programs may start a pipeline segment, risky shell and PowerShell constructs are
  refused, and path-qualified binaries must come from trusted system folders. It is the first wall, not the last:
  `python` and `node` are allowed and can run anything, which is exactly why everything runs in the sandbox.
- **Audit log**: one line per call (caller, tool, detail, result, time), including blocked and rejected calls.
- **Keys**: two keys of at least 32 characters (Copilot and sub-agents), exactly one key header per request.

See [SECURITY.md](SECURITY.md) for the security review findings and fixes.

## Run it

Tests (no Docker needed):

```bash
pip install -r requirements.txt
python -m pytest -q          # allow-list, key gate, multi-edit rollback, the 26 tools are registered
```

On a Linux host with Docker, as root:

```bash
mkdir -p /opt/devtools && cp -r . /opt/devtools/src && cd /opt/devtools/src
python3 -m venv /opt/devtools/venv
bash deploy/install.sh       # builds the sandbox image, firewall, systemd service, writes /opt/devtools/.env
```

Then:

1. Put `ANTHROPIC_API_KEY=...` in `/opt/devtools/claude.env` (mode 600) for sub-agents, and install the
   Claude Code CLI for the `DEVTOOLS_SUBAGENT_USER` user.
2. For pushes and pull requests: add the deploy key (`/opt/devtools/secrets/deploy_key.pub`) to your repo with
   write access, put a fine-grained GitHub token in `/opt/devtools/secrets/github_token`, and list the repo in
   `DEVTOOLS_GITHUB_REPOS`.
3. Put the server behind HTTPS (it listens on 127.0.0.1:8095) and set `DEVTOOLS_PUBLIC_HOSTS`.
4. Check it: `python tests/smoke_mcp.py https://your-host/mcp <key>` lists the tools;
   `python tests/smoke_mcp.py https://your-host/mcp <key> tests/calls_a.json` runs real calls, including ones that
   must be blocked.
5. In Copilot Studio, add an MCP server tool (Streamable HTTP) with the URL and an API key header `x-api-key`,
   and paste `agent_instructions.md` into the agent's instructions.

## The demo job

`demo-repo/invoice-totals` is the broken repo from the episode, as it was before the fix: 6 of its 13 tests fail
on purpose. Two bugs: money is rounded with float `round()` (banker's rounding on binary floats) in two files,
and the discount is applied after VAT instead of before. The right answer for the sample invoice is net 168.65,
discount 16.87, VAT 27.32, gross 179.10. The broken code gets the gross right by coincidence and the other three
numbers wrong. Push it to your own GitHub repo and set `DEVTOOLS_DEMO_REPO` for `deploy/reset_demo.sh`, which
rewinds the demo between runs.

## Honest limits

- The allow-list is a policy layer. The container and its firewall are the real boundary.
- Copilot Studio rate-limits bursts of tool calls. Long jobs can pause with a rate-limit message and resume on
  "continue". `DEVTOOLS_MIN_CALL_S` spaces calls out.
- Built and run on one Linux host. The installer assumes systemd, Docker and iptables.
- `web_search` and `web_fetch` reach the public internet from the sandbox by design.
