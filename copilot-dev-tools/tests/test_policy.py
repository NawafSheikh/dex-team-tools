import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from policy import AuditLog, check_bash, check_pwsh  # noqa: E402


@pytest.mark.parametrize("cmd", [
    "pytest -q",
    "pytest -q 2>&1 | tail -20",
    "git status --short && git diff --stat",
    "cd src && python -m ledger.cli totals.csv",
    "PYTHONPATH=src python -c 'print(1)'",
    "find . -name '*.py' | xargs wc -l",
    "ls -la; echo done",
])
def test_bash_allowed(cmd):
    assert check_bash(cmd).allowed, check_bash(cmd).reason


@pytest.mark.parametrize("cmd,why", [
    ("curl https://example.com", "network"),
    ("sudo apt install x", "privilege"),
    ("rm -rf /", "root"),
    ("echo $(whoami)", "substitution"),
    ("echo `id`", "substitution"),
    ("perl -e 'print 1'", "allow-list"),
    ("ls | bash", "allow-list"),
    ("docker ps", "container"),
    ("", "empty"),
])
def test_bash_blocked(cmd, why):
    verdict = check_bash(cmd)
    assert not verdict.allowed
    assert why in verdict.reason


@pytest.mark.parametrize("cmd", [
    "Get-ChildItem -Recurse -Filter *.py | Measure-Object",
    "$PSVersionTable.PSVersion",
    "Get-Content README.md | Select-Object -First 5",
    "git log --oneline -3",
])
def test_pwsh_allowed(cmd):
    assert check_pwsh(cmd).allowed, check_pwsh(cmd).reason


@pytest.mark.parametrize("cmd", [
    "Invoke-WebRequest https://example.com",
    "iex 'calc'",
    "Start-Process notepad",
    "Stop-Computer",
])
def test_pwsh_blocked(cmd):
    assert not check_pwsh(cmd).allowed


def test_audit_log_writes_both_files(tmp_path):
    log = AuditLog(tmp_path)
    log.write("copilot", "bash", "pytest -q", "exit 0", 1.23)
    assert '"tool": "bash"' in (tmp_path / "calls.jsonl").read_text()
    assert "pytest -q" in (tmp_path / "audit.log").read_text()


# Regressions from the 2026-10-30 Codex review.
@pytest.mark.parametrize("cmd", [
    "/work/payload/ls",                       # uploaded binary named like an allowed program
    "./ls -la",
    "env bash -c id",                         # env removed from the allow-list
    "find . -exec /work/x \\;",               # find -exec target is checked
    "find . -name '*.py' -exec perl {} \\;",
    "ls | xargs -I {} sh -c 'echo {}'",       # xargs target is checked
    "cat <(id)",                              # process substitution
])
def test_bash_bypasses_blocked(cmd):
    assert not check_bash(cmd).allowed, cmd


@pytest.mark.parametrize("cmd", [
    "find . -name '*.py' -exec grep -n round {} +",
    "find . -name '*.py' | xargs -n 1 wc -l",
    "/usr/bin/git status",
])
def test_bash_legit_launchers_allowed(cmd):
    assert check_bash(cmd).allowed, check_bash(cmd).reason


@pytest.mark.parametrize("cmd", [
    "$p = Start-Process /usr/bin/id",
    "$x = $(bash -c id)",
    "& /work/x",
    ". /work/evil.ps1",
    "Add-Type -TypeDefinition 'x'",
    "[System.Diagnostics.Process]::Start('bash')",
])
def test_pwsh_bypasses_blocked(cmd):
    assert not check_pwsh(cmd).allowed, cmd


@pytest.mark.parametrize("cmd", [
    "$n = 5; Get-ChildItem | Select-Object -First $n",
    "$files = Get-ChildItem -Recurse -Filter *.py",
])
def test_pwsh_assignments_allowed(cmd):
    assert check_pwsh(cmd).allowed, check_pwsh(cmd).reason


@pytest.mark.parametrize("cmd", ["/usr/bin/../../work/ls", "/usr/bin/./../../tmp/cat x", "./ls", "work/ls"])
def test_path_traversal_out_of_trusted_dirs_blocked(cmd):
    assert not check_bash(cmd).allowed, cmd


def test_trusted_absolute_path_allowed():
    assert check_bash("/usr/bin/git status").allowed
