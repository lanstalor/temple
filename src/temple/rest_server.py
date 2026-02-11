"""REST/OpenAPI compatibility server for Temple."""

from __future__ import annotations

import base64
import logging
from typing import Any

import uvicorn
from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
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


class SurveySubmitRequest(BaseModel):
    survey_id: str
    respondent_id: str
    response: str
    source: str = "survey"
    version: str = "1"
    idempotency_key: str | None = None
    metadata: dict[str, Any] | None = None
    scope: str = "project:survey"


class SurveyReviewDecisionRequest(BaseModel):
    decision: str
    reviewer: str | None = None
    notes: str | None = None


class IngestSubmitRequest(BaseModel):
    item_type: str
    actor_id: str
    source: str
    content: str
    source_id: str | None = None
    timestamp: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] | None = None
    scope: str = "global"


class IngestReviewDecisionRequest(BaseModel):
    decision: str
    reviewer: str | None = None
    notes: str | None = None


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
        "SurveySubmitRequest": SurveySubmitRequest.model_json_schema(),
        "SurveyReviewDecisionRequest": SurveyReviewDecisionRequest.model_json_schema(),
        "IngestSubmitRequest": IngestSubmitRequest.model_json_schema(),
        "IngestReviewDecisionRequest": IngestReviewDecisionRequest.model_json_schema(),
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
            "/api/v1/surveys/submit": {"post": {"summary": "Submit survey response and queue enrichment", "requestBody": req("SurveySubmitRequest"), "responses": {"200": {"description": "Queued job"}}}},
            "/api/v1/surveys/jobs/{job_id}": {"get": {"summary": "Get survey enrichment job status", "responses": {"200": {"description": "Job status"}}}},
            "/api/v1/surveys/reviews": {"get": {"summary": "List inferred relation review queue", "responses": {"200": {"description": "Review candidates"}}}},
            "/api/v1/surveys/reviews/{review_id}": {"post": {"summary": "Approve/reject inferred relation", "requestBody": req("SurveyReviewDecisionRequest"), "responses": {"200": {"description": "Review result"}}}},
            "/api/v1/ingest/submit": {"post": {"summary": "Submit content for ingest and enrichment", "requestBody": req("IngestSubmitRequest"), "responses": {"200": {"description": "Queued job"}}}},
            "/api/v1/ingest/jobs/{job_id}": {"get": {"summary": "Get ingest job status", "responses": {"200": {"description": "Job status"}}}},
            "/api/v1/ingest/reviews": {"get": {"summary": "List inferred relation review queue", "responses": {"200": {"description": "Review candidates"}}}},
            "/api/v1/ingest/reviews/{review_id}": {"post": {"summary": "Approve/reject inferred relation", "requestBody": req("IngestReviewDecisionRequest"), "responses": {"200": {"description": "Review result"}}}},
            "/api/v1/relationship-map": {"get": {"summary": "Get relationship map around an entity", "responses": {"200": {"description": "Relationship map"}}}},
            "/api/v1/admin/stats": {"get": {"summary": "Get stats", "responses": {"200": {"description": "Stats"}}}},
            "/api/v1/admin/graph/export": {"get": {"summary": "Export graph for visualization", "responses": {"200": {"description": "Graph export"}}}},
            "/api/v1/admin/graph-schema": {"get": {"summary": "Get graph schema status", "responses": {"200": {"description": "Status"}}}},
            "/api/v1/admin/graph-schema/migrate": {"post": {"summary": "Migrate graph schema", "requestBody": req("MigrateGraphSchemaRequest"), "responses": {"200": {"description": "Migration result"}}}},
        },
        "components": {"schemas": components},
    }


