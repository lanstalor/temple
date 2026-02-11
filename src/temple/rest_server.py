"""REST/OpenAPI compatibility server for Temple."""

from __future__ import annotations

import logging
from typing import Any

import uvicorn
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from temple.config import Settings, settings
from temple.memory.broker import MemoryBroker

logger = logging.getLogger(__name__)


class MemoryStoreRequest(BaseModel):
    content: str
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    scope: str | None = None


class MemoryRetrieveRequest(BaseModel):
    query: str
    n_results: int = 5
    scope: str | None = None


class MemorySearchRequest(BaseModel):
    query: str | None = None
    tags: list[str] | None = None
    scope: str | None = None
    n_results: int = 10


class EntityCreateRequest(BaseModel):
    entities: list[dict[str, Any]]


class EntityUpdateRequest(BaseModel):
    entity_type: str | None = None
    observations: list[str] | None = None


class NamesRequest(BaseModel):
    names: list[str]


class RelationBatchRequest(BaseModel):
    relations: list[dict[str, Any]]


class RelationPathRequest(BaseModel):
    source: str
    target: str
    max_hops: int = 5


class ObservationsRequest(BaseModel):
    entity_name: str
    observations: list[str]


class ContextSetRequest(BaseModel):
    project: str | None = None
    session: str | None = None


class MigrateGraphSchemaRequest(BaseModel):
    backup_path: str | None = None


