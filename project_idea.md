# Context-aware memory broker systems for AI agents

**A fully self-hosted, CPU-friendly memory broker for AI agents is not only feasible — it’s becoming a well-trodden path.** The MCP ecosystem exploded in 2024–2025, yielding dozens of persistent memory servers, while projects like Mem0, Letta, and Graphiti have matured into production-grade memory layers. The critical architectural insight is that memory and inference are separable: you can run lightweight memory infrastructure (embeddings, vector search, knowledge graphs) on a CPU-only home server while leveraging cloud LLMs for intelligence. Microsoft’s general availability of MCP support in Copilot Studio  (May 2025)  and preview support in M365 declarative agents  (November 2025)  now creates a viable bridge from self-hosted memory to enterprise AI. This report synthesizes practical implementations, architecture patterns, Unraid deployment strategies, M365 integration paths, and the landscape of open-source memory tools.

-----

## The MCP memory ecosystem has matured rapidly

The Model Context Protocol memory server landscape went from a single reference implementation to over 50 knowledge/memory-focused servers in under 18 months. Three dominant storage patterns have emerged, each with distinct tradeoffs.

**JSONL knowledge graphs** represent the simplest approach. Anthropic’s official MCP memory server stores entities, relations, and observations as line-delimited JSON in a single file. It requires no dependencies beyond Node.js but offers only substring matching — no semantic search. The **mcp-knowledge-graph** project (AIM Memory) extends this pattern with named databases, supporting a master database plus topic-specific databases (work, personal, health) and automatic project detection via `.aim` directories.  This hierarchical JSONL approach suits users who want human-readable, version-controllable memory with minimal infrastructure.

**Vector databases with semantic search** form the most practical middle ground. The standout project is **mcp-memory-service** by doobidoo (852+ stars, Apache 2.0), which uses ChromaDB for vector storage and sentence-transformers for embeddings, with an ONNX-powered lightweight mode that eliminates PyTorch dependencies entirely. It delivers **~5ms retrieval** and **7–16ms quality scoring on CPU**, works across 13+ AI clients, and includes an 8-tab web dashboard with D3.js knowledge graph visualization.  For a fully air-gapped stack, **local-mem0-mcp** combines PostgreSQL with pgvector, Ollama running phi3:mini for inference, and nomic-embed-text for embeddings — zero external API dependencies, deployable with a single `docker compose up`.

**Graph databases with temporal awareness** offer the most sophisticated memory. **Graphiti** (22.3K stars), the engine behind Zep, builds real-time knowledge graphs on Neo4j,  FalkorDB, or Kuzu  with a bi-temporal data model that tracks both when events occurred and when they were ingested.   Its hybrid retrieval combines semantic embeddings, BM25, and graph traversal  — achieving **94.8% accuracy** on the Deep Memory Retrieval benchmark.   Graphiti supports multi-tenancy  via `group_id` namespacing  and incremental updates without batch recomputation.  

**Basic Memory** (basicmachines-co) deserves special mention for its philosophy: all knowledge stored as standard Markdown files on disk, indexed in local SQLite, navigable via `memory://` URLs, and fully compatible with Obsidian. LLMs can both read and write to the knowledge base, making it a bidirectional bridge between human PKM and AI memory.

-----

## CPU-optimized architectures make home deployment viable

The key technical insight for CPU-only deployments is that **embedding generation — not LLM inference — is the primary compute bottleneck** for memory systems, and it’s a much more tractable problem.

For CPU embedding, two models dominate the practical landscape. **all-MiniLM-L6-v2** (22M parameters, 384 dimensions)  delivers 5,000–14,000 sentences per second on CPU, making it ideal for high-throughput, low-latency scenarios.  **BAAI/bge-base-en-v1.5** (110M parameters, 768 dimensions)  offers the best accuracy-speed tradeoff for RAG applications. A surprising benchmark finding: smaller retrieval-optimized models like **e5-small** achieved **100% Top-5 accuracy** in product retrieval benchmarks, outperforming larger 7B+ models due to hubness effects in high-dimensional spaces. 

