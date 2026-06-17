from __future__ import annotations

import argparse
import atexit
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .monitor import WatchManager

DEFAULT_HOST = os.environ.get("XRAY_MCP_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("XRAY_MCP_PORT", "8000"))
DEFAULT_STATE_FILE = Path(os.environ.get("XRAY_MCP_STATE_FILE", "./xray_watch_state.json"))

mcp = FastMCP(
    name="xray-monitor",
    host=DEFAULT_HOST,
    port=DEFAULT_PORT,
    json_response=True,
)
watch_manager = WatchManager(DEFAULT_STATE_FILE)
atexit.register(watch_manager.shutdown)


@mcp.tool()
def register_subscription_monitor(
    subscription_url: str,
    interval_seconds: int = 300,
    timeout_seconds: float = 5.0,
    node_name_keyword: str | None = None,
) -> dict[str, Any]:
    """Create a scheduled connectivity monitor for an Xray subscription URL."""

    return watch_manager.register_watch(
        subscription_url=subscription_url,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
        node_name_keyword=node_name_keyword,
    )


@mcp.tool()
def check_subscription_once(
    subscription_url: str,
    timeout_seconds: float = 5.0,
    node_name_keyword: str | None = None,
) -> dict[str, Any]:
    """Fetch a subscription URL and run a one-time connectivity check."""

    return watch_manager.check_subscription_once(
        subscription_url=subscription_url,
        timeout_seconds=timeout_seconds,
        node_name_keyword=node_name_keyword,
    )


@mcp.tool()
def list_subscription_monitors() -> dict[str, Any]:
    """List all registered scheduled monitors."""

    return watch_manager.list_watches()


@mcp.tool()
def get_subscription_monitor(watch_id: str) -> dict[str, Any]:
    """Get a monitor by watch ID, including the latest stored result."""

    return watch_manager.get_watch(watch_id)


@mcp.tool()
def run_monitor_now(watch_id: str) -> dict[str, Any]:
    """Run a monitor immediately."""

    return watch_manager.run_check(watch_id)


@mcp.tool()
def set_monitor_enabled(watch_id: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable a scheduled monitor."""

    return watch_manager.set_watch_enabled(watch_id, enabled)


@mcp.tool()
def remove_subscription_monitor(watch_id: str) -> dict[str, Any]:
    """Remove a scheduled monitor."""

    return watch_manager.remove_watch(watch_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Xray subscription connectivity MCP server")
    parser.add_argument(
        "--transport",
        default=os.environ.get("XRAY_MCP_TRANSPORT", "stdio"),
        choices=["stdio", "streamable-http", "sse"],
        help="MCP transport",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
