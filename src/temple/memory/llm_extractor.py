"""Entity and relation extraction — LLM-powered with heuristic fallback."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from temple.config import Settings

logger = logging.getLogger(__name__)

_ENTITY_TYPES = ["person", "organization", "technology", "project", "concept", "location"]
_RELATION_TYPES = [
    "works_with", "uses", "manages", "blocked_by", "interested_in",
    "mentors", "collaborates_with", "related_to", "reports_to",
    "depends_on", "owns", "created", "supports",
]

_SYSTEM_PROMPT = f"""\
You are an entity and relation extractor. Given a text payload, extract structured entities and relations.

Return ONLY valid JSON (no markdown fences) with this exact schema:
{{
  "entities": [
    {{"name": "string", "type": "string", "confidence": 0.0}}
  ],
  "relations": [
    {{"source": "string", "target": "string", "type": "string", "confidence": 0.0}}
  ]
}}

Entity type must be one of: {", ".join(_ENTITY_TYPES)}
Relation type must be one of: {", ".join(_RELATION_TYPES)}
Confidence is a float between 0.0 and 1.0.

Rules:
- Extract real named entities, not generic nouns or pronouns.
- Normalize names to title case (except all-caps acronyms).
- For each relation, both source and target must appear in the entities list.
- Assign confidence based on how explicitly the text supports the extraction.
- If no entities or relations are found, return empty lists.
"""


@dataclass
class ExtractionResult:
    """Result of entity/relation extraction from text."""

    entities: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    extraction_method: str = "heuristic"
    llm_error: str | None = None
    llm_usage: dict[str, Any] | None = None


def extract(text: str, actor_id: str, settings: Settings) -> ExtractionResult:
    """Extract entities and relations from text.

    Uses LLM when configured (TEMPLE_LLM_API_KEY), falls back to heuristics.
    """
    if settings.llm_api_key:
        try:
            return _extract_with_llm(text, actor_id, settings)
        except Exception as exc:
            logger.warning("LLM extraction failed, falling back to heuristics: %s", exc)
            result = _extract_with_heuristics(text, actor_id)
            result.llm_error = str(exc)
            return result
    return _extract_with_heuristics(text, actor_id)


def _extract_with_llm(text: str, actor_id: str, settings: Settings) -> ExtractionResult:
    """Call Anthropic API for structured extraction."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package is required for LLM extraction. "
            "Install with: uv sync --extra llm"
        )

    client = anthropic.Anthropic(api_key=settings.llm_api_key)
    message = client.messages.create(
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )

    raw_text = message.content[0].text
    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }

    parsed = _parse_llm_json(raw_text)
    entities = _validate_entities(parsed.get("entities", []))
    relations = _validate_relations(parsed.get("relations", []), entities)

    # Ensure actor is present as an entity
    actor_normalized = _normalize_entity_name(actor_id)
    actor_names = {e["name"] for e in entities}
    if actor_normalized and actor_normalized not in actor_names:
        entities.insert(0, {
            "name": actor_normalized,
            "type": _infer_entity_type(actor_normalized),
            "confidence": 1.0,
        })

    return ExtractionResult(
        entities=entities,
        relations=relations,
        extraction_method="llm",
        llm_usage=usage,
    )


def _extract_with_heuristics(text: str, actor_id: str) -> ExtractionResult:
    """Heuristic extraction using regex and keyword matching."""
    respondent = _normalize_entity_name(actor_id)
    entity_names = _extract_entity_candidates(text)
    if respondent and respondent not in entity_names:
        entity_names.insert(0, respondent)

    entities = [
        {"name": name, "type": _infer_entity_type(name), "confidence": 0.7}
        for name in entity_names
    ]

    relation_candidates = _infer_relation_candidates(
        text=text,
        respondent=respondent,
        entities=entity_names,
    )
    relations = [
        {
            "source": c["source"],
            "target": c["target"],
            "type": c["relation_type"],
            "confidence": c["confidence"],
        }
        for c in relation_candidates
    ]

    return ExtractionResult(
        entities=entities,
        relations=relations,
        extraction_method="heuristic",
    )