def _build_openapi_schema(base_url: str) -> dict[str, Any]:
    """Build a compact OpenAPI schema for REST compatibility endpoints."""
    components = {
        "MemoryStoreRequest": MemoryStoreRequest.model_json_schema(),
        "MemoryRetrieveRequest": MemoryRetrieveRequest.model_json_schema(),
        "MemorySearchRequest": MemorySearchRequest.model_json_schema(),
        "EntityCreateRequest": EntityCreateRequest.model_json_schema(),
        "EntityUpdateRequest": EntityUpdateRequest.model_json_schema(),
        "NamesRequest": NamesRequest.model_json_schema(),
        "RelationBatchRequest": RelationBatchRequest.model_json_schema(),
        "RelationPathRequest": RelationPathRequest.model_json_schema(),
        "ObservationsRequest": ObservationsRequest.model_json_schema(),
        "ContextSetRequest": ContextSetRequest.model_json_schema(),
        "MigrateGraphSchemaRequest": MigrateGraphSchemaRequest.model_json_schema(),
    }

    def req(name: str) -> dict[str, Any]:
        return {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{name}"},
                }
            },
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Temple REST API",
            "version": "0.1.0",
            "description": (
                "REST compatibility surface for non-MCP clients. "
                "Use this API from LangChain, LlamaIndex, Semantic Kernel, and custom integrations."
            ),
        },
        "servers": [{"url": base_url}],
        "paths": {
            "/health": {"get": {"summary": "Health check", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/memory/store": {"post": {"summary": "Store memory", "requestBody": req("MemoryStoreRequest"), "responses": {"200": {"description": "Stored"}}}},
            "/api/v1/memory/retrieve": {"post": {"summary": "Semantic memory retrieval", "requestBody": req("MemoryRetrieveRequest"), "responses": {"200": {"description": "Results"}}}},
            "/api/v1/memory/search": {"post": {"summary": "Search memories", "requestBody": req("MemorySearchRequest"), "responses": {"200": {"description": "Results"}}}},
            "/api/v1/entities/create": {"post": {"summary": "Create entities", "requestBody": req("EntityCreateRequest"), "responses": {"200": {"description": "Results"}}}},
            "/api/v1/entities/delete": {"post": {"summary": "Delete entities", "requestBody": req("NamesRequest"), "responses": {"200": {"description": "Results"}}}},
            "/api/v1/entities/{name}": {"get": {"summary": "Get entity", "responses": {"200": {"description": "Entity"}}}, "patch": {"summary": "Update entity", "requestBody": req("EntityUpdateRequest"), "responses": {"200": {"description": "Result"}}}},
            "/api/v1/relations/create": {"post": {"summary": "Create relations", "requestBody": req("RelationBatchRequest"), "responses": {"200": {"description": "Results"}}}},
            "/api/v1/relations/delete": {"post": {"summary": "Delete relations", "requestBody": req("RelationBatchRequest"), "responses": {"200": {"description": "Results"}}}},
            "/api/v1/relations/path": {"post": {"summary": "Find graph path", "requestBody": req("RelationPathRequest"), "responses": {"200": {"description": "Path result"}}}},
            "/api/v1/observations/add": {"post": {"summary": "Add observations", "requestBody": req("ObservationsRequest"), "responses": {"200": {"description": "Result"}}}},
            "/api/v1/observations/remove": {"post": {"summary": "Remove observations", "requestBody": req("ObservationsRequest"), "responses": {"200": {"description": "Result"}}}},
            "/api/v1/context": {"get": {"summary": "Get context", "responses": {"200": {"description": "Context"}}}, "post": {"summary": "Set context", "requestBody": req("ContextSetRequest"), "responses": {"200": {"description": "Context"}}}},
            "/api/v1/admin/stats": {"get": {"summary": "Get stats", "responses": {"200": {"description": "Stats"}}}},
            "/api/v1/admin/graph-schema": {"get": {"summary": "Get graph schema status", "responses": {"200": {"description": "Status"}}}},
            "/api/v1/admin/graph-schema/migrate": {"post": {"summary": "Migrate graph schema", "requestBody": req("MigrateGraphSchemaRequest"), "responses": {"200": {"description": "Migration result"}}}},
        },
        "components": {"schemas": components},
    }


def create_app(
    broker: MemoryBroker | None = None,
    config: Settings | None = None,
) -> Starlette:
    """Create a Starlette app exposing Temple as REST + OpenAPI."""
    app_settings = config or settings
    app_broker = broker or MemoryBroker(app_settings)

    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    def error(message: str, status: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    def require_auth(request: Request) -> JSONResponse | None:
        if not app_settings.api_key:
            return None
        auth = request.headers.get("authorization", "")
        expected = f"Bearer {app_settings.api_key}"
        if auth == expected:
            return None
        return unauthorized()

    async def parse_json(request: Request, model: type[BaseModel]) -> BaseModel:
        payload = await request.json()
        return model.model_validate(payload)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse(app_broker.health_check())

    async def openapi(request: Request) -> JSONResponse:
        base_url = str(request.base_url).rstrip("/")
        return JSONResponse(_build_openapi_schema(base_url))

    async def docs(_: Request) -> HTMLResponse:
        return HTMLResponse(
            """<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>Temple REST API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      SwaggerUIBundle({ url: '/openapi.json', dom_id: '#swagger-ui' });
    </script>
  </body>
</html>""",
        )

    async def store_memory(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, MemoryStoreRequest)
            entry = app_broker.store_memory(
                body.content,
                tags=body.tags,
                metadata=body.metadata,
                scope=body.scope,
            )
            return JSONResponse(entry.model_dump())
        except ValidationError as e:
            return error(str(e), status=422)
        except ValueError as e:
            return error(str(e), status=400)

    async def retrieve_memory(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, MemoryRetrieveRequest)
            results = app_broker.retrieve_memory(
                body.query,
                n_results=body.n_results,
                scope=body.scope,
            )
            return JSONResponse([r.model_dump() for r in results])
        except ValidationError as e:
            return error(str(e), status=422)
        except ValueError as e:
            return error(str(e), status=400)

    async def search_memories(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, MemorySearchRequest)
            results = app_broker.search_memories(
                query=body.query,
                tags=body.tags,
                scope=body.scope,
                n_results=body.n_results,
            )
            return JSONResponse([r.model_dump() for r in results])
        except ValidationError as e:
            return error(str(e), status=422)
        except ValueError as e:
            return error(str(e), status=400)

    async def delete_memory(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        memory_id = request.path_params["memory_id"]
        scope = request.query_params.get("scope")
        try:
            deleted = app_broker.delete_memory(memory_id, scope=scope)
            return JSONResponse({"memory_id": memory_id, "deleted": deleted})
        except ValueError as e:
            return error(str(e), status=400)

    async def create_entities(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, EntityCreateRequest)
            return JSONResponse(app_broker.create_entities(body.entities))
        except ValidationError as e:
            return error(str(e), status=422)

    async def get_entity(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        name = request.path_params["name"]
        entity = app_broker.get_entity(name)
        if entity is None:
            return error(f"Entity '{name}' not found", status=404)
        return JSONResponse(entity)

    async def update_entity(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        name = request.path_params["name"]
        try:
            body = await parse_json(request, EntityUpdateRequest)
            updated = app_broker.update_entity(
                name,
                entity_type=body.entity_type,
                observations=body.observations,
            )
            return JSONResponse({"name": name, "updated": updated})
        except ValidationError as e:
            return error(str(e), status=422)

    async def delete_entities(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, NamesRequest)
            return JSONResponse(app_broker.delete_entities(body.names))
        except ValidationError as e:
            return error(str(e), status=422)

    async def create_relations(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, RelationBatchRequest)
            return JSONResponse(app_broker.create_relations(body.relations))
        except ValidationError as e:
            return error(str(e), status=422)

    async def delete_relations(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, RelationBatchRequest)
            return JSONResponse(app_broker.delete_relations(body.relations))
        except ValidationError as e:
            return error(str(e), status=422)

    async def get_relations(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        entity_name = request.path_params["name"]
        direction = request.query_params.get("direction", "both")
        return JSONResponse(app_broker.get_relations(entity_name, direction=direction))

    async def find_path(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, RelationPathRequest)
            path = app_broker.find_path(body.source, body.target, max_hops=body.max_hops)
            return JSONResponse({"found": path is not None, "path": path})
        except ValidationError as e:
            return error(str(e), status=422)

    async def add_observations(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, ObservationsRequest)
            success = app_broker.add_observations(body.entity_name, body.observations)
            return JSONResponse({
                "entity_name": body.entity_name,
                "observations_added": len(body.observations) if success else 0,
                "success": success,
            })
        except ValidationError as e:
            return error(str(e), status=422)

    async def remove_observations(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, ObservationsRequest)
            success = app_broker.remove_observations(body.entity_name, body.observations)
            return JSONResponse({
                "entity_name": body.entity_name,
                "observations_removed": len(body.observations) if success else 0,
                "success": success,
            })
        except ValidationError as e:
            return error(str(e), status=422)

    async def get_context(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        return JSONResponse(app_broker.get_context())

    async def set_context(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, ContextSetRequest)
            return JSONResponse(app_broker.set_context(project=body.project, session=body.session))
        except ValidationError as e:
            return error(str(e), status=422)

    async def list_projects(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        return JSONResponse(app_broker.list_projects())

    async def list_sessions(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        return JSONResponse(app_broker.list_sessions())

    async def get_stats(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        return JSONResponse(app_broker.get_stats())

    async def get_graph_schema_status(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        return JSONResponse(app_broker.get_graph_schema_status())

    async def migrate_graph_schema(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, MigrateGraphSchemaRequest)
            return JSONResponse(app_broker.migrate_graph_schema(backup_path=body.backup_path))
        except ValidationError as e:
            return error(str(e), status=422)

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/openapi.json", openapi, methods=["GET"]),
        Route("/docs", docs, methods=["GET"]),
        Route("/api/v1/memory/store", store_memory, methods=["POST"]),
        Route("/api/v1/memory/retrieve", retrieve_memory, methods=["POST"]),
        Route("/api/v1/memory/search", search_memories, methods=["POST"]),
        Route("/api/v1/memory/{memory_id}", delete_memory, methods=["DELETE"]),
        Route("/api/v1/entities/create", create_entities, methods=["POST"]),
        Route("/api/v1/entities/delete", delete_entities, methods=["POST"]),
        Route("/api/v1/entities/{name}", get_entity, methods=["GET"]),
        Route("/api/v1/entities/{name}", update_entity, methods=["PATCH"]),
        Route("/api/v1/relations/create", create_relations, methods=["POST"]),
        Route("/api/v1/relations/delete", delete_relations, methods=["POST"]),
        Route("/api/v1/relations/{name}", get_relations, methods=["GET"]),
        Route("/api/v1/relations/path", find_path, methods=["POST"]),
        Route("/api/v1/observations/add", add_observations, methods=["POST"]),
        Route("/api/v1/observations/remove", remove_observations, methods=["POST"]),
        Route("/api/v1/context", get_context, methods=["GET"]),
        Route("/api/v1/context", set_context, methods=["POST"]),
        Route("/api/v1/context/projects", list_projects, methods=["GET"]),
        Route("/api/v1/context/sessions", list_sessions, methods=["GET"]),
        Route("/api/v1/admin/stats", get_stats, methods=["GET"]),
        Route("/api/v1/admin/graph-schema", get_graph_schema_status, methods=["GET"]),
        Route("/api/v1/admin/graph-schema/migrate", migrate_graph_schema, methods=["POST"]),
    ]

    return Starlette(debug=False, routes=routes)


def main() -> None:
    """Run the REST compatibility server."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting Temple REST API on %s:%s", settings.host, settings.port)
    app = create_app()
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
