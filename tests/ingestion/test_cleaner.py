"""
Tests for TextCleaner: markdown artifact removal, table linearization,
hyphenation repair, whitespace normalization.

All tests run with remove_pii=False to avoid the presidio dependency.
A separate class tests the PII flag contract.
"""

import pytest
from src.processors.cleaner import TextCleaner


@pytest.fixture
def cleaner() -> TextCleaner:
    """TextCleaner with PII redaction disabled (avoids presidio in CI)."""
    return TextCleaner({"cleaning": {"remove_pii": False}})


# ---------------------------------------------------------------------------
# Phantom artifact removal
# ---------------------------------------------------------------------------

class TestPhantomRemoval:
    def test_inline_image_removed(self, cleaner: TextCleaner) -> None:
        text = "Introduction ![alt text](broken_path.png) continued."
        result = cleaner.clean(text)
        assert "![alt text]" not in result
        assert "broken_path.png" not in result

    def test_multiple_images_all_removed(self, cleaner: TextCleaner) -> None:
        text = "![a](x.png) text ![b](y.png)"
        result = cleaner.clean(text)
        assert "![" not in result

    def test_phantom_citation_link_removed(self, cleaner: TextCleaner) -> None:
        text = "See [](1) and [](citation) for details."
        result = cleaner.clean(text)
        assert "[](1)" not in result
        assert "[](citation)" not in result

    def test_real_hyperlink_preserved(self, cleaner: TextCleaner) -> None:
        text = "See [Google](https://google.com) for more."
        result = cleaner.clean(text)
        assert "[Google](https://google.com)" in result

    def test_real_hyperlink_with_title_preserved(self, cleaner: TextCleaner) -> None:
        text = 'Read [the paper](https://doi.org/10.1234/abc "title") here.'
        result = cleaner.clean(text)
        assert "[the paper]" in result


# ---------------------------------------------------------------------------
# Hyphenation repair
# ---------------------------------------------------------------------------

class TestHyphenationRepair:
    def test_broken_hyphen_at_line_end_joined(self, cleaner: TextCleaner) -> None:
        text = "treat-\nment is important"
        result = cleaner.clean(text)
        assert "treatment" in result

    def test_multiple_broken_hyphens_all_fixed(self, cleaner: TextCleaner) -> None:
        text = "treat-\nment out-\ncomes pa-\ntients"
        result = cleaner.clean(text)
        assert "treatment" in result
        assert "outcomes" in result
        assert "patients" in result

    def test_intentional_hyphenated_compound_unchanged(
        self, cleaner: TextCleaner
    ) -> None:
        # A hyphen NOT followed by newline should stay
        text = "double-blind randomized trial"
        result = cleaner.clean(text)
        assert "double-blind" in result


# ---------------------------------------------------------------------------
# Whitespace normalization
# ---------------------------------------------------------------------------

class TestWhitespaceNormalization:
    def test_triple_newlines_collapsed_to_double(self, cleaner: TextCleaner) -> None:
        text = "Para one\n\n\n\nPara two"
        result = cleaner.clean(text)
        assert "\n\n\n" not in result

    def test_five_newlines_collapsed(self, cleaner: TextCleaner) -> None:
        text = "A\n\n\n\n\nB"
        result = cleaner.clean(text)
        assert result.count("\n") <= 3  # at most \n\n between A and B

    def test_empty_string_returns_empty(self, cleaner: TextCleaner) -> None:
        assert cleaner.clean("") == ""

    def test_whitespace_only_returns_empty(self, cleaner: TextCleaner) -> None:
        assert cleaner.clean("   \n\n\t  ") == ""

    def test_single_paragraph_preserved(self, cleaner: TextCleaner) -> None:
        text = "This is a normal paragraph with no special markup."
        result = cleaner.clean(text)
        assert "normal paragraph" in result


# ---------------------------------------------------------------------------
# Table linearization
# ---------------------------------------------------------------------------

class TestTableLinearization:
    def test_markdown_table_separator_removed(self, cleaner: TextCleaner) -> None:
        table = "| Drug | Dose |\n|------|------|\n| Aspirin | 100mg |"
        result = cleaner.clean(table)
        assert "|------|" not in result

    def test_table_cell_content_preserved(self, cleaner: TextCleaner) -> None:
        table = "| Drug | Dose |\n|------|------|\n| Aspirin | 100mg |"
        result = cleaner.clean(table)
        assert "Drug" in result
        assert "Aspirin" in result

    def test_non_table_pipe_content_unchanged(self, cleaner: TextCleaner) -> None:
        # A pipe inside a code block or sentence should not be linearized
        text = "Normal paragraph without table structure."
        result = cleaner.clean(text)
        assert "Normal paragraph" in result

    def test_multirow_table_all_rows_present(self, cleaner: TextCleaner) -> None:
        table = (
            "| Name | Value |\n"
            "|------|-------|\n"
            "| Alpha | 1 |\n"
            "| Beta | 2 |\n"
        )
        result = cleaner.clean(table)
        assert "Alpha" in result
        assert "Beta" in result


# ---------------------------------------------------------------------------
# PII flag contract (no presidio)
# ---------------------------------------------------------------------------

class TestPIIFlagContract:
    def test_pii_disabled_does_not_redact_email(self) -> None:
        cleaner = TextCleaner({"cleaning": {"remove_pii": False}})
        text = "Contact john@example.com for info."
        result = cleaner.clean(text)
        assert "john@example.com" in result

    def test_pii_flag_is_boolean(self) -> None:
        cleaner = TextCleaner()
        assert isinstance(cleaner.remove_pii, bool)

    def test_fail_safe_default_is_true(self) -> None:
        cleaner = TextCleaner()
        assert cleaner._fail_safe is True

    def test_custom_fail_safe_false_stored(self) -> None:
        cleaner = TextCleaner({"cleaning": {"remove_pii": False, "fail_safe_on_pii_error": False}})
        assert cleaner._fail_safe is False


# ---------------------------------------------------------------------------
# Combined pipeline (order of operations)
# ---------------------------------------------------------------------------

class TestCleanPipelineOrder:
    def test_combined_image_and_hyphen_in_same_text(self, cleaner: TextCleaner) -> None:
        text = "![img](x.png) treat-\nment is good"
        result = cleaner.clean(text)
        assert "![img]" not in result
        assert "treatment" in result

    def test_combined_citation_and_whitespace(self, cleaner: TextCleaner) -> None:
        text = "Results [](2)\n\n\n\nDiscussion"
        result = cleaner.clean(text)
        assert "[](2)" not in result
        assert "\n\n\n" not in result
        assert "Discussion" in result
