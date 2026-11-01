#!/usr/bin/env bash
# Rewind the demo job: fresh clone of the broken repo in the sandbox, empty task list,
# no background processes, remote fix branches deleted and their pull requests closed.
# Usage (root on the host): DEVTOOLS_DEMO_REPO=<owner>/invoice-totals reset_demo.sh [--keep-remote]
set -euo pipefail
REPO=${DEVTOOLS_DEMO_REPO:?set DEVTOOLS_DEMO_REPO to owner/repo of your copy of demo-repo/invoice-totals}
TOKEN=$(cat /opt/devtools/secrets/github_token)
api() { python3 - "$@" <<'PY'
import json, sys, urllib.request
method, url, token = sys.argv[1], sys.argv[2], sys.argv[3]
data = sys.argv[4].encode() if len(sys.argv) > 4 else None
req = urllib.request.Request(url, data=data, method=method, headers={
    "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "devtools-reset"})
try:
    with urllib.request.urlopen(req) as r:
        body = r.read()
        print(body.decode() if body else "{}")
except urllib.error.HTTPError as e:
    print(json.dumps({"error": e.code}))
PY
}

if [[ "${1:-}" != "--keep-remote" ]]; then
  for n in $(api GET "https://api.github.com/repos/$REPO/pulls?state=open" "$TOKEN" | python3 -c 'import json,sys;[print(p["number"]) for p in json.load(sys.stdin)]'); do
    api PATCH "https://api.github.com/repos/$REPO/pulls/$n" "$TOKEN" '{"state":"closed"}' >/dev/null && echo "closed PR #$n"
  done
  for b in $(api GET "https://api.github.com/repos/$REPO/branches" "$TOKEN" | python3 -c 'import json,sys;[print(b["name"]) for b in json.load(sys.stdin) if b["name"]!="main"]'); do
    api DELETE "https://api.github.com/repos/$REPO/git/refs/heads/$b" "$TOKEN" >/dev/null && echo "deleted branch $b"
  done
fi

docker exec devbox bash -lc 'for f in ~/.procs/*.pid; do [ -f "$f" ] && kill -- -"$(cat "$f")" 2>/dev/null; done; rm -rf ~/.procs /tmp/dist'
docker exec -w /work devbox bash -lc "rm -rf invoice-totals"
# Clone through a one-shot container that holds the deploy key; the sandbox itself never sees it.
docker run --rm --network devbox-net --cap-drop ALL --security-opt no-new-privileges   -v /srv/devbox/work:/work -v /opt/devtools/secrets/deploy_key:/home/dev/.ssh/deploy_key:ro   devbox:1 bash -c "git clone -q git@github.com:$REPO.git /work/invoice-totals && git -C /work/invoice-totals log --oneline -1"
rm -f /opt/devtools/state/todos.json
echo "demo reset: /work/invoice-totals at main (broken)"
