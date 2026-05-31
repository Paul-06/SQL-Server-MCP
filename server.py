"""
server.py
---------
Servidor MCP para SQL Server — punto de entrada principal.

Usa FastMCP (Python SDK oficial de Anthropic/MCP) para exponer
las tools de query, DML, DDL y stored procedures a cualquier
agente de IA compatible con MCP.

Transportes soportados:
  - stdio  : para uso local (Claude Desktop, Claude Code, etc.)
  - http   : para despliegue remoto (streamable HTTP)

Arranque:
  python server.py                  ← stdio (default)
  python server.py --transport http ← HTTP en puerto 5000
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from config import settings, test_connection
from tools import (
    # Query
    execute_query,
    # DML
    insert_record, bulk_insert, update_record, delete_record,
    # DDL
    create_table, alter_table, execute_ddl_raw, drop_table,
    # Stored procedures
    execute_sp, list_stored_procedures, describe_stored_procedure,
    create_sp, alter_sp, drop_sp,
    # Schema
    list_databases, list_schemas, list_tables, describe_table,
    # Transaction
    execute_transaction,
)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("sqlserver-mcp")

# ── FastMCP ───────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="sqlserver-mcp",
    instructions=(
        "Servidor MCP para SQL Server. "
        "Permite ejecutar consultas SELECT parametrizadas, operaciones DML "
        "(INSERT individual o masivo, UPDATE, DELETE), DDL (CREATE TABLE, ALTER TABLE), "
        "y llamadas a stored procedures con parámetros opcionales. "
        "Siempre usa 'describe_table' o 'list_tables' antes de construir queries "
        "si no conoces la estructura de la tabla."
    ),
)

# ══════════════════════════════════════════════════════════════════════════════
# TOOLS — Schema / Introspección
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def tool_list_databases() -> dict[str, Any]:
    """
    Lista las bases de datos disponibles en el servidor.
    Excluye bases de datos del sistema (master, tempdb, model, msdb).
    """
    return list_databases()


@mcp.tool()
def tool_list_schemas(database: Optional[str] = None) -> dict[str, Any]:
    """
    Lista los schemas disponibles en la base de datos.
    Respeta la lista de schemas permitidos en la configuración.
    """
    return list_schemas(database=database)


@mcp.tool()
def tool_list_tables(
    schema: str = "dbo",
    name_filter: Optional[str] = None,
    include_views: bool = True,
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Lista tablas y vistas de un schema.

    - schema: Schema SQL a listar (default 'dbo').
    - name_filter: Filtro parcial de nombre.
    - include_views: Si True, incluye vistas.
    - database: Base de datos alternativa (override del .env).
    """
    return list_tables(schema=schema, name_filter=name_filter,
                       include_views=include_views, database=database)


