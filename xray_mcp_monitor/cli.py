from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from .monitor import WatchManager

DEFAULT_STATE_FILE = os.environ.get("XRAY_MCP_STATE_FILE", "./xray_watch_state.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Xray subscription monitors without an MCP client",
    )
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help="Path to the persistent watch state JSON file",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register", help="Create a scheduled monitor")
    register_parser.add_argument("subscription_url")
    register_parser.add_argument("--interval-seconds", type=int, default=300)
    register_parser.add_argument("--timeout-seconds", type=float, default=5.0)
    register_parser.add_argument("--node-name-keyword")
    register_parser.set_defaults(handler=_handle_register)

    check_once_parser = subparsers.add_parser("check-once", help="Run a one-off subscription check")
    check_once_parser.add_argument("subscription_url")
    check_once_parser.add_argument("--timeout-seconds", type=float, default=5.0)
    check_once_parser.add_argument("--node-name-keyword")
    check_once_parser.set_defaults(handler=_handle_check_once)

    list_parser = subparsers.add_parser("list", help="List stored monitors")
    list_parser.set_defaults(handler=_handle_list)

    get_parser = subparsers.add_parser("get", help="Get one stored monitor")
    get_parser.add_argument("watch_id")
    get_parser.set_defaults(handler=_handle_get)

    run_now_parser = subparsers.add_parser("run-now", help="Run one stored monitor immediately")
    run_now_parser.add_argument("watch_id")
    run_now_parser.set_defaults(handler=_handle_run_now)

    enable_parser = subparsers.add_parser("enable", help="Enable a stored monitor")
    enable_parser.add_argument("watch_id")
    enable_parser.set_defaults(handler=_handle_enable)

    disable_parser = subparsers.add_parser("disable", help="Disable a stored monitor")
    disable_parser.add_argument("watch_id")
    disable_parser.set_defaults(handler=_handle_disable)

    remove_parser = subparsers.add_parser("remove", help="Remove a stored monitor")
    remove_parser.add_argument("watch_id")
    remove_parser.set_defaults(handler=_handle_remove)

    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Run the background scheduler without starting the MCP server",
    )
    daemon_parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=60.0,
        help="How often the daemon wakes up while waiting for signals",
    )
    daemon_parser.set_defaults(handler=_handle_daemon)

    return parser


def _state_file_path(args: argparse.Namespace) -> Path:
    return Path(args.state_file).expanduser().resolve()


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _with_manager(
    args: argparse.Namespace,
    callback: Callable[[WatchManager], dict[str, Any]],
) -> dict[str, Any]:
    manager = WatchManager(_state_file_path(args))
    try:
        return callback(manager)
    finally:
        manager.shutdown()


def _handle_register(args: argparse.Namespace) -> int:
    payload = _with_manager(
        args,
        lambda manager: manager.register_watch(
            subscription_url=args.subscription_url,
            interval_seconds=args.interval_seconds,
            timeout_seconds=args.timeout_seconds,
            node_name_keyword=args.node_name_keyword,
        ),
    )
    _print_json(payload)
    return 0


def _handle_check_once(args: argparse.Namespace) -> int:
    payload = _with_manager(
        args,
        lambda manager: manager.check_subscription_once(
            subscription_url=args.subscription_url,
            timeout_seconds=args.timeout_seconds,
            node_name_keyword=args.node_name_keyword,
        ),
    )
    _print_json(payload)
    return 0


def _handle_list(args: argparse.Namespace) -> int:
    payload = _with_manager(args, lambda manager: manager.list_watches())
    _print_json(payload)
    return 0


def _handle_get(args: argparse.Namespace) -> int:
    payload = _with_manager(args, lambda manager: manager.get_watch(args.watch_id))
    _print_json(payload)
    return 0


def _handle_run_now(args: argparse.Namespace) -> int:
    payload = _with_manager(args, lambda manager: manager.run_check(args.watch_id))
    _print_json(payload)
    return 0


def _handle_enable(args: argparse.Namespace) -> int:
    payload = _with_manager(args, lambda manager: manager.set_watch_enabled(args.watch_id, True))
    _print_json(payload)
    return 0


def _handle_disable(args: argparse.Namespace) -> int:
    payload = _with_manager(args, lambda manager: manager.set_watch_enabled(args.watch_id, False))
    _print_json(payload)
    return 0


def _handle_remove(args: argparse.Namespace) -> int:
    payload = _with_manager(args, lambda manager: manager.remove_watch(args.watch_id))
    _print_json(payload)
    return 0


def _handle_daemon(args: argparse.Namespace) -> int:
    stop_event = threading.Event()
    manager = WatchManager(_state_file_path(args))

    def request_shutdown(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    try:
        _print_json(
            {
                "status": "running",
                "state_file": str(_state_file_path(args)),
                "watch_count": manager.list_watches()["count"],
            }
        )
        while not stop_event.wait(args.heartbeat_seconds):
            pass
    finally:
        manager.shutdown()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
