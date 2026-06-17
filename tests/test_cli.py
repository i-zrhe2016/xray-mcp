import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from xray_mcp_monitor.cli import main
from xray_mcp_monitor.models import NodeCheckResult


class CLITests(unittest.TestCase):
    def test_register_and_list_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            register_output = self._run_cli(
                state_file,
                [
                    "register",
                    "https://example.com/subscription",
                    "--interval-seconds",
                    "30",
                    "--node-name-keyword",
                    "hk",
                ],
            )

            self.assertEqual(register_output["result"]["matched_nodes"], 1)
            watch_id = register_output["watch"]["watch_id"]

            list_output = self._run_cli(state_file, ["list"])

            self.assertEqual(list_output["count"], 1)
            self.assertEqual(list_output["watches"][0]["watch_id"], watch_id)
            self.assertEqual(list_output["watches"][0]["node_name_keyword"], "hk")

    def test_disable_and_remove_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            register_output = self._run_cli(
                state_file,
                [
                    "register",
                    "https://example.com/subscription",
                    "--interval-seconds",
                    "30",
                ],
            )
            watch_id = register_output["watch"]["watch_id"]

            disable_output = self._run_cli(state_file, ["disable", watch_id])
            self.assertFalse(disable_output["enabled"])

            remove_output = self._run_cli(state_file, ["remove", watch_id])
            self.assertTrue(remove_output["removed"])

            list_output = self._run_cli(state_file, ["list"])
            self.assertEqual(list_output["count"], 0)

    def _run_cli(self, state_file: Path, args: list[str]) -> dict[str, object]:
        stdout = io.StringIO()
        with patch(
            "xray_mcp_monitor.monitor.fetch_subscription_text",
            return_value="vless://id@example.com:443?security=tls#hk-demo",
        ):
            with patch(
                "xray_mcp_monitor.monitor.check_node_connectivity",
                return_value=NodeCheckResult(
                    name="hk-demo",
                    scheme="vless",
                    host="example.com",
                    port=443,
                    network="tcp",
                    status="reachable",
                    checked_at="2026-06-17T00:00:00+00:00",
                    latency_ms=9.1,
                ),
            ):
                with redirect_stdout(stdout):
                    exit_code = main(["--state-file", str(state_file), *args])

        self.assertEqual(exit_code, 0)
        return json.loads(stdout.getvalue())
