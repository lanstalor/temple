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

        Args:
            entity_name: Name of the entity to add observations to
            observations: List of observation strings to add

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

        Args:
            entity_name: Name of the entity
            observations: List of observation strings to remove (exact match)

        Returns:
            Result indicating success/failure
        """
        result = broker.remove_observations(entity_name, observations)
        return {
            "entity_name": entity_name,
            "observations_removed": len(observations) if result else 0,
            "success": result,
        }
