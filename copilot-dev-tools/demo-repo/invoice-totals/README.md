# invoicekit

Invoice totals, VAT and CSV export for small businesses.

```bash
python -m pytest -q                      # run the tests
python -m invoicekit.api                 # serve totals on http://localhost:8000
python -m invoicekit.cli data/sample_invoice.json
```

Rules the totals must follow:
- Money is rounded to the cent, half up (2.675 becomes 2.68).
- A discount comes off the net amount, before VAT is added.
