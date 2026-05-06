"""
Tests for MarkdownChunker and _is_boilerplate.

Covers:
- _is_boilerplate: all 7 known patterns + clean content + case-insensitivity
- chunk(): return contract (type, required keys, char offsets)
- Empty / no-header document handling
- Section splitting at max_tokens boundary
- min_chunk_tokens filter
- context path breadcrumb construction
- is_boilerplate flag propagated to chunk dicts
"""

import pytest
from src.processors.chunker import MarkdownChunker, _is_boilerplate


# ---------------------------------------------------------------------------
# _is_boilerplate
# ---------------------------------------------------------------------------

class TestIsBoilerplate:
    @pytest.mark.parametrize("pattern", [
        "medrxiv preprint doi: 10.1101/2024.01.01",
        "biorxiv preprint doi: 10.1101/abc",
        "This article was not certified by peer review",
        "copyright holder for this preprint (which was not certified)",
        "perpetual embargo on commercial exploitation",
        "All rights reserved. No reuse allowed.",
        "This spraint reputs new tesearch not yet peer reviewed",
    ])
    def test_known_pattern_detected(self, pattern: str) -> None:
        assert _is_boilerplate(pattern) is True

    def test_clean_clinical_content_not_boilerplate(self) -> None:
        text = (
            "Patients were randomly assigned to receive either the experimental drug "
            "or placebo over 24 weeks. The primary endpoint was PFS."
        )
        assert _is_boilerplate(text) is False

    def test_case_insensitive_medrxiv(self) -> None:
        assert _is_boilerplate("MEDRXIV PREPRINT DOI") is True

    def test_case_insensitive_certified(self) -> None:
        assert _is_boilerplate("CERTIFIED BY PEER REVIEW") is True

    def test_empty_string_not_boilerplate(self) -> None:
        assert _is_boilerplate("") is False

    def test_partial_match_is_boilerplate(self) -> None:
        # Pattern must match anywhere in the string (re.search, not re.match)
        assert _is_boilerplate("Header line\nmedrxiv preprint doi: 10.1101/xxx\nBody") is True


# ---------------------------------------------------------------------------
# chunk() return type and key contract
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {"content", "context", "level", "page_number", "is_boilerplate",
                  "char_start", "char_end"}


class TestChunkReturnContract:
    def test_returns_list(self) -> None:
        chunker = MarkdownChunker()
        result = chunker.chunk("# Title\n\nSome content here.")
        assert isinstance(result, list)

    def test_each_element_is_dict(self) -> None:
        chunker = MarkdownChunker()
        result = chunker.chunk("# Title\n\nSome content here.")
        for chunk in result:
            assert isinstance(chunk, dict)

    def test_required_keys_present(self) -> None:
        chunker = MarkdownChunker()
        result = chunker.chunk("# Title\n\nSome content here.")
        for chunk in result:
            assert REQUIRED_KEYS.issubset(set(chunk.keys())), (
                f"Missing keys: {REQUIRED_KEYS - set(chunk.keys())}"
            )

    def test_char_start_and_end_are_integers(self) -> None:
        chunker = MarkdownChunker()
        result = chunker.chunk("# Title\n\nSome content here.")
        for chunk in result:
            assert isinstance(chunk["char_start"], int)
            assert isinstance(chunk["char_end"], int)

    def test_char_end_gte_char_start(self) -> None:
        chunker = MarkdownChunker()
        result = chunker.chunk("# Title\n\nSome content here.")
        for chunk in result:
            assert chunk["char_end"] >= chunk["char_start"]


# ---------------------------------------------------------------------------
# Empty / no-header documents
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string_produces_no_meaningful_content(self) -> None:
        # Chunker may return a chunk with empty content for empty input;
        # ensure any returned chunks have empty/whitespace content only.
        chunker = MarkdownChunker()
        result = chunker.chunk("")
        for chunk in result:
            assert chunk["content"].strip() == ""

    def test_whitespace_only_produces_no_meaningful_content(self) -> None:
        chunker = MarkdownChunker()
        result = chunker.chunk("   \n\n\t  ")
        for chunk in result:
            assert chunk["content"].strip() == ""

    def test_no_header_context_is_empty_string(self) -> None:
        # Text without any markdown headers → _parse_sections creates a section
        # with context_path='' (level=0 header stack is empty).
        chunker = MarkdownChunker()
        result = chunker.chunk("No headers here, just plain text content.")
        assert len(result) >= 1
        assert result[0]["context"] == ""

    def test_single_header_section_produces_chunk(self) -> None:
        chunker = MarkdownChunker()
        result = chunker.chunk("# Introduction\n\nThis is the introduction.")
        assert len(result) >= 1
        assert "Introduction" in result[0]["context"]


# ---------------------------------------------------------------------------
# min_chunk_tokens filter
# ---------------------------------------------------------------------------

