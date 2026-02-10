"""Admin MCP tools: stats, reindex, export, compact."""

from __future__ import annotations

import json
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
        entities = broker.search_entities(limit=10000)
        all_relations = []
        for entity in entities:
            rels = broker.get_relations(entity["name"], direction="out")
            all_relations.extend(rels)

        return {
            "entities": entities,
            "relations": all_relations,
            "entity_count": len(entities),
            "relation_count": len(all_relations),
        }

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
        removed = broker._audit.compact(scope, keep)
        return {"scope": scope, "entries_removed": removed, "entries_kept": keep}
