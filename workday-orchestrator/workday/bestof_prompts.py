"""Prompts for best-of-both missions: the competing candidates, the blind judge, and the merge."""
from __future__ import annotations

from pathlib import Path

from . import config
from .kinds import KINDS

CANDIDATE_NOTE = (
    "Best of both: the other agent is doing this same mission at the same time, independently, in its own "
    "folder. The independent verifier checks both results; if both pass, a judge compares them blind and the "
    "better one goes to the manager, possibly improved with the best parts of the other. Do your best work, "
    "stay inside your own folders, and do not look for the other agent's work."
)

RUBRIC = {
    "excel": "correct cleaning and numbers beyond the automatic checks, a clear Summary a manager reads in "
             "seconds, a chart that tells the story, tidy sheets",
    "deck": "a clear story for a manager, slide design (layout, hierarchy, consistency), correct numbers, good "
            "use of the real screenshots and chart, no clutter",
    "notes": "faithful to the transcript, crisp decisions, actions a team can act on, a follow-up email a "
             "manager would send as is",
    "guide": "a new user can borrow, return and approve with it alone, clean one-page layout, plain words",
}


def judge_prompt(m: dict, packet: Path, a_dir: Path, b_dir: Path, work: Path) -> str:
    outputs = ", ".join(o.replace("shared/", "") for o in KINDS[m["kind"]]["outputs"])
    return "\n".join([
        "You are the judge in a best-of-both comparison. Two agents did the same mission independently. Both "
        "results already passed the independent verifier's automatic checks, so judge what the checks cannot see.",
        f"Mission packet: {packet}",
        f"Candidate A outputs: {a_dir / 'shared'} ({outputs}). Candidate B outputs: {b_dir / 'shared'} (same names).",
        f"Judge on: {RUBRIC.get(m['kind'], 'quality and usefulness to the manager')}.",
        "Look at the real files: open workbooks with Python ({config.PYTHON}, openpyxl), and "
        "render documents and decks to images to see them (`soffice --headless --convert-to pdf`, then "
        f"`pdftoppm -png -r 50`), working only inside {work}. Never modify either candidate.",
        "Score each candidate 1 to 10 on each rubric point, pick a winner, and list the specific, concrete things "
        "the loser does better that the winner should take (empty if none). Set merge to true only if those "
        "things would clearly improve the winner.",
        f"Write your verdict as JSON to {work / 'judge.json'} with exactly these keys: "
        '{"winner": "A" or "B", "scores": {"A": {...}, "B": {...}}, "reasons": "two or three sentences", '
        '"take_from_loser": ["..."], "merge": true or false}. Never use em dashes.',
    ])


def merge_note(loser_dir: Path, take: list[str]) -> str:
    items = "\n".join(f"- {t}" for t in take)
    return (
        "Merge step of a best-of-both mission: your result won the blind comparison. Your winning files are "
        "already in your shared folder below. Improve them by bringing in these strengths of the other "
        f"agent's result (read only, in {loser_dir / 'shared'}):\n{items}\n"
        "Change only what these points need, keep everything the verifier checks correct, and update HANDOFF.md "
        "with a line on what you took from the other result."
    )