class TestMinChunkTokensFilter:
    def test_tiny_chunk_filtered_with_threshold(self) -> None:
        # "Hi" ≈ 0 tokens; min_chunk_tokens=10 should discard it
        chunker = MarkdownChunker(min_chunk_tokens=10)
        result = chunker.chunk("# Title\n\nHi")
        # Either filtered entirely or content must meet threshold
        for chunk in result:
            assert len(chunk["content"]) // 4 >= 10

    def test_zero_threshold_keeps_all_chunks(self) -> None:
        chunker = MarkdownChunker(min_chunk_tokens=0)
        result = chunker.chunk("# Title\n\nHi")
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Context breadcrumb
# ---------------------------------------------------------------------------

class TestContextBreadcrumb:
    def test_h1_context_is_header_name(self) -> None:
        chunker = MarkdownChunker()
        doc = "# Methods\n\nWe enrolled 100 patients."
        result = chunker.chunk(doc)
        assert any("Methods" in c["context"] for c in result)

    def test_h2_context_includes_parent_h1(self) -> None:
        chunker = MarkdownChunker()
        doc = (
            "# Clinical Study\n\n"
            "## Efficacy Results\n\n"
            "The drug showed 50% improvement."
        )
        result = chunker.chunk(doc)
        # The H2 chunk should have a breadcrumb like "Clinical Study > Efficacy Results"
        h2_chunks = [c for c in result if "Efficacy" in c["context"]]
        assert h2_chunks
        assert "Clinical Study" in h2_chunks[0]["context"]
        assert "Efficacy Results" in h2_chunks[0]["context"]

    def test_context_in_content_prefixed(self) -> None:
        chunker = MarkdownChunker()
        doc = "# Background\n\nThe disease affects millions."
        result = chunker.chunk(doc)
        # _build_chunk_with_context prepends "Context: ..."
        assert any("Context:" in c["content"] for c in result)


# ---------------------------------------------------------------------------
# Large section splitting
# ---------------------------------------------------------------------------

class TestLargeSectionSplitting:
    def test_large_section_split_into_multiple_chunks(self) -> None:
        # Build a section with multiple \n\n-separated paragraphs so the
        # paragraph-splitter has natural boundaries to work with.
        # Each paragraph is ~500 chars → ~125 tokens; max_tokens=100 forces a split.
        para = "word " * 100  # 500 chars → 125 tokens
        long_content = "\n\n".join([para] * 10)
        doc = f"# Long Section\n\n{long_content}"
        chunker = MarkdownChunker(max_tokens=100)
        result = chunker.chunk(doc)
        assert len(result) > 1

    def test_small_section_kept_whole(self) -> None:
        doc = "# Short\n\nJust a few words."
        chunker = MarkdownChunker(max_tokens=512)
        result = chunker.chunk(doc)
        # Should be exactly one chunk (small section, no splitting)
        assert len(result) == 1

    def test_split_chunks_all_have_required_keys(self) -> None:
        para = "word " * 100
        long_content = "\n\n".join([para] * 10)
        doc = f"# Long Section\n\n{long_content}"
        chunker = MarkdownChunker(max_tokens=100)
        result = chunker.chunk(doc)
        for chunk in result:
            assert REQUIRED_KEYS.issubset(set(chunk.keys()))


# ---------------------------------------------------------------------------
# is_boilerplate flag in chunk dict
# ---------------------------------------------------------------------------

class TestBoilerplateFlagInChunks:
    def test_clean_chunk_not_flagged(self) -> None:
        chunker = MarkdownChunker()
        doc = "# Methods\n\nPatients enrolled in a randomized controlled trial."
        result = chunker.chunk(doc)
        assert all(not c["is_boilerplate"] for c in result)

    def test_boilerplate_chunk_flagged(self) -> None:
        chunker = MarkdownChunker()
        doc = "# Watermark\n\nmedrxiv preprint doi: 10.1101/2024.01.01.12345"
        result = chunker.chunk(doc)
        assert any(c["is_boilerplate"] for c in result)


# ---------------------------------------------------------------------------
# Multiple sections — ordering and isolation
# ---------------------------------------------------------------------------

class TestMultipleSections:
    def test_two_sections_produce_two_or_more_chunks(self) -> None:
        doc = (
            "# Introduction\n\nThis is the intro.\n\n"
            "# Methods\n\nThis is the methods."
        )
        chunker = MarkdownChunker()
        result = chunker.chunk(doc)
        assert len(result) >= 2

    def test_sections_in_order(self) -> None:
        doc = (
            "# Introduction\n\nIntro content.\n\n"
            "# Methods\n\nMethods content."
        )
        chunker = MarkdownChunker()
        result = chunker.chunk(doc)
        contexts = [c["context"] for c in result]
        intro_idx = next(i for i, ctx in enumerate(contexts) if "Introduction" in ctx)
        methods_idx = next(i for i, ctx in enumerate(contexts) if "Methods" in ctx)
        assert intro_idx < methods_idx
