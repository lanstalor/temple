"""Tests for LLM-powered and heuristic entity/relation extraction."""

from unittest.mock import MagicMock, patch

import pytest

from temple.config import Settings
from temple.memory.llm_extractor import (
    ExtractionResult,
    _extract_entity_candidates,
    _extract_with_heuristics,
    _infer_entity_type,
    _infer_relation_candidates,
    _normalize_entity_name,
    _parse_llm_json,
    _validate_entities,
    _validate_relations,
    extract,
)


# ── Heuristic extraction tests ─────────────────────────────────────


def test_heuristic_extraction_basic():
    """Heuristic extraction finds proper nouns and infers relations."""
    result = _extract_with_heuristics(
        "I work with Alice Johnson and use Azure daily.",
        "lance",
    )
    assert result.extraction_method == "heuristic"
    assert result.llm_error is None
    entity_names = [e["name"] for e in result.entities]
    assert "Lance" in entity_names
    assert "Alice Johnson" in entity_names


def test_heuristic_extraction_respondent_added():
    """Actor is added as entity if not already extracted."""
    result = _extract_with_heuristics("no proper nouns here at all", "bob")
    entity_names = [e["name"] for e in result.entities]
    assert "Bob" in entity_names


def test_extract_entity_candidates():
    """Regex extracts proper nouns and acronyms."""
    candidates = _extract_entity_candidates(
        "Alice Smith works at NASA with Bob Jones on the SCADA project."
    )
    assert "Alice Smith" in candidates
    assert "NASA" in candidates
    assert "Bob Jones" in candidates
    assert "SCADA" in candidates


def test_extract_entity_candidates_blocks_common_words():
    """Common English words are blocked from entity extraction."""
    candidates = _extract_entity_candidates("The quick brown Fox")
    assert "The" not in candidates
    assert "Fox" in candidates


def test_infer_relation_candidates_collaborates():
    """Keyword 'work with' triggers collaborates_with."""
    candidates = _infer_relation_candidates(
        "I work with Temple on deployment.",
        "Lance",
        ["Lance", "Temple"],
    )
    assert len(candidates) == 1
    assert candidates[0]["relation_type"] == "collaborates_with"
    assert candidates[0]["confidence"] >= 0.80


def test_infer_relation_candidates_uses():
    """Keyword 'use' triggers uses relation."""
    candidates = _infer_relation_candidates(
        "I use Docker for everything.",
        "Lance",
        ["Lance", "Docker"],
    )
    assert len(candidates) == 1
    assert candidates[0]["relation_type"] == "uses"


def test_infer_relation_candidates_default():
    """No keywords → related_to with lower confidence."""
    candidates = _infer_relation_candidates(
        "Something about Alice.",
        "Bob",
        ["Bob", "Alice"],
    )
    assert candidates[0]["relation_type"] == "related_to"
    assert candidates[0]["confidence"] < 0.70


def test_normalize_entity_name():
    """Name normalization handles various cases."""
    assert _normalize_entity_name("alice smith") == "Alice Smith"
    assert _normalize_entity_name("  spaces  ") == "Spaces"
    assert _normalize_entity_name("NASA") == "NASA"
    assert _normalize_entity_name("") == ""


def test_infer_entity_type():
    """Entity type inference from token shape."""
    assert _infer_entity_type("Alice Smith") == "person"
    assert _infer_entity_type("NASA") == "technology"
    assert _infer_entity_type("Docker") == "concept"


# ── LLM JSON parsing tests ─────────────────────────────────────────


def test_parse_llm_json_plain():
    """Parse plain JSON response."""
    result = _parse_llm_json('{"entities": [], "relations": []}')
    assert result == {"entities": [], "relations": []}


def test_parse_llm_json_markdown_fenced():
    """Parse JSON wrapped in markdown code fences."""
    raw = '```json\n{"entities": [{"name": "X", "type": "person", "confidence": 0.9}], "relations": []}\n```'
    result = _parse_llm_json(raw)
    assert len(result["entities"]) == 1
    assert result["entities"][0]["name"] == "X"


def test_parse_llm_json_invalid():
    """Invalid JSON raises an error."""
    with pytest.raises(Exception):
        _parse_llm_json("not json at all")


# ── Validation tests ────────────────────────────────────────────────


def test_validate_entities_normalizes():
    """Entity validation normalizes types and clamps confidence."""
    raw = [
        {"name": "Alice", "type": "person", "confidence": 0.95},
        {"name": "Foo", "type": "invalid_type", "confidence": 1.5},
        {"name": "Alice", "type": "person", "confidence": 0.8},  # duplicate
        {"not_a_valid": "entry"},
    ]
    valid = _validate_entities(raw)
    assert len(valid) == 2
    assert valid[0]["name"] == "Alice"
    assert valid[0]["type"] == "person"
    assert valid[1]["name"] == "Foo"
    assert valid[1]["type"] == "concept"  # invalid → concept
    assert valid[1]["confidence"] == 1.0  # clamped


def test_validate_relations_filters_invalid():
    """Relation validation filters out invalid entries."""
    entities = [
        {"name": "A", "type": "person", "confidence": 0.9},
        {"name": "B", "type": "person", "confidence": 0.9},
    ]
    raw = [
        {"source": "A", "target": "B", "type": "works_with", "confidence": 0.85},
        {"source": "A", "target": "A", "type": "works_with", "confidence": 0.85},  # self-ref
        {"source": "A", "target": "C", "type": "works_with", "confidence": 0.85},  # C not in entities
        {"source": "A", "target": "B", "type": "bad_type", "confidence": 0.85},  # bad type
    ]
    valid = _validate_relations(raw, entities)
    assert len(valid) == 2
    assert valid[0]["type"] == "works_with"
    assert valid[1]["type"] == "related_to"  # bad_type → related_to


# ── Integration: extract() dispatcher ───────────────────────────────


def test_extract_uses_heuristics_when_no_key():
    """extract() uses heuristics when no LLM key is set."""
    settings = Settings(
        chroma_mode="embedded",
        llm_api_key="",
    )
    result = extract("Alice works with Bob on Temple.", "lance", settings)
    assert result.extraction_method == "heuristic"
    assert result.llm_error is None


def test_extract_falls_back_on_llm_failure():
    """extract() falls back to heuristics when LLM call fails."""
    settings = Settings(
        chroma_mode="embedded",
        llm_api_key="fake-key-for-testing",
    )
    with patch("temple.memory.llm_extractor._extract_with_llm", side_effect=RuntimeError("API error")):
        result = extract("Alice works with Bob on Temple.", "lance", settings)
    assert result.extraction_method == "heuristic"
    assert result.llm_error == "API error"


def test_extract_with_mocked_llm():
    """extract() uses LLM path when key is set and API succeeds."""
    settings = Settings(
        chroma_mode="embedded",
        llm_api_key="fake-key-for-testing",
    )
    mock_result = ExtractionResult(
        entities=[
            {"name": "Alice", "type": "person", "confidence": 0.95},
            {"name": "Temple", "type": "project", "confidence": 0.90},
        ],
        relations=[
            {"source": "Alice", "target": "Temple", "type": "uses", "confidence": 0.88},
        ],
        extraction_method="llm",
        llm_usage={"input_tokens": 100, "output_tokens": 50},
    )
    with patch("temple.memory.llm_extractor._extract_with_llm", return_value=mock_result):
        result = extract("Alice uses Temple for memory.", "lance", settings)
    assert result.extraction_method == "llm"
    assert len(result.entities) == 2
    assert len(result.relations) == 1
    assert result.llm_usage is not None
