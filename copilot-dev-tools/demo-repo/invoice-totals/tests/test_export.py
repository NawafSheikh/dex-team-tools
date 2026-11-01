import json
from pathlib import Path

from invoicekit.export import lines_to_csv

SAMPLE = json.loads((Path(__file__).parents[1] / "data" / "sample_invoice.json").read_text())


def test_csv_header():
    assert lines_to_csv(SAMPLE).splitlines()[0] == "sku,description,qty,unit_price,line_total"


def test_csv_line_totals_round_half_up():
    rows = lines_to_csv(SAMPLE).splitlines()[1:]
    assert [r.split(",")[-1] for r in rows] == ["55.35", "92.67", "20.63"]
