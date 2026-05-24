"""
tools/stored_procedures.py
--------------------------
Herramientas para stored procedures: execute_sp, list_sp, describe_sp,
create_sp, alter_sp, drop_sp.
Soporta parámetros opcionales nativamente — el agente solo pasa
los que necesita y SQL Server aplica los DEFAULT del SP.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import get_connection, rows_to_dicts, settings

logger = logging.getLogger(__name__)


# ── EJECUTAR SP ───────────────────────────────────────────────────────────────

def execute_sp(
    procedure: str,
    params: Optional[dict[str, Any]] = None,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Ejecuta un stored procedure con parámetros nombrados.

    Los parámetros son OPCIONALES por diseño: si el SP tiene parámetros
    con DEFAULT en su definición y no los pasas aquí, SQL Server usará
    el valor default del SP sin error. Esto es el comportamiento nativo
    de EXEC con parámetros nombrados.

    Parámetros
    ----------
    procedure : Nombre del stored procedure (sin schema).
    params    : Dict {nombre_param: valor}. Omite parámetros opcionales.
                Nota: los nombres NO incluyen el '@'; se añade automáticamente.
    schema    : Schema SQL (default 'dbo').
    database  : Overridea la base de datos del .env.

    Retorna
    -------
    {
      "resultsets": [   ← Lista de result sets (un SP puede devolver varios)
        {"columns": [...], "rows": [...]},
        ...
      ],
      "return_value": <int>   ← Valor de RETURN del SP (si aplica)
    }

    Ejemplo de llamada
    ------------------
    execute_sp(
        procedure="sp_GetCatalogo",
        params={"IdIdioma": 2},   # parámetro opcional del SP
    )
    # El SP puede tener @IdIdioma INT = NULL -- SQL Server lo recibe normalmente
    """
    if not settings.is_op_allowed("exec_sp"):
        raise PermissionError("La ejecución de stored procedures no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    params = params or {}
    db_prefix = f"[{database}]." if database else ""
    sp_ref = f"{db_prefix}[{schema}].[{procedure}]"

    # Construir EXEC con parámetros nombrados: EXEC sp @param1=?, @param2=?
    # Pasar solo los params que el llamador proporcionó — los demás usan DEFAULT del SP
    if params:
        named_params = ", ".join(f"@{k} = ?" for k in params)
        sql = f"EXEC {sp_ref} {named_params}"
        sql_params = list(params.values())
    else:
        sql = f"EXEC {sp_ref}"
        sql_params = []

    if settings.log_queries:
        logger.info("[EXEC SP] %s | params=%s", sql, sql_params)

    resultsets: list[dict[str, Any]] = []

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, sql_params)

        # Iterar todos los result sets que el SP devuelva
        while True:
            if cursor.description:
                rs_rows = rows_to_dicts(cursor)
                rs_cols = [col[0] for col in cursor.description]
                resultsets.append({"columns": rs_cols, "rows": rs_rows})
            if not cursor.nextset():
                break

        # Intentar leer el RETURN value (pyodbc no lo expone directamente,
        # pero podemos capturarlo si el SP usa OUTPUT o SELECT)
        return_value = None

    return {
        "resultsets": resultsets,
        "return_value": return_value,
        "procedure": f"{schema}.{procedure}",
        "params_used": list(params.keys()),
    }


# ── LISTAR SPs DISPONIBLES ────────────────────────────────────────────────────

def list_stored_procedures(
    schema: str = "dbo",
    name_filter: Optional[str] = None,
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Lista los stored procedures disponibles en el schema indicado.

    Parámetros
    ----------
    schema      : Schema SQL a listar (default 'dbo').
    name_filter : Filtro parcial de nombre (LIKE). Ej: "sp_Get" → sp_GetXxx.
    database    : Overridea la base de datos del .env.

    Retorna
    -------
    {"procedures": [{"name": ..., "schema": ..., "created": ..., "modified": ...}]}
    """
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    db_prefix = f"USE [{database}];\n" if database else ""

    sql = f"""
    {db_prefix}
    SELECT
        SCHEMA_NAME(p.schema_id)  AS [schema],
        p.name                    AS [name],
        p.create_date             AS [created],
        p.modify_date             AS [modified]
    FROM sys.procedures p
    WHERE SCHEMA_NAME(p.schema_id) = ?
    """
    params: list[Any] = [schema]

    if name_filter:
        sql += " AND p.name LIKE ?"
        params.append(f"%{name_filter}%")

    sql += " ORDER BY p.name"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        procs = rows_to_dicts(cursor)

    return {"procedures": procs, "total": len(procs)}


# ── DESCRIBIR PARÁMETROS DE UN SP ─────────────────────────────────────────────

def describe_stored_procedure(
    procedure: str,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Describe los parámetros de un stored procedure consultando sys.parameters.
    Útil para que el agente sepa qué parámetros acepta antes de llamarlo.

    Parámetros
    ----------
    procedure : Nombre del SP.
    schema    : Schema SQL (default 'dbo').
    database  : Overridea la base de datos del .env.

    Retorna
    -------
    {
      "procedure": "dbo.sp_Nombre",
      "parameters": [
        {
          "name": "@IdIdioma",
          "type": "int",
          "max_length": 4,
          "is_output": false,
          "has_default": true   ← True si el parámetro es opcional
        },
        ...
      ]
    }
    """
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    db_prefix = f"USE [{database}];\n" if database else ""

    sql = f"""
    {db_prefix}
    SELECT
        p.name                          AS [name],
        TYPE_NAME(p.user_type_id)       AS [type],
        p.max_length                    AS [max_length],
        p.is_output                     AS [is_output],
        p.has_default_value             AS [has_default]
    FROM sys.procedures sp
    JOIN sys.parameters p ON sp.object_id = p.object_id
    JOIN sys.schemas s    ON sp.schema_id = s.schema_id
    WHERE s.name = ? AND sp.name = ?
    ORDER BY p.parameter_id
    """

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, [schema, procedure])
        params_info = rows_to_dicts(cursor)

    return {
        "procedure": f"{schema}.{procedure}",
        "parameters": params_info,
        "total_params": len(params_info),
        "optional_params": sum(1 for p in params_info if p.get("has_default")),
    }