def _build_actions_openapi_schema(base_url: str) -> dict[str, Any]:
    """Build a stricter OpenAPI schema for GPT Actions imports."""

    def json_response(description: str) -> dict[str, Any]:
        return {
            "description": description,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                }
            },
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
        "openapi": "3.0.3",
        "info": {
            "title": "Temple REST API (Actions)",
            "version": "0.1.0",
            "description": (
                "Action-friendly OpenAPI schema for Temple. "
                "Use Authorization: Bearer <TEMPLE_API_KEY>."
            ),
        },
        "servers": [{"url": base_url}],
        "security": [{"bearerAuth": []}],
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health check",
                    "operationId": "healthCheck",
                    "security": [],
                    "responses": {"200": json_response("Service health")},
                }
            },
            "/api/v1/admin/stats": {
                "get": {
                    "summary": "Get platform stats",
                    "operationId": "getAdminStats",
                    "responses": {"200": json_response("Platform stats")},
                }
            },
            "/api/v1/context": {
                "get": {
                    "summary": "Get active context",
                    "operationId": "getContext",
                    "responses": {"200": json_response("Active context")},
                },
                "post": {
                    "summary": "Set active context",
                    "operationId": "setContext",
                    "requestBody": req("ContextSetRequest"),
                    "responses": {"200": json_response("Updated context")},
                },
            },
            "/api/v1/memory/store": {
                "post": {
                    "summary": "Store memory item",
                    "operationId": "storeMemory",
                    "requestBody": req("MemoryStoreRequest"),
                    "responses": {"200": json_response("Stored memory")},
                }
            },
            "/api/v1/memory/search": {
                "post": {
                    "summary": "Search memories",
                    "operationId": "searchMemories",
                    "requestBody": req("MemorySearchRequest"),
                    "responses": {"200": json_response("Memory search results")},
                }
            },
            "/api/v1/memory/retrieve": {
                "post": {
                    "summary": "Semantic memory retrieval",
                    "operationId": "retrieveMemory",
                    "requestBody": req("MemoryRetrieveRequest"),
                    "responses": {"200": json_response("Retrieved memories")},
                }
            },
            "/api/v1/entities/create": {
                "post": {
                    "summary": "Create entities",
                    "operationId": "createEntities",
                    "requestBody": req("EntityCreateRequest"),
                    "responses": {"200": json_response("Entity creation result")},
                }
            },
            "/api/v1/entities/{name}": {
                "get": {
                    "summary": "Get entity",
                    "operationId": "getEntity",
                    "parameters": [
                        {
                            "name": "name",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Entity name",
                        }
                    ],
                    "responses": {"200": json_response("Entity details")},
                },
                "patch": {
                    "summary": "Update entity",
                    "operationId": "updateEntity",
                    "parameters": [
                        {
                            "name": "name",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Entity name",
                        }
                    ],
                    "requestBody": req("EntityUpdateRequest"),
                    "responses": {"200": json_response("Update result")},
                },
            },
            "/api/v1/relations/path": {
                "post": {
                    "summary": "Find relationship path",
                    "operationId": "findRelationshipPath",
                    "requestBody": req("RelationPathRequest"),
                    "responses": {"200": json_response("Path result")},
                }
            },
            "/api/v1/relationship-map": {
                "get": {
                    "summary": "Get relationship map around an entity",
                    "operationId": "getRelationshipMap",
                    "parameters": [
                        {
                            "name": "entity",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "depth",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                        },
                        {
                            "name": "scope",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {"200": json_response("Relationship map")},
                }
            },
            "/api/v1/ingest/submit": {
                "post": {
                    "summary": "Submit content for ingest and enrichment",
                    "operationId": "submitIngestItem",
                    "requestBody": req("IngestSubmitRequest"),
                    "responses": {"200": json_response("Queued ingest job")},
                }
            },
            "/api/v1/ingest/jobs/{job_id}": {
                "get": {
                    "summary": "Get ingest job status",
                    "operationId": "getIngestJob",
                    "parameters": [
                        {
                            "name": "job_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": json_response("Ingest job status")},
                }
            },
            "/api/v1/ingest/reviews": {
                "get": {
                    "summary": "List ingest review queue",
                    "operationId": "listIngestReviews",
                    "parameters": [
                        {
                            "name": "status",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "default": "pending"},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 100, "minimum": 1, "maximum": 1000},
                        },
                    ],
                    "responses": {"200": json_response("Review queue entries")},
                }
            },
            "/api/v1/ingest/reviews/{review_id}": {
                "post": {
                    "summary": "Approve or reject inferred relation",
                    "operationId": "reviewIngestRelation",
                    "parameters": [
                        {
                            "name": "review_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "requestBody": req("IngestReviewDecisionRequest"),
                    "responses": {"200": json_response("Review decision result")},
                }
            },
            "/api/v1/admin/graph/export": {
                "get": {
                    "summary": "Export graph for visualization",
                    "operationId": "exportGraph",
                    "parameters": [
                        {
                            "name": "scope",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 10000, "minimum": 1, "maximum": 50000},
                        },
                        {
                            "name": "include_memories",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "boolean", "default": False},
                        },
                        {
                            "name": "memory_limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 5000, "minimum": 1, "maximum": 100000},
                        },
                    ],
                    "responses": {"200": json_response("Graph export payload")},
                }
            },
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "APIKey",
                }
            },
            "schemas": {
                "MemoryStoreRequest": {
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "metadata": {
                            "type": "object",
                            "properties": {
                                "_note": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                        "scope": {"type": "string"},
                    },
                },
                "MemoryRetrieveRequest": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "n_results": {"type": "integer", "default": 5},
                        "scope": {"type": "string"},
                    },
                },
                "MemorySearchRequest": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "scope": {"type": "string"},
                        "n_results": {"type": "integer", "default": 10},
                    },
                },
                "EntityCreateRequest": {
                    "type": "object",
                    "required": ["entities"],
                    "properties": {
                        "entities": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "entity_type": {"type": "string"},
                                    "observations": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "additionalProperties": True,
                            },
                        }
                    },
                },
                "EntityUpdateRequest": {
                    "type": "object",
                    "properties": {
                        "entity_type": {"type": "string"},
                        "observations": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "RelationPathRequest": {
                    "type": "object",
                    "required": ["source", "target"],
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "max_hops": {"type": "integer", "default": 5},
                    },
                },
                "ContextSetRequest": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "session": {"type": "string"},
                    },
                },
                "IngestSubmitRequest": {
                    "type": "object",
                    "required": ["item_type", "actor_id", "source", "content"],
                    "properties": {
                        "item_type": {"type": "string"},
                        "actor_id": {"type": "string"},
                        "source": {"type": "string"},
                        "content": {"type": "string"},
                        "source_id": {"type": "string"},
                        "timestamp": {"type": "string"},
                        "idempotency_key": {"type": "string"},
                        "metadata": {
                            "type": "object",
                            "properties": {
                                "_note": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                        "scope": {"type": "string", "default": "global"},
                    },
                },
                "IngestReviewDecisionRequest": {
                    "type": "object",
                    "required": ["decision"],
                    "properties": {
                        "decision": {"type": "string", "enum": ["approve", "reject"]},
                        "reviewer": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                },
            },
        },
    }


