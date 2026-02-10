"""Observation MCP tools: add and remove observations on entities."""

from __future__ import annotations

from typing import Any

from temple.memory.broker import MemoryBroker


def register_observation_tools(mcp, broker: MemoryBroker) -> None:
    """Register observation tools with the MCP server."""

    @mcp.tool()
    def add_observations(
        entity_name: str,
        observations: list[str],
    ) -> dict[str, Any]:
        """Add observations (facts) to an existing entity.

        Observations are individual facts that describe an entity. Use this to
        incrementally build up knowledge — each time you learn something new
        about an entity, add it as an observation rather than replacing everything.

        Prefer observations over memories when the fact is clearly about a specific
        entity (e.g., "Speaks French" on a person entity, rather than a standalone
        memory "Lance speaks French").

        Args:
            entity_name: Name of the entity to add observations to (must already exist)
            observations: List of factual statements to add (e.g.,
                ["Joined the company in 2020", "Manages the data team"])

        Returns:
            Result indicating success/failure
        """
        result = broker.add_observations(entity_name, observations)
        return {
            "entity_name": entity_name,
            "observations_added": len(observations) if result else 0,
            "success": result,
        }

    @mcp.tool()
    def remove_observations(
        entity_name: str,
        observations: list[str],
    ) -> dict[str, Any]:
        """Remove specific observations from an entity.

        Use this to correct outdated or incorrect facts. The observation text
        must match exactly — use get_entity first to see current observations.

        Args:
            entity_name: Name of the entity
            observations: List of observation strings to remove (exact text match)

        Returns:
            Result indicating success/failure
        """
        result = broker.remove_observations(entity_name, observations)
        return {
            "entity_name": entity_name,
            "observations_removed": len(observations) if result else 0,
            "success": result,
        }
