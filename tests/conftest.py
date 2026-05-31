from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def make_mock_cursor(
    rows: list[list[Any]] | None = None,
    columns: list[str] | None = None,
    rowcount: int = 0,
    fetchone_result: list[Any] | None = None,
    nextset_results: list[list[list[Any]] | None] | None = None,
) -> MagicMock:
    cursor = MagicMock()
    if columns:
        cursor.description = [(c, None, None, None, None, None, None) for c in columns]
    else:
        cursor.description = None

    cursor.fetchall.return_value = rows or []
    cursor.rowcount = rowcount
    cursor.fetchone.return_value = fetchone_result

    if nextset_results:
        nextset_iter = iter(nextset_results + [None])
        def nextset_side_effect():
            try:
                val = next(nextset_iter)
                return val
            except StopIteration:
                return None
        cursor.nextset.side_effect = nextset_side_effect
    else:
        cursor.nextset.return_value = None

    return cursor


def make_mock_connection(mock_cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value = mock_cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = None
    return conn


def make_mock_cm(mock_conn: MagicMock) -> MagicMock:
    """Crea un context manager mock que entra en mock_conn."""
    cm = MagicMock()
    cm.__enter__.return_value = mock_conn
    cm.__exit__.return_value = None
    return cm