# ── LLM response parsing helpers ────────────────────────────────────


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Parse JSON from LLM response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        # Strip markdown code fence
        lines = text.split("\n")
        lines = lines[1:]  # skip opening ```json or ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def _validate_entities(raw: list[Any]) -> list[dict[str, Any]]:
    """Validate and normalize entity list from LLM output."""
    valid = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        etype = str(item.get("type", "concept"))
        if etype not in _ENTITY_TYPES:
            etype = "concept"
        confidence = item.get("confidence", 0.7)
        if not isinstance(confidence, (int, float)):
            confidence = 0.7
        confidence = max(0.0, min(1.0, float(confidence)))
        valid.append({"name": name, "type": etype, "confidence": confidence})
    return valid


def _validate_relations(
    raw: list[Any], entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Validate and normalize relation list from LLM output."""
    entity_names = {e["name"] for e in entities}
    valid = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        rtype = str(item.get("type", "related_to"))
        if rtype not in _RELATION_TYPES:
            rtype = "related_to"
        if not source or not target or source == target:
            continue
        if source not in entity_names or target not in entity_names:
            continue
        confidence = item.get("confidence", 0.7)
        if not isinstance(confidence, (int, float)):
            confidence = 0.7
        confidence = max(0.0, min(1.0, float(confidence)))
        valid.append({
            "source": source,
            "target": target,
            "type": rtype,
            "confidence": confidence,
        })
    return valid


# ── Heuristic helpers (moved from broker.py) ─────────────────────────


def _extract_entity_candidates(text: str) -> list[str]:
    """Extract likely entity names from text using regex."""
    proper = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text)
    acronyms = re.findall(r"\b[A-Z]{2,}(?:[0-9]+)?\b", text)
    blocked = {
        "I", "We", "The", "This", "That", "And", "But", "For", "With",
        "You", "Your", "Our", "It", "MCP", "REST", "API",
    }

    candidates: list[str] = []
    seen: set[str] = set()
    for raw in proper + acronyms:
        name = _normalize_entity_name(raw)
        if not name or name in blocked:
            continue
        if name in seen:
            continue
        seen.add(name)
        candidates.append(name)
    return candidates[:25]


def _infer_relation_candidates(
    text: str,
    respondent: str,
    entities: list[str],
) -> list[dict[str, Any]]:
    """Infer candidate relations from text using keyword heuristics."""
    lower = text.lower()
    relation_type = "related_to"
    confidence = 0.62
    if any(k in lower for k in ["work with", "works with", "collaborat", "partner"]):
        relation_type, confidence = "collaborates_with", 0.86
    elif any(k in lower for k in ["mentor", "coaching"]):
        relation_type, confidence = "mentors", 0.84
    elif any(k in lower for k in ["blocked by", "blocker", "obstacle", "dependency"]):
        relation_type, confidence = "blocked_by", 0.81
    elif any(k in lower for k in ["use ", "using ", "tool", "platform"]):
        relation_type, confidence = "uses", 0.82
    elif any(k in lower for k in ["interested in", "want to learn", "goal"]):
        relation_type, confidence = "interested_in", 0.78

    candidates: list[dict[str, Any]] = []
    for entity in entities:
        if entity == respondent:
            continue
        candidates.append({
            "source": respondent,
            "target": entity,
            "relation_type": relation_type,
            "confidence": confidence,
        })
    return candidates[:50]


def _normalize_entity_name(value: str) -> str:
    """Normalize an entity string for graph writes."""
    compact = " ".join(value.strip().split())
    if not compact:
        return compact
    if compact.isupper():
        return compact
    return " ".join(part.capitalize() for part in compact.split(" "))


def _infer_entity_type(name: str) -> str:
    """Infer a coarse entity type from token shape."""
    if " " in name and name[0].isupper():
        return "person"
    if name.isupper():
        return "technology"
    return "concept"
