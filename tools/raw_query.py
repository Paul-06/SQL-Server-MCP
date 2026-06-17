"""
tools/raw_query.py
------------------
Herramienta: execute_raw_select
Ejecuta consultas SELECT arbitrarias (JOINs, CTEs, subconsultas, funciones
ventana, etc.) con parametrización y paginación OFFSET/FETCH.

A diferencia de execute_query (que opera sobre una sola tabla/vista),
esta herramienta acepta cualquier SELECT con la estructura que necesites.

Seguridad:
- Solo permite sentencias que comiencen con SELECT o WITH ... SELECT
- Bloquea INSERT, UPDATE, DELETE, MERGE, EXEC, CREATE, ALTER, DROP,
  TRUNCATE, GRANT, REVOKE
- Respeta la configuración de MSSQL_ALLOWED_OPS (requiere "select")
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from config import get_connection, log_query, rows_to_dicts, settings

logger = logging.getLogger(__name__)

# ── Validación de seguridad ───────────────────────────────────────────────────

# Patrones prohibidos en el statement completo
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

    # Remover comentarios del inicio para ver el primer keyword real
    clean = re.sub(
        r"^(?:\s*--[^\n]*\n\s*|\s*/\*.*?\*/\s*)*",
        "",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if not clean:
        raise PermissionError("SQL vacío.")

    exec_guidance = _build_exec_guidance(clean)
    if exec_guidance:
        raise PermissionError(exec_guidance)

    # Bloquear keywords de escritura en todo el statement
    if _FORBIDDEN_KEYWORDS.search(clean):
        raise PermissionError(
            "La sentencia contiene operaciones no permitidas "
            "(INSERT/UPDATE/DELETE/MERGE/EXEC/DDL). "
            "Solo se permiten SELECTs."
        )

    # Verificar que comience con SELECT o WITH
    if not re.match(r"^\s*(?:WITH|SELECT)\s", clean, re.IGNORECASE):
        raise PermissionError(
            "Solo se permiten sentencias SELECT (o WITH ... SELECT). "
            "Bloqueado: no comienza con SELECT/WITH."
        )


# ── Lógica principal ──────────────────────────────────────────────────────────


def execute_raw_select(
    sql: str,
    params: Optional[list[Any]] = None,
    page: int = 1,
    page_size: int = 100,
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Ejecuta un SELECT arbitrario y seguro con paginación opcional.

    Parámetros
    ----------
    sql       : Sentencia SELECT completa con '?' como placeholders.
                Ej: "SELECT o.*, c.Name FROM Orders o JOIN Customers c
                     ON o.CustomerID = c.CustomerID WHERE o.Status = ?"
    params    : Lista de valores para los placeholders '?' (opcional).
    page      : Número de página (1-based). Default 1.
    page_size : Filas por página (máx 1000). Default 100.
    database  : Overridea la base de datos del .env (opcional).

    Retorna
    -------
    {
      "columns"  : list[str],       ← nombres de columnas
      "rows"     : list[dict],      ← filas como dicts
      "page"     : int,
      "page_size": int,
      "has_more" : bool             ← True si hay más páginas
    }
    """
    if not settings.is_op_allowed("select"):
        raise PermissionError(
            "La operación SELECT no está habilitada en la configuración."
        )

    _validate_sql(sql)

    params = params or []
    page_size = min(max(1, page_size), 1000)
    offset = (max(1, page) - 1) * page_size

    db_prefix = f"USE [{database}];\n" if database else ""
    sql_clean = sql.rstrip().rstrip(";").strip()

    # Agregar paginación OFFSET/FETCH
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

    final_sql = f"{db_prefix}{sql_clean}{pagination}"

    log_query(logger, "RAW SELECT", final_sql, params)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(final_sql, params)
        all_rows = rows_to_dicts(cursor)

    has_more = len(all_rows) > page_size
    rows = all_rows[:page_size]
    columns_out = list(rows[0].keys()) if rows else []

    return {
        "columns": columns_out,
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }
