"""
tools/ddl.py
------------
Herramientas DDL: create_table, alter_table, execute_ddl_raw.
Permiten crear y modificar esquemas directamente desde el agente de IA,
con las guardas de seguridad configuradas en el .env.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from config import get_connection, log_query, settings

logger = logging.getLogger(__name__)

# Palabras clave DDL peligrosas que requieren confirmación explícita
_DESTRUCTIVE_KEYWORDS = re.compile(
    r"\b(DROP|TRUNCATE|ALTER\s+TABLE.*DROP)\b", re.IGNORECASE
)


# ── CREATE TABLE ──────────────────────────────────────────────────────────────

def create_table(
    table: str,
    columns: list[dict[str, Any]],
    schema: str = "dbo",
    database: Optional[str] = None,
    if_not_exists: bool = True,
) -> dict[str, Any]:
    """
    Crea una tabla nueva en SQL Server.

    Parámetros
    ----------
    table         : Nombre de la tabla a crear.
    columns       : Lista de dicts que definen cada columna:
                    {
                      "name"       : "id",           # requerido
                      "type"       : "INT",          # requerido (T-SQL type)
                      "nullable"   : False,          # default True
                      "default"    : None,           # valor DEFAULT (opcional)
                      "primary_key": True,           # default False
                      "identity"   : True,           # IDENTITY(1,1) si True
                    }
    schema        : Schema SQL (default 'dbo').
    database      : Overridea la base de datos del .env.
    if_not_exists : Si True, usa IF NOT EXISTS para no romper en re-ejecución.

    Retorna
    -------
    {"created": True, "table": "<schema>.<table>", "ddl": "<SQL ejecutado>"}
    """
    if not settings.is_op_allowed("ddl"):
        raise PermissionError("Las operaciones DDL no están habilitadas en la configuración.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    # Validar prefijo de tabla si está configurado
    if settings.ddl_table_prefix:
        prefixes = [p.strip() for p in settings.ddl_table_prefix.split(",") if p.strip()]
        if not any(table.startswith(p) for p in prefixes):
            raise PermissionError(
                f"DDL solo permitido en tablas con prefijo: {prefixes}. "
                f"La tabla '{table}' no cumple."
            )

    col_defs: list[str] = []
    pk_cols: list[str] = []

    for col in columns:
        name = col["name"]
        dtype = col["type"]
        nullable = col.get("nullable", True)
        default = col.get("default")
        is_pk = col.get("primary_key", False)
        is_identity = col.get("identity", False)

        definition = f"  [{name}] {dtype}"
        if is_identity:
            definition += " IDENTITY(1,1)"
        if not nullable:
            definition += " NOT NULL"
        else:
            definition += " NULL"
        if default is not None:
            definition += f" DEFAULT {default}"

        col_defs.append(definition)
        if is_pk:
            pk_cols.append(f"[{name}]")

    if pk_cols:
        col_defs.append(f"  CONSTRAINT [PK_{table}] PRIMARY KEY ({', '.join(pk_cols)})")

    db_prefix = f"[{database}]." if database else ""
    full_name = f"{db_prefix}[{schema}].[{table}]"
    columns_sql = ",\n".join(col_defs)

    if if_not_exists:
        ddl = (
            f"IF NOT EXISTS (\n"
            f"  SELECT 1 FROM sys.tables t\n"
            f"  JOIN sys.schemas s ON t.schema_id = s.schema_id\n"
            f"  WHERE s.name = '{schema}' AND t.name = '{table}'\n"
            f")\nBEGIN\n"
            f"  CREATE TABLE {full_name} (\n{columns_sql}\n  );\n"
            f"END"
        )
    else:
        ddl = f"CREATE TABLE {full_name} (\n{columns_sql}\n);"

    log_query(logger, "DDL CREATE", ddl)

    with get_connection() as conn:
        conn.cursor().execute(ddl)

    return {"created": True, "table": f"{schema}.{table}", "ddl": ddl}


# ── ALTER TABLE ───────────────────────────────────────────────────────────────

def alter_table(
    table: str,
    action: str,
    column_name: str,
    column_type: Optional[str] = None,
    schema: str = "dbo",
    database: Optional[str] = None,
    nullable: bool = True,
) -> dict[str, Any]:
    """
    Modifica una tabla existente (ADD o ALTER COLUMN).

    Parámetros
    ----------
    table       : Nombre de la tabla.
    action      : "ADD" o "ALTER" (ALTER COLUMN).
    column_name : Nombre de la columna a agregar/modificar.
    column_type : Tipo de dato T-SQL (requerido para ADD, opcional para ALTER).
    schema      : Schema SQL (default 'dbo').
    database    : Overridea la base de datos del .env.
    nullable    : Si la columna acepta NULL (default True).

    Retorna
    -------
    {"altered": True, "ddl": "<SQL ejecutado>"}
    """
    if not settings.is_op_allowed("ddl"):
        raise PermissionError("Las operaciones DDL no están habilitadas.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    action_upper = action.upper()
    if action_upper not in ("ADD", "ALTER"):
        raise ValueError(f"Acción '{action}' no soportada. Use 'ADD' o 'ALTER'.")

    null_clause = "NULL" if nullable else "NOT NULL"
    db_prefix = f"[{database}]." if database else ""
    table_ref = f"{db_prefix}[{schema}].[{table}]"

    if action_upper == "ADD":
        if not column_type:
            raise ValueError("Se requiere 'column_type' para ADD COLUMN.")
        ddl = f"ALTER TABLE {table_ref} ADD [{column_name}] {column_type} {null_clause};"
    else:  # ALTER COLUMN
        if not column_type:
            raise ValueError("Se requiere 'column_type' para ALTER COLUMN.")
        ddl = f"ALTER TABLE {table_ref} ALTER COLUMN [{column_name}] {column_type} {null_clause};"

    log_query(logger, "DDL ALTER", ddl)

    with get_connection() as conn:
        conn.cursor().execute(ddl)

    return {"altered": True, "ddl": ddl}


# ── DDL RAW (escape hatch con validación) ────────────────────────────────────

def execute_ddl_raw(
    ddl_statement: str,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """
    Ejecuta un statement DDL arbitrario.
    Para casos avanzados que create_table/alter_table no cubren.

    ⚠️  Las operaciones destructivas (DROP, TRUNCATE) requieren
        allow_destructive=True explícito.

    Parámetros
    ----------
    ddl_statement    : Statement DDL completo en T-SQL.
    allow_destructive: Si False (default), bloquea DROP/TRUNCATE.

    Retorna
    -------
    {"executed": True, "ddl": "<SQL ejecutado>"}
    """
    if not settings.is_op_allowed("ddl"):
        raise PermissionError("Las operaciones DDL no están habilitadas.")

    if not allow_destructive and _DESTRUCTIVE_KEYWORDS.search(ddl_statement):
        raise PermissionError(
            "El statement contiene operaciones destructivas (DROP/TRUNCATE). "
            "Pasa allow_destructive=True si estás seguro."
        )

    log_query(logger, "DDL RAW", ddl_statement)

    with get_connection() as conn:
        conn.cursor().execute(ddl_statement)

    return {"executed": True, "ddl": ddl_statement}


# ── DROP TABLE ──────────────────────────────────────────────────────────────


def drop_table(
    table: str,
    schema: str = "dbo",
    database: Optional[str] = None,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """
    Elimina una tabla (DROP TABLE IF EXISTS).

    ⚠️  Requiere allow_destructive=True explícito como medida de seguridad.

    Parámetros
    ----------
    table              : Nombre de la tabla a eliminar.
    schema             : Schema SQL (default 'dbo').
    database           : Overridea la base de datos del .env.
    allow_destructive  : Debe ser True para ejecutar el DROP.

    Retorna
    -------
    {"dropped": True, "table": "<schema>.<table>"}
    """
    if not settings.is_op_allowed("ddl"):
        raise PermissionError("Las operaciones DDL no están habilitadas.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    if not allow_destructive:
        raise PermissionError(
            f"DROP TABLE es una operación destructiva. "
            f"Pasa allow_destructive=True si estás seguro de eliminar '{schema}.{table}'."
        )

    db_prefix = f"USE [{database}];\n" if database else ""
    table_ref = f"{db_prefix}[{schema}].[{table}]"
    ddl = f"DROP TABLE IF EXISTS {table_ref};"

    log_query(logger, "DROP TABLE", ddl)

    with get_connection() as conn:
        conn.cursor().execute(ddl)

    return {"dropped": True, "table": f"{schema}.{table}"}
