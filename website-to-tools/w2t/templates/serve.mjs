// Standalone runner for the generated MCP server: node serve.mjs [port]. Endpoint: POST http://host:port/mcp
// Safe defaults: listens on 127.0.0.1 only. To expose it (HOST=0.0.0.0), MCP_API_KEY must be set; every /mcp call
// must then send it in the x-api-key header. A public deploy behind a platform (Vercel) uses mcp-server.mjs directly.
import { createServer } from "node:http";
import handler from "./mcp-server.mjs";

const port = Number(process.argv[2] || process.env.PORT || 8787);
const host = process.env.HOST || "127.0.0.1";
const KEY = process.env.MCP_API_KEY || "";
const LOCAL = new Set(["127.0.0.1", "localhost", "::1"]);
if (!LOCAL.has(host) && KEY.length < 16) {
  process.stderr.write("Refusing to listen on " + host + " without MCP_API_KEY (16+ characters).\n");
  process.exit(1);
}
const MAX_BODY = 256 * 1024;

createServer((req, res) => {
  const path = (req.url || "/").split("?")[0];
  if (path === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end('{"ok":true}');
  }
  if (KEY && req.headers["x-api-key"] !== KEY) {
    res.writeHead(401, { "Content-Type": "application/json" });
    return res.end('{"error":"missing or wrong x-api-key"}');
  }
  if (path !== "/mcp") {
    res.writeHead(404);
    return res.end();
  }
  const chunks = [];
  let size = 0;
  req.on("data", (c) => {
    size += c.length;
    if (size > MAX_BODY) { res.writeHead(413); res.end(); req.destroy(); return; }
    chunks.push(c);
  });
  req.on("end", () => {
    if (res.writableEnded) return;
    try {
      req.body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : undefined;
    } catch {
      res.writeHead(400, { "Content-Type": "application/json" });
      return res.end('{"jsonrpc":"2.0","error":{"code":-32700,"message":"Parse error"},"id":null}');
    }
    handler(req, res);
  });
}).listen(port, host, () => process.stderr.write(`MCP server on http://${host}:${port}/mcp\n`));
