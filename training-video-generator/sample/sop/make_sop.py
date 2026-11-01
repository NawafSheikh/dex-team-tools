"""Brightwater Logistics SOP FIN-SOP-014 as a real Word document with the app's screenshots embedded."""
import pathlib
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

HERE = pathlib.Path(__file__).resolve().parent
SHOTS = HERE / "shots"
TEAL = RGBColor(0x0F, 0x76, 0x6E)

d = Document()
st = d.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(11)
for s in d.sections:
    s.left_margin = s.right_margin = Cm(2.2); s.top_margin = s.bottom_margin = Cm(2)

p = d.add_paragraph(); r = p.add_run("BRIGHTWATER LOGISTICS"); r.bold = True; r.font.color.rgb = TEAL; r.font.size = Pt(10)
d.add_heading("Standard Operating Procedure: Submitting an expense in Brightwater Expenses", 0)

t = d.add_table(rows=5, cols=2); t.style = "Light Grid Accent 1"
for row, (k, v) in zip(t.rows, [("Document", "FIN-SOP-014"), ("Version", "2.0 (replaces FIN-SOP-009, paper claim form)"),
                                ("Owner", "Finance Operations"), ("Effective", "3 November 2026"), ("Applies to", "All Brightwater employees")]):
    row.cells[0].text = k; row.cells[1].text = v

d.add_heading("1. Purpose", 1)
d.add_paragraph("From 3 November 2026 all work expenses are claimed in the new Brightwater Expenses app. "
                "This procedure explains how to submit an expense so it is approved and paid without delays.")
d.add_heading("2. Before you start", 1)
for b in ["Keep the receipt. A receipt is required for every expense over EUR 25.",
          "Submit within 30 days of the expense date. Older expenses need your manager to approve an exception.",
          "Meals are reimbursed up to EUR 60 per person."]:
    d.add_paragraph(b, style="List Bullet")

d.add_heading("3. Procedure", 1)
steps = [
    ("Open a new expense", "Open Brightwater Expenses. On the My expenses page, select New expense in the top right corner.", "01_my_expenses.png"),
    ("Add the receipt", "Drag the photo or scan of your receipt into the Receipt box, or select Browse files. PNG, JPG and WEBP files up to 10 MB are accepted.", "02_new_expense.png"),
    ("Check the receipt preview", "The receipt appears in the Receipt box with a green tick. If it is the wrong file, remove it and add the right one.", "03_receipt.png"),
    ("Fill in the details", "Enter the Merchant, Date, Amount, Category and Cost centre. For Meals, enter the Number of people; the app shows the amount per person. Describe the Business purpose: who it was for and why it was needed.", "04_details.png"),
    ("Confirm the policy and submit", "Tick I confirm this expense follows the Brightwater expense policy, then select Submit for approval. The button stays grey until everything required is filled in.", "05_confirm.png"),
    ("Check that it was sent", "A message confirms the expense was submitted to your manager, and it appears at the top of My expenses with the status Submitted.", "06_submitted.png"),
    ("Follow the status", "Select the expense to see its status: Manager approval, then Finance check, then Reimbursed in the Friday payment run.", "07_status.png"),
]
for i, (h, body, shot) in enumerate(steps, 1):
    d.add_heading(f"Step {i}: {h}", 2)
    d.add_paragraph(body)
    d.add_picture(str(SHOTS / shot), width=Cm(16.5))
    cap = d.add_paragraph(f"Figure {i}: {h}"); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER; cap.runs[0].italic = True; cap.runs[0].font.size = Pt(9)

d.add_heading("4. Common problems", 1)
for b in ["Submit for approval is grey: the line next to the button lists what is still missing.",
          "Meal over EUR 60 per person: the app shows a warning. Add the reason in the Business purpose; your manager decides.",
          "Expense older than 30 days: submit it anyway and explain why; your manager must approve an exception."]:
    d.add_paragraph(b, style="List Bullet")
d.add_heading("5. Help", 1)
d.add_paragraph("Questions go to Finance Operations in the Expenses help channel in Teams.")
d.add_heading("6. Revision history", 1)
rh = d.add_table(rows=3, cols=3); rh.style = "Light Grid Accent 1"
for row, vals in zip(rh.rows, [("Version", "Date", "Change"), ("1.0", "12 March 2024", "Paper claim form (FIN-SOP-009)"), ("2.0", "28 October 2026", "Rewritten for Brightwater Expenses")]):
    for c, v in zip(row.cells, vals): c.text = v

out = HERE / "Brightwater_SOP_Submit_an_expense.docx"
d.save(out); print(out, out.stat().st_size)
