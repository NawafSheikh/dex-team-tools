"""Excel mission verifier: recount the raw export independently and reconcile with the workbook."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from .common import check, result

CUTOFF = dt.date(2026, 10, 30)
LABELS = ["Raw rows", "Duplicates removed", "Blank rows removed", "Clean loans", "Overdue loans",
          "Overdue rate", "Top item"]


def parse_date(value) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y", "%d %B %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date {text!r}")


def truth(raw_path: Path) -> dict:
    ws = load_workbook(raw_path, data_only=True).worksheets[0]
    rows = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]
    while rows and all(v in (None, "") for v in rows[-1]):
        rows.pop()
    raw = len(rows)
    with_item = [r for r in rows if r[1] not in (None, "")]
    blanks = raw - len(with_item)
    seen, clean = set(), []
    for r in with_item:
        if r[0] in seen:
            continue
        seen.add(r[0])
        clean.append(r)
    overdue = 0
    for r in clean:
        due, returned = parse_date(r[5]), parse_date(r[6])
        if (returned and due and returned > due) or (returned is None and due and due < CUTOFF):
            overdue += 1
    counts = Counter(r[1] for r in clean)
    top_item, top_n = counts.most_common(1)[0]
    return {
        "Raw rows": raw, "Duplicates removed": len(with_item) - len(clean), "Blank rows removed": blanks,
        "Clean loans": len(clean), "Overdue loans": overdue, "Overdue rate": overdue / len(clean),
        "Top item": top_item, "top_item_loans": top_n,
    }


def read_summary(path: Path) -> dict:
    wb = load_workbook(path, data_only=True)
    if "Summary" not in wb.sheetnames:
        return {}
    return {str(a).strip(): b for a, b in wb["Summary"].iter_rows(min_col=1, max_col=2, values_only=True) if a}


def as_rate(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) / 100 if value > 1 else float(value)
    text = str(value).strip().replace(",", ".")
    num = float(text.rstrip("%").strip())
    return num / 100 if text.endswith("%") or num > 1 else num


def has_chart(path: Path) -> bool:
    wb = load_workbook(path)
    return any(getattr(ws, "_charts", []) for ws in wb.worksheets)


def verify(rdir: Path, state: dict, mission: dict) -> dict:
    out = rdir / "shared" / "Loans_Analysis.xlsx"
    png = rdir / "shared" / "top_items.png"
    t = truth(rdir / "inbox" / "loans_export.xlsx")
    checks = [check("workbook saved", out.exists(), str(out.relative_to(rdir)))]
    if not out.exists():
        return result(checks)
    s = read_summary(out)
    checks.append(check("Summary sheet has all labels", all(k in s for k in LABELS),
                        f"missing: {[k for k in LABELS if k not in s]}"))
    def num(k):
        try:
            value = float(s.get(k))
        except (TypeError, ValueError):
            return None
        return int(value) if value.is_integer() else None
    recon = (num("Raw rows") is not None and
             num("Raw rows") == (num("Clean loans") or 0) + (num("Duplicates removed") or 0) + (num("Blank rows removed") or 0))
    checks.append(check("raw = clean + duplicates + blanks", recon,
                        f"{num('Raw rows')} = {num('Clean loans')} + {num('Duplicates removed')} + {num('Blank rows removed')}"))
    for k in ("Raw rows", "Duplicates removed", "Blank rows removed", "Clean loans", "Overdue loans"):
        checks.append(check(f"{k} matches recount", num(k) == t[k], f"workbook {num(k)}, recount {t[k]}"))
    try:
        rate = as_rate(s.get("Overdue rate"))
    except ValueError:
        rate = None
    checks.append(check("Overdue rate matches recount", rate is not None and abs(rate - t["Overdue rate"]) < 0.0015,
                        f"workbook {s.get('Overdue rate')}, recount {t['Overdue rate']:.1%}"))
    checks.append(check("Top item matches recount", str(s.get("Top item", "")).strip() == t["Top item"],
                        f"workbook {s.get('Top item')}, recount {t['Top item']} ({t['top_item_loans']} loans)"))
    checks.append(check("workbook has a chart", has_chart(out), "chart object in a sheet"))
    checks.append(check("chart image saved", png.exists() and png.stat().st_size > 5000, "shared/top_items.png"))
    facts = {"clean_loans": t["Clean loans"], "overdue_loans": t["Overdue loans"],
             "overdue_rate": f"{t['Overdue rate']:.1%}", "top_item": t["Top item"]}
    return result(checks, facts=facts)
