"""Export a Penpot shape/board to PNG via the hosted Penpot MCP (no plugin-side base64 juggling).

Usage:  python docs/design/_tools/penpot_export.py <shapeId> <out.png> [--svg]
Reads the MCP key from ~/.claude.json (mcpServers.penpot.url). Requires the Penpot MCP plugin to be
connected in an open browser tab (see docs/design/README.md).
"""
import base64
import json
import os
import sys
import urllib.request


def _key() -> str:
    cfg = json.load(open(os.path.expanduser("~/.claude.json"), encoding="utf-8"))
    return cfg["mcpServers"]["penpot"]["url"].split("userToken=")[1]


def _post(url: str, body: dict, sid: str | None = None):
    h = {"User-Agent": "candleviewer-design-tools", "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if sid:
        h["Mcp-Session-Id"] = sid
    r = urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), h), timeout=300)
    sid = r.headers.get("Mcp-Session-Id") or sid
    data = [json.loads(l[5:]) for l in r.read().decode().splitlines() if l.startswith("data:")]
    return sid, data


def export(shape_id: str, out: str, fmt: str = "png") -> int:
    url = "https://design.penpot.app/mcp/stream?userToken=" + _key()
    sid, _ = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "cv-export", "version": "1"}}})
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    _, d = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "export_shape", "arguments": {"shapeId": shape_id, "format": fmt}}}, sid)
    msg = d[-1]
    if "error" in msg:
        raise SystemExit("MCP error: " + json.dumps(msg["error"])[:400])
    for c in msg["result"].get("content", []):
        if c.get("type") == "image":
            raw = base64.b64decode(c["data"])
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            open(out, "wb").write(raw)
            return len(raw)
        if c.get("type") == "text" and fmt == "svg":
            open(out, "w", encoding="utf-8").write(c["text"])
            return len(c["text"])
    raise SystemExit("no image in response: " + json.dumps(msg)[:400])


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    n = export(sys.argv[1], sys.argv[2], "svg" if "--svg" in sys.argv else "png")
    print(f"wrote {sys.argv[2]} ({n} bytes)")