**INT8 quantization dramatically improves CPU performance.** Intel’s fastRAG framework achieves **up to 10x speedup** for BGE-large embedding indexing when quantized on Xeon CPUs with AVX-512/AMX extensions.  ONNX Runtime INT8 quantization yields **1.5–3x speedup** on commodity CPUs with minimal accuracy loss.  The practical recipe: take bge-base-en-v1.5, apply ONNX INT8 quantization with optimization level 2, and batch process with dynamic shapes. This runs comfortably on a home server CPU.

For vector search at memory-system scale, the choice depends on collection size:

|Scale       |Recommended engine             |Rationale                         |
|------------|-------------------------------|----------------------------------|
|<10K vectors|sqlite-vec or NumPy            |Near-instant, zero setup          |
|10K–100K    |sqlite-vector with quantization|**3.97ms queries**, perfect recall|
|100K–1M     |FAISS IVFFlat or vectorlite    |ANN indices needed; ~10ms queries |
|1M+         |Qdrant single-node             |Persistence, CRUD, filtering      |

**sqlite-vec** (pure C, zero dependencies, SIMD-accelerated) is particularly compelling for embedded deployments — it runs anywhere SQLite runs, including Raspberry Pi.  On the SIFT1M benchmark, FAISS achieves **10ms** query time versus sqlite-vec’s **17ms** for brute-force search.  However, **sqlite-vector** from SQLite.ai with quantization and preload achieves **3.97ms** on 100K vectors with perfect recall — 17x faster than sqlite-vec,  though it carries an Elastic License 2.0.

The hybrid storage pattern that NVIDIA and BlackRock validated achieves **96% factual faithfulness**:  vector DB handles unstructured semantic search, graph DB handles structured relationships, and results merge into unified LLM context.  For a home server, this translates to ChromaDB or sqlite-vec for vectors, plus a lightweight graph like Kuzu or FalkorDB, with JSONL as an append-only audit trail.

-----

## Hierarchical context is the critical design pattern

The most important architectural decision in a memory broker is how to organize hierarchical contexts. The emerging consensus across Google ADK, OpenAI, and AWS converges on a three-tier model with clear precedence rules.

**Global context** (always loaded) contains core identity, universal rules, and user preferences — stored as structured configuration files and persistent vector collections. **Project/domain context** (loaded based on active scope) holds project-specific knowledge, team preferences, and domain vocabulary — stored as scoped vector collections and project-specific graph subgraphs. **Session context** (highest precedence) manages current conversation history, active task state, and session-specific overrides — stored as a rolling buffer with timestamped notes.

Google ADK’s key insight is that **“context is a compiled view over a richer stateful system.”**  The context window gets divided into stable prefixes (system instructions, summaries) and variable suffixes (latest user turn, tool outputs).  Large data objects become **artifacts** — named, versioned objects referenced by handle rather than included in the prompt. 

For conflict resolution, OpenAI’s cookbook pattern establishes clear precedence: the user’s latest message overrides everything, session memory overrides global memory for the current task, and within the same memory tier, the most recent entry by date wins.  Amazon Bedrock AgentCore implements this via hierarchical namespaces (`/org_id/user_id/preferences`) with per-level TTL policies.  

For incremental indexing — critical for a memory system that grows continuously — HNSW indices natively support dynamic insertion.   The practical strategy: use append-only writes with periodic background merges, implement content hashing to skip unchanged documents, and partition by time or category to limit update scope.  For knowledge bases under 100K documents, full re-embedding with a quantized model is often fast enough to run on schedule.

-----

## Unraid deployment requires specific optimizations

Running AI memory infrastructure on Unraid is functional but requires deliberate storage and resource management. The single most impactful optimization: **bypass the FUSE layer** by mapping container paths directly to `/mnt/cache/appdata/<container>` instead of `/mnt/user/appdata/<container>`. This alone can double transfer speeds for the small-file-intensive workloads typical of vector databases and JSONL stores.

For Docker resource management, set explicit limits via Extra Parameters:

```
--memory="4g" --memory-swap="4g" --cpus=1.5
```

Pin all Docker containers to cores 2 through N, leaving core 1 for Unraid OS. Use `--cpu-shares` (default 1024) to prioritize embedding/query services over batch processing jobs. 

