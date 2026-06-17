import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from xray_mcp_monitor.models import NodeCheckResult, XrayNode
from xray_mcp_monitor.monitor import WatchManager, check_node_connectivity


class MonitorTests(unittest.TestCase):
    def test_tcp_connectivity_success(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        stop_event = threading.Event()

        def accept_once() -> None:
            try:
                conn, _ = listener.accept()
                conn.close()
            finally:
                stop_event.set()

        thread = threading.Thread(target=accept_once, daemon=True)
        thread.start()
        try:
            result = check_node_connectivity(
                XrayNode(
                    scheme="vless",
                    name="local",
                    host="127.0.0.1",
                    port=port,
                    raw="",
                ),
                timeout_seconds=1.0,
            )
        finally:
            stop_event.wait(timeout=1)
            listener.close()

        self.assertEqual(result.status, "reachable")
        self.assertIsNotNone(result.latency_ms)

    def test_register_watch_runs_initial_check(self) -> None:
        subscription_payload = "vless://id@example.com:443?security=tls#demo"
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = WatchManager(Path(tmpdir) / "state.json")
            try:
                with patch(
                    "xray_mcp_monitor.monitor.fetch_subscription_text",
                    return_value=subscription_payload,
                ):
                    with patch(
                        "xray_mcp_monitor.monitor.check_node_connectivity",
                        return_value=NodeCheckResult(
                            name="demo",
                            scheme="vless",
                            host="example.com",
                            port=443,
                            network="tcp",
                            status="reachable",
                            checked_at="2026-06-17T00:00:00+00:00",
                            latency_ms=12.5,
                        ),
                    ) as mock_check:
                        result = manager.register_watch(
                            subscription_url="https://example.com/sub",
                            interval_seconds=30,
                            timeout_seconds=1.0,
                        )
            finally:
                manager.shutdown()

        self.assertIn("watch", result)
        self.assertEqual(result["result"]["matched_nodes"], 1)
        self.assertEqual(mock_check.call_count, 1)


if __name__ == "__main__":
    unittest.main()
