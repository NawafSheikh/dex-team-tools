"""Unit tests for the pure parts: grouping, schema inference, plan enforcement, OpenAPI and server generation."""
from __future__ import annotations

import json
from pathlib import Path

from w2t import approval, catalog, mcpgen, openapi, schema
from w2t.cli import mark_reads
from w2t.endpoints import group_calls, in_scope, template_path
from w2t.plan import enforce


def call(method, url, rtype="fetch", req=None, resp=None, status=200):
    return {"method": method, "url": url, "resource_type": rtype, "request_body": req, "response_body": resp,
            "status": status, "content_type": "application/json", "page": "https://shop.test/"}


CALLS = [
    call("GET", "https://shop.test/api/items?q=shoe", resp='{"items":[{"id":1,"name":"Shoe"}]}'),
    call("GET", "https://shop.test/api/items?q=hat", resp='{"items":[{"id":2,"name":"Hat","price":9.5}]}'),
    call("GET", "https://shop.test/api/items/123", resp='{"id":123,"name":"Shoe"}'),
    call("POST", "https://api.shop.test/orders", req='{"item":1,"website":""}', resp=None, status=None),
    call("GET", "https://www.google-analytics.com/collect"),
    call("GET", "https://shop.test/data.js", rtype="script"),
]


def test_template_path_replaces_ids():
    assert template_path("/api/items/123") == "/api/items/{id}"
    assert template_path("/u/3f2a9c1e-1b2c-4d5e-8f90-123456789abc/x") == "/u/{id}/x"
    assert template_path("/api/items") == "/api/items"


def test_scope_is_site_and_subdomains_only():
    assert in_scope("api.shop.test", "shop.test")
    assert in_scope("shop.test", "www.shop.test")
    assert not in_scope("evilshop.test", "shop.test")
    assert not in_scope("www.google-analytics.com", "shop.test")


def test_group_calls_merges_and_drops_third_parties():
    eps, assets = group_calls(CALLS, "shop.test")
    keys = {e.key for e in eps}
    assert keys == {"GET shop.test/api/items", "GET shop.test/api/items/{id}", "POST api.shop.test/orders"}
    items = next(e for e in eps if e.key == "GET shop.test/api/items")
    assert items.calls == 2 and items.query == {"q": ["shoe", "hat"]}
    assert [a["path"] for a in assets] == ["/data.js"]


def test_schema_merges_samples():
    s = schema.infer([{"a": 1, "b": [{"x": "y"}]}, {"a": 2.5, "c": True}])
    assert s["properties"]["a"] == {"type": "number"}
    assert s["properties"]["b"]["items"]["properties"]["x"] == {"type": "string"}
    assert s["properties"]["c"] == {"type": "boolean"}
    assert schema.infer([]) == {"type": "object"}


def _plan():
    eps, _ = group_calls(CALLS, "shop.test")
    raw = {"title": "Shop", "description": "Find items and place orders.", "skipped": [], "gaps": [], "tools": [
        {"endpoint": "GET shop.test/api/items", "operation_id": "SearchItems", "summary": "Search items",
         "description": "Find items by name.", "kind": "read", "response_description": "Matching items",
         "params": [{"name": "q", "in": "query", "type": "string", "required": True, "description": "words"}]},
        {"endpoint": "GET shop.test/api/items/{id}", "operation_id": "GetItem", "summary": "Get item",
         "description": "One item.", "kind": "read", "response_description": "The item",
         "params": [{"name": "itemId", "in": "path", "type": "integer", "required": True, "description": "id"}]},
        {"endpoint": "POST api.shop.test/orders", "operation_id": "PlaceOrder", "summary": "Place order",
         "description": "Order an item.", "kind": "read", "response_description": "Order",
         "params": [{"name": "item", "in": "body", "type": "integer", "required": True, "description": "id"},
                    {"name": "src", "in": "body", "type": "string", "required": False, "description": "source"}]},
        {"endpoint": "GET shop.test/never-seen", "operation_id": "Invented", "summary": "x", "description": "x",
         "kind": "read", "response_description": "x", "params": []},
        {"endpoint": "GET shop.test/api/items", "operation_id": "SearchItems", "summary": "dup",
         "description": "dup", "kind": "read", "response_description": "x", "params": []},
    ]}
    return enforce(raw, eps), eps


