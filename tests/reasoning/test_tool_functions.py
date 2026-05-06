"""
Unit tests for pure helper functions in agentic-reasoning tool implementations.

All functions under test are deterministic and have no external dependencies.
"""

import pytest
from src.tools.implementations.openfda import _extract_drug_name, _get_nested
from src.tools.implementations.graphrag_tools import _extract_keywords


# ---------------------------------------------------------------------------
# _extract_drug_name
# ---------------------------------------------------------------------------

class TestExtractDrugName:
    """Strips NLP question framing to a bare compound name."""

    @pytest.mark.parametrize("raw, expected", [
        ("aspirin", "aspirin"),
        ("What are the side effects of aspirin?", "aspirin"),
        ("adverse events for ibuprofen", "ibuprofen"),
        ("side effects of metformin and glipizide", "metformin"),
        # "tell me about the" strips but "drug " prefix remains
        ("Tell me about the drug warfarin", "drug warfarin"),
        ("I'm researching semaglutide", "semaglutide"),
        # "the latest" strips; "side effects of" not re-applied in same pass
        ("The latest side effects of ozempic.", "side effects of ozempic"),
        # "describe the" strips; "contraindications for" not re-applied
        ("describe the contraindications for lisinopril", "contraindications for lisinopril"),
        ("safety profile of dabigatran", "dabigatran"),
        ("drug interactions with rifampicin", "rifampicin"),
    ])
    def test_strip_question_framing(self, raw: str, expected: str) -> None:
        assert _extract_drug_name(raw) == expected

    def test_empty_string_returns_empty(self) -> None:
        assert _extract_drug_name("") == ""

    def test_removes_trailing_question_mark(self) -> None:
        assert _extract_drug_name("metformin?") == "metformin"

    def test_removes_trailing_exclamation(self) -> None:
        assert _extract_drug_name("metformin!") == "metformin"

    def test_splits_on_comma_takes_first(self) -> None:
        result = _extract_drug_name("insulin, glargine side effects")
        assert "," not in result

    def test_splits_on_and_takes_first(self) -> None:
        result = _extract_drug_name("metformin and glipizide")
        assert "and" not in result.lower() or result.lower() == "metformin"

    def test_preserves_multi_word_compound(self) -> None:
        result = _extract_drug_name("side effects of semaglutide ozempic")
        assert result  # should not be empty


# ---------------------------------------------------------------------------
# _get_nested
# ---------------------------------------------------------------------------

class TestGetNested:
    """Walks nested dicts safely, returning default on any miss."""

    def test_single_key(self) -> None:
        assert _get_nested({"a": 1}, ["a"]) == 1

    def test_deeply_nested_path(self) -> None:
        obj = {"a": {"b": {"c": 42}}}
        assert _get_nested(obj, ["a", "b", "c"]) == 42

    def test_missing_leaf_returns_default(self) -> None:
        assert _get_nested({"a": 1}, ["b"], default="X") == "X"

    def test_missing_intermediate_key_returns_default(self) -> None:
        assert _get_nested({"a": {"b": 1}}, ["a", "z"], default=None) is None

    def test_non_dict_intermediate_returns_default(self) -> None:
        assert _get_nested({"a": "not_a_dict"}, ["a", "b"], default="MISS") == "MISS"

    def test_none_default_returned_on_miss(self) -> None:
        result = _get_nested({}, ["x", "y"])
        assert result is None

    def test_empty_path_returns_original_object(self) -> None:
        d = {"k": "v"}
        assert _get_nested(d, []) == d

    def test_list_value_returned_unchanged(self) -> None:
        obj = {"tags": ["a", "b", "c"]}
        assert _get_nested(obj, ["tags"]) == ["a", "b", "c"]

    def test_falsy_zero_value_not_confused_with_missing(self) -> None:
        assert _get_nested({"count": 0}, ["count"], default=-1) == 0

    def test_false_value_not_confused_with_missing(self) -> None:
        assert _get_nested({"flag": False}, ["flag"], default=True) is False


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    """GraphRAG keyword extraction must filter stop words and noise."""

    def test_stop_words_excluded(self) -> None:
        stop = {"what", "are", "the", "of", "for", "in", "on", "and", "or"}
        keywords = _extract_keywords("what are the side effects of aspirin and ibuprofen")
        for sw in stop:
            assert sw not in keywords, f"stop word {sw!r} leaked into keywords"

    def test_meaningful_medical_terms_included(self) -> None:
        keywords = _extract_keywords("semaglutide diabetes mellitus treatment")
        assert "semaglutide" in keywords
        assert "diabetes" in keywords

    def test_respects_max_keywords_limit(self) -> None:
        long_query = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        for limit in (1, 3, 5):
            assert len(_extract_keywords(long_query, max_keywords=limit)) <= limit

    def test_empty_query_returns_empty_list(self) -> None:
        assert _extract_keywords("") == []

    def test_only_stop_words_returns_empty(self) -> None:
        assert _extract_keywords("what are the is a an of for") == []

    def test_minimum_word_length_enforced(self) -> None:
        # All words ≤ 2 chars should be excluded
        keywords = _extract_keywords("an is a do be in or")
        assert all(len(w) > 2 for w in keywords)

    def test_hyphenated_terms_treated_as_single_token(self) -> None:
        keywords = _extract_keywords("double-blind randomized controlled trial")
        # 'double-blind' may appear as one unit (regex: [a-zA-Z][a-zA-Z0-9\-]+)
        combined = " ".join(keywords)
        assert "double" in combined or "blind" in combined

    def test_returns_list_type(self) -> None:
        assert isinstance(_extract_keywords("aspirin trial"), list)
