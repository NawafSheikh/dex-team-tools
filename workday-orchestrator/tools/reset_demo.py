"""Reset the demo environment between workday test runs: remove what the agents built (wd_ tables, the
WorkdayEquipmentLoans solution, its flows, and canvas apps named 'Equipment Loans' created by test runs).

Usage: python reset_demo.py --since 2026-10-30T15:00:00Z [--apply]   (needs DV_ENV_ID and a signed-in `dv`)
Without --apply it only lists what it would remove. It removes only wd_ tables, the WorkdayEquipmentLoans
solution, and flows and apps with the exact names the missions use, created after --since.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

DV = os.environ.get("WORKDAY_DV", "dv")
API = "/api/data/v9.2"
PA = ("https://api.powerapps.com/providers/Microsoft.PowerApps/scopes/admin/environments/"
      f"{os.environ.get('DV_ENV_ID', '<set DV_ENV_ID>')}/apps")
TABLES = ["wd_loan", "wd_item", "wd_staff"]  # children first: loans hold the lookups
OUR_FLOWS = {"loan approval", "overdue reminder"}  # the pp_flows mission's flow names
OUR_APPS = {"Equipment Loan Desk"}  # the exact name the pp_app mission uses


def dv(method: str, path: str) -> tuple[int, dict]:
    proc = subprocess.run([DV, method, path], capture_output=True, text=True, timeout=300)
    status = int((proc.stderr.strip().splitlines() or ["HTTP 0"])[-1].split()[1])
    try:
        return status, json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return status, {}


def _pa(method: str, url: str) -> tuple[int, dict]:
    token = subprocess.run([DV, "token", "powerapps"], capture_output=True, text=True, timeout=300).stdout.strip()
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def powerapps_apps() -> list[dict]:
    return _pa("GET", f"{PA}?api-version=2016-11-01&$top=250")[1].get("value", [])


def delete_app(app_id: str) -> int:
    return _pa("DELETE", f"{PA}/{app_id}?api-version=2016-11-01")[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--since", required=True, help="only remove flows and apps created after this UTC time")
    args = ap.parse_args()
    if not os.environ.get("DV_ENV_ID"):
        print("set DV_ENV_ID", file=sys.stderr)
        return 2
    plan: list[tuple[str, str, str]] = []
    _, flows = dv("GET", f"{API}/workflows?$select=name,workflowid,statecode,createdon"
                         f"&$filter=category eq 5 and createdon gt {args.since}")
    # Only what workday missions create, by exact name AND created after --since: other sessions share this
    # environment, so nothing is removed for its age alone.
    for f in flows.get("value", []):
        if f["name"].strip().lower() in OUR_FLOWS:
            plan.append(("flow", f["name"], f["workflowid"]))
    for a in powerapps_apps():  # Dataverse's canvasapps table misses apps saved outside a solution
        p = a.get("properties") or {}
        if p.get("createdTime", "") > args.since and p.get("displayName", "") in OUR_APPS:
            plan.append(("canvasapp", p.get("displayName", ""), a["name"]))
    for t in TABLES:
        status, ent = dv("GET", f"{API}/EntityDefinitions(LogicalName='{t}')?$select=MetadataId")
        if status == 200:
            plan.append(("table", t, ent["MetadataId"]))
    _, sols = dv("GET", f"{API}/solutions?$select=solutionid,uniquename&$filter=uniquename eq 'WorkdayEquipmentLoans'")
    for s in sols.get("value", []):
        plan.append(("solution", s["uniquename"], s["solutionid"]))
    for kind, name, ident in plan:
        print(f"{'REMOVE' if args.apply else 'would remove'} {kind}: {name} ({ident})")
        if not args.apply:
            continue
        if kind == "flow":
            subprocess.run([DV, "PATCH", f"{API}/workflows({ident})", json.dumps({"statecode": 0, "statuscode": 1})],
                           capture_output=True, text=True, timeout=300)
            status, _ = dv("DELETE", f"{API}/workflows({ident})")
        elif kind == "canvasapp":
            status = delete_app(ident)
        elif kind == "table":
            status, _ = dv("DELETE", f"{API}/EntityDefinitions({ident})")
        else:
            status, _ = dv("DELETE", f"{API}/solutions({ident})")
        print(f"   HTTP {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
