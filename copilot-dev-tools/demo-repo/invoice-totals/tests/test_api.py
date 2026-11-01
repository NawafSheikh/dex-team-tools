import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from invoicekit.api import Handler


def test_health_and_totals():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert json.loads(urllib.request.urlopen(f"{base}/health").read()) == {"status": "ok"}
        body = json.loads(urllib.request.urlopen(f"{base}/totals").read())
        assert body["invoice"] == "INV-2026-0142"
        assert set(body) >= {"net", "discount", "vat", "gross"}
    finally:
        server.shutdown()
