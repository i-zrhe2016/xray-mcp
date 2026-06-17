from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .monitor import WatchManager

DEFAULT_HOST = os.environ.get("XRAY_MCP_WEB_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("XRAY_MCP_WEB_PORT", "8080"))
DEFAULT_STATE_FILE = Path(os.environ.get("XRAY_MCP_STATE_FILE", "./xray_watch_state.json"))

STATIC_FILES = {
    "/": ("web/index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("web/styles.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("web/app.js", "application/javascript; charset=utf-8"),
}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], state_file: str | Path) -> None:
        super().__init__(server_address, DashboardHandler)
        self.watch_manager = WatchManager(state_file)

    def shutdown(self) -> None:
        try:
            super().shutdown()
        finally:
            self.watch_manager.shutdown()


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer
    server_version = "XrayMCPDashboard/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in STATIC_FILES:
            self._serve_static(parsed.path)
            return
        if parsed.path == "/api/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path == "/api/watches":
            self._run_action(lambda: self.server.watch_manager.list_watches())
            return
        if parsed.path.startswith("/api/watches/"):
            watch_id = parsed.path.removeprefix("/api/watches/")
            if watch_id:
                self._run_action(lambda: self.server.watch_manager.get_watch(watch_id))
                return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/watches":
            payload = self._read_json_body()
            self._run_action(
                lambda: self.server.watch_manager.register_watch(
                    subscription_url=str(payload["subscription_url"]),
                    interval_seconds=int(payload.get("interval_seconds", 300)),
                    timeout_seconds=float(payload.get("timeout_seconds", 5.0)),
                    node_name_keyword=self._optional_string(payload.get("node_name_keyword")),
                )
            )
            return
        if parsed.path == "/api/check-once":
            payload = self._read_json_body()
            self._run_action(
                lambda: self.server.watch_manager.check_subscription_once(
                    subscription_url=str(payload["subscription_url"]),
                    timeout_seconds=float(payload.get("timeout_seconds", 5.0)),
                    node_name_keyword=self._optional_string(payload.get("node_name_keyword")),
                )
            )
            return
        if parsed.path.startswith("/api/watches/"):
            watch_id, action = self._parse_watch_action(parsed.path)
            if watch_id and action == "run":
                self._run_action(lambda: self.server.watch_manager.run_check(watch_id))
                return
            if watch_id and action == "enable":
                self._run_action(lambda: self.server.watch_manager.set_watch_enabled(watch_id, True))
                return
            if watch_id and action == "disable":
                self._run_action(lambda: self.server.watch_manager.set_watch_enabled(watch_id, False))
                return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/watches/"):
            watch_id = parsed.path.removeprefix("/api/watches/")
            if watch_id and "/" not in watch_id:
                self._run_action(lambda: self.server.watch_manager.remove_watch(watch_id))
                return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _run_action(self, action: Any) -> None:
        try:
            payload = action()
        except KeyError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return
        self._send_json(HTTPStatus.OK, payload)

    def _serve_static(self, path: str) -> None:
        relative_path, content_type = STATIC_FILES[path]
        content = resources.files("xray_mcp_monitor").joinpath(relative_path).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("request body is required")
        body = self.rfile.read(content_length)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _parse_watch_action(self, path: str) -> tuple[str | None, str | None]:
        suffix = path.removeprefix("/api/watches/")
        parts = [part for part in suffix.split("/") if part]
        if len(parts) != 2:
            return None, None
        return parts[0], parts[1]

    def _optional_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


def create_server(host: str, port: int, state_file: str | Path) -> DashboardServer:
    return DashboardServer((host, port), state_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Xray monitor web dashboard")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port, args.state_file)

    def request_shutdown(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    print(f"Xray monitor dashboard listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
