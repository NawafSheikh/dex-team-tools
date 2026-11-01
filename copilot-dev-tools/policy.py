"""Command allow-list and audit log for the dev-tools MCP server.

The sandbox container is the real security boundary. This module is the policy
layer on top: only listed programs may start a pipeline segment, a few shell
constructs are refused outright, and every tool call is written to an audit log.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

BASH_ALLOW = frozenset(
    os.environ.get(
        "DEVTOOLS_BASH_ALLOW",
        "git python python3 pip pip3 pytest ruff black ls cat head tail wc sort uniq cut tr "
        "grep egrep rg sed awk find xargs diff cmp echo printf true false test pwd cd which "
        "date sleep mkdir cp mv rm rmdir touch ln chmod stat du df basename dirname "
        "realpath tee file tree jq node npm npx make pwsh uname whoami id hostname ps kill",
    ).split()
)

# PowerShell: allowed cmdlet verbs plus the bash allow-list for native programs.
PWSH_VERBS = frozenset(
    "Get Select Where ForEach Sort Measure Format Out Write Test Set New Add Copy Move "
    "Remove Rename Join Split Compare Group ConvertTo ConvertFrom Import Export Resolve "
    "Push Pop Clear".split()
)
PWSH_ALIASES = frozenset("ls dir cat cd pwd echo gci gc sls % ? select where sort measure".split())

# Refused anywhere in a command, whatever the program.
DENY_PATTERNS = (
    (r"\bsudo\b|\bsu\s", "privilege escalation"),
    (r"\b(curl|wget|nc|ncat|socat|ssh|scp|telnet)\b", "raw network tools (use web_fetch)"),
    (r"\bdocker\b|\bkubectl\b", "container control"),
    (r"(?i)\binvoke-(webrequest|restmethod|expression)\b|\biex\b", "PowerShell network or eval"),
    (r"\brm\s+(-[a-zA-Z]*\s+)*/(\s|$)", "delete filesystem root"),
    (r":\(\)\s*\{", "fork bomb"),
    (r"(?i)\badd-type\b|\[\s*(system\.)?(diagnostics\.process|net\.|reflection\.|runtime\.interopservices)",
     ".NET process, network or reflection calls"),
    (r"\bmkfs\b|\bshutdown\b|\breboot\b", "system control"),
)

SEGMENT_SPLIT = re.compile(r"\|\||&&|[|;&\n]")
REDIRECT_AMP = re.compile(r"\d*[<>]&\d*-?|&>>?")
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""
    programs: tuple[str, ...] = field(default_factory=tuple)


TRUSTED_DIRS = ("/usr/bin/", "/bin/", "/usr/local/bin/", "/usr/sbin/", "/sbin/")
# Programs that run another program given as an argument; that program is checked too.
XARGS_VALUE_OPTS = {"-I", "-i", "-n", "-P", "-L", "-l", "-d", "-s", "-E", "-e", "-a", "--max-args", "--max-procs"}
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}


def _words(segment: str) -> list[str]:
    segment = segment.strip().lstrip("({ ").strip()
    if not segment:
        return []
    try:
        words = shlex.split(segment, posix=True)
    except ValueError:
        words = segment.split()
    while words and ENV_ASSIGN.match(words[0]):
        words = words[1:]
    return words


def _program_name(word: str) -> str | None:
    """Name of the program a word runs; None if it is a path outside the trusted system folders."""
    if "/" in word:
        # Normalise first: /usr/bin/../../work/ls must not pass as a trusted system path.
        if not word.startswith("/") or ".." in word.split("/"):
            return None
        norm = posixpath.normpath(word)
        return os.path.basename(norm) if norm.startswith(TRUSTED_DIRS) else None
    return word


def _launched(words: list[str]) -> list[str]:
    """Every program a segment starts: the first word, plus what xargs or find -exec would run."""
    if not words:
        return []
    launched = [words[0]]
    first = _program_name(words[0])
    if first == "xargs":
        rest, skip = words[1:], False
        for w in rest:
            if skip:
                skip = False
                continue
            if w in XARGS_VALUE_OPTS:
                skip = True
                continue
            if w.startswith("-"):
                continue
            launched.append(w)
            break
    elif first == "find":
        for i, w in enumerate(words[:-1]):
            if w in FIND_EXEC:
                launched.append(words[i + 1])
    return launched


def _first_word(segment: str) -> str | None:
    words = _words(segment)
    return os.path.basename(words[0]) if words else None


def _deny_reason(command: str) -> str | None:
    for pattern, reason in DENY_PATTERNS:
        if re.search(pattern, command):
            return reason
    return None


def check_bash(command: str) -> Verdict:
    """Allow a bash command only if every program it starts is on the allow-list.

    This is the policy layer, not the security boundary: allowed interpreters (python, node)
    can still run arbitrary code, which is why everything executes inside the sandbox.
    """
    if not command.strip():
        return Verdict(False, "empty command")
    reason = _deny_reason(command)
    if reason:
        return Verdict(False, f"blocked: {reason}")
    if "`" in command or "$(" in command or "<(" in command or ">(" in command:
        return Verdict(False, "blocked: command substitution")
    programs = []
    # Redirections such as 2>&1 and &> contain "&" but do not start a new program.
    normalized = REDIRECT_AMP.sub(" > ", command)
    for segment in SEGMENT_SPLIT.split(normalized):
        for word in _launched(_words(segment)):
            name = _program_name(word)
            if name is None:
                return Verdict(False, f"blocked: '{word}' is not a trusted program path")
            if name not in BASH_ALLOW:
                return Verdict(False, f"blocked: '{name}' is not on the allow-list")
            programs.append(name)
    return Verdict(True, "", tuple(programs))


def _pwsh_allowed(word: str) -> bool:
    name = _program_name(word)
    if name is None:
        return False
    if name in PWSH_ALIASES or name in BASH_ALLOW:
        return True
    verb, _, noun = name.partition("-")
    return bool(noun) and verb.capitalize() in PWSH_VERBS


PWSH_ASSIGN = re.compile(r"^\$[\w:.\[\]]+\s*[-+*/]?=\s*(.*)$", re.S)
PWSH_VALUE_START = tuple("$('\"@[{-0123456789")


def check_pwsh(command: str) -> Verdict:
    """Allow a PowerShell command only if every segment starts with an allowed cmdlet or program."""
    if not command.strip():
        return Verdict(False, "empty command")
    reason = _deny_reason(command)
    if reason:
        return Verdict(False, f"blocked: {reason}")
    if "$(" in command or "`" in command:
        return Verdict(False, "blocked: sub-expressions and escapes")
    programs = []
    for segment in re.split(r"\|\||&&|[|;\n]", command):
        segment = segment.strip().lstrip("({ ").strip()
        if not segment or segment.startswith("#"):
            continue
        if segment.startswith(("&", ". ")):
            return Verdict(False, "blocked: call operator")
        assign = PWSH_ASSIGN.match(segment)
        if segment.startswith("$"):
            if not assign:
                continue  # a bare expression such as $PSVersionTable.PSVersion
            segment = assign.group(1).strip()
            if not segment or segment.startswith(PWSH_VALUE_START):
                continue
        word = segment.split()[0].rstrip("(")
        if not _pwsh_allowed(word):
            return Verdict(False, f"blocked: '{word}' is not on the allow-list")
        programs.append(word)
    return Verdict(True, "", tuple(programs))


class AuditLog:
    """Append-only JSONL log plus a one-line-per-call human log for tail -f."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, caller: str, tool: str, detail: str, outcome: str, duration_s: float,
              extra: dict | None = None) -> None:
        now = time.time()
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "caller": caller, "tool": tool, "detail": detail[:2000],
            "outcome": outcome, "duration_s": round(duration_s, 3), **(extra or {}),
        }
        line = (f"{time.strftime('%H:%M:%S', time.localtime(now))}  {caller:<9} {tool:<20} "
                f"{detail.splitlines()[0][:90] if detail else '':<90}  {outcome} ({duration_s:.1f}s)")
        with self._lock:
            with (self.directory / "calls.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            with (self.directory / "audit.log").open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
