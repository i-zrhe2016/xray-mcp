from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .models import NodeCheckResult, WatchRecord, WatchResult, utc_now_iso
from .subscription import fetch_subscription_text, parse_subscription_text


class WatchManager:
    def __init__(self, state_file: str | Path) -> None:
        self._state_file = Path(state_file).expanduser().resolve()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._watches: dict[str, WatchRecord] = {}
        self._load_state()
        self.start()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._scheduler_loop,
                name="xray-mcp-monitor",
                daemon=True,
            )
            self._thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def register_watch(
        self,
        subscription_url: str,
        interval_seconds: int = 300,
        timeout_seconds: float = 5.0,
        node_name_keyword: str | None = None,
    ) -> dict[str, Any]:
        if interval_seconds < 10:
            raise ValueError("interval_seconds must be at least 10")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")

        now = time.time()
        timestamp = utc_now_iso()
        watch = WatchRecord(
            watch_id=str(uuid.uuid4()),
            subscription_url=subscription_url,
            interval_seconds=int(interval_seconds),
            timeout_seconds=float(timeout_seconds),
            node_name_keyword=node_name_keyword.strip() if node_name_keyword else None,
            enabled=True,
            created_at=timestamp,
            updated_at=timestamp,
            next_run_epoch=now + interval_seconds,
        )
        with self._lock:
            self._watches[watch.watch_id] = watch
            self._persist_state_locked()

        result = self.run_check(watch.watch_id)
        return result

    def check_subscription_once(
        self,
        subscription_url: str,
        timeout_seconds: float = 5.0,
        node_name_keyword: str | None = None,
    ) -> dict[str, Any]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")

        result = self._perform_check(
            subscription_url=subscription_url,
            timeout_seconds=timeout_seconds,
            node_name_keyword=node_name_keyword.strip() if node_name_keyword else None,
        )
        return {
            "subscription_url": subscription_url,
            "timeout_seconds": timeout_seconds,
            "node_name_keyword": node_name_keyword.strip() if node_name_keyword else None,
            "result": result.to_dict(),
        }

    def list_watches(self) -> dict[str, Any]:
        with self._lock:
            items = [watch.to_response_dict() for watch in self._watches.values()]
        return {"count": len(items), "watches": items}

    def get_watch(self, watch_id: str) -> dict[str, Any]:
        with self._lock:
            watch = self._watches.get(watch_id)
            if not watch:
                raise KeyError(f"watch '{watch_id}' not found")
            return watch.to_response_dict()

    def set_watch_enabled(self, watch_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            watch = self._watches.get(watch_id)
            if not watch:
                raise KeyError(f"watch '{watch_id}' not found")
            watch.enabled = enabled
            watch.updated_at = utc_now_iso()
            watch.next_run_epoch = time.time() + watch.interval_seconds if enabled else None
            self._persist_state_locked()
            return watch.to_response_dict()

    def remove_watch(self, watch_id: str) -> dict[str, Any]:
        with self._lock:
            watch = self._watches.pop(watch_id, None)
            if not watch:
                raise KeyError(f"watch '{watch_id}' not found")
            self._persist_state_locked()
        return {"removed": True, "watch_id": watch_id}

    def run_check(self, watch_id: str) -> dict[str, Any]:
        with self._lock:
            watch = self._watches.get(watch_id)
            if not watch:
                raise KeyError(f"watch '{watch_id}' not found")
            snapshot = WatchRecord.from_state_dict(watch.to_state_dict())

        result = self._perform_check(
            subscription_url=snapshot.subscription_url,
            timeout_seconds=snapshot.timeout_seconds,
            node_name_keyword=snapshot.node_name_keyword,
        )

        with self._lock:
            current = self._watches.get(watch_id)
            if not current:
                raise KeyError(f"watch '{watch_id}' not found")
            current.last_result = result
            current.last_error = "; ".join(result.errors) if result.errors else None
            current.updated_at = utc_now_iso()
            if current.enabled:
                current.next_run_epoch = time.time() + current.interval_seconds
            self._persist_state_locked()
            return {"watch": current.to_response_dict(), "result": result.to_dict()}

    def _scheduler_loop(self) -> None:
        while not self._stop_event.wait(1.0):
            due_ids: list[str] = []
            now = time.time()
            with self._lock:
                for watch in self._watches.values():
                    if not watch.enabled or watch.next_run_epoch is None:
                        continue
                    if watch.next_run_epoch <= now:
                        watch.next_run_epoch = now + watch.interval_seconds
                        due_ids.append(watch.watch_id)
                if due_ids:
                    self._persist_state_locked()

            for watch_id in due_ids:
                try:
                    self.run_check(watch_id)
                except Exception as exc:
                    self._record_watch_error(watch_id, str(exc))

    def _record_watch_error(self, watch_id: str, error: str) -> None:
        with self._lock:
            watch = self._watches.get(watch_id)
            if not watch:
                return
            watch.last_error = error
            watch.updated_at = utc_now_iso()
            self._persist_state_locked()

    def _perform_check(
        self,
        subscription_url: str,
        timeout_seconds: float,
        node_name_keyword: str | None,
    ) -> WatchResult:
        checked_at = utc_now_iso()
        errors: list[str] = []

        try:
            subscription_text = fetch_subscription_text(subscription_url, timeout_seconds=timeout_seconds)
        except Exception as exc:
            return WatchResult(
                checked_at=checked_at,
                status="error",
                total_nodes=0,
                matched_nodes=0,
                reachable_nodes=0,
                unreachable_nodes=0,
                unsupported_nodes=0,
                nodes=[],
                errors=[f"failed to fetch subscription: {exc}"],
            )

        nodes, parse_errors = parse_subscription_text(subscription_text)
        errors.extend(parse_errors)

        total_nodes = len(nodes)
        matched_nodes = self._filter_nodes(nodes, node_name_keyword)
        node_results = [check_node_connectivity(node, timeout_seconds) for node in matched_nodes]

        reachable_nodes = sum(1 for item in node_results if item.status == "reachable")
        unreachable_nodes = sum(1 for item in node_results if item.status == "unreachable")
        unsupported_nodes = sum(1 for item in node_results if item.status == "unsupported")

        status = summarize_watch_status(
            total_nodes=len(nodes),
            matched_nodes=len(matched_nodes),
            reachable_nodes=reachable_nodes,
            unreachable_nodes=unreachable_nodes,
            unsupported_nodes=unsupported_nodes,
            has_errors=bool(errors),
        )

        return WatchResult(
            checked_at=checked_at,
            status=status,
            total_nodes=total_nodes,
            matched_nodes=len(matched_nodes),
            reachable_nodes=reachable_nodes,
            unreachable_nodes=unreachable_nodes,
            unsupported_nodes=unsupported_nodes,
            nodes=node_results,
            errors=errors,
        )

    def _filter_nodes(self, nodes: list[Any], node_name_keyword: str | None) -> list[Any]:
        if not node_name_keyword:
            return nodes
        keyword = node_name_keyword.lower()
        return [
            node
            for node in nodes
            if keyword in node.name.lower() or keyword in node.host.lower()
        ]

    def _load_state(self) -> None:
        if not self._state_file.exists():
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            return

        for item in payload.get("watches", []):
            try:
                watch = WatchRecord.from_state_dict(item)
            except Exception:
                continue
            self._watches[watch.watch_id] = watch

    def _persist_state_locked(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"watches": [watch.to_state_dict() for watch in self._watches.values()]}
        tmp_file = self._state_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_file.replace(self._state_file)


def check_node_connectivity(node: Any, timeout_seconds: float) -> NodeCheckResult:
    checked_at = utc_now_iso()
    if getattr(node, "network", "tcp") != "tcp":
        return NodeCheckResult(
            name=node.name,
            scheme=node.scheme,
            host=node.host,
            port=node.port,
            network=node.network,
            status="unsupported",
            checked_at=checked_at,
            error="only TCP probes are supported",
        )

    started = time.perf_counter()
    try:
        with socket.create_connection((node.host, node.port), timeout=timeout_seconds):
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return NodeCheckResult(
                name=node.name,
                scheme=node.scheme,
                host=node.host,
                port=node.port,
                network=node.network,
                status="reachable",
                checked_at=checked_at,
                latency_ms=latency_ms,
            )
    except OSError as exc:
        return NodeCheckResult(
            name=node.name,
            scheme=node.scheme,
            host=node.host,
            port=node.port,
            network=node.network,
            status="unreachable",
            checked_at=checked_at,
            error=str(exc),
        )


def summarize_watch_status(
    total_nodes: int,
    matched_nodes: int,
    reachable_nodes: int,
    unreachable_nodes: int,
    unsupported_nodes: int,
    has_errors: bool,
) -> str:
    if total_nodes == 0:
        return "empty"
    if matched_nodes == 0:
        return "no_match"
    if reachable_nodes == matched_nodes and matched_nodes > 0:
        return "healthy" if not has_errors else "healthy_with_warnings"
    if reachable_nodes > 0 and unreachable_nodes > 0:
        return "degraded"
    if reachable_nodes > 0 and unsupported_nodes > 0:
        return "partial"
    if unsupported_nodes == matched_nodes:
        return "unsupported"
    return "down"
