"""Verifiers for the document missions: manager deck, meeting notes plus email draft, user guide."""
from __future__ import annotations

import datetime as dt
import email
import json
import re
from email import policy
from pathlib import Path

from docx import Document
from pptx import Presentation
from pptx.util import Emu

from .. import config
from .common import check, file_hashes, result, sha, soffice_pdf_pages

TRUTH_DIR = config.TRUTH_DIR
EM_DASH = "\u2014"  # house style: deliverables never use it


def _pptx_images(prs) -> list[bytes]:
    blobs = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if getattr(shape, "shape_type", None) == 13 or hasattr(shape, "image"):
                try:
                    blobs.append(shape.image.blob)
                except (AttributeError, ValueError):
                    continue
    return blobs


def _pptx_text(prs) -> str:
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False) and shape.has_table:
                parts += [c.text for r in shape.table.rows for c in r.cells]
    return "\n".join(parts)


def _rate_variants(rate: str) -> list[str]:
    value = float(rate.rstrip("%"))
    return sorted({f"{value:.1f}%", f"{value:.0f}%", f"{value:.1f} %", f"{value:.0f} %"})


def verify_deck(rdir: Path, state: dict, mission: dict) -> dict:
    path = rdir / "shared" / "Equipment_Loans_Briefing.pptx"
    checks = [check("deck saved", path.exists(), "shared/Equipment_Loans_Briefing.pptx")]
    if not path.exists():
        return result(checks)
    prs = Presentation(str(path))
    n = len(prs.slides)
    checks.append(check("8 to 10 slides", 8 <= n <= 10, f"{n} slides"))
    checks.append(check("16:9", abs(Emu(prs.slide_width) / Emu(prs.slide_height) - 16 / 9) < 0.02,
                        f"{prs.slide_width}x{prs.slide_height}"))
    pages = soffice_pdf_pages(path)
    checks.append(check("opens in an office suite", bool(pages), f"rendered {pages} pages"))
    images = {sha(b) for b in _pptx_images(prs)}
    screens = file_hashes(sorted((rdir / "shared" / "screens").glob("*.png")))
    chart = file_hashes([rdir / "shared" / "top_items.png"])
    used_screens = [Path(p).name for h, p in screens.items() if h in images]
    if any(m.get("kind") == "pp_app" for m in state.get("missions", [])):  # only when this day builds an app
        checks.append(check("at least two real app screenshots", len(used_screens) >= 2,
                            ", ".join(used_screens) or "none"))
    checks.append(check("the analysis chart", any(h in images for h in chart), "shared/top_items.png"))
    facts = state.get("facts", {})
    text = _pptx_text(prs)
    rate, count = facts.get("overdue_rate"), facts.get("clean_loans")
    checks.append(check("no em dashes", EM_DASH not in text, "house style"))
    checks.append(check("overdue rate matches the analysis",
                        bool(rate) and any(v in text for v in _rate_variants(rate)),
                        f"expected {rate}" if rate else "no verified analysis to compare with"))
    checks.append(check("loan count matches the analysis",
                        bool(count) and re.search(rf"(?<![\d.,]){count}(?![\d])", text) is not None,
                        f"expected {count}" if count else "no verified analysis to compare with"))
    return result(checks, facts={"deck_slides": n})


def _docx_text(doc) -> str:
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        parts += [" | ".join(c.text for c in row.cells) for row in table.rows]
    return "\n".join(parts)


def _parse_any_date(text: str) -> dt.date | None:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%A %d %B %Y", "%a %d %b %Y", "%d/%m/%Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def verify_notes(rdir: Path, state: dict, mission: dict) -> dict:
    truth = json.loads((TRUTH_DIR / "notes_truth.json").read_text(encoding="utf-8"))
    notes = rdir / "shared" / "Ops_Meeting_Notes.docx"
    eml = rdir / "shared" / "Follow_up_email.eml"
    checks = [check("notes saved", notes.exists(), "shared/Ops_Meeting_Notes.docx"),
              check("email draft saved", eml.exists(), "shared/Follow_up_email.eml")]
    if not notes.exists():
        return result(checks)
    doc = Document(str(notes))
    rows = []
    for table in doc.tables:
        header = [c.text.strip().lower() for c in table.rows[0].cells]
        if "owner" in header and "due" in " ".join(header):
            oi = header.index("owner")
            di = next(i for i, h in enumerate(header) if "due" in h)
            rows += [[c.text.strip() for c in r.cells] + [oi, di] for r in table.rows[1:]]
    checks.append(check("actions table with Owner and Due", bool(rows), f"{len(rows)} actions"))
    bad_dates = [r[r[-1]] for r in rows if not _parse_any_date(r[r[-1]])]
    checks.append(check("every due date is a real date", rows and not bad_dates, f"unparsed: {bad_dates}"))
    bad_owners = [r[r[-2]] for r in rows if r[r[-2]] not in truth["attendees"]]
    checks.append(check("every owner is an attendee", rows and not bad_owners, f"not attendees: {bad_owners}"))
    for want in truth["actions"]:
        hit = [r for r in rows if r[r[-2]] == want["owner"]
               and any(k in " ".join(r[:-2]).lower() for k in want["keywords"])
               and _parse_any_date(r[r[-1]]) == dt.date.fromisoformat(want["due"])]
        checks.append(check(f"action for {want['owner']} ({want['keywords'][0]})", bool(hit), f"due {want['due']}"))
    text = _docx_text(doc).lower()
    checks.append(check("no em dashes", EM_DASH not in text, "house style"))
    for words in truth.get("decision_keywords", []):
        checks.append(check(f"decision captured: {words[0]}", any(w in text for w in words), " / ".join(words)))
    if eml.exists():
        msg = email.message_from_bytes(eml.read_bytes(), policy=policy.default)
        to = (msg.get("To") or "").lower()
        missing = [a for a in truth["attendees"]
                   if a.lower() not in to and a.split()[0].lower() + "." not in to]
        checks.append(check("email addressed to the attendees", not missing, f"missing: {missing}"))
        checks.append(check("email has a subject", bool(msg.get("Subject")), msg.get("Subject") or ""))
        checks.append(check("email marked unsent (draft only)", (msg.get("X-Unsent") or "").strip() == "1", "X-Unsent: 1"))
    return result(checks, facts={"actions": len(rows)})


def verify_guide(rdir: Path, state: dict, mission: dict) -> dict:
    path = rdir / "shared" / "Equipment_Loans_User_Guide.docx"
    checks = [check("guide saved", path.exists(), "shared/Equipment_Loans_User_Guide.docx")]
    if not path.exists():
        return result(checks)
    pages = soffice_pdf_pages(path)
    checks.append(check("exactly one page", pages == 1, f"{pages} pages"))
    text = _docx_text(Document(str(path))).lower()
    checks.append(check("no em dashes", EM_DASH not in text, "house style"))
    for word in ("borrow", "return", "approv", "overdue"):
        checks.append(check(f"covers {word}", word in text, ""))
    doc = Document(str(path))
    blobs = {sha(rel.target_part.blob) for rel in doc.part.rels.values() if "image" in rel.reltype}
    screens = file_hashes(sorted((rdir / "shared" / "screens").glob("*.png")))
    checks.append(check("contains a real app screenshot", any(h in blobs for h in screens), ""))
    return result(checks)
