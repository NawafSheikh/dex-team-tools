"""Git and GitHub operations.

Local git runs inside the sandbox. The sandbox holds no GitHub credential: pushes go through a one-shot
broker container that alone mounts the deploy key, copies just the branch into a clean mirror and pushes
it to an allow-listed GitHub repo. Pull requests are opened host-side with a token the sandbox never sees.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import urllib.request
from pathlib import Path

import sandbox_exec as sb

TOKEN_FILE = Path(os.environ.get("DEVTOOLS_GITHUB_TOKEN_FILE", "/opt/devtools/secrets/github_token"))
ALLOWED_REPOS = frozenset(r.lower() for r in os.environ.get("DEVTOOLS_GITHUB_REPOS", "").split() if r)
WORK_HOST = Path(os.environ.get("DEVTOOLS_WORK_HOST", "/srv/devbox/work"))
DEPLOY_KEY = os.environ.get("DEVTOOLS_DEPLOY_KEY", "/opt/devtools/secrets/deploy_key")
IMAGE = os.environ.get("DEVTOOLS_IMAGE", "devbox:1")
BRANCH_RE = re.compile(r"(?!-)(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,80}(?<![./])(?<!\.lock)")
PUSH_SCRIPT = (
    'set -e; git init -q --bare /tmp/mirror; '
    'git -C /tmp/mirror fetch -q --no-tags /src "refs/heads/$BRANCH:refs/heads/$BRANCH"; '
    'git -C /tmp/mirror push "git@github.com:$SLUG.git" "refs/heads/$BRANCH:refs/heads/$BRANCH" 2>&1'
)


def check_branch(name: str) -> str:
    """A branch name that can never be read as a git option or an odd ref."""
    if not BRANCH_RE.fullmatch(name or ""):
        raise sb.SandboxError("branch name: letters, digits, . _ / - only; no leading '-', no '..'")
    return name


def check_repo_dir(repo: str) -> str:
    """The repo must be a plain folder directly under /work (no nesting, no links)."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", repo or "") or repo in {".", ".."}:
        raise sb.SandboxError("repo must be a folder name directly under /work, e.g. invoice-totals")
    path = WORK_HOST / repo
    if path.is_symlink() or not (path / ".git").is_dir() or (path / ".git").is_symlink():
        raise sb.SandboxError(f"{repo} is not a git repository folder")
    return repo


def git(repo: str, args: str, timeout_s: int = 60) -> dict:
    result = sb.bash(f"git {args}", repo, timeout_s).as_dict()
    if result["exit_code"] != 0:
        raise sb.SandboxError(f"git {args.split()[0]} failed (exit {result['exit_code']}):\n{result['output']}")
    return result


def status(repo: str) -> dict:
    out = git(repo, "status --short --branch")["output"]
    return {"repo": repo, "status": out.strip() or "clean"}


def diff(repo: str, staged: bool, path: str) -> dict:
    flags = "--staged " if staged else ""
    target = f" -- {shlex.quote(path)}" if path else ""
    stat = git(repo, f"diff {flags}--stat{target}")["output"]
    body = git(repo, f"diff {flags}{target}")["output"]
    return {"repo": repo, "stat": stat.strip() or "no changes", "diff": body}


def branch(repo: str, name: str, checkout: bool) -> dict:
    if not name:
        return {"repo": repo, "branches": git(repo, "branch -a -vv")["output"]}
    q = shlex.quote(check_branch(name))
    exists = sb.bash(f"git rev-parse --verify --quiet refs/heads/{q}", repo, 20).exit_code == 0
    if checkout:
        git(repo, f"switch {'' if exists else '-c '}{q} --")
    elif not exists:
        git(repo, f"branch -- {q}")
    current = git(repo, "branch --show-current")["output"].strip()
    return {"repo": repo, "branch": name, "created": not exists, "current": current}


def commit(repo: str, message: str, files: list[str]) -> dict:
    if not message.strip():
        raise sb.SandboxError("commit message is empty")
    add = "add -A" if not files else "add -- " + " ".join(shlex.quote(f) for f in files)
    git(repo, add)
    git(repo, f"commit -m {shlex.quote(message)}")
    head = git(repo, "log -1 --pretty=format:'%h %an%n%s' --stat")["output"]
    return {"repo": repo, "commit": head}


def push(repo: str, branch_name: str) -> dict:
    repo = check_repo_dir(repo)
    name = check_branch(branch_name or git(repo, "branch --show-current")["output"].strip())
    slug = origin_slug(repo)
    if slug.lower() not in ALLOWED_REPOS:
        raise sb.SandboxError(f"{slug} is not on the push allow-list")
    argv = ["docker", "run", "--rm", "--network", "devbox-net", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "300m", "--pids-limit", "64",
            "-v", f"{WORK_HOST / repo}:/src:ro", "-v", f"{DEPLOY_KEY}:/home/dev/.ssh/deploy_key:ro",
            "-e", f"BRANCH={name}", "-e", f"SLUG={slug}", IMAGE, "bash", "-c", PUSH_SCRIPT]
    proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=120)
    out = proc.stdout.decode("utf-8", "replace")[-4000:]
    if proc.returncode != 0:
        raise sb.SandboxError(f"push failed (exit {proc.returncode}):\n{out}")
    # Record the remote branch locally so git_status shows the branch as up to date.
    q = shlex.quote(name)
    sb.bash(f"git update-ref refs/remotes/origin/{q} refs/heads/{q} && git branch -q -u origin/{q} {q}", repo, 20)
    return {"repo": repo, "branch": name, "pushed_to": f"github.com/{slug}", "output": out.strip()}


def origin_slug(repo: str) -> str:
    url = git(repo, "remote get-url origin")["output"].strip()
    match = re.search(r"github\.com[:/]([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$", url)
    if not match:
        raise sb.SandboxError(f"origin is not a GitHub repo: {url}")
    return match.group(1)


def create_pull_request(repo: str, title: str, body: str, head: str, base: str) -> dict:
    slug = origin_slug(repo)
    if slug.lower() not in ALLOWED_REPOS:
        raise sb.SandboxError(f"{slug} is not on the pull request allow-list")
    head = check_branch(head or git(repo, "branch --show-current")["output"].strip())
    base = check_branch(base or "main")
    token = TOKEN_FILE.read_text().strip()
    payload = json.dumps({"title": title, "body": body, "head": head, "base": base or "main"}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/pulls", data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "dex-dev-tools"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise sb.SandboxError(f"GitHub refused the pull request ({exc.code}): {detail}") from exc
    return {"repo": slug, "number": data["number"], "url": data["html_url"], "head": head,
            "base": data["base"]["ref"], "state": data["state"]}


def detect(repo: str, kind: str) -> str:
    """Pick the test or build command from the files in the repo."""
    listing = sb.op("ls", {"path": repo})["entries"]
    names = {e["name"] for e in listing}
    if kind == "test":
        if "package.json" in names:
            return "npm test --silent"
        return "python -m pytest -q"
    if "pyproject.toml" in names or "setup.py" in names:
        return "python -m pip wheel --no-deps --no-build-isolation -q -w /tmp/dist . && ls -la /tmp/dist"
    if "package.json" in names:
        return "npm run build"
    if "Makefile" in names:
        return "make"
    raise sb.SandboxError("no build file found (pyproject.toml, setup.py, package.json, Makefile)")
