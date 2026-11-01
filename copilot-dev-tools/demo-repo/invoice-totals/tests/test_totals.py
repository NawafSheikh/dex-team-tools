import json
from pathlib import Path

from invoicekit import compute_totals

SAMPLE = json.loads((Path(__file__).parents[1] / "data" / "sample_invoice.json").read_text())


def test_no_vat_no_discount():
    invoice = {"lines": [{"qty": 2, "unit_price": 10.0}]}
    totals = compute_totals(invoice)
    assert (totals.net, totals.vat, totals.discount, totals.gross) == (20.0, 0.0, 0.0, 20.0)


def test_vat_only():
    invoice = {"vat_rate": 0.18, "lines": [{"qty": 1, "unit_price": 100.0}]}
    assert compute_totals(invoice).gross == 118.0


def test_discount_comes_off_net_before_vat():
    invoice = {"vat_rate": 0.20, "discount_pct": 0.10, "lines": [{"qty": 1, "unit_price": 100.0}]}
    totals = compute_totals(invoice)
    assert totals.discount == 10.0
    assert totals.vat == 18.0
    assert totals.gross == 108.0


def test_sample_invoice_matches_the_accountant():
    totals = compute_totals(SAMPLE)
    assert totals.net == 168.65
    assert totals.discount == 16.87
    assert totals.vat == 27.32
    assert totals.gross == 179.10
