# Xray MCP Monitor

`xray-mcp-monitor` is an MCP server for checking the reachability of nodes inside an Xray subscription.

It accepts an `http` or `https` subscription URL, parses common node formats, runs scheduled TCP probes against each matched node, and exposes the whole workflow through MCP tools.

## Features

- Fetches Xray subscriptions from `http` and `https` URLs
- Parses raw URI lists and common base64-encoded subscription payloads
- Supports `vmess`, `vless`, `trojan`, `ss`, `socks`, `http`, and `https`
- Recognizes `hy2`, `hysteria`, `hysteria2`, and `tuic`, but marks them unsupported for probing
- Runs a background scheduler for recurring checks
- Persists monitor definitions and latest results to a local JSON state file
- Exposes both one-off checks and long-running monitors through MCP tools
- Works over `stdio`, `streamable-http`, and `sse`

## How It Works

1. A client calls `register_subscription_monitor` or `check_subscription_once`.
2. The server fetches the subscription payload from the provided URL.
3. The payload is parsed into Xray nodes.
4. Each matched TCP node is checked with a direct `host:port` TCP connection.
5. The result is returned to the MCP client, and scheduled monitors are stored in local state.

## Limits

- This is a TCP reachability probe, not a full proxy or handshake validation.
- UDP-style protocols are currently not actively checked.
- Monitor state is local to the process and stored in a JSON file.
- `interval_seconds` must be at least `10`.
- `timeout_seconds` must be greater than `0`.

## Requirements

- Python `>=3.10`
- `mcp[cli] >=1.27,<2`

## Install

Using `pip`:

```bash
python3 -m venv .venv
./.venv/bin/pip install -e .
```

Using `uv`:

```bash
uv sync
```

## Run The Server

Stdio transport:

```bash
./.venv/bin/python -m xray_mcp_monitor.server
```

Streamable HTTP transport:

```bash
./.venv/bin/python -m xray_mcp_monitor.server --transport streamable-http
```

SSE transport:

```bash
./.venv/bin/python -m xray_mcp_monitor.server --transport sse
```

You can also use the installed console script:

```bash
./.venv/bin/xray-mcp-monitor
```

Manage scheduled checks without Codex:

```bash
./.venv/bin/xray-mcp-monitor-cli --help
```

## Environment Variables

```bash
export XRAY_MCP_TRANSPORT=stdio
export XRAY_MCP_HOST=127.0.0.1
export XRAY_MCP_PORT=8000
export XRAY_MCP_STATE_FILE=./xray_watch_state.json
```

- `XRAY_MCP_TRANSPORT`: default transport when `--transport` is omitted
- `XRAY_MCP_HOST`: bind host for network transports
- `XRAY_MCP_PORT`: bind port for network transports
- `XRAY_MCP_STATE_FILE`: path to the persistent watch state JSON file

## Run Without Codex

If you want the scheduler to keep running without an interactive Codex session, use the bundled CLI manager instead of the MCP transport.

Register a scheduled watch:

```bash
./.venv/bin/xray-mcp-monitor-cli \
  --state-file /root/xray-mcp/.codex/xray_watch_state.json \
  register "https://example.com/subscription" \
  --interval-seconds 300 \
  --timeout-seconds 5 \
  --node-name-keyword hk
```

List stored watches:

```bash
./.venv/bin/xray-mcp-monitor-cli \
  --state-file /root/xray-mcp/.codex/xray_watch_state.json \
  list
```

Run the background scheduler as a long-lived process:

```bash
XRAY_MCP_STATE_FILE=/root/xray-mcp/.codex/xray_watch_state.json \
./.venv/bin/python -m xray_mcp_monitor.cli daemon
```

You can also use:

```bash
./.venv/bin/python -m xray_mcp_monitor cli list
```

The scheduler state is persisted in `XRAY_MCP_STATE_FILE`, so the daemon reloads existing watches on startup.

## systemd Service

This repository includes a sample unit at [deploy/systemd/xray-mcp-monitor.service](/root/xray-mcp/deploy/systemd/xray-mcp-monitor.service).

Recommended install flow:

