"""
tools/transaction.py
--------------------
Ejecuta múltiples statements SQL arbitrarios en una sola transacción.
Todas las operaciones se commitean juntas o se revierten por completo.
"""

from __future__ import annotations

import logging
from typing import Any

from config import get_connection, log_query, rows_to_dicts, settings
from tools._database import assert_configured_database

logger = logging.getLogger(__name__)


def execute_transaction(
    statements: list[dict[str, Any]],
    database: str | None = None,
) -> dict[str, Any]:
    """
    Ejecuta una lista de statements SQL en una sola transacción atómica.
    Si alguno falla, TODAS las operaciones se revierten (ROLLBACK).

    Parámetros
    ----------
    statements : Lista de dicts, cada uno con:
                 - "sql": str — Statement T-SQL con placeholders '?'.
                 - "params": list (opcional) — Valores para los '?'.
    database   : Debe omitirse o coincidir con MSSQL_DATABASE.

    Retorna
    -------
    {
      "success": True/False,
      "results": [{"statement": N, "rows_affected": M, "columns": [...], "rows": [...]}, ...],
      "error": "mensaje si falló"
    }
    """
    if not statements:
        return {"success": True, "results": [], "error": None}

    assert_configured_database(database, settings.database)
    results: list[dict[str, Any]] = []

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            for idx, stmt in enumerate(statements):
                sql = stmt["sql"]
                params = stmt.get("params") or []

                log_query(logger, "TRANSACTION", sql, params)
                cursor.execute(sql, params)

                result_entry: dict[str, Any] = {"statement": idx + 1, "rows_affected": cursor.rowcount}

                if cursor.description:
                    result_entry["columns"] = [col[0] for col in cursor.description]
                    result_entry["rows"] = rows_to_dicts(cursor)
                else:
                    result_entry["columns"] = []
                    result_entry["rows"] = []

                results.append(result_entry)

            # get_connection auto-commita al salir del with
    except Exception as exc:
        return {"success": False, "results": results, "error": str(exc)}

    return {"success": True, "results": results, "error": None}
