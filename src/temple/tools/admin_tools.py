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

        Returns:
            Comprehensive system statistics
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

        Returns:
            Dict with entities and relations lists
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

        Args:
            scope: Scope to compact (default 'global')
            keep: Number of entries to keep (default 1000)

        Returns:
            Compaction result
        """
        removed = broker._audit.compact(scope, keep)
        return {"scope": scope, "entries_removed": removed, "entries_kept": keep}