# ── CREAR SP ──────────────────────────────────────────────────────────────────

def create_sp(
    procedure: str,
    definition: str,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Crea un nuevo stored procedure.

    Parámetros
    ----------
    procedure  : Nombre del SP (sin schema).
    definition : Cuerpo completo del SP en T-SQL, incluyendo los parámetros
                 y el bloque AS BEGIN...END. NO incluyas CREATE PROCEDURE ni
                 el nombre — se construye automáticamente para garantizar
                 el schema correcto.

                 Ejemplo de definition:
                 '''
                 @IdIdioma INT = NULL,
                 @Activo   BIT = 1
                 AS
                 BEGIN
                     SET NOCOUNT ON;
                     SELECT * FROM [OPERACIONES].[CAB_OPERACIONES]
                     WHERE (@IdIdioma IS NULL OR IdIdioma = @IdIdioma)
                       AND Activo = @Activo;
                 END
                 '''

    schema     : Schema SQL (default 'dbo').
    database   : Overridea la base de datos del .env.

    Retorna
    -------
    {"created": True, "procedure": "<schema>.<name>", "ddl": "<SQL ejecutado>"}
    """
    if not settings.is_op_allowed("ddl_sp"):
        raise PermissionError("La gestión de stored procedures (ddl_sp) no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    db_prefix = f"USE [{database}];\n" if database else ""
    sp_ref = f"[{schema}].[{procedure}]"
    ddl = f"{db_prefix}CREATE PROCEDURE {sp_ref}\n{definition}"

    if settings.log_queries:
        logger.info("[CREATE SP] %s", sp_ref)

    with get_connection() as conn:
        conn.cursor().execute(ddl)

    return {"created": True, "procedure": f"{schema}.{procedure}", "ddl": ddl}


# ── MODIFICAR SP ──────────────────────────────────────────────────────────────

def alter_sp(
    procedure: str,
    definition: str,
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Modifica un stored procedure existente (ALTER PROCEDURE).
    Mismo contrato que create_sp pero usa ALTER en lugar de CREATE.
    Útil para agregar parámetros opcionales sin recrear el SP.

    Parámetros
    ----------
    procedure  : Nombre del SP existente (sin schema).
    definition : Nuevo cuerpo completo del SP (igual que en create_sp).
    schema     : Schema SQL (default 'dbo').
    database   : Overridea la base de datos del .env.

    Retorna
    -------
    {"altered": True, "procedure": "<schema>.<name>", "ddl": "<SQL ejecutado>"}
    """
    if not settings.is_op_allowed("ddl_sp"):
        raise PermissionError("La gestión de stored procedures (ddl_sp) no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    db_prefix = f"USE [{database}];\n" if database else ""
    sp_ref = f"[{schema}].[{procedure}]"
    ddl = f"{db_prefix}ALTER PROCEDURE {sp_ref}\n{definition}"

    if settings.log_queries:
        logger.info("[ALTER SP] %s", sp_ref)

    with get_connection() as conn:
        conn.cursor().execute(ddl)

    return {"altered": True, "procedure": f"{schema}.{procedure}", "ddl": ddl}


# ── ELIMINAR SP ───────────────────────────────────────────────────────────────

def drop_sp(
    procedure: str,
    schema: str = "dbo",
    database: Optional[str] = None,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """
    Elimina un stored procedure (DROP PROCEDURE).

    ⚠️  Requiere allow_destructive=True explícito como medida de seguridad,
        igual que execute_ddl_raw para DROP de tablas.

    Parámetros
    ----------
    procedure        : Nombre del SP a eliminar (sin schema).
    schema           : Schema SQL (default 'dbo').
    database         : Overridea la base de datos del .env.
    allow_destructive: Debe ser True para ejecutar el DROP.

    Retorna
    -------
    {"dropped": True, "procedure": "<schema>.<name>"}
    """
    if not settings.is_op_allowed("ddl_sp"):
        raise PermissionError("La gestión de stored procedures (ddl_sp) no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    if not allow_destructive:
        raise PermissionError(
            f"DROP PROCEDURE es una operación destructiva. "
            f"Pasa allow_destructive=True si estás seguro de eliminar '{schema}.{procedure}'."
        )

    db_prefix = f"USE [{database}];\n" if database else ""
    sp_ref = f"[{schema}].[{procedure}]"
    ddl = f"{db_prefix}DROP PROCEDURE IF EXISTS {sp_ref};"

    if settings.log_queries:
        logger.info("[DROP SP] %s", sp_ref)

    with get_connection() as conn:
        conn.cursor().execute(ddl)

    return {"dropped": True, "procedure": f"{schema}.{procedure}"}