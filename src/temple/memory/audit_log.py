"""JSONL append-only audit trail."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    """Append-only JSONL audit logger scoped to a directory."""

    def __init__(self, audit_dir: Path) -> None:
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _log_file(self, scope: str) -> Path:
        """Get the log file path for a given scope."""
        safe_name = scope.replace(":", "_").replace("/", "_")
        return self._dir / f"{safe_name}.jsonl"

    def log(
        self,
        action: str,
        scope: str = "global",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append a log entry."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "scope": scope,
            **(details or {}),
        }
        with open(self._log_file(scope), "a") as f:
            f.write(json.dumps(entry) + "\n")

    def read(self, scope: str = "global", limit: int = 100) -> list[dict[str, Any]]:
        """Read the last N entries for a scope."""
        path = self._log_file(scope)
        if not path.exists():
            return []
        lines = path.read_text().strip().split("\n")
        entries = [json.loads(line) for line in lines if line]
        return entries[-limit:]

    def compact(self, scope: str = "global", keep: int = 1000) -> int:
        """Keep only the last N entries, return number removed."""
        path = self._log_file(scope)
        if not path.exists():
            return 0
        lines = path.read_text().strip().split("\n")
        if len(lines) <= keep:
            return 0
        removed = len(lines) - keep
        path.write_text("\n".join(lines[-keep:]) + "\n")
        return removed
