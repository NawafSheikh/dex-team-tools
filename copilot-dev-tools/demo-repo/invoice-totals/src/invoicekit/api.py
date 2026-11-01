"""A tiny HTTP API: GET /health, GET /totals (sample invoice) and POST /totals (JSON invoice)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .totals import compute_totals

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample_invoice.json"


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/totals":
            invoice = json.loads(SAMPLE.read_text())
            self._send(200, {"invoice": invoice["number"], **asdict(compute_totals(invoice))})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/totals":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("content-length", 0))
        invoice = json.loads(self.rfile.read(length))
        self._send(200, asdict(compute_totals(invoice)))

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.command} {self.path} -> {args[1] if len(args) > 1 else ''}", flush=True)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    print(f"invoicekit api on http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
