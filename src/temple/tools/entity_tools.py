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

        Use entities for things with a persistent identity — people, places, projects,
        organizations, technologies, pets, etc. If something has a name and you'll
        refer to it again, it should be an entity.

        Always use get_entity first to check if the entity already exists. If it does,
        use add_observations to attach new facts instead of creating a duplicate.

        Args:
            entities: List of entity dicts with 'name', 'entity_type', and optional 'observations'.
                - name: Unique identifier (e.g., "Python", "Nova Scotia")
                - entity_type: Category string (e.g., "person", "place", "project",
                  "organization", "technology", "pet", "concept")
                - observations: List of factual statements about the entity
                  (e.g., ["Founded in 1991", "Created by Guido van Rossum"])

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

        Use this to change an entity's type or replace all observations.
        To add new facts without replacing existing ones, use add_observations instead.

        Args:
            name: Entity name to update
            entity_type: New entity type (optional)
            observations: Replace ALL observations with this list (optional).
                Caution: this overwrites existing observations entirely.

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
        """Delete entities and all their relations from the knowledge graph.

        This removes the entity and any relations connecting to or from it.
        Use with care — this is not reversible.

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

        Use this to check if an entity exists before creating it, and to see its
        current observations and type. This is the best way to look up a specific
        known entity.

        Args:
            name: Entity name (exact match)

        Returns:
            Entity details including type and observations, or error if not found
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

        Use this to discover what's in the knowledge graph — for example,
        "what people do I know about?" (entity_type="person") or
        "what entities exist in this project?" (scope="project:temple").

        Args:
            entity_type: Filter by entity type (e.g., "person", "project",
                "organization", "technology", "place")
            scope: Filter by scope
            limit: Max results (default 50)

        Returns:
            List of matching entities with their types and observations
        """
        return broker.search_entities(entity_type=entity_type, scope=scope, limit=limit)
