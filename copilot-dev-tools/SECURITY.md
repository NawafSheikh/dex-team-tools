# Security review of dev-tools

Before the episode was filmed, an independent code review (OpenAI Codex, 2026-10-30) went through the server. Every
finding was fixed and checked against the running server. Several fixes also have regression tests in
`tests/test_policy.py`.

| Severity | Finding | Fix | Check |
|---|---|---|---|
| P1 | A duplicate `x-api-key` header could raise the caller's role | requests with zero or several key headers are rejected; the caller is mapped only from the two exact keys | two headers: 401 |
| P1 | The deploy key was readable inside the sandbox | key removed from the sandbox; pushes go through a one-shot broker container (clean mirror, allow-listed repo) | key absent; push from inside the sandbox: permission denied |
| P1 | A sub-agent could push through `bash` | follows from the above: no credential exists in the sandbox | sub-agent push exits 128, logged |
| P1 | Unbounded command output was buffered on the host | output is streamed with a 2 MB cap, then the process is killed | flood script killed |
| P2 | Path-qualified binaries passed the allow-list | only trusted system folders; `env` removed; `xargs` and `find -exec` targets checked | unit tests |
| P2 | PowerShell assignment, `$( )`, `&`, `Add-Type`, .NET Process | checked or blocked | unit tests |
| P2 | `grep` followed symlinks out of `/work` | every file's real path is checked | a link to `/etc/passwd` gives no match |
| P2 | A working-directory symlink could escape `/work` | real-path guard inside the container | exit 126 "outside /work" |
| P2 | Process-name path traversal | one canonical name for spawn, output and stop | `../../etc/passwd` becomes a plain name, not found |
| P2 | Sub-agent credential visible in argv | passed through the environment only | no process command line contains it |
| P2 | Empty or identical keys accepted | startup refuses keys under 32 characters or equal keys | service starts only with valid keys |
| P2 | A failed sub-agent setup leaked its slot | the whole setup is inside the error handler; the slot is freed | forced failure freed the slot |
| P2 | Sub-agent capacity race | check and reserve under one lock | code |
| P2 | `multi_edit` was not atomic on a write failure | originals restored on any write error | code |
| P2 | GitHub repo names with dots were rejected | repo pattern allows `.` `_` `-` | unit check |
| P2 | Branch names could be read as git options (`--mirror`) | validated, with `--` separators | `--mirror` rejected |

Report a security problem privately to the repository owner rather than in a public issue.
