import base64
import json
import unittest

from xray_mcp_monitor.subscription import parse_node_line, parse_subscription_text


class SubscriptionParsingTests(unittest.TestCase):
    def test_parse_vmess_subscription_payload(self) -> None:
        vmess_json = json.dumps(
            {
                "v": "2",
                "ps": "demo-node",
                "add": "example.com",
                "port": "443",
                "id": "00000000-0000-0000-0000-000000000000",
            }
        )
        vmess_uri = "vmess://" + base64.b64encode(vmess_json.encode()).decode()
        payload = base64.b64encode((vmess_uri + "\n").encode()).decode()

        nodes, errors = parse_subscription_text(payload)

        self.assertEqual(errors, [])
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].name, "demo-node")
        self.assertEqual(nodes[0].host, "example.com")
        self.assertEqual(nodes[0].port, 443)

    def test_parse_ss_uri(self) -> None:
        encoded = base64.urlsafe_b64encode(b"aes-256-gcm:secret@example.org:8388").decode().rstrip("=")
        node = parse_node_line(f"ss://{encoded}#ss-node")

        self.assertEqual(node.scheme, "ss")
        self.assertEqual(node.host, "example.org")
        self.assertEqual(node.port, 8388)
        self.assertEqual(node.name, "ss-node")

    def test_reject_unknown_scheme(self) -> None:
        with self.assertRaises(ValueError):
            parse_node_line("unknown://example.com:1")


if __name__ == "__main__":
    unittest.main()
