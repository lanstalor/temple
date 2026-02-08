"""Tests for audit log."""

from temple.memory.audit_log import AuditLog


def test_log_and_read(tmp_path):
    """Log an entry and read it back."""
    audit = AuditLog(tmp_path)
    audit.log("test_action", "global", {"key": "value"})

    entries = audit.read("global")
    assert len(entries) == 1
    assert entries[0]["action"] == "test_action"
    assert entries[0]["key"] == "value"


def test_log_multiple_scopes(tmp_path):
    """Logs to different scopes stay separate."""
    audit = AuditLog(tmp_path)
    audit.log("action1", "global")
    audit.log("action2", "project:test")

    global_entries = audit.read("global")
    project_entries = audit.read("project:test")

    assert len(global_entries) == 1
    assert len(project_entries) == 1


def test_compact(tmp_path):
    """Compact keeps only the last N entries."""
    audit = AuditLog(tmp_path)
    for i in range(20):
        audit.log(f"action_{i}", "global")

    removed = audit.compact("global", keep=5)
    assert removed == 15

    entries = audit.read("global")
    assert len(entries) == 5
    assert entries[0]["action"] == "action_15"


def test_read_empty(tmp_path):
    """Reading non-existent scope returns empty list."""
    audit = AuditLog(tmp_path)
    entries = audit.read("nonexistent")
    assert entries == []
