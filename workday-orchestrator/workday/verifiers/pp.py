"""Power Platform verifiers: tables and data, canvas app, flows. They read the demo environment
through the same `dv` helper the workers use, but decide on their own queries."""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from .. import config
from .common import check, result

DV = config.DV
API = "/api/data/v9.2"


def dv(method: str, path: str, body: dict | None = None, flow: bool = False) -> tuple[int, dict]:
    argv = [DV] + (["flow", method, path] if flow else [method, path])
    if body is not None:
        argv.append(json.dumps(body))
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return 0, {"error": "dv timed out"}
    status_line = (proc.stderr.strip().splitlines() or ["HTTP 0"])[-1]
    try:
        status = int(status_line.split()[1])
    except (IndexError, ValueError):
        status = 0
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {"raw": proc.stdout[:500]}
    return status, data


def _count(entity_set: str, filt: str = "") -> int:
    q = f"{API}/{entity_set}?$select=createdon&$top=5000" + (f"&$filter={filt}" if filt else "")
    status, data = dv("GET", q)
    return len(data.get("value", [])) if status == 200 else -1


TABLES = {
    "wd_item": ["wd_name"],
    "wd_staff": ["wd_name"],
    "wd_loan": ["wd_item", "wd_staff"],
}


def _entity(logical: str) -> dict | None:
    status, data = dv("GET", f"{API}/EntityDefinitions(LogicalName='{logical}')?$select=LogicalName,EntitySetName"
                              f"&$expand=Attributes($select=LogicalName,AttributeType)")
    return data if status == 200 else None


def verify_tables(rdir: Path, state: dict, mission: dict) -> dict:
    checks, sets, attrs_by = [], {}, {}
    for logical in TABLES:
        ent = _entity(logical)
        checks.append(check(f"table {logical} exists", ent is not None, ent.get("EntitySetName", "") if ent else "not found"))
        if ent:
            sets[logical] = ent["EntitySetName"]
            attrs_by[logical] = {a["LogicalName"]: a["AttributeType"] for a in ent["Attributes"]}
    if len(sets) < 3:
        return result(checks)
    loan_attrs = attrs_by["wd_loan"]
    want = {"wd_item": "Lookup", "wd_staff": "Lookup", "wd_borrowedon": "DateTime", "wd_dueon": "DateTime",
            "wd_returnedon": "DateTime", "wd_status": "Picklist"}
    missing = [f"{a} ({t})" for a, t in want.items() if loan_attrs.get(a) != t]
    checks.append(check("loan columns wd_item, wd_staff, wd_borrowedon, wd_dueon, wd_returnedon, wd_status",
                        not missing, f"missing or wrong type: {missing}" if missing else "all present"))
    lookups = ["wd_item", "wd_staff"] if not missing else []
    due, ret = ("wd_dueon", "wd_returnedon") if not missing else (None, None)
    n_items, n_staff, n_loans = (_count(sets[t]) for t in ("wd_item", "wd_staff", "wd_loan"))
    checks.append(check("at least 12 items", n_items >= 12, str(n_items)))
    checks.append(check("at least 8 staff", n_staff >= 8, str(n_staff)))
    checks.append(check("at least 15 loans", n_loans >= 15, str(n_loans)))
    if len(lookups) >= 2:
        filt = " or ".join(f"_{a}_value eq null" for a in lookups)
        orphans = _count(sets["wd_loan"], filt)
        checks.append(check("every loan has an item and a staff member", orphans == 0, f"{orphans} without"))
    overdue = -1
    if due and ret:
        today = dt.date.today().isoformat()
        overdue = _count(sets["wd_loan"], f"{due} lt {today} and {ret} eq null")
        checks.append(check("at least 3 overdue loans", overdue >= 3, str(overdue)))
    facts = {"loan_table": sets["wd_loan"], "items": n_items, "staff": n_staff, "loans": n_loans,
             "overdue_in_app": overdue}
    return result(checks, facts=facts)