def _build_atlas_html() -> str:
    """Return the Temple Atlas interactive graph viewer page."""
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Temple Atlas</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
      :root {
        --bg: #f5f2e8;
        --bg2: #ece6d6;
        --panel: #fcfbf8;
        --ink: #1f2a24;
        --muted: #5f695f;
        --global: #2a9d8f;
        --project: #e76f51;
        --session: #e63946;
        --edge: #6c757d;
        --ring: #1f2a24;
        --ok: #2b9348;
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        min-height: 100vh;
        color: var(--ink);
        font-family: "IBM Plex Sans", "Helvetica Neue", sans-serif;
        background:
          radial-gradient(circle at 12% 18%, rgba(42,157,143,0.18), transparent 36%),
          radial-gradient(circle at 88% 10%, rgba(231,111,81,0.19), transparent 32%),
          radial-gradient(circle at 84% 88%, rgba(230,57,70,0.16), transparent 28%),
          linear-gradient(140deg, var(--bg), var(--bg2));
      }
      body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background-image:
          linear-gradient(rgba(31,42,36,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(31,42,36,0.03) 1px, transparent 1px);
        background-size: 24px 24px;
        mask-image: radial-gradient(circle at center, black 35%, transparent 85%);
      }
      .shell {
        padding: 20px;
        display: grid;
        gap: 14px;
      }
      .hero {
        border: 1px solid rgba(31,42,36,0.14);
        border-radius: 18px;
        padding: 16px 18px;
        background: linear-gradient(145deg, rgba(252,251,248,0.9), rgba(252,251,248,0.74));
        backdrop-filter: blur(2px);
        box-shadow: 0 12px 30px rgba(31,42,36,0.08);
        animation: reveal 500ms ease-out;
      }
      .hero h1 {
        margin: 0;
        font-family: "Sora", "IBM Plex Sans", sans-serif;
        letter-spacing: 0.02em;
        font-size: clamp(1.25rem, 2vw, 1.8rem);
      }
      .hero p {
        margin: 8px 0 0;
        color: var(--muted);
        line-height: 1.45;
      }
      .controls {
        border: 1px solid rgba(31,42,36,0.14);
        border-radius: 18px;
        padding: 14px;
        background: rgba(252,251,248,0.92);
        box-shadow: 0 8px 24px rgba(31,42,36,0.07);
        animation: reveal 560ms ease-out;
      }
      .control-grid {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 10px;
      }
      .field {
        display: grid;
        gap: 6px;
      }
      .field label {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #465048;
      }
      .field input,
      .field select,
      .field button {
        width: 100%;
        border-radius: 10px;
        border: 1px solid rgba(31,42,36,0.22);
        padding: 9px 10px;
        min-height: 38px;
        background: #fffdfa;
        color: var(--ink);
        font: inherit;
      }
      .field input:focus,
      .field select:focus {
        outline: 2px solid rgba(42,157,143,0.45);
        outline-offset: 1px;
      }
      .field button {
        border: none;
        color: #fff;
        font-weight: 600;
        cursor: pointer;
        background: linear-gradient(160deg, #1f7a71, var(--global));
      }
      .field button.secondary {
        background: linear-gradient(160deg, #6f4e37, #a47148);
      }
      .field button:hover {
        filter: brightness(1.04);
      }
      .field.span-2 {
        grid-column: span 2;
      }
      .field.span-3 {
        grid-column: span 3;
      }
      .layout {
        display: grid;
        grid-template-columns: 1.8fr 1fr;
        gap: 14px;
      }
      .panel {
        border: 1px solid rgba(31,42,36,0.15);
        border-radius: 18px;
        background: rgba(252,251,248,0.94);
        box-shadow: 0 10px 28px rgba(31,42,36,0.08);
        overflow: hidden;
        animation: reveal 620ms ease-out;
      }
      .panel-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
        padding: 12px 14px;
        border-bottom: 1px solid rgba(31,42,36,0.12);
      }
      .panel-title {
        margin: 0;
        font: 600 0.95rem "Sora", sans-serif;
      }
      .status {
        font-family: "IBM Plex Mono", monospace;
        font-size: 0.78rem;
        color: var(--muted);
      }
      #graph-wrap {
        height: min(74vh, 760px);
        position: relative;
      }
      #graph {
        width: 100%;
        height: 100%;
      }
      .empty {
        position: absolute;
        inset: 0;
        display: grid;
        place-items: center;
        text-align: center;
        color: var(--muted);
        padding: 20px;
        font-size: 0.95rem;
      }
      .stats {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }
      .stat {
        border: 1px solid rgba(31,42,36,0.12);
        border-radius: 12px;
        padding: 10px 11px;
        background: rgba(255,255,255,0.8);
      }
      .stat .label {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        color: var(--muted);
      }
      .stat .value {
        margin-top: 4px;
        font: 600 1.15rem "Sora", sans-serif;
      }
      .legend {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 10px;
      }
      .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 0.82rem;
        color: var(--muted);
      }
      .dot {
        width: 10px;
        height: 10px;
        border-radius: 999px;
      }
      .detail {
        padding: 14px;
        display: grid;
        gap: 10px;
        height: calc(min(74vh, 760px) - 49px);
        overflow: auto;
      }
      .detail h3 {
        margin: 0;
        font: 600 1rem "Sora", sans-serif;
      }
      .pill {
        display: inline-block;
        border-radius: 999px;
        padding: 2px 8px;
        font-size: 0.75rem;
        border: 1px solid rgba(31,42,36,0.2);
        color: #304138;
        background: rgba(255,255,255,0.85);
      }
      .block {
        border: 1px solid rgba(31,42,36,0.12);
        border-radius: 12px;
        padding: 10px;
        background: #fffefb;
      }
      .block h4 {
        margin: 0 0 8px;
        font-size: 0.85rem;
        letter-spacing: 0.03em;
      }
      .list {
        margin: 0;
        padding-left: 16px;
        display: grid;
        gap: 6px;
        color: #2e3a32;
      }
      .list li {
        line-height: 1.35;
      }
      .xref {
        border: none;
        background: none;
        text-decoration: underline;
        cursor: pointer;
        color: #17635a;
        font: inherit;
        padding: 0;
      }
      .xref:hover {
        color: #0f4c45;
      }
      .ok {
        color: var(--ok);
      }
      @keyframes reveal {
        from {
          opacity: 0;
          transform: translateY(6px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }
      @media (max-width: 1120px) {
        .control-grid {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .field.span-2,
        .field.span-3 {
          grid-column: span 2;
        }
        .layout {
          grid-template-columns: 1fr;
        }
        #graph-wrap {
          height: 56vh;
        }
        .detail {
          height: auto;
          max-height: 48vh;
        }
      }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
  </head>
  <body>
    <div class="shell">
      <section class="hero">
        <h1>Temple Atlas</h1>
        <p>Interactive knowledge graph explorer for Temple memory data. Load entities and relations, filter by scope and type, and drill into linked notes.</p>
      </section>

      <section class="controls">
        <div class="control-grid">
          <div class="field span-2">
            <label for="baseUrl">Temple Base URL</label>
            <input id="baseUrl" type="text" />
          </div>
          <div class="field span-2">
            <label for="apiKey">API Key (optional in dev)</label>
            <input id="apiKey" type="password" placeholder="Bearer token for auth-enabled servers"/>
          </div>
          <div class="field">
            <label for="scopeFilter">Scope Filter</label>
            <select id="scopeFilter">
              <option value="all">all scopes</option>
              <option value="global">global</option>
              <option value="project">project</option>
              <option value="session">session</option>
            </select>
          </div>
          <div class="field">
            <label for="typeFilter">Entity Type</label>
            <select id="typeFilter">
              <option value="all">all types</option>
            </select>
          </div>
          <div class="field span-2">
            <label for="searchInput">Search Nodes</label>
            <input id="searchInput" type="text" placeholder="name, scope, or observation text"/>
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <button id="loadBtn" type="button">Load Graph</button>
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <button id="resetBtn" class="secondary" type="button">Reset View</button>
          </div>
        </div>
      </section>

      <section class="layout">
        <article class="panel">
          <header class="panel-head">
            <h2 class="panel-title">Graph View</h2>
            <span id="status" class="status">idle</span>
          </header>
          <div id="graph-wrap">
            <svg id="graph" aria-label="Temple graph visualization"></svg>
            <div id="emptyState" class="empty">Click <strong>Load Graph</strong> to fetch data.</div>
          </div>
        </article>

        <aside class="panel">
          <header class="panel-head">
            <h2 class="panel-title">Inspector</h2>
            <span id="loadHealth" class="status">No data loaded</span>
          </header>
          <div class="detail">
            <div class="stats">
              <div class="stat">
                <div class="label">Entities</div>
                <div class="value" id="entityCount">0</div>
              </div>
              <div class="stat">
                <div class="label">Relations</div>
                <div class="value" id="relationCount">0</div>
              </div>
              <div class="stat">
                <div class="label">Scopes</div>
                <div class="value" id="scopeCount">0</div>
              </div>
            </div>

            <div class="legend">
              <span class="legend-item"><span class="dot" style="background: var(--global)"></span>Global</span>
              <span class="legend-item"><span class="dot" style="background: var(--project)"></span>Project</span>
              <span class="legend-item"><span class="dot" style="background: var(--session)"></span>Session</span>
            </div>

            <div id="nodeDetail" class="block">
              <h4>Selection</h4>
              <p style="margin:0;color:var(--muted)">Select a node to inspect observations and cross-links.</p>
            </div>
          </div>
        </aside>
      </section>
    </div>

    <script>
      (() => {
        const baseUrlInput = document.getElementById("baseUrl");
        const apiKeyInput = document.getElementById("apiKey");
        const scopeFilter = document.getElementById("scopeFilter");
        const typeFilter = document.getElementById("typeFilter");
        const searchInput = document.getElementById("searchInput");
        const loadBtn = document.getElementById("loadBtn");
        const resetBtn = document.getElementById("resetBtn");
        const statusEl = document.getElementById("status");
        const healthEl = document.getElementById("loadHealth");
        const emptyState = document.getElementById("emptyState");
        const nodeDetail = document.getElementById("nodeDetail");
        const entityCountEl = document.getElementById("entityCount");
        const relationCountEl = document.getElementById("relationCount");
        const scopeCountEl = document.getElementById("scopeCount");
        const svg = d3.select("#graph");

        const storageKeys = {
          baseUrl: "temple.atlas.base_url",
          apiKey: "temple.atlas.api_key",
        };

        function safeStorageGet(key) {
          try {
            return window.localStorage.getItem(key) || "";
          } catch (_) {
            return "";
          }
        }

        function safeStorageSet(key, value) {
          try {
            if (value) {
              window.localStorage.setItem(key, value);
            } else {
              window.localStorage.removeItem(key);
            }
          } catch (_) {
            // Ignore storage failures (private mode or policy restrictions).
          }
        }

        function normalizeBaseUrl(value) {
          return value.trim().replace(/\\/$/, "");
        }

        function restoreAuthInputs() {
          const savedBaseUrl = normalizeBaseUrl(safeStorageGet(storageKeys.baseUrl));
          const savedApiKey = safeStorageGet(storageKeys.apiKey).trim();

          baseUrlInput.value = savedBaseUrl || window.location.origin;
          apiKeyInput.value = savedApiKey;

          return { hasSavedApiKey: Boolean(savedApiKey) };
        }

        function persistAuthInputs() {
          const baseUrl = normalizeBaseUrl(baseUrlInput.value || "");
          const apiKey = (apiKeyInput.value || "").trim();
          safeStorageSet(storageKeys.baseUrl, baseUrl);
          safeStorageSet(storageKeys.apiKey, apiKey);
        }

        const restored = restoreAuthInputs();

        const state = {
          raw: null,
          nodes: [],
          links: [],
          filteredNodes: [],
          filteredLinks: [],
          selectedNodeId: null,
          simulation: null,
          zoomLayer: null,
          linkLayer: null,
          nodeLayer: null,
          labelLayer: null,
        };

        function setStatus(text, isOk = false) {
          statusEl.textContent = text;
          statusEl.classList.toggle("ok", isOk);
        }

        function scopeClass(scope) {
          if (!scope || scope === "global") {
            return "global";
          }
          if (scope.startsWith("project:")) {
            return "project";
          }
          if (scope.startsWith("session:")) {
            return "session";
          }
          return "global";
        }

        function scopeColor(scope) {
          const cls = scopeClass(scope);
          if (cls === "project") return getComputedStyle(document.documentElement).getPropertyValue("--project").trim();
          if (cls === "session") return getComputedStyle(document.documentElement).getPropertyValue("--session").trim();
          return getComputedStyle(document.documentElement).getPropertyValue("--global").trim();
        }

        function nodeId(name, scope) {
          return `${scope || "global"}::${name}`;
        }

        function buildGraph(payload) {
          const entities = Array.isArray(payload.entities) ? payload.entities : [];
          const relations = Array.isArray(payload.relations) ? payload.relations : [];
          const memories = Array.isArray(payload.memories) ? payload.memories : [];

          const scopeSet = new Set();
          const nodes = entities.map((entity) => {
            const scope = entity.scope || "global";
            scopeSet.add(scope);
            const id = nodeId(entity.name, scope);
            return {
              id,
              name: entity.name,
              scope,
              entity_type: entity.entity_type || "unknown",
              node_kind: "entity",
              observations: Array.isArray(entity.observations) ? entity.observations : [],
              content: "",
              tags: [],
              created_at: entity.created_at || "",
              updated_at: entity.updated_at || "",
              degree: 0,
            };
          });

          memories.forEach((memory) => {
            const scope = memory.scope || "global";
            scopeSet.add(scope);
            const title = (memory.content || "").trim().slice(0, 48);
            nodes.push({
              id: `memory::${memory.id}`,
              name: title ? `note: ${title}` : `note: ${memory.id.slice(0, 12)}`,
              raw_name: memory.id,
              scope,
              entity_type: "memory-note",
              node_kind: "memory",
              observations: [],
              content: memory.content || "",
              tags: Array.isArray(memory.tags) ? memory.tags : [],
              created_at: memory.created_at || "",
              updated_at: memory.updated_at || "",
              degree: 0,
            });
          });

          const byId = new Map(nodes.map((n) => [n.id, n]));
          const byName = new Map();
          nodes
            .filter((n) => n.node_kind === "entity")
            .forEach((n) => {
              const arr = byName.get(n.name) || [];
              arr.push(n);
              byName.set(n.name, arr);
            });

          scopeSet.forEach((scope) => {
            const id = `scope::${scope}`;
            if (byId.has(id)) return;
            const scopeLabel = scope === "global" ? "scope: global" : `scope: ${scope}`;
            const scopeNode = {
              id,
              name: scopeLabel,
              scope,
              entity_type: "scope",
              node_kind: "scope",
              observations: [],
              content: "",
              tags: [],
              created_at: "",
              updated_at: "",
              degree: 0,
            };
            nodes.push(scopeNode);
            byId.set(id, scopeNode);
          });

          const links = [];
          const seen = new Set();
          function addLink(sourceId, targetId, relationType, scope) {
            if (!byId.has(sourceId) || !byId.has(targetId)) return;
            const key = `${sourceId}|${targetId}|${relationType}|${scope || ""}`;
            if (seen.has(key)) return;
            seen.add(key);
            links.push({
              source: sourceId,
              target: targetId,
              relation_type: relationType,
              scope: scope || "",
            });
          }

          relations.forEach((rel) => {
            const srcScope = rel.source_scope || rel.scope || "global";
            const tgtScope = rel.target_scope || rel.scope || null;
            const sourceId = nodeId(rel.source, srcScope);
            let targetId = null;

            if (tgtScope && byId.has(nodeId(rel.target, tgtScope))) {
              targetId = nodeId(rel.target, tgtScope);
            } else if (byId.has(nodeId(rel.target, rel.scope || "global"))) {
              targetId = nodeId(rel.target, rel.scope || "global");
            } else {
              const candidates = byName.get(rel.target) || [];
              if (candidates.length === 1) {
                targetId = candidates[0].id;
              } else if (candidates.length > 1) {
                const match = candidates.find((c) => c.scope === srcScope) || candidates[0];
                targetId = match.id;
              }
            }
            if (targetId) {
              addLink(sourceId, targetId, rel.relation_type || "related_to", rel.scope || "");
            }
          });

          memories.forEach((memory) => {
            const memoryId = `memory::${memory.id}`;
            const memoryScope = memory.scope || "global";
            addLink(memoryId, `scope::${memoryScope}`, "in_scope", memoryScope);

            const content = (memory.content || "").toLowerCase();
            if (!content) return;
            for (const [entityName, candidates] of byName.entries()) {
              if (!content.includes(entityName.toLowerCase())) continue;
              const target = candidates.find((c) => c.scope === memoryScope) || candidates[0];
              addLink(memoryId, target.id, "mentions", memoryScope);
            }
          });

          links.forEach((l) => {
            const src = byId.get(l.source);
            const tgt = byId.get(l.target);
            if (src) src.degree += 1;
            if (tgt) tgt.degree += 1;
          });

          return { nodes, links };
        }

        function populateTypeFilter(nodes) {
          const current = typeFilter.value;
          typeFilter.innerHTML = "";
          const all = document.createElement("option");
          all.value = "all";
          all.textContent = "all types";
          typeFilter.appendChild(all);

          const types = [...new Set(nodes.map((n) => n.entity_type).filter(Boolean))].sort();
          types.forEach((type) => {
            const option = document.createElement("option");
            option.value = type;
            option.textContent = type;
            typeFilter.appendChild(option);
          });
          typeFilter.value = types.includes(current) ? current : "all";
        }

        function applyFilters() {
          if (!state.raw) return;

          const scopeValue = scopeFilter.value;
          const typeValue = typeFilter.value;
          const needle = searchInput.value.trim().toLowerCase();

          const nodes = state.nodes.filter((n) => {
            const scopeOk = scopeValue === "all" ? true : scopeClass(n.scope) === scopeValue;
            const typeOk = typeValue === "all" ? true : n.entity_type === typeValue;
            const text = `${n.name} ${n.scope} ${n.observations.join(" ")} ${n.content || ""} ${(n.tags || []).join(" ")}`.toLowerCase();
            const searchOk = needle ? text.includes(needle) : true;
            return scopeOk && typeOk && searchOk;
          });

          const allowed = new Set(nodes.map((n) => n.id));
          const links = state.links.filter((l) => allowed.has(l.source) && allowed.has(l.target));

          state.filteredNodes = nodes;
          state.filteredLinks = links;
          drawGraph();
          renderStats();
          renderSelection();
        }

        function renderStats() {
          const nodes = state.filteredNodes;
          const links = state.filteredLinks;
          const dataNodes = nodes.filter((n) => n.node_kind !== "scope");
          const scopes = new Set(dataNodes.map((n) => n.scope));
          entityCountEl.textContent = String(dataNodes.length);
          relationCountEl.textContent = String(links.length);
          scopeCountEl.textContent = String(scopes.size);
        }

        function fitView() {
          const graphEl = document.getElementById("graph");
          const bounds = graphEl.getBoundingClientRect();
          const width = bounds.width || 900;
          const height = bounds.height || 600;
          svg.attr("viewBox", `0 0 ${width} ${height}`);
          return { width, height };
        }

        function renderSelection() {
          const node = state.filteredNodes.find((n) => n.id === state.selectedNodeId);
          if (!node) {
            nodeDetail.innerHTML = '<h4>Selection</h4><p style="margin:0;color:var(--muted)">Select a node to inspect observations and cross-links.</p>';
            return;
          }

          const outgoing = state.filteredLinks.filter((l) => l.source.id ? l.source.id === node.id : l.source === node.id);
          const incoming = state.filteredLinks.filter((l) => l.target.id ? l.target.id === node.id : l.target === node.id);
          const byId = new Map(state.filteredNodes.map((n) => [n.id, n]));

          function linkList(entries, kind) {
            if (!entries.length) return "<p style=\\"margin:0;color:var(--muted)\\">none</p>";
            const items = entries.map((link) => {
              const targetId = kind === "out"
                ? (link.target.id || link.target)
                : (link.source.id || link.source);
              const target = byId.get(targetId);
              const label = target ? `${target.name} (${target.scope})` : targetId;
              const rel = link.relation_type || "related_to";
              return `<li>${rel} -> <button class=\\"xref\\" data-node-id=\\"${targetId}\\">${label}</button></li>`;
            }).join("");
            return `<ul class=\\"list\\">${items}</ul>`;
          }

          const obsItems = node.observations.length
            ? `<ul class="list">${node.observations.map((o) => `<li>${o}</li>`).join("")}</ul>`
            : '<p style="margin:0;color:var(--muted)">none</p>';
          const tagsItems = (node.tags || []).length
            ? `<ul class="list">${node.tags.map((t) => `<li>${t}</li>`).join("")}</ul>`
            : '<p style="margin:0;color:var(--muted)">none</p>';
          const contentBlock = node.content
            ? `<div class="block"><h4>Note Content</h4><p style="margin:0;line-height:1.5;white-space:pre-wrap">${node.content}</p></div>`
            : "";
          const tagsBlock = node.node_kind === "memory"
            ? `<div class="block"><h4>Tags</h4>${tagsItems}</div>`
            : "";

          nodeDetail.innerHTML = `
            <h3>${node.name}</h3>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <span class="pill">${node.entity_type}</span>
              <span class="pill">${node.scope}</span>
              <span class="pill">degree ${node.degree}</span>
            </div>
            ${contentBlock}
            ${tagsBlock}
            <div class="block">
              <h4>Observations</h4>
              ${obsItems}
            </div>
            <div class="block">
              <h4>Outgoing Relations</h4>
              ${linkList(outgoing, "out")}
            </div>
            <div class="block">
              <h4>Incoming Relations</h4>
              ${linkList(incoming, "in")}
            </div>
          `;

          nodeDetail.querySelectorAll(".xref").forEach((btn) => {
            btn.addEventListener("click", () => {
              const id = btn.getAttribute("data-node-id");
              state.selectedNodeId = id;
              renderSelection();
              drawGraph();
            });
          });
        }

        function drawGraph() {
          const nodes = state.filteredNodes.map((n) => ({ ...n }));
          const links = state.filteredLinks.map((l) => ({ ...l }));

          if (!nodes.length) {
            emptyState.style.display = "grid";
          } else {
            emptyState.style.display = "none";
          }

          const { width, height } = fitView();
          svg.selectAll("*").remove();

          state.zoomLayer = svg.append("g");
          state.linkLayer = state.zoomLayer.append("g").attr("stroke-linecap", "round");
          state.nodeLayer = state.zoomLayer.append("g");
          state.labelLayer = state.zoomLayer.append("g");

          const zoom = d3.zoom().scaleExtent([0.2, 4]).on("zoom", (event) => {
            state.zoomLayer.attr("transform", event.transform);
          });
          svg.call(zoom);

          const simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id((d) => d.id).distance(92).strength(0.22))
            .force("charge", d3.forceManyBody().strength(-250))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collide", d3.forceCollide().radius((d) => 9 + Math.min(d.degree, 8)));
          state.simulation = simulation;

          const linkSel = state.linkLayer.selectAll("line")
            .data(links)
            .join("line")
            .attr("stroke", "var(--edge)")
            .attr("stroke-opacity", 0.42)
            .attr("stroke-width", (d) => d.relation_type ? 1.5 : 1);

          const nodeSel = state.nodeLayer.selectAll("circle")
            .data(nodes, (d) => d.id)
            .join("circle")
            .attr("r", (d) => {
              if (d.node_kind === "scope") return 9 + Math.min(d.degree, 6);
              if (d.node_kind === "memory") return 5 + Math.min(d.degree, 5);
              return 6 + Math.min(d.degree, 8);
            })
            .attr("fill", (d) => scopeColor(d.scope))
            .attr("stroke", "var(--ring)")
            .attr("stroke-width", (d) => d.id === state.selectedNodeId ? 2.4 : 1.1)
            .style("cursor", "pointer")
            .on("click", (_, d) => {
              state.selectedNodeId = d.id;
              renderSelection();
              drawGraph();
            })
            .call(
              d3.drag()
                .on("start", (event, d) => {
                  if (!event.active) simulation.alphaTarget(0.3).restart();
                  d.fx = d.x;
                  d.fy = d.y;
                })
                .on("drag", (event, d) => {
                  d.fx = event.x;
                  d.fy = event.y;
                })
                .on("end", (event, d) => {
                  if (!event.active) simulation.alphaTarget(0);
                  d.fx = null;
                  d.fy = null;
                })
            );

          const labels = state.labelLayer.selectAll("text")
            .data(nodes)
            .join("text")
            .text((d) => {
              if (d.node_kind === "scope") return d.name;
              if (d.node_kind === "memory") return d.name.slice(0, 36);
              return d.name;
            })
            .attr("font-size", 11)
            .attr("font-weight", 500)
            .attr("font-family", "IBM Plex Sans, sans-serif")
            .attr("fill", "#203028")
            .attr("paint-order", "stroke")
            .attr("stroke", "rgba(252,251,248,0.85)")
            .attr("stroke-width", 3)
            .attr("stroke-linecap", "round")
            .attr("stroke-linejoin", "round");

          simulation.on("tick", () => {
            linkSel
              .attr("x1", (d) => d.source.x)
              .attr("y1", (d) => d.source.y)
              .attr("x2", (d) => d.target.x)
              .attr("y2", (d) => d.target.y);

            nodeSel
              .attr("cx", (d) => d.x)
              .attr("cy", (d) => d.y);

            labels
              .attr("x", (d) => d.x + 10)
              .attr("y", (d) => d.y + 3);
          });
        }

        async function loadGraph() {
          const baseUrl = normalizeBaseUrl(baseUrlInput.value || "");
          const apiKey = apiKeyInput.value.trim();
          if (!baseUrl) {
            setStatus("base URL missing");
            return;
          }

          const url = `${baseUrl}/api/v1/admin/graph/export?include_memories=1&memory_limit=5000`;
          const headers = {};
          if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

          setStatus("loading...");
          healthEl.textContent = "Fetching graph export";
          try {
            const response = await fetch(url, { headers });
            if (!response.ok) {
              const text = await response.text();
              throw new Error(`HTTP ${response.status}: ${text.slice(0, 180)}`);
            }
            const payload = await response.json();
            state.raw = payload;
            const graph = buildGraph(payload);
            state.nodes = graph.nodes;
            state.links = graph.links;
            populateTypeFilter(state.nodes);
            state.selectedNodeId = null;
            applyFilters();
            persistAuthInputs();
            setStatus("loaded", true);
            healthEl.textContent = `Loaded ${state.nodes.length} nodes / ${state.links.length} links`;
            if (!state.nodes.length) {
              emptyState.textContent = "No graph or memory notes found for this scope yet.";
            }
          } catch (err) {
            console.error(err);
            setStatus("load failed");
            healthEl.textContent = String(err.message || err);
            state.raw = null;
            state.nodes = [];
            state.links = [];
            state.filteredNodes = [];
            state.filteredLinks = [];
            drawGraph();
            renderStats();
            renderSelection();
          }
        }

        loadBtn.addEventListener("click", loadGraph);
        resetBtn.addEventListener("click", () => {
          scopeFilter.value = "all";
          typeFilter.value = "all";
          searchInput.value = "";
          applyFilters();
        });
        scopeFilter.addEventListener("change", applyFilters);
        typeFilter.addEventListener("change", applyFilters);
        searchInput.addEventListener("input", applyFilters);
        baseUrlInput.addEventListener("change", persistAuthInputs);
        apiKeyInput.addEventListener("change", persistAuthInputs);
        window.addEventListener("resize", () => {
          if (state.raw) drawGraph();
        });

        if (restored.hasSavedApiKey) {
          loadGraph();
        }
      })();
    </script>
  </body>
</html>
"""


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

    def request_base_url(request: Request) -> str:
        """Resolve externally reachable base URL, honoring reverse-proxy headers."""
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        forwarded_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        if forwarded_proto and forwarded_host:
            return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
        host = request.headers.get("host", "").strip()
        if forwarded_proto and host:
            return f"{forwarded_proto}://{host}".rstrip("/")
        return str(request.base_url).rstrip("/")

    def _check_basic_auth(request: Request) -> bool:
        """Return True if the request carries valid Atlas Basic Auth credentials."""
        if not app_settings.atlas_user or not app_settings.atlas_pass:
            return False
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                user, password = decoded.split(":", 1)
                return user == app_settings.atlas_user and password == app_settings.atlas_pass
            except Exception:
                pass
        return False

    def require_auth(request: Request) -> JSONResponse | None:
        if not app_settings.api_key:
            return None
        auth = request.headers.get("authorization", "")
        expected = f"Bearer {app_settings.api_key}"
        if auth == expected:
            return None
        if _check_basic_auth(request):
            return None
        return unauthorized()

    def require_atlas_auth(request: Request) -> Response | None:
        if not app_settings.atlas_user or not app_settings.atlas_pass:
            return None
        if _check_basic_auth(request):
            return None
        return Response(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Atlas"'},
        )

    async def parse_json(request: Request, model: type[BaseModel]) -> BaseModel:
        payload = await request.json()
        return model.model_validate(payload)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse(app_broker.health_check())

    async def openapi(request: Request) -> JSONResponse:
        base_url = request_base_url(request)
        return JSONResponse(_build_openapi_schema(base_url))

    async def openapi_actions(request: Request) -> JSONResponse:
        base_url = request_base_url(request)
        return JSONResponse(_build_actions_openapi_schema(base_url))

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

    async def atlas(request: Request) -> HTMLResponse | Response:
        auth = require_atlas_auth(request)
        if auth:
            return auth
        return HTMLResponse(_build_atlas_html())

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

    async def submit_survey(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, SurveySubmitRequest)
            result = app_broker.submit_survey_response(
                survey_id=body.survey_id,
                respondent_id=body.respondent_id,
                response=body.response,
                source=body.source,
                version=body.version,
                idempotency_key=body.idempotency_key,
                metadata=body.metadata,
                scope=body.scope,
            )
            return JSONResponse(result)
        except ValidationError as e:
            return error(str(e), status=422)
        except ValueError as e:
            return error(str(e), status=400)

    async def get_survey_job(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        job_id = request.path_params["job_id"]
        record = app_broker.get_survey_job(job_id)
        if record is None:
            return error(f"Survey job '{job_id}' not found", status=404)
        return JSONResponse(record)

    async def list_survey_reviews(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        status = request.query_params.get("status", "pending")
        limit_raw = request.query_params.get("limit", "100")
        try:
            limit = max(1, min(int(limit_raw), 1000))
        except ValueError:
            return error("limit must be an integer", status=422)
        return JSONResponse(app_broker.list_survey_reviews(status=status, limit=limit))

    async def review_survey_relation(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        review_id = request.path_params["review_id"]
        try:
            body = await parse_json(request, SurveyReviewDecisionRequest)
            result = app_broker.review_survey_relation(
                review_id=review_id,
                decision=body.decision,
                reviewer=body.reviewer,
                notes=body.notes,
            )
            if result is None:
                return error(f"Review '{review_id}' not found", status=404)
            return JSONResponse(result)
        except ValidationError as e:
            return error(str(e), status=422)
        except ValueError as e:
            return error(str(e), status=400)

    async def submit_ingest(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        try:
            body = await parse_json(request, IngestSubmitRequest)
            result = app_broker.submit_ingest_item(
                item_type=body.item_type,
                actor_id=body.actor_id,
                source=body.source,
                content=body.content,
                source_id=body.source_id,
                timestamp=body.timestamp,
                idempotency_key=body.idempotency_key,
                metadata=body.metadata,
                scope=body.scope,
            )
            return JSONResponse(result)
        except ValidationError as e:
            return error(str(e), status=422)
        except ValueError as e:
            return error(str(e), status=400)

    async def get_ingest_job(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        job_id = request.path_params["job_id"]
        record = app_broker.get_ingest_job(job_id)
        if record is None:
            return error(f"Ingest job '{job_id}' not found", status=404)
        return JSONResponse(record)

    async def list_ingest_reviews(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        status = request.query_params.get("status", "pending")
        limit_raw = request.query_params.get("limit", "100")
        try:
            limit = max(1, min(int(limit_raw), 1000))
        except ValueError:
            return error("limit must be an integer", status=422)
        return JSONResponse(app_broker.list_ingest_reviews(status=status, limit=limit))

    async def review_ingest_relation(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        review_id = request.path_params["review_id"]
        try:
            body = await parse_json(request, IngestReviewDecisionRequest)
            result = app_broker.review_ingest_relation(
                review_id=review_id,
                decision=body.decision,
                reviewer=body.reviewer,
                notes=body.notes,
            )
            if result is None:
                return error(f"Review '{review_id}' not found", status=404)
            return JSONResponse(result)
        except ValidationError as e:
            return error(str(e), status=422)
        except ValueError as e:
            return error(str(e), status=400)

    async def relationship_map(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        entity = request.query_params.get("entity", "").strip()
        if not entity:
            return error("entity query parameter is required", status=422)
        depth_raw = request.query_params.get("depth", "2")
        limit_raw = request.query_params.get("limit", "200")
        scope = request.query_params.get("scope")
        try:
            depth = max(1, min(int(depth_raw), 4))
        except ValueError:
            return error("depth must be an integer", status=422)
        try:
            limit = max(1, min(int(limit_raw), 1000))
        except ValueError:
            return error("limit must be an integer", status=422)
        try:
            return JSONResponse(
                app_broker.get_relationship_map(
                    entity=entity,
                    depth=depth,
                    scope=scope,
                    limit=limit,
                )
            )
        except ValueError as e:
            return error(str(e), status=422)

    async def get_stats(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        return JSONResponse(app_broker.get_stats())

    async def export_graph(request: Request) -> JSONResponse:
        auth = require_auth(request)
        if auth:
            return auth
        scope = request.query_params.get("scope")
        limit_raw = request.query_params.get("limit", "10000")
        include_memories_raw = request.query_params.get("include_memories", "false").strip().lower()
        include_memories = include_memories_raw in {"1", "true", "yes", "on"}
        memory_limit_raw = request.query_params.get("memory_limit", "5000")
        try:
            limit = max(1, min(int(limit_raw), 50000))
        except ValueError:
            return error("limit must be an integer", status=422)
        try:
            memory_limit = max(1, min(int(memory_limit_raw), 100000))
        except ValueError:
            return error("memory_limit must be an integer", status=422)
        try:
            return JSONResponse(
                app_broker.export_knowledge_graph(
                    scope=scope,
                    limit=limit,
                    include_memories=include_memories,
                    memory_limit=memory_limit,
                )
            )
        except ValueError as e:
            return error(str(e), status=422)

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
        Route("/openapi.actions.json", openapi_actions, methods=["GET"]),
        Route("/docs", docs, methods=["GET"]),
        Route("/atlas", atlas, methods=["GET"]),
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
        Route("/api/v1/surveys/submit", submit_survey, methods=["POST"]),
        Route("/api/v1/surveys/jobs/{job_id}", get_survey_job, methods=["GET"]),
        Route("/api/v1/surveys/reviews", list_survey_reviews, methods=["GET"]),
        Route("/api/v1/surveys/reviews/{review_id}", review_survey_relation, methods=["POST"]),
        Route("/api/v1/ingest/submit", submit_ingest, methods=["POST"]),
        Route("/api/v1/ingest/jobs/{job_id}", get_ingest_job, methods=["GET"]),
        Route("/api/v1/ingest/reviews", list_ingest_reviews, methods=["GET"]),
        Route("/api/v1/ingest/reviews/{review_id}", review_ingest_relation, methods=["POST"]),
        Route("/api/v1/relationship-map", relationship_map, methods=["GET"]),
        Route("/api/v1/admin/stats", get_stats, methods=["GET"]),
        Route("/api/v1/admin/graph/export", export_graph, methods=["GET"]),
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