@mcp.tool()
def tool_describe_table(
    table: str,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Describe la estructura de una tabla: columnas, tipos, PKs e índices.
    Úsala antes de hacer INSERT o CREATE para conocer la estructura exacta.
    """
    return describe_table(table=table, schema=schema, database=database)


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS — SELECT
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def tool_execute_query(
    table: str,
    schema: str = "dbo",
    columns: Optional[list[str]] = None,
    where: Optional[str] = None,
    where_params: Optional[list[Any]] = None,
    order_by: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Ejecuta un SELECT parametrizado y seguro.

    - table: Tabla o vista a consultar.
    - columns: Lista de columnas (None = todas).
    - where: Condición WHERE con '?' como placeholder. Ej: "id = ? AND activo = ?"
    - where_params: Valores para los '?' del WHERE.
    - order_by: Ordenamiento. Ej: "nombre ASC, fecha DESC".
    - page / page_size: Paginación (page_size máx 1000).
    - database: Base de datos alternativa.
    """
    return execute_query(
        table=table, schema=schema, columns=columns,
        where=where, where_params=where_params,
        order_by=order_by, page=page, page_size=page_size,
        database=database,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS — DML (INSERT / UPDATE / DELETE)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def tool_insert_record(
    table: str,
    data: dict[str, Any],
    schema: str = "dbo",
    return_generated: bool = True,
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Inserta un registro en la tabla indicada.

    - data: Dict {columna: valor} con los campos a insertar.
    - return_generated: Si True, retorna el ID generado (SCOPE_IDENTITY).
    """
    return insert_record(table=table, data=data, schema=schema,
                         return_generated=return_generated, database=database)


@mcp.tool()
def tool_bulk_insert(
    table: str,
    rows: list[dict[str, Any]],
    schema: str = "dbo",
    database: Optional[str] = None,
    batch_size: int = 500,
    transactional: bool = True,
) -> dict[str, Any]:
    """
    Inserta múltiples registros de forma eficiente (bulk).
    Ideal para cargar tablas de traducciones u otros catálogos.

    - rows: Lista de dicts, todos con las mismas claves.
    - batch_size: Filas por lote (default 500).
    - transactional: Si True (default), todo es atómico — ninguna fila
      se inserta si hay algún error. Si False, cada lote se commitea
      por separado y los errores no afectan lotes anteriores.

    Retorna el total insertado, número de lotes y lista de errores.
    """
    return bulk_insert(table=table, rows=rows, schema=schema,
                       database=database, batch_size=batch_size,
                       transactional=transactional)


@mcp.tool()
def tool_update_record(
    table: str,
    fields: dict[str, Any],
    where: str,
    where_params: list[Any],
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Actualiza registros que cumplan la condición WHERE.

    - fields: Dict {columna: nuevo_valor}.
    - where: Condición WHERE con '?' como placeholder. Es OBLIGATORIO.
    - where_params: Valores para los '?' del WHERE.
    """
    return update_record(table=table, fields=fields, where=where,
                         where_params=where_params, schema=schema, database=database)


@mcp.tool()
def tool_delete_record(
    table: str,
    where: str,
    where_params: list[Any],
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Elimina registros que cumplan la condición WHERE.
    WHERE es obligatorio por seguridad.

    - where: Condición WHERE con '?' como placeholder.
    - where_params: Valores para los '?'.
    """
    return delete_record(table=table, where=where, where_params=where_params,
                         schema=schema, database=database)


@mcp.tool()
def tool_execute_transaction(
    statements: list[dict[str, Any]],
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Ejecuta múltiples statements SQL en una sola transacción atómica.

    - statements: Lista de dicts, cada uno con:
        {"sql": "UPDATE ... WHERE id = ?", "params": [1]}
      El parámetro "params" es opcional.
    - database: Base de datos alternativa.

    Si algún statement falla, TODA la transacción se revierte (ROLLBACK).
    Útil para operaciones que deben ser atómicas entre varias tablas.
    """
    return execute_transaction(statements=statements, database=database)


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS — DDL (CREATE / ALTER TABLE)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def tool_create_table(
    table: str,
    columns: list[dict[str, Any]],
    schema: str = "dbo",
    database: Optional[str] = None,
    if_not_exists: bool = True,
) -> dict[str, Any]:
    """
    Crea una tabla nueva en SQL Server.

    Cada columna se define como un dict:
    {
      "name"       : "id",         # requerido
      "type"       : "INT",        # tipo T-SQL requerido
      "nullable"   : false,        # default true
      "default"    : null,         # valor DEFAULT (opcional)
      "primary_key": true,         # default false
      "identity"   : true          # IDENTITY(1,1) si true
    }

    - if_not_exists: Si True, no falla si la tabla ya existe.
    """
    return create_table(table=table, columns=columns, schema=schema,
                        database=database, if_not_exists=if_not_exists)


@mcp.tool()
def tool_alter_table(
    table: str,
    action: str,
    column_name: str,
    column_type: Optional[str] = None,
    schema: str = "dbo",
    database: Optional[str] = None,
    nullable: bool = True,
) -> dict[str, Any]:
    """
    Modifica una tabla existente.

    - action: "ADD" para agregar columna, "ALTER" para modificarla.
    - column_name: Nombre de la columna.
    - column_type: Tipo T-SQL (requerido para ADD y ALTER).
    - nullable: Si la columna acepta NULL.
    """
    return alter_table(table=table, action=action, column_name=column_name,
                       column_type=column_type, schema=schema, database=database,
                       nullable=nullable)


@mcp.tool()
def tool_execute_ddl_raw(
    ddl_statement: str,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """
    Ejecuta un statement DDL arbitrario en T-SQL.
    Para casos avanzados que create_table/alter_table no cubren.

    ⚠️  Por seguridad, DROP y TRUNCATE están bloqueados a menos que
        allow_destructive=True se pase explícitamente.
    """
    return execute_ddl_raw(ddl_statement=ddl_statement,
                           allow_destructive=allow_destructive)


@mcp.tool()
def tool_drop_table(
    table: str,
    schema: str = "dbo",
    database: Optional[str] = None,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """
    Elimina una tabla (DROP TABLE IF EXISTS).

    - table: Nombre de la tabla a eliminar.
    - schema: Schema SQL (default 'dbo').
    - database: Base de datos alternativa.

    ⚠️  allow_destructive=True es obligatorio para ejecutar el DROP.
    """
    return drop_table(table=table, schema=schema, database=database,
                      allow_destructive=allow_destructive)


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS — Stored Procedures
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def tool_list_stored_procedures(
    schema: str = "dbo",
    name_filter: Optional[str] = None,
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Lista los stored procedures disponibles en el schema indicado.
    Usa name_filter para buscar por nombre parcial.
    """
    return list_stored_procedures(schema=schema, name_filter=name_filter,
                                  database=database)


@mcp.tool()
def tool_describe_stored_procedure(
    procedure: str,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Describe los parámetros de un stored procedure.
    Muestra nombre, tipo, si es OUTPUT y si tiene valor DEFAULT (es opcional).
    Úsala antes de ejecutar un SP para saber qué parámetros acepta.
    """
    return describe_stored_procedure(procedure=procedure, schema=schema,
                                     database=database)


@mcp.tool()
def tool_execute_sp(
    procedure: str,
    params: Optional[dict[str, Any]] = None,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Ejecuta un stored procedure con parámetros nombrados opcionales.

    - procedure: Nombre del SP (sin schema ni '@').
    - params: Dict {nombre_param: valor}. Omite los parámetros opcionales
              que quieras dejar en su valor DEFAULT del SP.

    Ejemplo: {"IdIdioma": 2}  →  EXEC dbo.sp_GetCatalogo @IdIdioma = 2
    El SP puede tener otros parámetros con DEFAULT que no necesitas pasar.

    Retorna todos los result sets que devuelva el SP.
    """
    return execute_sp(procedure=procedure, params=params,
                      schema=schema, database=database)


@mcp.tool()
def tool_create_sp(
    procedure: str,
    definition: str,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Crea un nuevo stored procedure.

    - procedure: Nombre del SP (sin schema).
    - definition: Cuerpo completo en T-SQL con parámetros y AS BEGIN...END.
                  NO incluyas CREATE PROCEDURE ni el nombre.
    - schema: Schema SQL (default 'dbo').
    - database: Base de datos alternativa.

    Requiere ddl_sp en MSSQL_ALLOWED_OPS.
    """
    return create_sp(procedure=procedure, definition=definition,
                     schema=schema, database=database)


@mcp.tool()
def tool_alter_sp(
    procedure: str,
    definition: str,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Modifica un stored procedure existente (ALTER PROCEDURE).
    Mismo contrato que tool_create_sp pero usa ALTER.
    Ideal para agregar parámetros opcionales sin romper el uso actual del SP.

    Requiere ddl_sp en MSSQL_ALLOWED_OPS.
    """
    return alter_sp(procedure=procedure, definition=definition,
                    schema=schema, database=database)


@mcp.tool()
def tool_drop_sp(
    procedure: str,
    schema: str = "dbo",
    database: Optional[str] = None,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """
    Elimina un stored procedure (DROP PROCEDURE IF EXISTS).

    ⚠️  allow_destructive=True es obligatorio para ejecutar el DROP.

    Requiere ddl_sp en MSSQL_ALLOWED_OPS.
    """
    return drop_sp(procedure=procedure, schema=schema,
                   database=database, allow_destructive=allow_destructive)


# ══════════════════════════════════════════════════════════════════════════════
# Arranque del servidor
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="SQL Server MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transporte MCP (default: stdio)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host para HTTP (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Puerto para HTTP (default: 5000)")
    args = parser.parse_args()

    logger.info("🚀 Iniciando SQL Server MCP...")
    logger.info("   Servidor  : %s:%s", settings.server, settings.port)
    logger.info("   Base datos: %s", settings.database)
    logger.info("   Ops allow : %s", ", ".join(sorted(settings.allowed_ops)))

    if not test_connection():
        logger.error("Abortando: no se pudo conectar a SQL Server.")
        sys.exit(1)

    logger.info("✅ MCP listo. Transporte: %s", args.transport)

    if args.transport == "streamable-http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()