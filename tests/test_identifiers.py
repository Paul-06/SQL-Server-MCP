"""Tests for SQL Server identifier validation and quoting."""

from __future__ import annotations

import pytest

from tools._identifiers import quote_identifier


class TestQuoteIdentifier:
    def test_quotes_identifier(self):
        assert quote_identifier("MySchema") == "[MySchema]"

    def test_escapes_closing_bracket(self):
        assert quote_identifier("name]with]brackets") == "[name]]with]]brackets]"

    @pytest.mark.parametrize("value", ["", "   ", "name\x00suffix"])
    def test_rejects_empty_or_nul(self, value):
        with pytest.raises(ValueError):
            quote_identifier(value)

    def test_rejects_identifier_longer_than_sysname(self):
        with pytest.raises(ValueError, match="128"):
            quote_identifier("a" * 129)

    def test_rejects_multipart_identifier(self):
        with pytest.raises(ValueError, match="simple"):
            quote_identifier("database.schema")

    def test_rejects_non_text_identifier(self):
        with pytest.raises(ValueError, match="texto"):
            quote_identifier(123)  # type: ignore[arg-type]
