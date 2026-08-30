#!/usr/bin/env python3
"""Stable QGIS MCP client with length-prefix framing. Usage:
  python3 qgis_mcp.py <json_payload_or_type> [params_json]

Examples:
  python3 qgis_mcp.py '{"type":"ping","params":{}}'
  python3 qgis_mcp.py ping
  python3 qgis_mcp.py get_layers
  python3 qgis_mcp.py add_field '{"layer_id":"xxx","field_name":"test","expression":"...", "field_type":"Double"}'

Host and port from env QGIS_MCP_HOST / QGIS_MCP_PORT, defaults to 127.0.0.1:9877.
"""
import socket, json, time, sys, os

HOST = os.environ.get("QGIS_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("QGIS_MCP_PORT", "9877"))
TIMEOUT = 60  # max total wait seconds


def _recv_exact(s, n):
    """Read exactly n bytes from socket."""
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            return None  # connection closed
        buf += chunk
    return buf


def q(cmd, timeout=TIMEOUT):
    """Send a command to QGIS MCP server and return the parsed response.
    Uses 4-byte length-prefix framing for reliable message boundaries."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((HOST, PORT))
        s.sendall(json.dumps(cmd).encode("utf-8"))
    except Exception as e:
        s.close()
        return {"status": "error", "message": f"Connection failed: {e}"}

    # Read 4-byte length prefix
    len_bytes = _recv_exact(s, 4)
    if len_bytes is None:
        s.close()
        return {"status": "error", "message": "Empty response (connection closed)"}

    payload_len = int.from_bytes(len_bytes, "big")

    # Read exactly the payload
    payload = _recv_exact(s, payload_len)
    s.close()

    if payload is None:
        return {"status": "error", "message": "Incomplete response (connection closed)"}

    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"Bad JSON: {payload[:200]} — {e}"}


def pretty(r):
    """Print response nicely."""
    if r is None:
        return "No response"
    if r.get("status") == "error":
        return f"ERROR: {r.get('message', '')}"
    if "result" in r:
        res = r["result"]
        if isinstance(res, dict):
            return json.dumps(res, indent=2, ensure_ascii=False)
        return str(res)
    return json.dumps(r, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 qgis_mcp.py <type> [params_json]")
        print("  or:  python3 qgis_mcp.py '{\"type\":\"...\",\"params\":{...}}'")
        print("\nEnv: QGIS_MCP_HOST (default 127.0.0.1), QGIS_MCP_PORT (default 9877)")
        sys.exit(1)

    arg = sys.argv[1]

    # If it looks like a JSON object, parse it as full command
    if arg.startswith("{"):
        cmd = json.loads(arg)
    else:
        cmd_type = arg
        params = {}
        if len(sys.argv) > 2:
            params = json.loads(sys.argv[2])
        cmd = {"type": cmd_type, "params": params}

    print(f">>> {cmd['type']} {cmd.get('params', {})}")
    r = q(cmd)
    print(pretty(r))
