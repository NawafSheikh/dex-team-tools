"""A stand-in agent for the smoke test: reads the mission prompt on stdin and writes a correct notes deliverable.

It proves the plumbing (plan, dispatch, handoff, independent verification), not an AI. Real runs use Claude Code
or Codex through WORKDAY_CLAUDE_CMD / WORKDAY_CODEX_CMD.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixtures"))
import make_fixtures  # noqa: E402

ACTION_TEXT = {"access": "Set up app access for all staff", "label": "Label every item with its asset code",
               "cost": "Pull replacement-hire costs", "brief": "Brief team leads on approvals",
               "tripod": "Remove the broken tripods from the list"}


def main() -> None:
    prompt = sys.stdin.read()
    shared = Path(re.search(r"Shared deliverables folder: (.+?) \(save", prompt).group(1))
    handoff = Path(re.search(r"When you are finished, write (.+?HANDOFF\.md)", prompt).group(1))
    doc = Document()
    doc.add_heading("Decisions", 1)
    for d in make_fixtures.TRUTH["decisions"]:
        doc.add_paragraph(d, style="List Bullet")
    doc.add_heading("Actions", 1)
    table = doc.add_table(rows=1, cols=3)
    for cell, text in zip(table.rows[0].cells, ("Action", "Owner", "Due")):
        cell.text = text
    for a in make_fixtures.TRUTH["actions"]:
        row = table.add_row().cells
        row[0].text, row[1].text, row[2].text = ACTION_TEXT[a["keywords"][0]], a["owner"], a["due"]
    doc.save(shared / "Ops_Meeting_Notes.docx")
    to = ", ".join(f"{n} <{n.split()[0].lower()}@example.com>" for n in make_fixtures.TRUTH["attendees"])
    (shared / "Follow_up_email.eml").write_text(
        f"To: {to}\nSubject: Ops meeting follow-up\nX-Unsent: 1\n\nDecisions and actions are in the notes.\n",
        encoding="utf-8")
    handoff.write_text("# Handoff\n\nWhat I did: notes and email draft (smoke agent).\n", encoding="utf-8")
    print("smoke agent wrote the notes")


if __name__ == "__main__":
    main()
