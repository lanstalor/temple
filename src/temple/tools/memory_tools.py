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

        Use this for preferences, decisions, experiences, notes, and freeform knowledge.
        Content is automatically embedded for semantic search. Duplicate content
        (by hash) is detected and skipped.

        Before storing, use recall_memory to check if this knowledge already exists.

        Args:
            content: The text content to remember. Be specific and self-contained —
                this text is what semantic search matches against.
            tags: Categorization tags for filtering (e.g., ["preference", "food"],
                ["decision", "architecture"], ["learning", "python"]).
                Consistent tagging makes search_memories more effective.
            metadata: Arbitrary key-value pairs (e.g., {"source": "conversation",
                "confidence": "high"}). Stored but not embedded.
            scope: Target scope (global, project:<name>, session:<id>).
                Defaults to the most specific active scope.

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

        This is the primary semantic search tool. Results are ranked by a combination
        of scope precedence (session > project > global) and cosine similarity,
        so more specific scopes surface first.

        Use this when you need to find knowledge related to a topic, question, or concept.

        Args:
            query: Natural language query — describe what you're looking for
                conversationally (e.g., "dietary preferences" not just "food")
            n_results: Maximum number of results to return (default 5)
            scope: Limit search to a specific scope (e.g., "project:temple").
                Defaults to all active scopes.

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
        """Quick semantic search across all active scopes.

        Convenience wrapper around retrieve_memory — use this for fast lookups when
        you don't need to filter by scope. Ideal as a first check before storing
        new knowledge ("do I already know this?").

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

        Use this when you want to filter by tags or scope rather than (or in
        addition to) semantic similarity. For example, find all memories tagged
        "preference" or all memories in a specific project scope.

        Args:
            query: Optional text query for semantic similarity matching
            tags: Optional tags to filter by — memories must have ALL specified tags
            scope: Optional scope to limit search (e.g., "global", "project:temple")
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

        Use this to clean up outdated, incorrect, or duplicate memories.
        The memory_id is the content hash returned when the memory was stored.

        Args:
            memory_id: The memory's content hash ID
            scope: Scope to delete from. Defaults to all active scopes.

        Returns:
            Deletion result
        """
        deleted = broker.delete_memory(memory_id, scope=scope)
        return {"memory_id": memory_id, "deleted": deleted}
