"""
Diagnostic service for capturing API calls, ADB commands, and errors.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils import utc_iso

logger = logging.getLogger(__name__)


@dataclass
class DiagnosticEntry:
    """A single diagnostic entry."""
    id: str
    timestamp: str
    category: str  # 'api', 'adb', 'websocket', 'error', 'action', 'system'
    level: str  # 'info', 'warning', 'error'
    source: str  # Component that generated this entry
    message: str
    details: dict = field(default_factory=dict)
    duration_ms: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "category": self.category,
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "details": self.details,
            "duration_ms": self.duration_ms,
        }


class DiagnosticCollector:
    """
    Centralized diagnostic collector for the entire application.
    Collects API calls, ADB commands, WebSocket messages, errors, etc.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._entries: deque[DiagnosticEntry] = deque(maxlen=1000)
        self._entry_counter = 0
        self._enabled = True
        self._execution_context: dict[str, Any] = {}

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def clear(self):
        """Clear all entries."""
        with self._lock:
            self._entries.clear()

    def set_execution_context(self, execution_id: str, case_id: int, case_name: str):
        """Set current execution context for filtering."""
        self._execution_context = {
            "execution_id": execution_id,
            "case_id": case_id,
            "case_name": case_name,
            "start_time": utc_iso(),
        }

    def clear_execution_context(self):
        """Clear execution context."""
        self._execution_context = {}

    def _generate_id(self) -> str:
        self._entry_counter += 1
        return f"diag_{self._entry_counter:06d}"

    def add_entry(
        self,
        category: str,
        level: str,
        source: str,
        message: str,
        details: dict | None = None,
        duration_ms: int | None = None,
    ) -> DiagnosticEntry:
        """Add a diagnostic entry."""
        if not self._enabled:
            return DiagnosticEntry(
                id="",
                timestamp="",
                category=category,
                level=level,
                source=source,
                message=message,
            )

        entry = DiagnosticEntry(
            id=self._generate_id(),
            timestamp=utc_iso(),
            category=category,
            level=level,
            source=source,
            message=message,
            details=details or {},
            duration_ms=duration_ms,
        )

        with self._lock:
            self._entries.append(entry)

        # Log to console for debugging
        log_msg = f"[{category.upper()}] {source}: {message}"
        if level == "error":
            logger.error(log_msg)
        elif level == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        return entry

    def log_api_call(
        self,
        method: str,
        url: str,
        status_code: int | None = None,
        request_body: Any = None,
        response_body: Any = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ):
        """Log an API call."""
        level = "error" if error or (status_code and status_code >= 400) else "info"
        details = {
            "method": method,
            "url": url,
            "status_code": status_code,
        }
        if request_body:
            # Truncate large request bodies
            body_str = json.dumps(request_body, ensure_ascii=False)[:500]
            details["request_body"] = body_str
        if response_body:
            body_str = json.dumps(response_body, ensure_ascii=False)[:500]
            details["response_body"] = body_str
        if error:
            details["error"] = error

        self.add_entry(
            category="api",
            level=level,
            source="http_client",
            message=f"{method} {url} -> {status_code or 'ERROR'}",
            details=details,
            duration_ms=duration_ms,
        )

    def log_adb_command(
        self,
        command: str,
        device_udid: str | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        return_code: int | None = None,
        duration_ms: int | None = None,
    ):
        """Log an ADB command."""
        level = "error" if stderr and "error" in stderr.lower() else "info"
        details = {
            "command": command,
            "device_udid": device_udid,
            "return_code": return_code,
        }
        if stdout:
            details["stdout"] = stdout[:500]
        if stderr:
            details["stderr"] = stderr[:500]

        self.add_entry(
            category="adb",
            level=level,
            source="adb_service",
            message=f"adb {command}",
            details=details,
            duration_ms=duration_ms,
        )

    def log_websocket(
        self,
        direction: str,  # 'send' or 'receive'
        message_type: str,
        data_size: int | None = None,
        details: dict | None = None,
    ):
        """Log a WebSocket message."""
        self.add_entry(
            category="websocket",
            level="info",
            source="screen_stream",
            message=f"WS {direction}: {message_type}",
            details={
                "direction": direction,
                "message_type": message_type,
                "data_size": data_size,
                **(details or {}),
            },
        )

    def log_action(
        self,
        action_type: str,
        action_params: dict,
        success: bool,
        message: str,
    ):
        """Log a phone agent action."""
        level = "error" if not success else "info"
        self.add_entry(
            category="action",
            level=level,
            source="phone_agent",
            message=f"Action: {action_type} -> {'OK' if success else 'FAIL'}",
            details={
                "action_type": action_type,
                "action_params": action_params,
                "success": success,
                "message": message,
            },
        )

    def log_error(
        self,
        source: str,
        message: str,
        exception: Exception | None = None,
        details: dict | None = None,
    ):
        """Log an error."""
        error_details = details or {}
        if exception:
            error_details["exception_type"] = type(exception).__name__
            error_details["exception_message"] = str(exception)

        self.add_entry(
            category="error",
            level="error",
            source=source,
            message=message,
            details=error_details,
        )

    def log_system(
        self,
        message: str,
        details: dict | None = None,
    ):
        """Log a system event."""
        self.add_entry(
            category="system",
            level="info",
            source="system",
            message=message,
            details=details,
        )

    def get_entries(
        self,
        category: str | None = None,
        level: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get filtered entries."""
        with self._lock:
            entries = list(self._entries)

        # Apply filters
        if category:
            entries = [e for e in entries if e.category == category]
        if level:
            entries = [e for e in entries if e.level == level]
        if source:
            entries = [e for e in entries if e.source == source]

        # Sort by timestamp descending and limit
        entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)[:limit]
        return [e.to_dict() for e in entries]

    def get_summary(self) -> dict:
        """Get diagnostic summary."""
        with self._lock:
            entries = list(self._entries)

        total = len(entries)
        by_category: dict[str, int] = {}
        by_level: dict[str, int] = {}
        errors: list[dict] = []

        for entry in entries:
            by_category[entry.category] = by_category.get(entry.category, 0) + 1
            by_level[entry.level] = by_level.get(entry.level, 0) + 1
            if entry.level == "error":
                errors.append(entry.to_dict())

        return {
            "total_entries": total,
            "by_category": by_category,
            "by_level": by_level,
            "recent_errors": errors[:10],
            "execution_context": self._execution_context,
        }

    def get_errors_by_execution(self, execution_id: str | None = None) -> dict[str, list[dict]]:
        """Get errors grouped by execution context."""
        with self._lock:
            entries = list(self._entries)

        # Group errors by execution_id
        by_execution: dict[str, list[dict]] = {}
        for entry in entries:
            if entry.level != "error":
                continue

            # Get execution_id from details or current context
            exec_id = entry.details.get("execution_id")
            if not exec_id and execution_id:
                exec_id = execution_id

            if exec_id:
                if exec_id not in by_execution:
                    by_execution[exec_id] = []
                by_execution[exec_id].append(entry.to_dict())

        return by_execution

    def get_execution_errors(self, execution_id: str) -> list[dict]:
        """Get all errors for a specific execution."""
        with self._lock:
            entries = list(self._entries)

        errors = []
        for entry in entries:
            if entry.level == "error" and entry.details.get("execution_id") == execution_id:
                errors.append(entry.to_dict())

        return errors

    def export_to_file(self, filepath: Path) -> None:
        """Export all entries to a JSON file."""
        with self._lock:
            entries = [e.to_dict() for e in self._entries]

        data = {
            "export_time": utc_iso(),
            "execution_context": self._execution_context,
            "entries": entries,
        }

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# Global instance
diagnostic = DiagnosticCollector()
