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
- Visual graph explorer is available (`Atlas`)
- Background enrichment pipeline is running
- Human review queue exists for ambiguous inferred relationships
- Enrichment state persists across service restarts

### Not Yet at End State
- Ingestion model is still named around a narrow "survey" pattern and needs generalization
- First-class connectors for inbox/doc/chat ingestion are not yet implemented
- Extraction quality is currently heuristic and needs stronger NLP/LLM-assisted stages
- Policy controls and operational dashboards need enterprise hardening

## Recommended Next 90 Days
1. Generalize ingest contract
- move from "survey" semantics to source-agnostic ingest item semantics
- keep backward compatibility while transitioning

2. Build highest-value connector first
- inbox ingestion (batch + incremental)
- immediate value for commitment tracking and stakeholder intelligence

3. Improve enrichment quality and governance
- stronger entity linking and relation inference
- configurable confidence thresholds by source/type
- maintain human approval path for uncertain links

4. Operational hardening
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