```bash
sudo mkdir -p /opt/xray-mcp /var/lib/xray-mcp-monitor
sudo cp -r /root/xray-mcp /opt/xray-mcp
cd /opt/xray-mcp
python3 -m venv .venv
./.venv/bin/pip install -e .
sudo cp deploy/systemd/xray-mcp-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xray-mcp-monitor
```

After that:

```bash
sudo systemctl status xray-mcp-monitor
journalctl -u xray-mcp-monitor -f
```

Before enabling the service, edit the unit file paths if your checkout is not under `/opt/xray-mcp`.

## MCP Tools

### `register_subscription_monitor`

Create a scheduled monitor and immediately run the first check.

Parameters:

- `subscription_url: str`
- `interval_seconds: int = 300`
- `timeout_seconds: float = 5.0`
- `node_name_keyword: str | None = None`

### `check_subscription_once`

Fetch a subscription and run a one-time check without storing a monitor.

Parameters:

- `subscription_url: str`
- `timeout_seconds: float = 5.0`
- `node_name_keyword: str | None = None`

### `list_subscription_monitors`

List all registered monitors.

### `get_subscription_monitor`

Return one stored monitor and its latest result.

Parameters:

- `watch_id: str`

### `run_monitor_now`

Run a stored monitor immediately.

Parameters:

- `watch_id: str`

### `set_monitor_enabled`

Enable or disable a stored monitor.

Parameters:

- `watch_id: str`
- `enabled: bool`

### `remove_subscription_monitor`

Remove a stored monitor.

Parameters:

- `watch_id: str`

## Status Values

Watch-level statuses:

- `error`: fetching the subscription failed
- `empty`: no nodes were found
- `no_match`: nodes were parsed, but none matched `node_name_keyword`
- `healthy`: all matched nodes were reachable
- `healthy_with_warnings`: all matched nodes were reachable, but some non-fatal parse warnings were recorded
- `degraded`: some matched nodes were reachable and some were unreachable
- `partial`: some matched nodes were reachable and some were unsupported
- `unsupported`: all matched nodes were unsupported for probing
- `down`: no matched nodes were reachable

Node-level statuses:

- `reachable`
- `unreachable`
- `unsupported`

## Example Tool Call

Input:

```json
{
  "subscription_url": "https://example.com/path/to/subscription",
  "interval_seconds": 300,
  "timeout_seconds": 5,
  "node_name_keyword": "hk"
}
```

Useful response fields:

- `watch.watch_id`: stable ID for later operations
- `watch.last_result`: latest stored result for a scheduled monitor
- `result.status`: current overall health state
- `result.nodes`: per-node reachability, latency, and error details
- `result.errors`: parse or fetch warnings

## Codex Integration

This repository already includes a project-scoped Codex MCP config at `.codex/config.toml`.

If you want to configure it manually, use:

```toml
[mcp_servers.xray_monitor]
command = "/path/to/xray-mcp/.venv/bin/python"
args = ["-m", "xray_mcp_monitor.server"]
cwd = "/path/to/xray-mcp"
startup_timeout_sec = 15
tool_timeout_sec = 120
enabled = true

[mcp_servers.xray_monitor.env]
XRAY_MCP_STATE_FILE = "/path/to/xray-mcp/.codex/xray_watch_state.json"
```

If you use the checked-in `.codex/config.toml`, update the paths if this repository is not located at `/root/xray-mcp`.

Then start Codex in this project:

```bash
codex -C /path/to/xray-mcp
```

Inside Codex, use `/mcp` to verify that `xray_monitor` is connected.

## Claude Desktop Style Config

```json
{
  "mcpServers": {
    "xray-monitor": {
      "command": "/path/to/xray-mcp/.venv/bin/python",
      "args": ["-m", "xray_mcp_monitor.server"],
      "cwd": "/path/to/xray-mcp"
    }
  }
}
```

## Development

Run tests:

```bash
./.venv/bin/python -m unittest discover -s tests
```

Useful local checks:

```bash
./.venv/bin/python -m xray_mcp_monitor.server --help
codex -C /path/to/xray-mcp mcp list
codex -C /path/to/xray-mcp mcp get xray_monitor
```