**CPU-only Ollama on Unraid is slow but usable for embeddings.** Real users report 10–30+ seconds for simple LLM responses on a Ryzen 5800X, with complex responses taking minutes.   However, embedding generation with small models (nomic-embed-text, all-minilm) is much lighter. A critical finding: **Ollama is ~5x slower than Text Embeddings Inference (TEI)** for embedding workloads — TEI achieved 20ms versus Ollama’s 99ms per request in documented benchmarks.  For embedding-heavy memory systems, TEI or LocalAI (available in Unraid Community Apps, no GPU required) may be significantly better choices. 

Storage architecture for AI workloads on Unraid should use dedicated NVMe cache pools:

- **“AI” pool on NVMe** for vector databases, JSONL files, embedding indexes — set shares to “Cache Only” to prevent the mover from touching these files
- Keep standard appdata on SSD cache for Docker configs
- Use `tmpfs` mounts for log files to reduce SSD write wear 
- Run regular BTRFS Balance and Scrub operations on cache pools 

For backup, the Appdata Backup plugin (Commifreak) stops containers, backs up appdata, and restarts  — adequate for filesystem-level backups but **database-specific dumps are essential** for PostgreSQL/pgvector.  Script `pg_dump` via the User Scripts plugin before filesystem backup.  Implement 3-2-1: local backup to a scratch drive (Unassigned Devices), copy to array, offsite via Borgmatic to Hetzner Storage Box or S3-compatible storage. 

Network access follows a dual pattern adopted by most Unraid users: **Tailscale for personal access** (end-to-end WireGuard encryption, peer-to-peer mesh,  native in Unraid 7) and **Cloudflare Tunnels for any services requiring public exposure** (outbound-only connections,  free tier, WAF integration).  Both have Community Apps templates. For MCP servers specifically, Tailscale’s peer-to-peer mesh offers lower latency for personal use,  while Cloudflare Tunnels with Access authentication gates are necessary if the MCP server needs to receive connections from cloud services.

-----

## M365 Copilot can now connect to self-hosted MCP servers

Microsoft’s MCP integration timeline moved fast: public preview in Copilot Studio in March 2025,  **general availability in May 2025**,  and MCP support in M365 declarative agents announced at Ignite in November 2025 (public preview).  This creates a concrete path from a self-hosted memory broker to enterprise Copilot.

**In Copilot Studio**, MCP servers connect via the Power Platform connector infrastructure.   The simplified flow (as of November 2025): navigate to Tools → Add Tool → New Tool → MCP, specify the server URL,  and configure authentication.  The connector uses Streamable HTTP transport  (SSE was deprecated in August 2025)  with the `x-ms-agentic-protocol: mcp-streamable-1.0` header.  Authentication options include none, API key, and OAuth 2.0.  Dynamic tool discovery means server-side tool changes automatically reflect in Copilot Studio. 

**For M365 declarative agents**, the Microsoft 365 Agents Toolkit in VS Code scaffolds agents that connect to MCP servers.  The process: create a declarative agent, select “Add Action → Start with an MCP server,” enter the URL, and the toolkit auto-generates plugin specs.   Partners like monday.com and Canva have already shipped MCP-based declarative agents. 

The critical infrastructure question for connecting M365 cloud services to a home server has four options:

- **On-Premises Data Gateway**: Microsoft’s supported pattern — creates outbound connections to Azure Service Bus Relay, no inbound ports needed.  Supports Power BI, Power Apps, Power Automate, and Logic Apps. TCP 443 outbound only. 
- **MCP server exposed via Cloudflare Tunnel**: Run your MCP server locally, expose it through a Cloudflare Tunnel with Access authentication, and register the public URL in Copilot Studio.
- **Dev tunnels** (for development): Microsoft’s own tunneling solution for local development and testing. 
- **Custom connectors via Azure API Management**: Centralized API gateway approach for production deployments. 

Enterprise security operates through Microsoft Entra ID with least-privilege access.   **Data separation is enforced architecturally**: M365 Copilot licensed users access shared enterprise data, while non-licensed Copilot Chat users cannot access shared enterprise data.  Sensitivity labels, DLP policies, and compliance controls apply automatically.  For self-hosted MCP servers, the organization assumes responsibility for the tools and data accessed. 

