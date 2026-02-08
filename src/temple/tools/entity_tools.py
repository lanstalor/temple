"""Entity MCP tools: create, update, delete, get, search."""

from __future__ import annotations

from typing import Any

from temple.memory.broker import MemoryBroker


def register_entity_tools(mcp, broker: MemoryBroker) -> None:
    """Register entity tools with the MCP server."""

    @mcp.tool()
    def create_entities(
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Create entities in the knowledge graph.

        Args:
            entities: List of entity dicts with 'name', 'entity_type', and optional 'observations'
                Example: [{"name": "Python", "entity_type": "language", "observations": ["High-level language"]}]

        Returns:
            List of creation results
        """
        return broker.create_entities(entities)

    @mcp.tool()
    def update_entity(
        name: str,
        entity_type: str | None = None,
        observations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing entity's properties.

        Args:
            name: Entity name to update
            entity_type: New entity type (optional)
            observations: Replace all observations (optional)

        Returns:
            Update result
        """
        updates = {}
        if entity_type is not None:
            updates["entity_type"] = entity_type
        if observations is not None:
            updates["observations"] = observations
        result = broker.update_entity(name, **updates)
        return {"name": name, "updated": result}

    @mcp.tool()
    def delete_entities(
        names: list[str],
    ) -> list[dict[str, Any]]:
        """Delete entities and their relations from the knowledge graph.

        Args:
            names: List of entity names to delete

        Returns:
            List of deletion results
        """
        return broker.delete_entities(names)

    @mcp.tool()
    def get_entity(
        name: str,
    ) -> dict[str, Any]:
        """Get a single entity by name with all its details.

        Args:
            name: Entity name

        Returns:
            Entity details or error if not found
        """
        entity = broker.get_entity(name)
        if entity is None:
            return {"error": f"Entity '{name}' not found"}
        return entity

    @mcp.tool()
    def search_entities(
        entity_type: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search entities by type and/or scope.

        Args:
            entity_type: Filter by entity type (e.g., 'person', 'project')
            scope: Filter by scope
            limit: Max results (default 50)

        Returns:
            List of matching entities
        """
        return broker.search_entities(entity_type=entity_type, scope=scope, limit=limit)
