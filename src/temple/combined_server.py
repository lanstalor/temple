"""Unified server exposing MCP and REST endpoints on one process/port."""

from __future__ import annotations

import logging

import uvicorn
from starlette.routing import BaseRoute

from temple.config import Settings, settings
from temple.memory.broker import MemoryBroker
from temple.rest_server import create_app as create_rest_app
from temple.server import configure_logging, create_mcp_server

logger = logging.getLogger(__name__)


def _route_signature(route: BaseRoute) -> tuple[str | None, tuple[str, ...]]:
    """Build a simple signature for route de-duplication."""
    path = getattr(route, "path", None)
    methods = tuple(sorted(getattr(route, "methods", set()) or set()))
    return path, methods


def create_app(
    broker: MemoryBroker | None = None,
    config: Settings | None = None,
):
    """Create a single ASGI app serving MCP and REST interfaces together."""
    cfg = config or settings
    shared_broker = broker or MemoryBroker(cfg)

    mcp_server = create_mcp_server(broker=shared_broker, config=cfg)
    mcp_app = mcp_server.http_app(path="/mcp", transport="streamable-http")
    rest_app = create_rest_app(broker=shared_broker, config=cfg)

    existing = {_route_signature(route) for route in mcp_app.routes}
    for route in rest_app.routes:
        signature = _route_signature(route)
        if signature in existing:
            continue
        mcp_app.router.routes.append(route)
        existing.add(signature)

    return mcp_app


def main() -> None:
    """Run the combined MCP + REST server."""
    cfg = settings
    configure_logging(cfg)
    if cfg.mcp_transport == "stdio":
        raise ValueError(
            "Combined runtime requires an HTTP MCP transport. "
            "Set TEMPLE_MCP_TRANSPORT=streamable-http or run TEMPLE_RUNTIME_MODE=mcp for stdio."
        )

    app = create_app(config=cfg)
    logger.info(
        "Starting Temple combined server on %s:%s (MCP=/mcp, REST=/api/v1)",
        cfg.host,
        cfg.port,
    )
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
