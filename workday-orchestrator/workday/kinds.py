"""Mission kinds: what each kind of task must deliver and which verifier decides done.

The orchestrator (Copilot) picks the kind, the agent, the reason, the dependencies and any extra
criteria. The deliverable spec and the checks below are fixed per kind, so "done" is decided by an
independent verifier and never by the worker's own word.
"""
from __future__ import annotations

from . import config

KINDS: dict[str, dict] = {
    "pp_tables": {
        "label": "Dataverse tables and sample data",
        "deliverable": [
            "In the demo Dataverse environment (use the `dv` CLI), make sure a publisher with prefix `wd` "
            "(unique name `workday`) and an unmanaged solution `WorkdayEquipmentLoans` exist.",
            "Create three tables in that solution (send header MSCRM.SolutionUniqueName via DV_HEADERS): "
            "`wd_item` (Item: name, category, serial number, condition), `wd_staff` (Staff: name, email, "
            "team, manager name), `wd_loan` (Loan: primary column wd_name, lookups wd_item and wd_staff, dates wd_borrowedon, "
            "wd_dueon, wd_returnedon, choice wd_status with Requested / Approved / Rejected / Out / Returned).",
            "Publish the customizations, then add fictional sample data: at least 12 items (laptops, "
            "cameras, tripods, microphones), at least 8 staff, at least 15 loans with both lookups set, "
            "including at least 3 overdue (due before today, not returned).",
        ],
        "checks": [
            "tables wd_item, wd_staff, wd_loan exist with the listed columns",
            "row counts: items >= 12, staff >= 8, loans >= 15",
            "every loan has an item and a staff member; at least 3 loans are overdue",
        ],
        "outputs": [],
    },
    "pp_app": {
        "label": "Canvas app",
        "deliverable": [
            "Build a NEW Power Apps canvas app named `Equipment Loan Desk` on the wd_ tables from the earlier mission (names "
            "and ids are in its handoff), in Power Apps Studio on the desk screen, where people are watching.",
            "Step 1, the app shell, in the Studio UI with the `desk` command (desk shot PATH to see the screen, then "
            "desk glide X Y click, desk htype, desk key; look at a screenshot before every click): open "
            f"{config.power_apps_url('action=new-blank&form-factor=tablet')} "
            "in the browser (ctrl+t, type the address; Studio takes about a minute to load), click Skip on the "
            "welcome dialog, press ctrl+s and Save it as `Equipment Loan Desk` (a new app: never pick Replace existing). Then ... (toolbar overflow) > Settings > "
            "Updates > New > Coauthoring toggle > Update. That saves and reloads, and the reload opens ANOTHER blank "
            "app: ignore it. Get your app id with `pa-apps Equipment Loan Desk` and use only the one whose created time is after this mission started; if there is none, stop and say so in HANDOFF.md. Never open or edit any other app"
            + (f" (protected app ids: {', '.join(config.PROTECTED_APP_IDS)})" if config.PROTECTED_APP_IDS else "")
            + ". Then "
            f"and open {config.power_apps_url('action=edit&app-id=')}"
            "%2Fproviders%2FMicrosoft.PowerApps%2Fapps%2F<app id> in the same tab. Add the three wd_ tables there "
            "(Data > Add data > search > select) and Save. Keep that Studio tab open until the end of the mission: "
            "the MCP works through its coauthoring session. If a Microsoft sign-in page opens, it completes by "
            "itself; close the `Authentication Complete` tab afterwards. Never type a password.",
            f"Step 2, the screens, through the `canvas` MCP only. Read first: {config.CANVAS_SKILLS}/"
            "YamlSyntax.md, ControlGuide.md, LayoutGuide.md, PowerFxGuide.md, DataBehavior.md and ValidationWorkflow.md "
            f"(Microsoft's own canvas-apps guidance). connect with environment_id {config.PP_ENV_ID or '<environment id>'}, "
            "app_id from pa-apps, environment_category prod, auth_flow browser"
            + (f", login_hint {config.PP_LOGIN_HINT}" if config.PP_LOGIN_HINT else "")
            + f". The MCP may run in another container: use the folder "
            f"{config.CANVAS_DIR_MCP}/<run id> in MCP calls; it is {config.CANVAS_DIR_HOST}/<run id> for your "
            "own file edits (same folder). Order matters: sync_canvas first (it empties the folder, then writes the "
            "app's files), THEN write each screen as its own <Screen>.pa.yaml, add every new screen name to "
            "ScreensOrder in _EditorState.pa.yaml, and push with compile_canvas: a passing compile puts the screens "
            "live in Studio (check by syncing into a second folder). The screens: "
            "Borrow (pick an item, due date, submit a loan request), My loans (the signed-in user's loans with Return), "
            "Approvals (manager view of Requested loans with Approve / Reject). Clean light design, one accent colour. "
            "Never build screens by inserting controls by hand in the UI; if compile fails, fix the YAML.",
            "Step 3: Save and Publish in Studio (through `desk`), play each screen and save one real screenshot per "
            "screen, cropped to the app, into shared/screens/ as PNG. Then close your Studio tab.",
        ],
        "checks": [
            "a new canvas app named Equipment Loan Desk was created and published during this run, with its latest edits",
            "the app uses the wd_loan table",
            "shared/screens/ holds at least 3 PNG screenshots of the app",
        ],
        "outputs": ["shared/screens/"],
    },
    "pp_flows": {
        "label": "Approval and reminder flows",
        "deliverable": [
            "Create two cloud flows in the WorkdayEquipmentLoans solution (Dataverse `workflows` rows, "
            "category 5, with clientdata), using the environment's existing Dataverse and Approvals "
            "connections through connection references:",
            "1. `Loan approval`: when a wd_loan row is added with status Requested, start an approval to the "
            "manager and set the status to Approved or Rejected from the outcome.",
            "2. `Overdue reminder`: daily, find loans that are past due and not returned and record a "
            "reminder (an email draft is not sent; write the reminder text to the loan's notes).",
            "Turn both flows on.",
        ],
        "checks": [
            "both flows exist and are turned on",
            "a new test loan with status Requested starts a run of Loan approval",
        ],
        "outputs": [],
    },
    "excel": {
        "label": "Clean and analyse the loans export",
        "deliverable": [
            "Input: inbox/loans_export.xlsx (messy: blank rows, duplicate loan ids, mixed date formats).",
            "Rules: a loan id counts once (keep the first row); a row with no item is not a loan and is "
            "removed; a loan is overdue if it was returned after its due date, or is not returned and its due "
            "date is before 2026-10-30.",
            "Write shared/Loans_Analysis.xlsx with sheets `Clean` (one row per loan), `Top items` (item, "
            "loans, sorted, with a bar chart of the top 5), and `Summary` (column A label, column B value) "
            "with exactly these labels: Raw rows, Duplicates removed, Blank rows removed, Clean loans, "
            "Overdue loans, Overdue rate, Top item. Write the Summary as values, not formulas.",
            "Also save the chart as shared/top_items.png for the deck.",
        ],
        "checks": [
            "Summary numbers reconcile with the raw file: raw = clean + duplicates + blanks",
            "clean loans, overdue loans, overdue rate and top item match an independent recount",
            "the workbook has a chart and shared/top_items.png exists",
        ],
        "outputs": ["shared/Loans_Analysis.xlsx", "shared/top_items.png"],
    },
    "deck": {
        "label": "Manager deck",
        "deliverable": [
            "Write shared/Equipment_Loans_Briefing.pptx for the operations manager: the problem, how the new "
            "solution works (if shared/screens/ holds app screenshots, use them as they are; if not, show the tables, "
            "sample data and flows built today from the handoff notes, and never fake an app screen), the loans "
            "analysis (use shared/top_items.png "
            "and the Summary numbers), and the rollout plan. 8 to 10 slides, 16:9, a clean designed look with "
            "one accent colour, no template clip art.",
        ],
        "checks": [
            "the deck opens and has 8 to 10 slides",
            "it contains the chart (and, when the day builds an app, at least two app screenshots), byte-identical "
            "to the shared files",
            "the overdue rate and clean loan count it states match the verified analysis",
        ],
        "outputs": ["shared/Equipment_Loans_Briefing.pptx"],
    },
    "notes": {
        "label": "Meeting notes, actions and follow-up email",
        "deliverable": [
            "Input: inbox/ops_meeting_transcript.txt.",
            "Write shared/Ops_Meeting_Notes.docx with a Decisions list and an Actions table (Action, Owner, "
            "Due) where every owner is a meeting attendee and every due date is a real date.",
            "Draft the follow-up email as shared/Follow_up_email.eml (To: the attendees, a subject, the "
            "decisions and actions in the body, header X-Unsent: 1). Do not send it.",
        ],
        "checks": [
            "every decision and action agreed in the meeting is captured with the right owner",
            "every due date is a valid date; owners are attendees",
            "the email draft parses, is addressed to the attendees, is marked unsent, and was not sent",
        ],
        "outputs": ["shared/Ops_Meeting_Notes.docx", "shared/Follow_up_email.eml"],
    },
    "guide": {
        "label": "One-page user guide",
        "deliverable": [
            "Write shared/Equipment_Loans_User_Guide.docx: a one-page guide for staff and managers on how to "
            "borrow, return, approve, and what happens when an item is overdue, with one real app screenshot "
            "from shared/screens/.",
        ],
        "checks": [
            "the guide opens and renders to exactly one page",
            "it covers borrow, return, approve and overdue",
            "it contains one of the real app screenshots",
        ],
        "outputs": ["shared/Equipment_Loans_User_Guide.docx"],
    },
}

AGENTS = ("claude", "codex")


def other_agent(agent: str) -> str:
    return "codex" if agent == "claude" else "claude"


def describe_kinds() -> list[dict]:
    return [{"kind": k, "label": v["label"], "checks": v["checks"]} for k, v in KINDS.items()]
