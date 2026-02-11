# Temple Visuals

This file centralizes diagram views of Temple's architecture, auth model, and data flow.

## 1) Platform Topology

```mermaid
flowchart LR
    subgraph Clients["Agent and App Ecosystem"]
        A1["Claude Code / Claude Desktop / Claude.ai"]
        A2["M365 Copilot / Copilot Studio"]
        A3["ChatGPT Actions / SDK Apps"]
    end

    CF["Cloudflare Tunnel"] --> APP["Temple Combined Runtime :8100"]
    A1 -->|MCP| APP
    A2 -->|MCP| APP
    A3 -->|REST| APP

    APP --> V["ChromaDB (vector)"]
    APP --> G["Kuzu (graph)"]
    APP --> L["Audit JSONL"]
```

## 2) Retrieval Path

```mermaid
flowchart TD
    Q["User/Agent Query"] --> E["Embed query (ONNX)"]
    E --> S["Resolve active scopes"]
    S --> SG["global"]
    S --> SP["project:*"]
    S --> SS["session:*"]
    SG --> R["Vector + graph retrieval"]
    SP --> R
    SS --> R
    R --> M["Merge + rank"]
    M --> O["Return context payload"]
```

Ranking priority: `session > project > global`, then relevance score.

## 3) Memory Write Path

```mermaid
sequenceDiagram
    participant C as Client
    participant T as Temple
    participant V as ChromaDB
    participant G as Kuzu
    participant A as Audit Log

    C->>T: store_memory(content, tags, scope)
    T->>T: hash + dedup check
    T->>T: embed content
    T->>V: upsert vector + metadata
    T->>A: append store event
    T-->>C: MemoryEntry
```

## 4) OAuth Discovery Map

```mermaid
flowchart TD
    C["OAuth-capable MCP Client"] --> D1["/.well-known/oauth-authorization-server"]
    C --> D2["/.well-known/oauth-protected-resource/mcp"]
    C --> D3["/.well-known/oauth-protected-resource (compat)"]
    C --> D4["/mcp/.well-known/oauth-protected-resource (compat alias)"]

    D1 --> M["Auth metadata"]
    D2 --> M
    D3 --> M
    D4 --> M

    M --> P["Protected resource: /mcp"]
```

## 5) Graph Explorer Surface

```mermaid
flowchart LR
    UI["/atlas (Temple Atlas UI)"] --> X["GET /api/v1/admin/graph/export"]
    X --> B["MemoryBroker.export_knowledge_graph()"]
    B --> GS["GraphStore.search_entities + get_relations"]
    GS --> UI
```

Use `/atlas` for interactive drill-down, scope filtering, and cross-linked relation inspection.
