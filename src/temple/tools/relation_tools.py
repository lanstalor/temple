"""Relation MCP tools: create, delete, get, find_path."""

from __future__ import annotations

from typing import Any

from temple.memory.broker import MemoryBroker


def register_relation_tools(mcp, broker: MemoryBroker) -> None:
    """Register relation tools with the MCP server."""

    @mcp.tool()
    def create_relations(
        relations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Create relations between entities in the knowledge graph.

        Args:
            relations: List of relation dicts with 'source', 'target', 'relation_type'
                Example: [{"source": "Python", "target": "FastAPI", "relation_type": "powers"}]

        Returns:
            List of creation results
        """
        return broker.create_relations(relations)

    @mcp.tool()
    def delete_relations(
        relations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Delete specific relations from the knowledge graph.

        Args:
            relations: List of relation dicts with 'source', 'target', 'relation_type'

        Returns:
            List of deletion results
        """
        return broker.delete_relations(relations)

    @mcp.tool()
    def get_relations(
        entity_name: str,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Get all relations for an entity.

        Args:
            entity_name: Name of the entity
            direction: 'in', 'out', or 'both' (default)

        Returns:
            List of relations
        """
        return broker.get_relations(entity_name, direction)

    @mcp.tool()
    def find_path(
        source: str,
        target: str,
        max_hops: int = 5,
    ) -> dict[str, Any]:
        """Find shortest path between two entities in the knowledge graph.

        Args:
            source: Source entity name
            target: Target entity name
            max_hops: Maximum path length (default 5)

        Returns:
            Path information or null if no path found
        """
        result = broker.find_path(source, target, max_hops)
        if result is None:
            return {"found": False, "message": f"No path found between '{source}' and '{target}'"}
        return {"found": True, "path": result}
