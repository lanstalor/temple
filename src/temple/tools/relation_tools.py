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
        """Create directed relations between entities in the knowledge graph.

        Relations are the edges of the graph — they connect entities and encode how
        things relate to each other. The relation reads as "source relation_type target"
        (e.g., "Lance works_at Emera" or "Temple built_with Python").

        Both source and target entities must exist before creating a relation.

        Args:
            relations: List of relation dicts with 'source', 'target', 'relation_type'.
                - relation_type: A descriptive verb or phrase using snake_case
                  (e.g., "works_at", "lives_in", "manages", "built_with",
                  "member_of", "parent_of", "depends_on", "interested_in")

        Returns:
            List of creation results
        """
        return broker.create_relations(relations)

    @mcp.tool()
    def delete_relations(
        relations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Delete specific relations from the knowledge graph.

        Removes the specified edges without affecting the entities themselves.

        Args:
            relations: List of relation dicts with 'source', 'target', 'relation_type'
                (all three fields must match exactly)

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

        Use this to explore an entity's neighborhood in the graph — what it connects
        to and what connects to it. Useful for understanding context around an entity.

        Args:
            entity_name: Name of the entity
            direction: 'in' (relations pointing to this entity), 'out' (relations
                from this entity), or 'both' (default)

        Returns:
            List of relations with source, target, and relation_type
        """
        return broker.get_relations(entity_name, direction)

    @mcp.tool()
    def find_path(
        source: str,
        target: str,
        max_hops: int = 5,
    ) -> dict[str, Any]:
        """Find shortest path between two entities in the knowledge graph.

        Use this to discover indirect connections — how two seemingly unrelated
        entities are linked through the graph. For example, finding how a person
        connects to a technology through their projects and organizations.

        Args:
            source: Source entity name
            target: Target entity name
            max_hops: Maximum path length (default 5)

        Returns:
            Path information including intermediate entities, or not-found if no path exists
        """
        result = broker.find_path(source, target, max_hops)
        if result is None:
            return {"found": False, "message": f"No path found between '{source}' and '{target}'"}
        return {"found": True, "path": result}
