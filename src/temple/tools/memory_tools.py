"""Memory MCP tools: store, retrieve, recall, search, delete."""

from __future__ import annotations

from typing import Any, Optional

from temple.memory.broker import MemoryBroker


def register_memory_tools(mcp, broker: MemoryBroker) -> None:
    """Register memory tools with the MCP server."""

    @mcp.tool()
    def store_memory(
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Store a new memory with automatic embedding and deduplication.

        Args:
            content: The text content to remember
            tags: Optional categorization tags
            metadata: Optional key-value metadata
            scope: Target scope (global, project:<name>, session:<id>). Defaults to current active scope.

        Returns:
            The stored memory entry with its ID
        """
        entry = broker.store_memory(content, tags=tags, metadata=metadata, scope=scope)
        return entry.model_dump()

    @mcp.tool()
    def retrieve_memory(
        query: str,
        n_results: int = 5,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve memories by semantic similarity.

        Searches across all active context tiers and ranks by precedence (session > project > global)
        and cosine similarity.

        Args:
            query: Natural language query to search for
            n_results: Maximum number of results to return (default 5)
            scope: Limit search to specific scope. Defaults to all active scopes.

        Returns:
            List of matching memories with similarity scores
        """
        results = broker.retrieve_memory(query, n_results=n_results, scope=scope)
        return [r.model_dump() for r in results]

    @mcp.tool()
    def recall_memory(
        query: str,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Recall memories using natural language - searches across all active scopes.

        Convenience wrapper around retrieve_memory that always searches all active contexts.

        Args:
            query: Natural language description of what you're looking for
            n_results: Maximum number of results (default 5)

        Returns:
            List of matching memories with scores
        """
        results = broker.retrieve_memory(query, n_results=n_results)
        return [r.model_dump() for r in results]

    @mcp.tool()
    def search_memories(
        query: str | None = None,
        tags: list[str] | None = None,
        scope: str | None = None,
        n_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories by text query and/or tags.

        Args:
            query: Optional text query for semantic search
            tags: Optional tags to filter by
            scope: Optional scope to limit search
            n_results: Maximum results (default 10)

        Returns:
            List of matching memories
        """
        results = broker.search_memories(
            query=query, tags=tags, scope=scope, n_results=n_results,
        )
        return [r.model_dump() for r in results]

    @mcp.tool()
    def delete_memory(
        memory_id: str,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Delete a memory by its ID.

        Args:
            memory_id: The memory's content hash ID
            scope: Scope to delete from. Defaults to all active scopes.

        Returns:
            Deletion result
        """
        deleted = broker.delete_memory(memory_id, scope=scope)
        return {"memory_id": memory_id, "deleted": deleted}
