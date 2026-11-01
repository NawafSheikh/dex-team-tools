"""Run commands and operations inside the devbox sandbox container via docker exec."""
from __future__ import annotations

import json
import os
import posixpath
import subprocess
import threading
import time
from dataclasses import dataclass

CONTAINER = os.environ.get("DEVTOOLS_CONTAINER", "devbox")
WORK = "/work"
MAX_TIMEOUT_S = int(os.environ.get("DEVTOOLS_MAX_TIMEOUT_S", "100"))
MAX_OUTPUT = 30_000          # characters returned to the caller
MAX_READ_BYTES = 2_000_000   # bytes buffered on the host before the command is killed

# Runs inside the container: resolve the real working folder (symlinks included) and refuse
# anything outside /work before executing the command.
CWD_GUARD = ('d=$(realpath -e -- "$1" 2>/dev/null) || { echo "working folder not found: $1" >&2; exit 126; }; '
             'case "$d" in /work|/work/*) ;; *) echo "working folder outside /work: $1" >&2; exit 126;; esac; '
             'cd "$d" && shift && exec "$@"')


class SandboxError(Exception):
    pass


@dataclass(frozen=True)
class ShellResult:
    exit_code: int | None
    output: str
    duration_s: float
    timed_out: bool
    output_capped: bool = False

    def as_dict(self) -> dict:
        return {"exit_code": self.exit_code, "output": self.output, "duration_s": round(self.duration_s, 2),
                "timed_out": self.timed_out, "output_capped": self.output_capped}


def workdir(cwd: str | None) -> str:
    """Lexical check of a working folder relative to /work (the real check runs in the container)."""
    joined = posixpath.normpath(posixpath.join(WORK, cwd or "."))
    if joined != WORK and not joined.startswith(WORK + "/"):
        raise SandboxError(f"working folder must be inside {WORK}: {cwd}")
    return joined


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    half = MAX_OUTPUT // 2
    return f"{text[:half]}\n... [{len(text) - MAX_OUTPUT} characters cut] ...\n{text[-half:]}"


def _bounded_run(argv: list[str], stdin_bytes: bytes | None, wall_s: float) -> tuple[int | None, bytes, bool]:
    """Run argv, read at most MAX_READ_BYTES of stdout, kill on overflow or wall-clock expiry."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    timer = threading.Timer(wall_s, proc.kill)
    timer.start()
    try:
        if stdin_bytes is not None:
            proc.stdin.write(stdin_bytes)
            proc.stdin.close()
        chunks, total, capped = [], 0, False
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_READ_BYTES:
                capped = True
                proc.kill()
                break
            chunks.append(chunk)
        code = proc.wait()
    finally:
        timer.cancel()
    return code, b"".join(chunks), capped


def run_shell(argv: list[str], cwd: str | None, timeout_s: int) -> ShellResult:
    timeout_s = max(1, min(int(timeout_s), MAX_TIMEOUT_S))
    target = workdir(cwd)
    full = ["docker", "exec", "-i", "-w", WORK, CONTAINER, "bash", "-c", CWD_GUARD, "guard", target,
            "timeout", "-k", "3", str(timeout_s), *argv]
    started = time.monotonic()
    code, out, capped = _bounded_run(full, None, timeout_s + 10)
    text = out.decode("utf-8", "replace")
    if capped:
        text += f"\n[output stopped after {MAX_READ_BYTES} bytes; the command was ended]"
    timed_out = code == 124
    return ShellResult(code, _clip(text), time.monotonic() - started, timed_out, capped)


def bash(command: str, cwd: str | None, timeout_s: int) -> ShellResult:
    return run_shell(["bash", "-lc", command], cwd, timeout_s)


def pwsh(command: str, cwd: str | None, timeout_s: int) -> ShellResult:
    plain = "$PSStyle.OutputRendering = 'PlainText'; " + command
    return run_shell(["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", plain], cwd, timeout_s)


def op(name: str, args: dict, timeout_s: int = 60) -> dict:
    """Call one operation of sandbox/op.py and return its JSON reply."""
    payload = json.dumps({"op": name, "args": args}).encode("utf-8")
    argv = ["docker", "exec", "-i", CONTAINER, "python3", "/opt/devtools/op.py"]
    code, out, capped = _bounded_run(argv, payload, timeout_s)
    if capped:
        raise SandboxError(f"{name} produced too much output")
    if code != 0:
        raise SandboxError(out.decode("utf-8", "replace")[-2000:] or f"{name} failed or timed out")
    reply = json.loads(out.decode("utf-8"))
    if not reply.pop("ok", False):
        raise SandboxError(reply.get("error", f"{name} failed"))
    return reply
