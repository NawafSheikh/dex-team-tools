"""The connector definition matches the server's routes and never carries a key."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "connector"))
sys.path.insert(0, str(HERE.parent))

import build_connector  # noqa: E402


def test_connector_paths_exist_on_the_server(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKDAY_API_KEY", "k" * 40)
    import server

    spec = build_connector.build("workday.example.com/api")
    assert spec["host"] == "workday.example.com" and spec["basePath"] == "/api"
    # read the served paths from the OpenAPI document, not from route objects (their classes change between FastAPI versions)
    routes = set(server.create_app(tmp_path).openapi()["paths"])
    assert set(spec["paths"]) <= routes
    assert "X-API-Key" not in json.dumps(spec["paths"])
    ops = {o["operationId"] for item in spec["paths"].values() for o in item.values()}
    assert {"PlanWorkday", "GetWorkday", "GetMission", "ListMissionKinds", "StartWorkday"} <= ops