ENV_ID = config.PP_ENV_ID
APP_NAME = "Equipment Loan Desk"  # a unique name, so the mission never collides with an existing app
PA_APPS = (f"https://api.powerapps.com/providers/Microsoft.PowerApps/scopes/admin/environments/{ENV_ID}/apps"
           "?api-version=2016-11-01&$top=250")


def powerapps_apps() -> list[dict]:
    """Canvas apps from the Power Apps service. Dataverse's canvasapps table misses apps saved outside a
    solution, so the app check reads the service the maker portal uses."""
    try:
        tok = subprocess.run([DV, "token", "powerapps"], capture_output=True, text=True, timeout=120).stdout.strip()
        req = urllib.request.Request(PA_APPS, headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read()).get("value", [])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def app_tables(app: dict) -> set[str]:
    refs = (app.get("properties") or {}).get("databaseReferences") or {}
    return {src.get("logicalName", "") for ref in refs.values() for src in (ref.get("dataSources") or {}).values()}


def verify_app(rdir: Path, state: dict, mission: dict) -> dict:
    started = (mission.get("started_epoch") or 0) - 60
    apps = [a for a in powerapps_apps() if (a.get("properties") or {}).get("displayName") == APP_NAME
            and _parse_ts(a["properties"].get("createdTime", "1970-01-01T00:00:00Z")).timestamp() >= started]
    checks = [check(f"new canvas app {APP_NAME} created in this run", bool(apps), f"{len(apps)} found")]
    published = [a for a in apps if a["properties"].get("appVersion")
                 and _parse_ts(a["properties"]["appVersion"]).timestamp() >= started]
    # a new app's first save is already a published version, so also require the latest edits to be published
    current = [a for a in published if a["properties"].get("lastModifiedTime") and
               _parse_ts(a["properties"]["appVersion"]).timestamp()
               >= _parse_ts(a["properties"]["lastModifiedTime"]).timestamp() - 300]
    checks.append(check("published during this run, with the latest edits", bool(current),
                        ", ".join(f"published {a['properties'].get('appVersion') or 'never'}, edited "
                                  f"{a['properties'].get('lastModifiedTime') or '?'}" for a in apps) or "no app"))
    published = current
    using = [a for a in published if "wd_loan" in app_tables(a)]
    checks.append(check("the app uses the wd_loan table", bool(using),
                        "; ".join(", ".join(sorted(app_tables(a))) or "no tables" for a in published) or "no app"))
    screens = sorted((rdir / "shared" / "screens").glob("*.png"))
    checks.append(check("at least 3 app screenshots", len(screens) >= 3, ", ".join(p.name for p in screens)))
    app_id = (using or published or [{}])[0].get("name", "")
    return result(checks, facts={"app_id": app_id} if app_id else {})


def verify_flows(rdir: Path, state: dict, mission: dict) -> dict:
    status, data = dv("GET", f"{API}/workflows?$select=name,statecode,category,workflowid,createdon"
                              f"&$filter=category eq 5")
    started = (mission.get("started_epoch") or 0) - 60
    flows = [f for f in (data.get("value", []) if status == 200 else [])
             if f.get("createdon") and _parse_ts(f["createdon"]).timestamp() >= started]
    def find(word):
        return [f for f in flows if word in (f.get("name") or "").lower()]
    approval, overdue = find("approval"), find("overdue")
    checks = [
        check("Loan approval flow exists", bool(approval), ", ".join(f["name"] for f in approval)),
        check("Overdue reminder flow exists", bool(overdue), ", ".join(f["name"] for f in overdue)),
        check("both flows turned on", approval and overdue and all(f["statecode"] == 1 for f in approval[:1] + overdue[:1]),
              ", ".join(f"{f['name']}={f['statecode']}" for f in approval[:1] + overdue[:1])),
    ]
    if not (approval and approval[0]["statecode"] == 1):
        return result(checks)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)
    created_ok, detail, loan_id = _create_test_loan(state)
    checks.append(check("test loan with status Requested created", created_ok, detail))
    run_seen = False
    flow_id = approval[0]["workflowid"]
    deadline = time.time() + 240
    while time.time() < deadline and not run_seen:
        st, runs = dv("GET", f"/providers/Microsoft.ProcessSimple/environments/{{env}}/flows/{flow_id}/runs", flow=True)
        for run in runs.get("value", []) if st == 200 else []:
            start = run.get("properties", {}).get("startTime", "")
            if start and _parse_ts(start) >= since:
                run_seen = True
        if not run_seen:
            time.sleep(15)
    checks.append(check("the test loan started a Loan approval run", run_seen, "flow run history"))
    if loan_id:
        dv("DELETE", f"{API}/{state.get('facts', {}).get('loan_table', 'wd_loans')}({loan_id})")
    return result(checks)


