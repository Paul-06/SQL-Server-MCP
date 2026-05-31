"""
tools/schema.py
---------------
Herramientas de introspección: list_tables, describe_table, list_schemas.
Permiten al agente explorar la estructura de la base de datos
antes de construir queries o insertar datos.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import get_connection, rows_to_dicts, settings

logger = logging.getLogger(__name__)


def list_schemas(database: Optional[str] = None) -> dict[str, Any]:
    """
    Lista los schemas disponibles en la base de datos.

    Retorna solo los schemas que estén en MSSQL_ALLOWED_SCHEMAS (si aplica).
    """
    db_prefix = f"USE [{database}];\n" if database else ""
    sql = f"""
    {db_prefix}
    SELECT
        s.name          AS [schema],
        s.schema_id     AS [schema_id],
        p.name          AS [owner]
    FROM sys.schemas s
    JOIN sys.database_principals p ON s.principal_id = p.principal_id
    WHERE s.name NOT IN ('sys','INFORMATION_SCHEMA','guest','db_owner',
                         'db_accessadmin','db_securityadmin','db_ddladmin',
                         'db_backupoperator','db_datareader','db_datawriter',
                         'db_denydatareader','db_denydatawriter')
    ORDER BY s.name
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql)
        schemas = rows_to_dicts(cursor)

    # Filtrar según configuración
    if settings.allowed_schemas:
        schemas = [s for s in schemas if s["schema"].lower() in settings.allowed_schemas]

    return {"schemas": schemas, "total": len(schemas)}


def list_databases() -> dict[str, Any]:
    """
    Lista las bases de datos disponibles en el servidor.
    Filtra bases de datos del sistema (master, tempdb, model, msdb).
    """
    sql = """
    SELECT
        name            AS [name],
        database_id     AS [database_id],
        create_date     AS [created],
        state_desc      AS [state]
    FROM sys.databases
    WHERE name NOT IN ('master', 'tempdb', 'model', 'msdb')
    ORDER BY name
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql)
        databases = rows_to_dicts(cursor)

    return {"databases": databases, "total": len(databases)}


def list_tables(
    schema: str = "dbo",
    name_filter: Optional[str] = None,
    include_views: bool = True,
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Lista tablas (y vistas opcionalmente) en un schema.

    Parámetros
    ----------
    schema        : Schema SQL (default 'dbo').
    name_filter   : Filtro parcial de nombre (LIKE).
    include_views : Si True, incluye vistas además de tablas.
    database      : Overridea la base de datos del .env.

    Retorna
    -------
    {"tables": [{name, type, created, rows_estimate}], "total": N}
    """
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    db_prefix = f"USE [{database}];\n" if database else ""
    type_filter = "AND t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')" if include_views else "AND t.TABLE_TYPE = 'BASE TABLE'"

    params: list[Any] = [schema]

    if name_filter:
        type_filter += " AND t.TABLE_NAME LIKE ?"
        params.append(f"%{name_filter}%")

    sql = f"""
    {db_prefix}
    SELECT
        t.TABLE_NAME            AS [name],
        t.TABLE_TYPE            AS [type],
        o.create_date           AS [created],
        o.modify_date           AS [modified],
        p.rows                  AS [rows_estimate]
    FROM INFORMATION_SCHEMA.TABLES t
    JOIN sys.objects o
        ON o.name = t.TABLE_NAME
        AND SCHEMA_NAME(o.schema_id) = t.TABLE_SCHEMA
    LEFT JOIN sys.partitions p
        ON p.object_id = o.object_id AND p.index_id IN (0, 1)
    WHERE t.TABLE_SCHEMA = ?
    {type_filter}
    ORDER BY t.TABLE_TYPE, t.TABLE_NAME
    """

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        tables = rows_to_dicts(cursor)

    return {"tables": tables, "total": len(tables), "schema": schema}


def describe_table(
    table: str,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Describe la estructura de una tabla: columnas, tipos, PKs, índices.

    Retorna
    -------
    {
      "table": "dbo.nombre",
      "columns": [{name, type, max_length, nullable, default, is_pk, is_identity}],
      "indexes": [{name, type, columns}]
    }
    """
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    db_prefix = f"USE [{database}];\n" if database else ""

    # Columnas
    col_sql = f"""
    {db_prefix}
    SELECT
        c.COLUMN_NAME                           AS [name],
        c.DATA_TYPE                             AS [type],
        c.CHARACTER_MAXIMUM_LENGTH              AS [max_length],
        c.IS_NULLABLE                           AS [nullable],
        c.COLUMN_DEFAULT                        AS [default],
        COLUMNPROPERTY(
            OBJECT_ID(c.TABLE_SCHEMA + '.' + c.TABLE_NAME),
            c.COLUMN_NAME, 'IsIdentity')        AS [is_identity],
        CASE WHEN kcu.COLUMN_NAME IS NOT NULL
             THEN 1 ELSE 0 END                 AS [is_pk]
    FROM INFORMATION_SCHEMA.COLUMNS c
    LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        ON tc.TABLE_SCHEMA = c.TABLE_SCHEMA
        AND tc.TABLE_NAME  = c.TABLE_NAME
        AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
    LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
        ON kcu.TABLE_SCHEMA = tc.TABLE_SCHEMA
        AND kcu.TABLE_NAME  = tc.TABLE_NAME
        AND kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
        AND kcu.COLUMN_NAME = c.COLUMN_NAME
    WHERE c.TABLE_SCHEMA = ? AND c.TABLE_NAME = ?
    ORDER BY c.ORDINAL_POSITION
    """

    # Índices
    idx_sql = f"""
    {db_prefix}
    SELECT
        i.name                                              AS [index_name],
        CASE i.type_desc
            WHEN 'CLUSTERED'    THEN 'CLUSTERED'
            WHEN 'NONCLUSTERED' THEN 'NONCLUSTERED'
            ELSE i.type_desc END                           AS [type],
        i.is_unique                                        AS [is_unique],
        STRING_AGG(c.name, ', ')
            WITHIN GROUP (ORDER BY ic.key_ordinal)         AS [columns]
    FROM sys.indexes i
    JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
    JOIN sys.columns c        ON ic.object_id = c.object_id AND ic.column_id = c.column_id
    JOIN sys.tables t         ON i.object_id = t.object_id
    JOIN sys.schemas s        ON t.schema_id = s.schema_id
    WHERE s.name = ? AND t.name = ? AND i.is_hypothetical = 0
    GROUP BY i.name, i.type_desc, i.is_unique
    ORDER BY i.name
    """

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(col_sql, [schema, table])
        columns = rows_to_dicts(cursor)

        cursor.execute(idx_sql, [schema, table])
        indexes = rows_to_dicts(cursor)

    return {
        "table": f"{schema}.{table}",
        "columns": columns,
        "indexes": indexes,
        "pk_columns": [c["name"] for c in columns if c.get("is_pk")],
    }
