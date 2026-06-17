from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def epoch_to_iso(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class XrayNode:
    scheme: str
    name: str
    host: str
    port: int
    raw: str
    network: str = "tcp"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NodeCheckResult:
    name: str
    scheme: str
    host: str
    port: int
    network: str
    status: str
    checked_at: str
    latency_ms: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WatchResult:
    checked_at: str
    status: str
    total_nodes: int
    matched_nodes: int
    reachable_nodes: int
    unreachable_nodes: int
    unsupported_nodes: int
    nodes: list[NodeCheckResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["nodes"] = [node.to_dict() for node in self.nodes]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WatchResult":
        return cls(
            checked_at=data["checked_at"],
            status=data["status"],
            total_nodes=data["total_nodes"],
            matched_nodes=data["matched_nodes"],
            reachable_nodes=data["reachable_nodes"],
            unreachable_nodes=data["unreachable_nodes"],
            unsupported_nodes=data["unsupported_nodes"],
            nodes=[NodeCheckResult(**node) for node in data.get("nodes", [])],
            errors=list(data.get("errors", [])),
        )


@dataclass
class WatchRecord:
    watch_id: str
    subscription_url: str
    interval_seconds: int
    timeout_seconds: float
    node_name_keyword: str | None
    enabled: bool
    created_at: str
    updated_at: str
    next_run_epoch: float | None
    last_result: WatchResult | None = None
    last_error: str | None = None

    def to_state_dict(self) -> dict[str, Any]:
        return {
            "watch_id": self.watch_id,
            "subscription_url": self.subscription_url,
            "interval_seconds": self.interval_seconds,
            "timeout_seconds": self.timeout_seconds,
            "node_name_keyword": self.node_name_keyword,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_run_epoch": self.next_run_epoch,
            "last_result": self.last_result.to_dict() if self.last_result else None,
            "last_error": self.last_error,
        }

    def to_response_dict(self) -> dict[str, Any]:
        return {
            "watch_id": self.watch_id,
            "subscription_url": self.subscription_url,
            "interval_seconds": self.interval_seconds,
            "timeout_seconds": self.timeout_seconds,
            "node_name_keyword": self.node_name_keyword,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "next_run_at": epoch_to_iso(self.next_run_epoch),
            "last_error": self.last_error,
            "last_result": self.last_result.to_dict() if self.last_result else None,
        }

    @classmethod
    def from_state_dict(cls, data: dict[str, Any]) -> "WatchRecord":
        last_result = data.get("last_result")
        return cls(
            watch_id=data["watch_id"],
            subscription_url=data["subscription_url"],
            interval_seconds=int(data["interval_seconds"]),
            timeout_seconds=float(data["timeout_seconds"]),
            node_name_keyword=data.get("node_name_keyword"),
            enabled=bool(data["enabled"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            next_run_epoch=data.get("next_run_epoch"),
            last_result=WatchResult.from_dict(last_result) if last_result else None,
            last_error=data.get("last_error"),
        )
