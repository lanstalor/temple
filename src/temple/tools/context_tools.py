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

        Memories stored after this will use the active context scope.
        Retrieval searches all active tiers with precedence: session > project > global.

        Args:
            project: Project name to activate (empty string to clear)
            session: Session ID to activate (empty string to clear)

        Returns:
            Updated context state
        """
        return broker.set_context(project=project, session=session)

    @mcp.tool()
    def get_context() -> dict[str, Any]:
        """Get the current active context (project, session, active scopes).

        Returns:
            Current context configuration
        """
        return broker.get_context()

    @mcp.tool()
    def list_projects() -> list[str]:
        """List all known project contexts.

        Returns:
            List of project names that have stored memories
        """
        return broker.list_projects()

    @mcp.tool()
    def list_sessions() -> list[str]:
        """List all known session contexts.

        Returns:
            List of session IDs that have stored memories
        """
        return broker.list_sessions()
