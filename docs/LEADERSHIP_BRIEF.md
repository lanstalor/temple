# Temple Leadership Brief (1-Page)

Date: `2026-02-11`

## What Temple Is
Temple is a **shared memory and relationship intelligence platform** for AI tools.

It gives multiple assistants (Claude, Copilot, ChatGPT-style clients, internal apps) access to the same long-term organizational context, instead of each tool working from isolated conversation history.

## Why This Matters
Without a shared memory layer:
- context is repeatedly re-explained
- decisions and commitments are lost across tools and time
- outputs are inconsistent between AI systems

With Temple:
- knowledge compounds over time
- stakeholder/project relationships become queryable
- AI outputs become more consistent, explainable, and operationally useful

## End Target State (Business View)
Temple becomes a **digital work brain** that can ingest and reason over:
- email inbox and threads
- documents and notes
- AI conversations
- tickets/CRM/project systems

Then provide cross-tool intelligence such as:
- unresolved commitments and owners
- repeated blockers and risk signals
- relationship maps across people, projects, vendors, and decisions

## Where We Are Today
### Live and Working
- Unified platform supports both `MCP` and `REST` integrations
- Core memory + relationship graph is operational
- Visual graph explorer (`Atlas`) with HTTP Basic Auth gate
- Universal ingest API (`/api/v1/ingest/submit`) — accepts any content type (email, document, chat, meeting note, ticket, note)
- LLM-assisted entity/relation extraction (Claude via Anthropic API) with heuristic fallback
- Background enrichment pipeline with confidence gating and human review queue
- Enrichment state persists across service restarts
- 92 automated tests, 26 MCP tools

### Not Yet at End State
- First-class connectors for inbox/doc/chat ingestion are not yet implemented (API is ready, connectors are next)
- Policy controls and operational dashboards need enterprise hardening
- Stronger entity linking/canonicalization and cross-document dedup

## Recommended Next 90 Days
1. Build highest-value connector first
- inbox ingestion (batch + incremental)
- immediate value for commitment tracking and stakeholder intelligence

2. Improve enrichment quality and governance
- stronger entity linking and cross-document dedup
- configurable confidence thresholds by source/type
- maintain human approval path for uncertain links

3. Operational hardening
- queue/replay controls
- monitoring and alerting for throughput, errors, review backlog
- backup/restore drills and documented runbooks

## Success Criteria (Leadership Metrics)
- Reduced time spent re-establishing context in AI workflows
- Increased consistency of AI outputs across tools
- Measurable capture of commitments, blockers, and stakeholder insights from inbox/document streams
- Demonstrable trust: evidence-backed outputs with review/audit traceability

## Strategic Positioning
Temple is not "another assistant." It is foundational infrastructure:
- a reusable memory layer
- interoperable across vendors
- designed for compounding institutional intelligence over time