def _parse_ts(text: str) -> dt.datetime:
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?", text)
    base = dt.datetime.fromisoformat(m.group(1)).replace(tzinfo=dt.timezone.utc)
    return base + dt.timedelta(seconds=float(m.group(2) or 0))


def _requested_value(loan_logical: str = "wd_loan") -> tuple[str | None, int | None]:
    status, data = dv("GET", f"{API}/EntityDefinitions(LogicalName='{loan_logical}')/Attributes/"
                              f"Microsoft.Dynamics.CRM.PicklistAttributeMetadata?$select=LogicalName"
                              f"&$expand=OptionSet($select=Options),GlobalOptionSet($select=Options)")
    for attr in data.get("value", []) if status == 200 else []:
        if "status" not in attr["LogicalName"]:
            continue
        opts = (attr.get("OptionSet") or {}).get("Options") or (attr.get("GlobalOptionSet") or {}).get("Options") or []
        for opt in opts:
            labels = [l.get("Label", "") for l in opt.get("Label", {}).get("LocalizedLabels", [])]
            if any(l.lower() == "requested" for l in labels):
                return attr["LogicalName"], opt["Value"]
    return None, None


def _create_test_loan(state: dict) -> tuple[bool, str, str | None]:
    loan_set = state.get("facts", {}).get("loan_table", "wd_loans")
    field, value = _requested_value()
    if field is None:
        return False, "no status choice with a Requested option on wd_loan", None
    _, rels = dv("GET", f"{API}/EntityDefinitions(LogicalName='wd_loan')/ManyToOneRelationships"
                        f"?$select=ReferencingAttribute,ReferencingEntityNavigationPropertyName,ReferencedEntity")
    nav = {r["ReferencingAttribute"]: r for r in rels.get("value", [])}
    _, sample = dv("GET", f"{API}/{loan_set}?$top=1&$filter=_wd_item_value ne null and _wd_staff_value ne null")
    row = (sample.get("value") or [{}])[0]
    _, meta = dv("GET", f"{API}/EntityDefinitions(LogicalName='wd_loan')?$select=PrimaryNameAttribute,PrimaryIdAttribute")
    primary, id_attr = meta.get("PrimaryNameAttribute", "wd_name"), meta.get("PrimaryIdAttribute", "wd_loanid")
    body = {primary: "Verifier test loan", field: value}
    for attr in ("wd_item", "wd_staff"):
        target_id, rel = row.get(f"_{attr}_value"), nav.get(attr)
        target = _entity(rel["ReferencedEntity"]) if (target_id and rel) else None
        if target:
            body[f"{rel['ReferencingEntityNavigationPropertyName']}@odata.bind"] = f"/{target['EntitySetName']}({target_id})"
    status, created = dv("POST", f"{API}/{loan_set}", body)
    loan_id = created.get(id_attr) if isinstance(created, dict) else None
    return status in (200, 201, 204), f"HTTP {status} {json.dumps(created)[:200] if status >= 400 else ''}", loan_id
