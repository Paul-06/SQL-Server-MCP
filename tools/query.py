"""
tools/query.py
--------------
Herramienta: execute_query
Ejecuta consultas SELECT parametrizadas contra SQL Server.
Soporta filtros WHERE, columnas específicas, ORDER BY y paginación (OFFSET/FETCH).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import get_connection, log_query, rows_to_dicts, settings

logger = logging.getLogger(__name__)

# ── Tipos de retorno ──────────────────────────────────────────────────────────

QueryResult = dict[str, Any]  # {"columns": [...], "rows": [...], "total": int}


# ── Lógica principal ──────────────────────────────────────────────────────────

def execute_query(
    table: str,
    schema: str = "dbo",
    columns: Optional[list[str]] = None,
    where: Optional[str] = None,
    where_params: Optional[list[Any]] = None,
    order_by: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
    database: Optional[str] = None,
) -> QueryResult:
    """
    Ejecuta un SELECT seguro y parametrizado.

    Parámetros
    ----------
    table       : Nombre de la tabla o vista.
    schema      : Schema SQL (default 'dbo').
    columns     : Lista de columnas a seleccionar. None = todas (*).
    where       : Condición WHERE en T-SQL, SIN el keyword WHERE.
                  Usar '?' como placeholder: "id = ? AND activo = ?"
    where_params: Valores para los placeholders '?' del WHERE.
    order_by    : Columna(s) de ordenamiento, ej: "nombre ASC, fecha DESC".
    page        : Número de página (1-based).
    page_size   : Registros por página (máx 1000).
    database    : Overridea la base de datos del .env para esta query.

    Retorna
    -------
    Dict con claves: columns, rows, page, page_size, has_more.
    """
    if not settings.is_op_allowed("select"):
        raise PermissionError("La operación SELECT no está habilitada en la configuración.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"El schema '{schema}' no está en la lista de schemas permitidos.")

    page_size = min(max(1, page_size), 1000)
    offset = (max(1, page) - 1) * page_size

    col_clause = ", ".join(f"[{c}]" for c in columns) if columns else "*"
    db_prefix = f"[{database}]." if database else ""
    base_sql = f"SELECT {col_clause} FROM {db_prefix}[{schema}].[{table}]"

    params: list[Any] = list(where_params or [])

    if where:
        base_sql += f" WHERE {where}"

    if order_by:
        base_sql += f" ORDER BY {order_by}"
    else:
        # OFFSET requiere ORDER BY en T-SQL
        base_sql += " ORDER BY (SELECT NULL)"

    base_sql += f" OFFSET {offset} ROWS FETCH NEXT {page_size + 1} ROWS ONLY"

    log_query(logger, "SELECT", base_sql, params)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(base_sql, params)
        all_rows = rows_to_dicts(cursor)

    has_more = len(all_rows) > page_size
    rows = all_rows[:page_size]
    columns_out = list(rows[0].keys()) if rows else (columns or [])

    return {
        "columns": columns_out,
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
    }
