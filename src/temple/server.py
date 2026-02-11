"""FastMCP server entry point for Temple memory broker."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from temple.auth import build_auth_provider
from temple.config import Settings, settings
from temple.memory.broker import MemoryBroker
from temple.tools.admin_tools import register_admin_tools
from temple.tools.context_tools import register_context_tools
from temple.tools.entity_tools import register_entity_tools
from temple.tools.memory_tools import register_memory_tools
from temple.tools.observation_tools import register_observation_tools
from temple.tools.relation_tools import register_relation_tools

logger = logging.getLogger(__name__)
_LOGGING_CONFIGURED = False

INSTRUCTIONS = """\
Temple is a personal knowledge graph — a persistent, growing foundation of knowledge that makes AI agents more useful over time. It stores memories, entities, and their relationships so that context is never lost between conversations.

## Core Concepts

**Memories** are freeform text with optional tags and metadata. Use them for preferences, decisions, experiences, notes, and anything that doesn't fit neatly as a named entity. They are embedded for semantic search.

**Entities** are named nodes in the knowledge graph with a type and structured observations (facts). Use them for people, places, projects, organizations, technologies, pets — anything with an identity that persists and accumulates facts over time.

**Relations** connect entities directionally with a descriptive verb (e.g., "works_at", "lives_in", "manages", "built_with"). They form the graph structure that lets you traverse connections.

**Observations** are individual facts attached to entities. Add new facts as you learn them rather than replacing all observations.

## Context Hierarchy

Temple has three scopes with strict precedence: **session > project > global**.
- **Global**: Knowledge that applies everywhere (personal facts, preferences, long-term knowledge)
- **Project**: Knowledge scoped to a specific project or domain (set with set_context)
- **Session**: Ephemeral knowledge for one conversation (set with set_context)

When retrieving, Temple searches all active scopes and ranks results by precedence, so session-scoped memories surface first. When storing, memories go to the most specific active scope by default.

## Best Practices

1. **Recall before storing.** Always check what Temple already knows before creating new memories or entities. Use recall_memory or get_entity to avoid duplicates.
2. **Use entities for things with identity.** If something has a name and you'll refer to it again, make it an entity. Attach facts as observations. Connect it to other entities with relations.
3. **Use memories for everything else.** Preferences, decisions, context, freeform notes — store as memories with descriptive tags.
4. **Tag consistently.** Tags like "preference", "decision", "project-note", "learning" make memories findable beyond semantic search.
5. **Build the graph organically.** When you learn something new about an existing entity, add observations. When you discover a connection, create a relation. The graph grows naturally through use.
6. **Scope appropriately.** Project-specific knowledge should be stored in a project context. Universal knowledge goes to global. Use get_context to check where you are before storing.
"""


def configure_logging(config: Settings) -> None:
    """Configure process logging once."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _LOGGING_CONFIGURED = True


def create_mcp_server(
    broker: MemoryBroker | None = None,
    config: Settings | None = None,
) -> FastMCP:
    """Create and configure the MCP server with all Temple tools."""
    cfg = config or settings
    configure_logging(cfg)
    auth = build_auth_provider(cfg, logger=logger)
    active_broker = broker or MemoryBroker(cfg)

    mcp = FastMCP(
        "Temple Memory Broker",
        instructions=INSTRUCTIONS,
        auth=auth,
    )

    register_memory_tools(mcp, active_broker)
    register_entity_tools(mcp, active_broker)
    register_relation_tools(mcp, active_broker)
    register_observation_tools(mcp, active_broker)
    register_context_tools(mcp, active_broker)
    register_admin_tools(mcp, active_broker)

    # Health endpoint (non-MCP, for Docker health checks)
    @mcp.custom_route("/health", methods=["GET"])
    async def health(request):
        from starlette.responses import JSONResponse

        status = active_broker.health_check()
        return JSONResponse(status)

    return mcp


def main() -> None:
    """Run the MCP server."""
    cfg = settings
    configure_logging(cfg)
    transport = cfg.mcp_transport
    mcp = create_mcp_server(config=cfg)

    if transport == "stdio":
        logger.info("Starting Temple Memory Broker with stdio transport")
        mcp.run(transport="stdio")
        return

    logger.info(
        "Starting Temple Memory Broker on %s:%s with %s transport",
        cfg.host,
        cfg.port,
        transport,
    )
    mcp.run(
        transport=transport,
        host=cfg.host,
        port=cfg.port,
    )


if __name__ == "__main__":
    main()
