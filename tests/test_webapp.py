import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import request

from xray_mcp_monitor.models import NodeCheckResult
from xray_mcp_monitor.webapp import create_server


class WebAppTests(unittest.TestCase):
    def test_dashboard_serves_index_and_create_watch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            with self._patched_monitor():
                server, thread, base_url = self._start_server(state_file)
                try:
                    with request.urlopen(f"{base_url}/") as response:
                        body = response.read().decode("utf-8")
                    self.assertIn("Subscription Health Console", body)

                    created = self._request_json(
                        f"{base_url}/api/watches",
                        method="POST",
                        payload={
                            "subscription_url": "https://example.com/sub",
                            "interval_seconds": 30,
                            "timeout_seconds": 1,
                            "node_name_keyword": "hk",
                        },
                    )
                    self.assertEqual(created["result"]["matched_nodes"], 1)

                    listed = self._request_json(f"{base_url}/api/watches")
                    self.assertEqual(listed["count"], 1)
                finally:
                    server.shutdown()
                    thread.join(timeout=2)
                    server.server_close()

    def test_quick_check_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            with self._patched_monitor():
                server, thread, base_url = self._start_server(state_file)
                try:
                    payload = self._request_json(
                        f"{base_url}/api/check-once",
                        method="POST",
                        payload={
                            "subscription_url": "https://example.com/sub",
                            "timeout_seconds": 1,
                            "node_name_keyword": "hk",
                        },
                    )
                    self.assertEqual(payload["result"]["status"], "healthy")
                finally:
                    server.shutdown()
                    thread.join(timeout=2)
                    server.server_close()

    def _start_server(self, state_file: Path) -> tuple[object, threading.Thread, str]:
        server = create_server("127.0.0.1", 0, state_file)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        return server, thread, f"http://{host}:{port}"

    def _request_json(self, url: str, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, method=method, data=data, headers=headers)
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))

    def _patched_monitor(self):  # type: ignore[no-untyped-def]
        from unittest.mock import patch

        return patch.multiple(
            "xray_mcp_monitor.monitor",
            fetch_subscription_text=lambda *_args, **_kwargs: "vless://id@example.com:443?security=tls#hk-demo",
            check_node_connectivity=lambda *_args, **_kwargs: NodeCheckResult(
                name="hk-demo",
                scheme="vless",
                host="example.com",
                port=443,
                network="tcp",
                status="reachable",
                checked_at="2026-06-17T00:00:00+00:00",
                latency_ms=8.4,
            ),
        )
