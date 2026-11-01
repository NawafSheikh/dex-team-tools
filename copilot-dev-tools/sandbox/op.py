"""Operation runner inside the devbox sandbox.

Reads one JSON request {"op": ..., "args": {...}} on stdin, writes one JSON reply
on stdout. Every path is confined to WORK. Runs as the unprivileged dev user.
"""
from __future__ import annotations

import fnmatch
import html
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

WORK = Path(os.environ.get("DEVTOOLS_WORK", "/work")).resolve()
PROCS = Path(os.environ.get("DEVTOOLS_PROCS", "/home/dev/.procs"))
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build"}
MAX_OUT = 60_000
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


class OpError(Exception):
    pass


def resolve(path: str, base: str = ".") -> Path:
    raw = Path(path or ".")
    full = (raw if raw.is_absolute() else (WORK / base / raw)).resolve()
    if full != WORK and WORK not in full.parents:
        raise OpError(f"path outside the workspace: {path}")
    return full


def inside_work(path: Path) -> bool:
    real = path.resolve()
    return real == WORK or WORK in real.parents


def proc_name(name: str) -> str:
    """One canonical, separator-free name for spawn, output and stop alike."""
    clean = re.sub(r"[^a-z0-9_-]", "-", str(name).lower())[:40].strip("-")
    if not clean:
        raise OpError("process name must contain letters or digits")
    return clean


def rel(path: Path) -> str:
    return str(path.relative_to(WORK)) if path != WORK else "."


def walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def op_read(a: dict) -> dict:
    path = resolve(a["path"])
    if not path.is_file():
        raise OpError(f"not a file: {a['path']}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(int(a.get("offset", 1)), 1)
    limit = int(a.get("limit", 400))
    chunk = lines[start - 1:start - 1 + limit]
    numbered = "\n".join(f"{start + i:>5}  {line}" for i, line in enumerate(chunk))
    return {"path": rel(path), "total_lines": len(lines), "from": start,
            "to": start + len(chunk) - 1, "content": numbered}


def op_write(a: dict) -> dict:
    path = resolve(a["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(a["content"], encoding="utf-8")
    return {"path": rel(path), "created": not existed, "lines": a["content"].count("\n") + 1}


def apply_edit(text: str, old: str, new: str, replace_all: bool) -> tuple[str, int]:
    count = text.count(old)
    if not old:
        raise OpError("old_string is empty")
    if count == 0:
        raise OpError("old_string not found in file")
    if count > 1 and not replace_all:
        raise OpError(f"old_string matches {count} places; add context or set replace_all")
    return text.replace(old, new, -1 if replace_all else 1), (count if replace_all else 1)


def op_edit(a: dict) -> dict:
    path = resolve(a["path"])
    text = path.read_text(encoding="utf-8")
    new_text, n = apply_edit(text, a["old_string"], a["new_string"], bool(a.get("replace_all")))
    path.write_text(new_text, encoding="utf-8")
    return {"path": rel(path), "replacements": n}


def op_multi_edit(a: dict) -> dict:
    """All edits apply in order, to one or more files, or none apply."""
    staged: dict[Path, str] = {}
    applied = []
    for i, edit in enumerate(a["edits"]):
        path = resolve(edit["path"])
        text = staged.get(path, path.read_text(encoding="utf-8") if path.exists() else None)
        if text is None:
            raise OpError(f"edit {i + 1}: file not found: {edit['path']}")
        try:
            text, n = apply_edit(text, edit["old_string"], edit["new_string"], bool(edit.get("replace_all")))
        except OpError as exc:
            raise OpError(f"edit {i + 1} ({edit['path']}): {exc}; no files were changed") from exc
        staged[path] = text
        applied.append({"path": rel(path), "replacements": n})
    originals = {p: (p.read_bytes() if p.exists() else None) for p in staged}
    touched: list[Path] = []
    try:
        for path, text in staged.items():
            touched.append(path)  # before the write: a failed write may already have truncated the file
            path.write_text(text, encoding="utf-8")
    except OSError as exc:
        for path in touched:
            if originals[path] is not None:
                path.write_bytes(originals[path])
            else:
                path.unlink(missing_ok=True)
        raise OpError(f"write failed ({exc}); every file was restored, no files were changed") from exc
    return {"files_changed": sorted({rel(p) for p in staged}), "edits": applied}


def op_glob(a: dict) -> dict:
    base = resolve(a.get("path", "."))
    pattern = a["pattern"]
    hits = []
    for f in walk_files(base):
        r = str(f.relative_to(base))
        if fnmatch.fnmatch(r, pattern) or fnmatch.fnmatch(f.name, pattern):
            hits.append((f.stat().st_mtime, rel(f)))
    hits.sort(reverse=True)
    return {"pattern": pattern, "count": len(hits), "files": [h[1] for h in hits[:300]]}


def op_ls(a: dict) -> dict:
    base = resolve(a.get("path", "."))
    if not base.is_dir():
        raise OpError(f"not a folder: {a.get('path')}")
    items = []
    for p in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
        if p.name in {".git"}:
            continue
        items.append({"name": p.name + ("/" if p.is_dir() else ""),
                      "size": p.stat().st_size if p.is_file() else None})
    return {"path": rel(base), "entries": items}


def op_grep(a: dict) -> dict:
    base = resolve(a.get("path", "."))
    flags = re.IGNORECASE if a.get("ignore_case") else 0
    try:
        rx = re.compile(a["pattern"], flags)
    except re.error as exc:
        raise OpError(f"bad regex: {exc}") from exc
    include = a.get("include") or "*"
    ctx = int(a.get("context", 0))
    limit = int(a.get("max_results", 100))
    matches = []
    files = [base] if base.is_file() else walk_files(base)
    for f in files:
        if not fnmatch.fnmatch(f.name, include) or not inside_work(f):
            continue
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines):
            if rx.search(line):
                lo, hi = max(i - ctx, 0), min(i + ctx + 1, len(lines))
                block = "\n".join(f"{j + 1}: {lines[j]}" for j in range(lo, hi))
                matches.append({"file": rel(f), "line": i + 1, "text": block})
                if len(matches) >= limit:
                    return {"pattern": a["pattern"], "matches": matches, "truncated": True}
    return {"pattern": a["pattern"], "matches": matches, "truncated": False}


def op_spawn(a: dict) -> dict:
    PROCS.mkdir(parents=True, exist_ok=True)
    pid_name = proc_name(a["name"])
    log = PROCS / f"{pid_name}.log"
    cwd = resolve(a.get("cwd", "."))
    argv = ["pwsh", "-NoLogo", "-NoProfile", "-Command", a["command"]] if a.get("shell") == "powershell" \
        else ["bash", "-lc", a["command"]]
    with log.open("w") as fh:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    (PROCS / f"{pid_name}.pid").write_text(str(proc.pid))
    time.sleep(float(a.get("settle_s", 1.5)))
    alive = proc.poll() is None
    return {"name": pid_name, "pid": proc.pid, "running": alive,
            "exit_code": None if alive else proc.returncode, "output": tail(log, 4000)}


def tail(path: Path, n: int) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()[-n:]
    return data.decode("utf-8", errors="replace")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split()[2]
        return state != "Z"
    except OSError:
        return False


def op_proc_output(a: dict) -> dict:
    name = proc_name(a["name"])
    pid_file = PROCS / f"{name}.pid"
    if not pid_file.exists():
        known = sorted(p.stem for p in PROCS.glob("*.pid")) if PROCS.exists() else []
        raise OpError(f"no process named {name}; known: {known}")
    pid = int(pid_file.read_text())
    return {"name": name, "pid": pid, "running": pid_alive(pid),
            "output": tail(PROCS / f"{name}.log", int(a.get("tail_chars", 6000)))}


def op_proc_stop(a: dict) -> dict:
    name = proc_name(a["name"])
    pid = int((PROCS / f"{name}.pid").read_text())
    try:
        os.killpg(pid, signal.SIGTERM)
        time.sleep(1)
        if pid_alive(pid):
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return {"name": name, "pid": pid, "running": pid_alive(pid)}


class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "pre", "section", "dt", "dd"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        joined = "".join(self.parts)
        return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", joined)).strip()


def http_get(url: str, timeout: float = 25) -> tuple[int, str, str]:
    if not url.startswith(("http://", "https://")):
        raise OpError("only http and https URLs")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(3_000_000).decode(resp.headers.get_content_charset() or "utf-8", "replace")
            return resp.status, resp.headers.get("content-type", ""), body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read(200_000).decode("utf-8", "replace")


def op_fetch(a: dict) -> dict:
    status, ctype, body = http_get(a["url"])
    text = body
    if "html" in ctype:
        parser = TextExtractor()
        parser.feed(body)
        text = parser.text()
    start = int(a.get("offset", 0))
    chunk = text[start:start + int(a.get("max_chars", 12000))]
    return {"url": a["url"], "status": status, "content_type": ctype,
            "total_chars": len(text), "offset": start, "text": chunk}


def op_search(a: dict) -> dict:
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(a["query"])
    _, _, body = http_get(url)
    results = []
    for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
                         body, re.S):
        href, title, snippet = m.groups()
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        link = q.get("uddg", [href])[0]
        if "duckduckgo.com/y.js" in link:
            continue
        clean = lambda s: html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s))).strip()  # noqa: E731
        results.append({"title": clean(title), "url": link, "snippet": clean(snippet)})
        if len(results) >= int(a.get("max_results", 6)):
            break
    return {"query": a["query"], "results": results}


OPS = {
    "read": op_read, "write": op_write, "edit": op_edit, "multi_edit": op_multi_edit,
    "glob": op_glob, "ls": op_ls, "grep": op_grep, "spawn": op_spawn,
    "proc_output": op_proc_output, "proc_stop": op_proc_stop, "fetch": op_fetch, "search": op_search,
}


def main() -> None:
    req = json.loads(sys.stdin.read())
    try:
        result = {"ok": True, **OPS[req["op"]](req.get("args", {}))}
    except (OpError, OSError, KeyError, ValueError) as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    out = json.dumps(result, ensure_ascii=False)
    if len(out) > MAX_OUT * 2:
        result = {**result, "truncated": True}
        for key in ("content", "text", "output"):
            if isinstance(result.get(key), str):
                result[key] = result[key][:MAX_OUT]
        out = json.dumps(result, ensure_ascii=False)
    sys.stdout.write(out)


if __name__ == "__main__":
    main()
