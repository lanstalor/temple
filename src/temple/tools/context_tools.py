"""Context MCP tools: set/get context, list projects/sessions."""

from __future__ import annotations

from typing import Any

from temple.memory.broker import MemoryBroker


def register_context_tools(mcp, broker: MemoryBroker) -> None:
    """Register context tools with the MCP server."""

    @mcp.tool()
    def set_context(
        project: str | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        """Set the active project and/or session context.

        This controls where new memories are stored and how retrieval is scoped.
        After setting context, stored memories go to the most specific active scope,
        and retrieval searches all active tiers with precedence: session > project > global.

        - **Project context**: Use for knowledge tied to a specific project or domain
          (e.g., "temple", "home-automation"). Persists across sessions.
        - **Session context**: Use for ephemeral, conversation-specific knowledge.
          Useful for temporary working state.

        Check get_context first to see what's currently active before changing it.

        Args:
            project: Project name to activate (empty string to clear)
            session: Session ID to activate (empty string to clear)

        Returns:
            Updated context state showing active scopes
        """
        return broker.set_context(project=project, session=session)

    @mcp.tool()
    def get_context() -> dict[str, Any]:
        """Get the current active context (project, session, active scopes).

        Call this to understand where you are before storing or retrieving memories.
        Shows which project and session are active and which scopes will be searched.

        Returns:
            Current context configuration including active project, session, and scopes
        """
        return broker.get_context()

    @mcp.tool()
    def list_projects() -> list[str]:
        """List all known project contexts.

        Use this to discover what projects have been used with Temple.

        Returns:
            List of project names that have stored memories
        """
        return broker.list_projects()

    @mcp.tool()
    def list_sessions() -> list[str]:
        """List all known session contexts.

        Use this to see what sessions have stored memories. Sessions are typically
        ephemeral and may accumulate over time.

        Returns:
            List of session IDs that have stored memories
        """
        return broker.list_sessions()
