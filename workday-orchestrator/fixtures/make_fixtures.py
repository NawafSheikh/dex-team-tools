"""Inputs for the workday: a messy loans export and a meeting transcript (fictional company).

Usage: python make_fixtures.py [inbox dir] [--truth truth dir]
--truth also writes notes_truth.json, the answer key the notes verifier checks against (keep it away from agents).
"""
from __future__ import annotations

import datetime as dt
import json
import random
import sys
from pathlib import Path

from openpyxl import Workbook

ITEMS = [
    ("Laptop 14 (L-01)", "Laptop"), ("Laptop 14 (L-02)", "Laptop"), ("Laptop 16 (L-03)", "Laptop"),
    ("Laptop 16 (L-04)", "Laptop"), ("Camera body (C-01)", "Camera"), ("Camera body (C-02)", "Camera"),
    ("Zoom lens 24-70 (Z-01)", "Lens"), ("Tripod (T-01)", "Tripod"), ("Tripod (T-02)", "Tripod"),
    ("Wireless mic kit (M-01)", "Audio"), ("Wireless mic kit (M-02)", "Audio"), ("LED panel (P-01)", "Lighting"),
    ("Projector (J-01)", "Projector"), ("Tablet (B-01)", "Tablet"),
]
WEIGHTS = [9, 8, 6, 5, 7, 6, 4, 5, 3, 6, 4, 3, 2, 3]
STAFF = ["Maya Collins", "Omar Haddad", "Lena Brooks", "Tom Becker", "Sara Lindqvist", "Ravi Menon",
         "Eva Novak", "Daniel Price", "Grace Okafor", "Jonas Weber", "Priya Shah", "Luca Romano"]
TODAY = dt.date(2026, 10, 30)


def fmt_date(d: dt.date, rng: random.Random):
    style = rng.random()
    if style < 0.6:
        return d
    if style < 0.85:
        return d.isoformat()
    return d.strftime("%d %b %Y")


def make_loans(path: Path, seed: int = 45) -> None:
    rng = random.Random(seed)
    rows = []
    for n in range(1, 341):
        item, cat = rng.choices(ITEMS, WEIGHTS)[0]
        borrowed = TODAY - dt.timedelta(days=rng.randint(1, 240))
        due = borrowed + dt.timedelta(days=rng.choice([3, 5, 7, 7, 14]))
        if due >= TODAY and rng.random() < 0.7:
            returned = None
        elif rng.random() < 0.08:
            returned = None
        else:
            late = rng.random() < 0.18
            returned = due + dt.timedelta(days=rng.randint(1, 6)) if late else borrowed + dt.timedelta(
                days=rng.randint(0, (due - borrowed).days))
            returned = min(returned, TODAY)
        rows.append([f"LN-{1000 + n}", item, cat, rng.choice(STAFF), fmt_date(borrowed, rng),
                     fmt_date(due, rng), fmt_date(returned, rng) if returned else None])
    messy = []
    for row in rows:
        messy.append(row)
        if rng.random() < 0.06:
            messy.append(list(row))  # exact duplicate export line
        if rng.random() < 0.04:
            messy.append([None] * 7)  # blank line
        if rng.random() < 0.03:
            messy.append([f"LN-X{rng.randint(100, 999)}", None, None, rng.choice(STAFF), None, None, None])
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(["Loan ID", "Item", "Category", "Borrower", "Borrowed", "Due", "Returned"])
    for row in messy:
        ws.append(row)
    for cell in ws["E"] + ws["F"] + ws["G"]:
        if isinstance(cell.value, dt.date):
            cell.number_format = "dd/mm/yyyy"
    wb.save(path)


TRANSCRIPT = """Operations weekly - Thursday 29 October 2026, 10:00
Attendees: Maya Collins (Operations Manager), Omar Haddad (IT Lead), Lena Brooks (Studio Coordinator), Ravi Menon (Finance)

Maya: Right, the equipment cupboard. Two cameras went missing for a week last month and nobody knew who had them.
Omar: The spreadsheet is the problem. People forget to fill it in, and there is no approval.
Maya: So we agree: from Monday 9 November every loan goes through the new loan app, no more spreadsheet. Decided.
Lena: Who approves? I do not want to be the bottleneck.
Maya: Line managers approve their own team's loans. Studio kit over 1,000 euros needs my approval as well. Decided.
Ravi: Overdue kit is costing us. We hired a replacement camera twice.
Maya: Then a reminder goes out the day after the due date, and after five days overdue it comes to me. Agreed.
Omar: I will set up the app access for all staff. I can do that by Wednesday 4 November.
Maya: Good. Lena, can you label every item with its asset code, so the app and the cupboard match?
Lena: Yes, by Friday 6 November.
Ravi: I will pull the replacement-hire costs for the last six months, so we know what this saves. Monday 16 November.
Maya: And I will brief the team leads on approvals. Let us say Thursday 5 November.
Omar: One more: the two old tripods are broken. Can we write them off?
Maya: Yes, write them off. Omar, remove them from the list by 6 November.
Maya: Last thing, we review how it is going in this meeting on 26 November. Thanks all.
"""

TRUTH = {
    "attendees": ["Maya Collins", "Omar Haddad", "Lena Brooks", "Ravi Menon"],
    "decisions": ["loan app from 9 November", "line managers approve", "reminder after due date",
                  "write off broken tripods", "review on 26 November"],
    "decision_keywords": [["9 november", "9 nov"], ["line manager"], ["reminder"],
                          ["tripod"], ["26 november", "26 nov"]],
    "actions": [
        {"owner": "Omar Haddad", "keywords": ["access"], "due": "2026-11-04"},
        {"owner": "Lena Brooks", "keywords": ["label"], "due": "2026-11-06"},
        {"owner": "Ravi Menon", "keywords": ["cost"], "due": "2026-11-16"},
        {"owner": "Maya Collins", "keywords": ["brief"], "due": "2026-11-05"},
        {"owner": "Omar Haddad", "keywords": ["tripod"], "due": "2026-11-06"},
    ],
}


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    make_loans(out / "loans_export.xlsx")
    (out / "ops_meeting_transcript.txt").write_text(TRANSCRIPT, encoding="utf-8")


def write_truth(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "notes_truth.json").write_text(json.dumps(TRUTH, indent=2), encoding="utf-8")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--truth" in args:
        i = args.index("--truth")
        write_truth(args[i + 1])
        args = args[:i] + args[i + 2:]
    main(args[0] if args else "inbox")