def test_enforce_drops_invented_and_duplicates_and_floors_writes():
    plan, _ = _plan()
    ids = [t["operation_id"] for t in plan["tools"]]
    assert ids == ["SearchItems", "GetItem", "PlaceOrder"]
    assert next(t for t in plan["tools"] if t["operation_id"] == "PlaceOrder")["kind"] == "write"


def test_mark_reads_is_explicit_and_recorded():
    plan, _ = _plan()
    marked = mark_reads(plan, {"PlaceOrder"})
    order = next(t for t in marked["tools"] if t["operation_id"] == "PlaceOrder")
    assert order["kind"] == "read" and order["read_ok_by_human"] is True
    assert next(t for t in plan["tools"] if t["operation_id"] == "PlaceOrder")["kind"] == "write"  # not mutated


def test_openapi_v2_shape_and_hidden_tag():
    plan, eps = _plan()
    spec = openapi.build(plan, eps, tag={"body": {"src": "?utm_source=copilot"}})
    assert spec["swagger"] == "2.0" and spec["host"] == "shop.test"
    assert "/api/items/{itemId}" in spec["paths"]
    order = spec["paths"]["/orders"]["post"]
    body = next(p for p in order["parameters"] if p["in"] == "body")["schema"]
    assert body["properties"]["src"]["x-ms-visibility"] == "internal"
    assert body["properties"]["src"]["default"] == "?utm_source=copilot"
    assert set(body["required"]) == {"item", "src"}
    assert order["x-openai-isConsequential"] is True
    assert spec["paths"]["/api/items"]["get"]["x-openai-isConsequential"] is False
    search = spec["paths"]["/api/items"]["get"]
    assert search["responses"]["200"]["schema"]["properties"]["items"]["type"] == "array"


def test_mcp_server_render_hides_tag_fields_and_marks_writes():
    plan, _ = _plan()
    tag = {"body": {"src": "?utm_source=mcp&utm_campaign={client}"}}
    src = mcpgen.render(plan, name="shop-tools", tag=tag)
    tools = mcpgen.tools_for_server(plan, tag)
    order = next(t for t in tools if t["name"] == "PlaceOrder")
    assert [p["name"] for p in order["params"]] == ["item"]
    assert "__" not in src.split("\n", 1)[1].replace("__proto__", "")  # every placeholder filled
    assert '"https://shop.test"' in src and "confirm=true" in mcpgen.instructions(plan)


def test_catalog_links_and_index_urls():
    linkset = {"linkset": [{"anchor": "https://shop.test/api", "service-desc": [{"href": "/openapi.json"}]}]}
    assert list(catalog._links(linkset, "https://shop.test/.well-known/api-catalog")) == [
        "https://shop.test/api", "https://shop.test/openapi.json"]
    index = {"parts": [{"url": "/api/a"}, {"nested": {"href": "b"}}]}
    assert list(catalog._index_urls(index, "https://shop.test/api/")) == [
        "https://shop.test/api/a", "https://shop.test/api/b"]


def test_file_approval_needs_a_written_decision(tmp_path: Path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"title": "t"}), encoding="utf-8")
    assert approval._decision(f) is None
    f.write_text(json.dumps({"decision": "approve"}), encoding="utf-8")
    assert approval._decision(f) is True
    f.write_text(json.dumps({"decision": "deny"}), encoding="utf-8")
    assert approval._decision(f) is False
    assert approval.DenyAll().ask(approval.Request("s", "t", "d", "r")) is False


def test_undash_and_short_title():
    from w2t.plan import undash
    assert undash({"a": ["x \u2014 y", "1\u20132"]}) == {"a": ["x, y", "1-2"]}
    assert openapi.short_title("mcpforwork.com, Hire Dex and her AI team") == "mcpforwork.com, Hire Dex and"
    assert openapi.short_title("Short") == "Short"
