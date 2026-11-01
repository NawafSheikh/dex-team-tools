"""End-to-end MCP smoke test: python smoke_mcp.py <url> <key> [tool json-args ...]

With no tool given: initialize, list tools, print names. Otherwise call each
tool with its JSON arguments and print the result text.
"""
import json
import sys

import httpx

LIMIT = 900
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def rpc(client, url, key, method, params, rid):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
    resp = client.post(url, json=body, headers={**HEADERS, "x-api-key": key})
    if resp.status_code != 200:
        return {"http_status": resp.status_code, "body": resp.text[:500]}
    return resp.json()


def main() -> None:
    url, key, *rest = sys.argv[1:]
    with httpx.Client(timeout=None) as client:
        init = rpc(client, url, key, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "1"}}, 1)
        print("initialize:", json.dumps(init.get("result", init))[:300])
        if not rest:
            tools = rpc(client, url, key, "tools/list", {}, 2)
            names = [t["name"] for t in tools.get("result", {}).get("tools", [])]
            print(len(names), "tools:", " ".join(names))
            return
        calls = json.loads(open(rest[0]).read()) if rest[0].endswith(".json") else             [[rest[i], json.loads(rest[i + 1])] for i in range(0, len(rest), 2)]
        for i, (name, args) in enumerate(calls):
            out = rpc(client, url, key, "tools/call", {"name": name, "arguments": args}, 10 + i)
            res = out.get("result", out)
            text = "".join(c.get("text", "") for c in res.get("content", [])) if "content" in res else res
            print(f"--- {name} error={res.get('isError')}\n{str(text)[:1500]}")


if __name__ == "__main__":
    main()
