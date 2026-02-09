"""FastMCP server entry point for Temple memory broker."""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from mcp.server.auth.settings import ClientRegistrationOptions

from temple.config import settings
from temple.memory.broker import MemoryBroker
from temple.tools.memory_tools import register_memory_tools
from temple.tools.entity_tools import register_entity_tools
from temple.tools.relation_tools import register_relation_tools
from temple.tools.observation_tools import register_observation_tools
from temple.tools.context_tools import register_context_tools
from temple.tools.admin_tools import register_admin_tools


class TempleAuthProvider(InMemoryOAuthProvider):
    """OAuth 2.1 provider that also accepts a static API key.

    - Static Bearer token  → Copilot Studio, Claude Code, curl
    - OAuth 2.1 flow       → Claude.ai remote MCP (dynamic registration)
    """

    def __init__(self, api_key: str, **kwargs):
        super().__init__(**kwargs)
        self._api_key = api_key

    async def verify_token(self, token: str) -> AccessToken | None:
        # Check static API key first
        if self._api_key and token == self._api_key:
            return AccessToken(
                token=token,
                client_id="static",
                scopes=["temple"],
            )
        # Fall back to OAuth-issued tokens
        return await super().verify_token(token)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Build auth provider if API key is configured
_auth = None
if settings.api_key:
    logger.info("API key + OAuth 2.1 (open registration) authentication enabled")
    _auth = TempleAuthProvider(
        api_key=settings.api_key,
        base_url=settings.base_url or None,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["temple"],
            default_scopes=["temple"],
        ),
    )

# Create MCP server
mcp = FastMCP(
    "Temple Memory Broker",
    instructions="Context-aware persistent memory for AI agents. "
    "Store, retrieve, and connect knowledge across sessions and projects.",
    auth=_auth,
)

# Initialize broker
broker = MemoryBroker(settings)

# Register all tools
register_memory_tools(mcp, broker)
register_entity_tools(mcp, broker)
register_relation_tools(mcp, broker)
register_observation_tools(mcp, broker)
register_context_tools(mcp, broker)
register_admin_tools(mcp, broker)


# Health endpoint (non-MCP, for Docker health checks)
@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse

    status = broker.health_check()
    return JSONResponse(status)


def main():
    """Run the MCP server."""
    logger.info(f"Starting Temple Memory Broker on {settings.host}:{settings.port}")
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
