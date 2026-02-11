"""Three-tier context hierarchy logic."""

from __future__ import annotations

import logging

from temple.models.context import ActiveContext, ContextScope, ContextTier

logger = logging.getLogger(__name__)


class ContextManager:
    """Manages the active context and scope resolution."""

    def __init__(self) -> None:
        self._context = ActiveContext()

    @property
    def context(self) -> ActiveContext:
        return self._context

    def set_project(self, project_name: str | None) -> None:
        """Set the active project (or None to clear)."""
        self._context.project = project_name
        logger.info(f"Active project: {project_name}")

    def set_session(self, session_id: str | None) -> None:
        """Set the active session (or None to clear)."""
        self._context.session = session_id
        logger.info(f"Active session: {session_id}")

    def get_active_scopes(self) -> list[ContextScope]:
        """Get all active scopes in precedence order (lowest first)."""
        return self._context.active_scopes

    def get_store_scope(self, scope: str | None = None) -> ContextScope:
        """Determine which scope to store to.

        If explicit scope provided, use that. Otherwise use highest active scope.
        """
        if scope:
            return self.parse_scope(scope)

        scopes = self.get_active_scopes()
        return scopes[-1]  # Highest precedence

    def get_retrieval_scopes(self) -> list[ContextScope]:
        """Get scopes to search during retrieval (all active)."""
        return self.get_active_scopes()

    def _parse_scope(self, scope_str: str) -> ContextScope:
        """Parse a scope string like 'global', 'project:myproj', 'session:abc123'."""
        if not scope_str:
            raise ValueError("Scope cannot be empty")

        if scope_str == "global":
            return ContextScope(tier=ContextTier.GLOBAL)
        if scope_str.startswith("project:"):
            name = scope_str[8:].strip()
            if not name:
                raise ValueError("Project scope must include a non-empty name")
            return ContextScope(tier=ContextTier.PROJECT, name=name)
        if scope_str.startswith("session:"):
            name = scope_str[8:].strip()
            if not name:
                raise ValueError("Session scope must include a non-empty identifier")
            return ContextScope(tier=ContextTier.SESSION, name=name)

        raise ValueError(
            f"Invalid scope '{scope_str}'. Expected one of: global, project:<name>, session:<id>."
        )

    def parse_scope(self, scope_str: str) -> ContextScope:
        """Public parser for scope strings."""
        return self._parse_scope(scope_str)

    def scope_precedence(self, scope: ContextScope) -> int:
        """Return numeric precedence for sorting (higher = more specific)."""
        return {
            ContextTier.GLOBAL: 0,
            ContextTier.PROJECT: 1,
            ContextTier.SESSION: 2,
        }[scope.tier]
