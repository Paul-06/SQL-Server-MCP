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


def make_scripted_cursor(executions: list[dict[str, Any]]) -> MagicMock:
    """Simula un cursor con múltiples execute() y nextset() programados."""
    cursor = MagicMock()
    state: dict[str, Any] = {
        "current_rows": [],
        "nextsets": [],
    }

    def apply_result(result: dict[str, Any] | None) -> None:
        if not result:
            cursor.description = None
            state["current_rows"] = []
            return

        columns = result.get("columns")
        cursor.description = (
            [(c, None, None, None, None, None, None) for c in columns]
            if columns else None
        )
        state["current_rows"] = result.get("rows", [])

    def execute_side(sql, params=None):
        if not executions:
            raise AssertionError(f"execute() inesperado: {sql!r}")
        current = executions.pop(0)
        apply_result(current)
        state["nextsets"] = list(current.get("nextsets", []))
        return cursor

    def fetchall_side():
        return state["current_rows"]

    def nextset_side():
        if not state["nextsets"]:
            cursor.description = None
            state["current_rows"] = []
            return None

        next_result = state["nextsets"].pop(0)
        apply_result(next_result)
        return True

    cursor.execute.side_effect = execute_side
    cursor.fetchall.side_effect = fetchall_side
    cursor.nextset.side_effect = nextset_side
    cursor.description = None
    return cursor
