"""
tools/raw_query.py
------------------
Herramienta: execute_raw_select
Ejecuta consultas SELECT arbitrarias (JOINs, CTEs, subconsultas, funciones
ventana, etc.) con parametrizacion y paginacion OFFSET/FETCH.

A diferencia de execute_query (que opera sobre una sola tabla/vista),
esta herramienta acepta cualquier SELECT con la estructura que necesites.

Seguridad:
- Solo permite sentencias que comiencen con SELECT o WITH ... SELECT
- Bloquea INSERT, UPDATE, DELETE, MERGE, EXEC, CREATE, ALTER, DROP,
  TRUNCATE, GRANT, REVOKE
- Respeta la configuracion de MSSQL_ALLOWED_OPS (requiere "select")
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from config import get_connection, log_query, rows_to_dicts, settings
from tools._database import assert_configured_database

logger = logging.getLogger(__name__)

# ── Validacion de seguridad ──────────────────────────────────────────────────

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|EXEC(?:UTE)?|"
    r"CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_EXEC_PATTERN = re.compile(
    r"^\s*EXEC(?:UTE)?\s+"
    r"(?:(?:\[(?P<schema_br>[^\]]+)\]|(?P<schema_plain>[^.\s\[]+))\s*\.\s*)?"
    r"(?:\[(?P<proc_br>[^\]]+)\]|(?P<proc_plain>[^\s;]+))",
    re.IGNORECASE,
)

_EXEC_PARAM_PATTERN = re.compile(r"@(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=")

_TOP_PATTERN = re.compile(r"\bTOP\b\s+\d+", re.IGNORECASE)


def _build_exec_guidance(sql: str) -> Optional[str]:
    """Construye una sugerencia concreta para usar tool_execute_sp."""
    match = _EXEC_PATTERN.match(sql)
    if not match:
        return None

    schema = match.group("schema_br") or match.group("schema_plain") or "dbo"
    procedure = match.group("proc_br") or match.group("proc_plain")
    param_names = [m.group("name") for m in _EXEC_PARAM_PATTERN.finditer(sql)]

    if param_names:
        params_hint = ", ".join(f'"{name}": ...' for name in param_names)
        return (
            "Detectado EXEC de stored procedure. "
            f"Usa tool_execute_sp(procedure=\"{procedure}\", schema=\"{schema}\", "
            f"params={{ {params_hint} }})."
        )

    return (
        "Detectado EXEC de stored procedure. "
        f"Usa tool_execute_sp(procedure=\"{procedure}\", schema=\"{schema}\")"
        "."
    )


def _validate_sql(sql: str) -> None:
    """
    Valida que sql sea una sentencia SELECT (o WITH...SELECT) segura.
    Lanza PermissionError si detecta algo prohibido.
    """
    stripped = sql.strip()

    clean = re.sub(
        r"^(?:\s*--[^\n]*\n\s*|\s*/\*.*?\*/\s*)*",
        "",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if not clean:
        raise PermissionError("SQL vacio.")

    exec_guidance = _build_exec_guidance(clean)
    if exec_guidance:
        raise PermissionError(exec_guidance)

    if _FORBIDDEN_KEYWORDS.search(clean):
        raise PermissionError(
            "La sentencia contiene operaciones no permitidas "
            "(INSERT/UPDATE/DELETE/MERGE/EXEC/DDL). "
            "Solo se permiten SELECTs."
        )

    if not re.match(r"^\s*(?:WITH|SELECT)\s", clean, re.IGNORECASE):
        raise PermissionError(
            "Solo se permiten sentencias SELECT (o WITH ... SELECT). "
            "Bloqueado: no comienza con SELECT/WITH."
        )


# ── Logica principal ──────────────────────────────────────────────────────────


def execute_raw_select(
    sql: str,
    params: Optional[list[Any]] = None,
    page: int = 1,
    page_size: int = 100,
    database: Optional[str] = None,
    paginate: bool = True,
) -> dict[str, Any]:
    """
    Ejecuta un SELECT arbitrario y seguro con paginacion opcional.

    Parametros
    ----------
    sql       : Sentencia SELECT completa con '?' como placeholders.
                Ej: "SELECT o.*, c.Name FROM Orders o JOIN Customers c
                     ON o.CustomerID = c.CustomerID WHERE o.Status = ?"
    params    : Lista de valores para los placeholders '?' (opcional).
    page      : Numero de pagina (1-based). Default 1.
    page_size : Filas por pagina (max 1000). Default 100.
    database  : Debe omitirse o coincidir con MSSQL_DATABASE.
    paginate  : Si True (default), inyecta OFFSET/FETCH para paginacion.
                Se desactiva automaticamente si el SQL ya contiene TOP.
                Pasa False si tu query ya tiene su propio TOP o no necesita
                paginacion.

    Retorna
    -------
    {
      "columns"  : list[str],
      "rows"     : list[dict],
      "page"     : int,
      "page_size": int,
      "has_more" : bool
    }
    """
    if not settings.is_op_allowed("select"):
        raise PermissionError(
            "La operacion SELECT no esta habilitada en la configuracion."
        )

    _validate_sql(sql)
    assert_configured_database(database, settings.database)

    params = params or []
    sql_clean = sql.rstrip().rstrip(";").strip()

    has_top = bool(_TOP_PATTERN.search(sql_clean))
    use_pagination = paginate and not has_top

    if use_pagination:
        page_size = min(max(1, page_size), 1000)
        offset = (max(1, page) - 1) * page_size

        has_order_by = bool(
            re.search(r"\bORDER\s+BY\s", sql_clean, re.IGNORECASE)
        )
        if has_order_by:
            pagination = (
                f" OFFSET {offset} ROWS FETCH NEXT {page_size + 1} ROWS ONLY"
            )
        else:
            pagination = (
                f" ORDER BY (SELECT NULL)"
                f" OFFSET {offset} ROWS FETCH NEXT {page_size + 1} ROWS ONLY"
            )

        final_sql = f"{sql_clean}{pagination}"
    else:
        final_sql = sql_clean

    log_query(logger, "RAW SELECT", final_sql, params)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(final_sql, params)
        all_rows = rows_to_dicts(cursor)

    if use_pagination:
        has_more = len(all_rows) > page_size
        rows = all_rows[:page_size]
        result_page = page
        result_page_size = page_size
    else:
        has_more = False
        rows = all_rows
        result_page = 1
        result_page_size = len(rows)

    columns_out = list(rows[0].keys()) if rows else []

    return {
        "columns": columns_out,
        "rows": rows,
        "page": result_page,
        "page_size": result_page_size,
        "has_more": has_more,
    }
