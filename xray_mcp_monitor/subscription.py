from __future__ import annotations

import base64
import json
import re
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from .models import XrayNode

SUPPORTED_TCP_SCHEMES = {"vmess", "vless", "trojan", "ss", "socks", "http", "https"}
SUPPORTED_UDP_SCHEMES = {"hy2", "hysteria", "hysteria2", "tuic"}
ALL_SUPPORTED_SCHEMES = SUPPORTED_TCP_SCHEMES | SUPPORTED_UDP_SCHEMES
SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")
USER_AGENT = "xray-mcp-monitor/0.1.0"


def validate_subscription_url(subscription_url: str) -> None:
    parsed = urlsplit(subscription_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("subscription_url must be a valid http or https URL")


def fetch_subscription_text(subscription_url: str, timeout_seconds: float) -> str:
    validate_subscription_url(subscription_url)
    request = Request(
        subscription_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain, application/octet-stream, */*",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset)
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def parse_subscription_text(subscription_text: str) -> tuple[list[XrayNode], list[str]]:
    normalized = subscription_text.strip()
    if not normalized:
        return [], ["subscription payload is empty"]

    payload = _decode_subscription_payload(normalized)
    lines = [line.strip() for line in payload.splitlines() if line.strip()]
    if not lines:
        return [], ["subscription does not contain any node entries"]

    nodes: list[XrayNode] = []
    errors: list[str] = []

    for index, line in enumerate(lines, start=1):
        try:
            nodes.append(parse_node_line(line))
        except ValueError as exc:
            errors.append(f"line {index}: {exc}")

    return nodes, errors


def parse_node_line(line: str) -> XrayNode:
    if not SCHEME_PATTERN.match(line):
        raise ValueError("node entry is not a URI")

    scheme = line.split("://", 1)[0].lower()
    if scheme not in ALL_SUPPORTED_SCHEMES:
        raise ValueError(f"unsupported scheme '{scheme}'")

    if scheme == "vmess":
        return _parse_vmess(line)
    if scheme == "ss":
        return _parse_ss(line)
    return _parse_generic(line, scheme)


def _decode_subscription_payload(payload: str) -> str:
    if _looks_like_uri_list(payload):
        return payload

    compact = "".join(payload.split())
    decoded = _try_base64_decode(compact)
    if decoded and _looks_like_uri_list(decoded):
        return decoded
    return payload


def _looks_like_uri_list(payload: str) -> bool:
    for line in payload.splitlines():
        stripped = line.strip()
        if stripped and SCHEME_PATTERN.match(stripped):
            return True
    return False


def _try_base64_decode(value: str) -> str | None:
    candidate = unquote(value).strip()
    if not candidate:
        return None
    padding = "=" * (-len(candidate) % 4)
    try:
        decoded = base64.b64decode(candidate + padding, altchars=b"-_", validate=True)
    except Exception:
        return None
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return decoded.decode("utf-8", errors="replace")


def _parse_vmess(line: str) -> XrayNode:
    payload = line.split("://", 1)[1]
    decoded = _try_base64_decode(payload)
    if not decoded:
        raise ValueError("invalid vmess payload")

    try:
        data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid vmess JSON: {exc.msg}") from exc

    host = str(data.get("add", "")).strip()
    port_value = data.get("port")
    if not host or port_value in (None, ""):
        raise ValueError("vmess node missing add or port")

    try:
        port = int(port_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("vmess node has invalid port") from exc

    name = str(data.get("ps") or f"{host}:{port}")
    return XrayNode(
        scheme="vmess",
        name=name,
        host=host,
        port=port,
        raw=line,
        network="tcp",
    )


def _parse_ss(line: str) -> XrayNode:
    payload = line.split("://", 1)[1]
    fragment = ""
    if "#" in payload:
        payload, fragment = payload.split("#", 1)

    if "@" not in payload:
        decoded = _try_base64_decode(payload)
        if not decoded:
            raise ValueError("invalid ss payload")
        ss_uri = f"ss://{decoded}"
    else:
        userinfo, host_part = payload.rsplit("@", 1)
        decoded_userinfo = _try_base64_decode(userinfo)
        if decoded_userinfo:
            ss_uri = f"ss://{decoded_userinfo}@{host_part}"
        else:
            ss_uri = f"ss://{payload}"

    parsed = urlsplit(ss_uri)
    if not parsed.hostname or parsed.port is None:
        raise ValueError("ss node missing host or port")

    name = unquote(fragment) or f"{parsed.hostname}:{parsed.port}"
    return XrayNode(
        scheme="ss",
        name=name,
        host=parsed.hostname,
        port=parsed.port,
        raw=line,
        network="tcp",
    )


def _parse_generic(line: str, scheme: str) -> XrayNode:
    parsed = urlsplit(line)
    if not parsed.hostname or parsed.port is None:
        raise ValueError(f"{scheme} node missing host or port")

    name = unquote(parsed.fragment) or f"{parsed.hostname}:{parsed.port}"
    network = "udp" if scheme in SUPPORTED_UDP_SCHEMES else "tcp"
    return XrayNode(
        scheme=scheme,
        name=name,
        host=parsed.hostname,
        port=parsed.port,
        raw=line,
        network=network,
    )
