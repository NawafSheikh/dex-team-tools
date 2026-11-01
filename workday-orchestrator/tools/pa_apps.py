#!/usr/bin/env python3
"""pa_apps: list a Power Platform environment's canvas apps (id, name, published version time, Dataverse tables).

Usage: python pa_apps.py [name filter]   (needs DV_ENV_ID and a signed-in `dv`)
The maker portal does not show a new app's id after "Save as"; this prints it. Read only.
"""
import json
import os
import subprocess
import sys
import urllib.request

ENV_ID = os.environ.get("DV_ENV_ID", "")
DV = os.environ.get("WORKDAY_DV", "dv")
URL = (f"https://api.powerapps.com/providers/Microsoft.PowerApps/scopes/admin/environments/{ENV_ID}/apps"
       "?api-version=2016-11-01&$top=250")


def main() -> int:
    if not ENV_ID:
        print("set DV_ENV_ID", file=sys.stderr)
        return 2
    needle = " ".join(sys.argv[1:]).lower()
    token = subprocess.run([DV, "token", "powerapps"], capture_output=True, text=True,
                           timeout=120).stdout.strip()
    if not token:
        print("could not get a Power Apps token from dv", file=sys.stderr)
        return 1
    req = urllib.request.Request(URL, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        apps = json.loads(resp.read()).get("value", [])
    for app in apps:
        p = app.get("properties") or {}
        if needle and needle not in p.get("displayName", "").lower():
            continue
        tables = sorted({s.get("logicalName", "") for ref in (p.get("databaseReferences") or {}).values()
                         for s in (ref.get("dataSources") or {}).values()})
        print(f"{app['name']}  {p.get('displayName')!r}  created {p.get('createdTime', '')[:19]}  "
              f"published {(p.get('appVersion') or 'never')[:19]}  tables {', '.join(tables) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