At Ignite 2025, Microsoft also announced **MCP server management in the M365 admin center** (centralized Block/Unblock controls), **Microsoft Entra Agent ID** for automatic agent identity management, and **Agent 365** as a unified control plane for enterprise agent governance. The 2026 roadmap emphasizes multi-agent orchestration, computer use capabilities, and scalable deployment frameworks.

-----

## The memory platform landscape spans from simple to enterprise-grade

The open-source memory platform ecosystem has stratified into clear tiers serving different needs.

**Mem0** (46K+ GitHub stars,  $24M funded)  is the de facto “memory as a service” for AI agents.  Its hybrid architecture combines key-value stores, graph stores, and vector stores,   with an elegant **AUDN cycle** (Add, Update, Delete, No-op) where an LLM decides how to handle each memory candidate rather than relying on brittle rules.  Benchmarks on LOCOMO show **26% higher accuracy** than OpenAI’s built-in memory, with **91% lower latency** and **90% lower token usage** versus full-context approaches.   Self-hosting requires managing vector DB plus graph DB infrastructure; the default uses OpenAI’s API but supports Ollama for fully local operation.  

**Letta** (formerly MemGPT,  21K stars) takes the most innovative architectural approach: treating LLM context as **virtual memory** inspired by operating system memory management.  Core memory (always in prompt, like RAM) contains persona and user info blocks that the agent can self-edit. Archival memory (like disk) uses vector databases for long-term storage. The agent autonomously manages its own memory via tool calls.  The 2025 V1 architecture added sleep-time compute — agents process and consolidate memory while idle. 

**Khoj** (25K stars) occupies the personal AI second brain niche,  with deep integrations into Obsidian, Emacs, WhatsApp, and Android.  It offers semantic search over personal documents  (PDFs, Markdown, Notion, Word),  custom AI agents, and automated research  scheduling. It runs  on consumer hardware with optional GPU acceleration.

**Cognee** (3K stars) focuses on structured knowledge graph generation from documents  via its ECL (Extract, Cognify, Load) pipeline, combining vector stores with graph databases   and supporting RDF-based ontologies for custom schemas.  **txtai** (12K stars) provides a lower-level embeddings database  with unique SQL-over-vectors capability (`SELECT text FROM txtai WHERE similar('query') AND flag = 1`), but lacks automatic memory management — it’s a building block rather than a turnkey memory service.  

The emerging academic concept of **Memory-as-a-Service (MaaS)**, formalized in a June 2025 arXiv paper, proposes decoupling contextual memory from localized state, making it an independently callable, dynamically composable service module.  This mirrors what Mem0 and Zep already offer in practice: portable memory that follows users across AI applications. 

-----

## Conclusion: a practical architecture emerges

The research converges on a concrete reference architecture for a context-aware memory broker on a home server. **The memory layer runs locally** — ONNX-quantized embeddings (bge-base-en-v1.5 at ~40ms per embedding on CPU), sqlite-vec or ChromaDB for vector search, optional Kuzu or FalkorDB for graph relationships, JSONL for audit trails and human-readable persistence. **The intelligence layer stays in the cloud** — cloud LLMs handle memory extraction, context compilation, and user interaction via MCP’s Streamable HTTP transport.

Three design decisions matter most. First, adopt the **three-tier context hierarchy** (global → project → session) with explicit precedence rules, following the pattern validated by Google ADK, OpenAI, and AWS. Second, choose **incremental HNSW indexing** with content hashing to avoid re-processing unchanged documents  — at sub-100K document scale, this keeps index updates under a second. Third, expose the MCP server via **Tailscale for personal access** and **Cloudflare Tunnel with Access authentication for M365 Copilot integration**, maintaining the outbound-only connection model that avoids opening ports on the home network.

The most underappreciated finding is that CPU-only embedding performance is already production-adequate for personal and small-team knowledge bases. With ONNX INT8 quantization, a modern consumer CPU generates embeddings in single-digit milliseconds  and searches 100K vectors in under 4ms.  The bottleneck is not compute — it’s the design work of defining context hierarchies, memory lifecycle policies, and integration patterns that make a memory broker genuinely useful across multiple AI surfaces.
