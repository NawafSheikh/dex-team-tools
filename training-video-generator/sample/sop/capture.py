"""Real screenshots of Brightwater Expenses (a fictional company's app) for the SOP, taken while the flow runs.

Usage: python capture.py   (needs playwright with Chromium: pip install playwright && playwright install chromium)
Writes shots/01..07 PNGs, then run make_sop.py to build the Word SOP from them.
"""
import http.server, threading, functools, pathlib
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Error as PlaywrightError, sync_playwright

APP = pathlib.Path(__file__).resolve().parent.parent / "expense-app"
OUT = pathlib.Path(__file__).resolve().parent / "shots"
RECEIPT = OUT / "receipt_harbour_cafe.png"


def make_receipt(path: pathlib.Path) -> None:
    """A plain, clearly fictional till receipt to upload in the form."""
    img = Image.new("RGB", (600, 900), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    lines = ["HARBOUR CAFE", "(fictional receipt)", "", "27/10/2026  12:41", "", "2 x Lunch special   32.00",
             "2 x Sparkling water  6.40", "", "TOTAL EUR          38.40", "", "Thank you"]
    for i, line in enumerate(lines):
        d.text((60, 80 + i * 60), line, fill="black", font=font)
    img.save(path)


def launch(p):
    """Playwright's own Chromium if installed, else an installed Chrome or Edge."""
    for kwargs in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
        try:
            return p.chromium.launch(**kwargs)
        except PlaywrightError:
            continue
    raise SystemExit("no browser: run `playwright install chromium`")


OUT.mkdir(exist_ok=True)
if not RECEIPT.exists():
    make_receipt(RECEIPT)

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(APP))
http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/"

with sync_playwright() as p:
    b = launch(p)
    pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=4 / 3)
    pg.clock.set_fixed_time("2026-10-28T09:30:00")
    pg.goto(url + "#reset"); pg.wait_for_timeout(400); pg.goto(url); pg.wait_for_timeout(600)
    pg.screenshot(path=OUT / "01_my_expenses.png")
    pg.locator("text=New expense").first.click(); pg.wait_for_timeout(500)
    pg.screenshot(path=OUT / "02_new_expense.png")
    pg.set_input_files("#f-receipt", str(RECEIPT)); pg.wait_for_timeout(700)
    pg.screenshot(path=OUT / "03_receipt.png")
    pg.fill("#f-merchant", "Harbour Cafe")
    pg.fill("#f-date", "2026-10-27")
    pg.fill("#f-amount", "38.40")
    pg.select_option("#f-category", label="Meals"); pg.wait_for_timeout(300)
    pg.fill("#f-attendees", "2")
    pg.select_option("#f-costCentre", index=1)
    pg.fill("#f-purpose", "Lunch with the Van Dijk Transport account manager to agree the winter delivery routes.")
    pg.wait_for_timeout(300)
    pg.screenshot(path=OUT / "04_details.png")
    pg.check("#f-confirm"); pg.wait_for_timeout(300)
    pg.screenshot(path=OUT / "05_confirm.png")
    pg.click("#btn-submit"); pg.wait_for_timeout(700)
    pg.screenshot(path=OUT / "06_submitted.png")
    pg.wait_for_timeout(4500)
    pg.locator("text=Harbour Cafe").first.click(); pg.wait_for_timeout(600)
    pg.screenshot(path=OUT / "07_status.png")
    b.close()
srv.shutdown()
print("ok", sorted(x.name for x in OUT.glob("0*.png")))
