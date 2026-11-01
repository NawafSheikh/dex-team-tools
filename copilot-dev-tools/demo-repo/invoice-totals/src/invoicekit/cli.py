"""Print the totals of an invoice file."""
from __future__ import annotations

import json
import sys

from .money import format_money
from .totals import compute_totals


def main(argv: list[str] | None = None) -> int:
    path = (argv or sys.argv[1:] or ["data/sample_invoice.json"])[0]
    invoice = json.loads(open(path, encoding="utf-8").read())
    totals = compute_totals(invoice)
    for name in ("net", "discount", "vat", "gross"):
        print(f"{name:>9}: {format_money(getattr(totals, name))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
