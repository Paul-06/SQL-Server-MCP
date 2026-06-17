"""
tools/query.py
--------------
Herramienta: execute_query
Ejecuta consultas SELECT parametrizadas contra SQL Server.
Soporta filtros WHERE, columnas simples y expresiones, TOP, DISTINCT,
GROUP BY, HAVING, ORDER BY y paginacion (OFFSET/FETCH o TOP).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from config import get_connection, log_query, rows_to_dicts, settings

logger = logging.getLogger(__name__)

QueryResult = dict[str, Any]

_EXPR_PATTERN = re.compile(
    r"(?:\(|\bAS\b|\bCOUNT\b|\bSUM\b|\bAVG\b|\bMIN\b|\bMAX\b|\*)",
    re.IGNORECASE,
)


def _format_column(col: str) -> str:
    if _EXPR_PATTERN.search(col):
        return col
    return f"[{col}]"


def execute_query(
    table: str,
    schema: str = "dbo",
    columns: Optional[list[str]] = None,
    where: Optional[str] = None,
    where_params: Optional[list[Any]] = None,
    order_by: Optional[str] = None,
    group_by: Optional[str] = None,
    having: Optional[str] = None,
    top: Optional[int] = None,
    distinct: bool = False,
    page: int = 1,
    page_size: int = 100,
    database: Optional[str] = None,
) -> QueryResult:
    """
    Ejecuta un SELECT seguro y parametrizado.

    Parametros
    ----------
    table       : Nombre de la tabla o vista.
    schema      : Schema SQL (default 'dbo').
    columns     : Lista de columnas o expresiones. None = todas (*).
                  Las expresiones con funciones (COUNT, SUM, etc.),
                  AS, parentesis o * se pasan sin brackets automaticamente.
                  Ej: ["COUNT(*) AS Total", "id"]
                  -> "COUNT(*) AS Total, [id]"
    where       : Condicion WHERE SIN el keyword WHERE.
                  Usar '?' como placeholder: "id = ? AND activo = ?"
    where_params: Valores para los placeholders '?' del WHERE.
    order_by    : Columna(s) de ordenamiento, ej: "nombre ASC, fecha DESC".
    group_by    : Columna(s) para GROUP BY, ej: "UNIDAD_MINERA, ESTADO".
    having      : Condicion HAVING (solo con group_by), ej: "COUNT(*) > ?".
    top         : Si se especifica, usa TOP N en vez de paginacion.
                  Ideal para "dame los 5 mas recientes".
    distinct    : Si True, agrega DISTINCT al SELECT.
    page        : Numero de pagina (1-based). Ignorado si top esta definido.
    page_size   : Registros por pagina (max 1000). Ignorado si top esta definido.
    database    : Overridea la base de datos del .env para esta query.

    Retorna
    -------
    Dict con claves: columns, rows, page, page_size, has_more.
    """
    if not settings.is_op_allowed("select"):
        raise PermissionError("La operacion SELECT no esta habilitada en la configuracion.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"El schema '{schema}' no esta en la lista de schemas permitidos.")

    params: list[Any] = list(where_params or [])
    col_clause = ", ".join(_format_column(c) for c in columns) if columns else "*"
    db_prefix = f"[{database}]." if database else ""
    table_ref = f"{db_prefix}[{schema}].[{table}]"

    distinct_kw = "DISTINCT " if distinct else ""
    top_kw = f"TOP {top} " if top else ""

    sql = f"SELECT {distinct_kw}{top_kw}{col_clause} FROM {table_ref}"

    if where:
        sql += f" WHERE {where}"

    if group_by:
        sql += f" GROUP BY {group_by}"

    if having:
        if not group_by:
            raise ValueError("HAVING requiere que se especifique group_by.")
        sql += f" HAVING {having}"

    use_pagination = top is None

    if use_pagination:
        page_size = min(max(1, page_size), 1000)
        offset = (max(1, page) - 1) * page_size

        if order_by:
            sql += f" ORDER BY {order_by}"
        else:
            sql += " ORDER BY (SELECT NULL)"

        sql += f" OFFSET {offset} ROWS FETCH NEXT {page_size + 1} ROWS ONLY"
    elif order_by:
        sql += f" ORDER BY {order_by}"

    log_query(logger, "SELECT", sql, params)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        all_rows = rows_to_dicts(cursor)

    if use_pagination:
        has_more = len(all_rows) > page_size
        rows = all_rows[:page_size]
    else:
        has_more = False
        rows = all_rows

    columns_out = list(rows[0].keys()) if rows else (columns or [])

    return {
        "columns": columns_out,
        "rows": rows,
        "page": page if use_pagination else 1,
        "page_size": page_size if use_pagination else len(rows),
        "has_more": has_more,
    }