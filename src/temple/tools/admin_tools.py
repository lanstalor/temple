"""Admin MCP tools: stats, reindex, export, compact, migrations."""

from __future__ import annotations

from typing import Any

from temple.memory.broker import MemoryBroker


def register_admin_tools(mcp, broker: MemoryBroker) -> None:
    """Register admin tools with the MCP server."""

    @mcp.tool()
    def get_stats() -> dict[str, Any]:
        """Get system statistics: memory counts, entity/relation counts, active context.

        Useful for understanding the current size and state of the knowledge base.

        Returns:
            Comprehensive system statistics including counts per scope
        """
        return broker.get_stats()

    @mcp.tool()
    def reindex() -> dict[str, Any]:
        """Trigger a reindex of the vector store.

        This is a no-op for ChromaDB (it auto-indexes) but useful for future backends.

        Returns:
            Reindex result
        """
        return {"status": "ok", "message": "ChromaDB auto-indexes; no manual reindex needed"}

    @mcp.tool()
    def export_knowledge_graph() -> dict[str, Any]:
        """Export the entire knowledge graph as entities and relations.

        Returns all entities and their outgoing relations. Useful for backup,
        visualization, or understanding the full graph structure.

        Returns:
            Dict with entities list, relations list, and counts
        """
        return broker.export_knowledge_graph()

    @mcp.tool()
    def compact_audit_log(
        scope: str = "global",
        keep: int = 1000,
    ) -> dict[str, Any]:
        """Compact the audit log for a scope, keeping the last N entries.

        The audit log tracks all operations. Use this to trim old entries
        and keep the log manageable.

        Args:
            scope: Scope to compact (default 'global')
            keep: Number of recent entries to keep (default 1000)

        Returns:
            Compaction result with count of removed entries
        """
        removed = broker.compact_audit_log(scope=scope, keep=keep)
        return {"scope": scope, "entries_removed": removed, "entries_kept": keep}

    @mcp.tool()
    def get_graph_schema_status() -> dict[str, Any]:
        """Get graph schema version and migration readiness details."""
        return broker.get_graph_schema_status()

    @mcp.tool()
    def migrate_graph_schema(backup_path: str | None = None) -> dict[str, Any]:
        """Migrate legacy Kuzu graph schema to the current v2 schema.

        A JSON backup snapshot is always written before migration.

        Args:
            backup_path: Optional path for the migration snapshot JSON.
                If omitted, Temple writes a timestamped file next to the Kuzu directory.

        Returns:
            Migration result, including backup path and migrated counts.
        """
        return broker.migrate_graph_schema(backup_path=backup_path)
