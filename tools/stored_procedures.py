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
import re
from typing import Any, Optional

from config import get_connection, log_query, rows_to_dicts, settings
from tools._database import assert_configured_database

logger = logging.getLogger(__name__)

_QUALIFIED_PROCEDURE_PATTERN = re.compile(
    r"^\s*(?:\[(?P<schema_br>[^\]]+)\]|(?P<schema_plain>[^.\[\]]+))"
    r"\s*\.\s*"
    r"(?:\[(?P<proc_br>[^\]]+)\]|(?P<proc_plain>[^.\[\]]+))\s*$"
)


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip("[]")


def _normalize_param_name(name: str) -> str:
    return name.strip().lstrip("@").strip()


def _resolve_procedure_reference(procedure: str, schema: str) -> tuple[str, str]:
    """Acepta procedure simple o calificado como schema.procedure."""
    match = _QUALIFIED_PROCEDURE_PATTERN.match(procedure)
    if match:
        resolved_schema = match.group("schema_br") or match.group("schema_plain") or schema
        resolved_procedure = match.group("proc_br") or match.group("proc_plain") or procedure
        return _normalize_identifier(resolved_schema), _normalize_identifier(resolved_procedure)

    return _normalize_identifier(schema), _normalize_identifier(procedure)


def _is_row_sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes, bytearray))


def _looks_like_tvp_value(value: Any) -> bool:
    if not _is_row_sequence(value):
        return False
    if not value:
        return True

    return all(isinstance(row, dict) or _is_row_sequence(row) for row in value)


def _load_tvp_columns(cursor: Any, schema: str, procedure: str) -> dict[str, list[dict[str, Any]]]:
    sql = """
    WITH tvp_params AS (
        SELECT
            p.parameter_id,
            p.name                   AS [parameter_name],
            SCHEMA_NAME(t.schema_id) AS [tvp_type_schema],
            t.name                   AS [tvp_type_name],
            tt.type_table_object_id
        FROM sys.procedures sp
        JOIN sys.schemas ps     ON ps.schema_id = sp.schema_id
        JOIN sys.parameters p   ON p.object_id = sp.object_id
        JOIN sys.types t        ON t.user_type_id = p.user_type_id
        JOIN sys.table_types tt ON tt.user_type_id = p.user_type_id
        WHERE ps.name = ? AND sp.name = ?
    )
    SELECT
        tp.parameter_name                   AS [parameter_name],
        tp.tvp_type_schema                  AS [tvp_type_schema],
        tp.tvp_type_name                    AS [tvp_type_name],
        c.column_id                         AS [ordinal],
        c.name                              AS [name],
        SCHEMA_NAME(ct.schema_id)           AS [type_schema],
        ct.name                             AS [type_name],
        bt.name                             AS [base_type],
        c.max_length                        AS [max_length],
        c.precision                         AS [precision],
        c.scale                             AS [scale],
        c.is_nullable                       AS [nullable]
    FROM tvp_params tp
    JOIN sys.columns c ON c.object_id = tp.type_table_object_id
    JOIN sys.types ct  ON ct.user_type_id = c.user_type_id
    JOIN sys.types bt  ON bt.system_type_id = c.system_type_id
                      AND bt.user_type_id = bt.system_type_id
    ORDER BY tp.parameter_id, c.column_id
    """

    cursor.execute(sql, [schema, procedure])
    tvp_columns = rows_to_dicts(cursor)
    grouped: dict[str, list[dict[str, Any]]] = {}

    for column in tvp_columns:
        param_name = _normalize_param_name(column.pop("parameter_name"))
        grouped.setdefault(param_name, []).append(column)

    return grouped


def _load_procedure_parameter_metadata(
    cursor: Any,
    schema: str,
    procedure: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        p.parameter_id                     AS [parameter_id],
        p.name                             AS [name],
        TYPE_NAME(p.user_type_id)          AS [type],
        p.max_length                       AS [max_length],
        p.is_output                        AS [is_output],
        p.has_default_value                AS [has_default],
        p.precision                        AS [precision],
        p.scale                            AS [scale],
        CASE WHEN tt.user_type_id IS NULL
             THEN 0 ELSE 1 END            AS [is_table_type],
        SCHEMA_NAME(t.schema_id)           AS [type_schema],
        t.name                             AS [type_name]
    FROM sys.procedures sp
    JOIN sys.parameters p   ON sp.object_id = p.object_id
    JOIN sys.schemas s      ON sp.schema_id = s.schema_id
    JOIN sys.types t        ON t.user_type_id = p.user_type_id
    LEFT JOIN sys.table_types tt ON tt.user_type_id = p.user_type_id
    WHERE s.name = ? AND sp.name = ?
    ORDER BY p.parameter_id
    """

    cursor.execute(sql, [schema, procedure])
    params_info = rows_to_dicts(cursor)
    tvp_columns_by_param = _load_tvp_columns(cursor, schema, procedure) if any(
        param.get("is_table_type") for param in params_info
    ) else {}

    for param in params_info:
        normalized_name = _normalize_param_name(param["name"])
        param["tvp_columns"] = tvp_columns_by_param.get(normalized_name, [])

    return params_info


def _coerce_tvp_value(value: Any, param_meta: dict[str, Any]) -> list[Any]:
    param_name = param_meta["name"]
    columns = param_meta.get("tvp_columns") or []

    if value is None:
        raise ValueError(
            f"El parametro TVP '{param_name}' no acepta None. "
            "Pasa una lista vacia si quieres enviar cero filas."
        )

    if not _is_row_sequence(value):
        raise ValueError(
            f"El parametro TVP '{param_name}' debe ser una lista o tupla de filas."
        )

    if not columns:
        raise ValueError(
            f"No se pudo resolver la metadata del TVP para el parametro '{param_name}'."
        )

    expected_by_lower = {str(col["name"]).lower(): col["name"] for col in columns}
    expected_names = [col["name"] for col in columns]
    tvp_rows: list[tuple[Any, ...]] = []

    for index, row in enumerate(value, start=1):
        if isinstance(row, dict):
            row_by_lower = {str(key).lower(): key for key in row}
            missing = [name for name in expected_names if name.lower() not in row_by_lower]
            extra = [str(key) for key in row if str(key).lower() not in expected_by_lower]

            if missing or extra:
                details: list[str] = []
                if missing:
                    details.append(f"faltan columnas: {', '.join(missing)}")
                if extra:
                    details.append(f"sobran columnas: {', '.join(extra)}")
                raise ValueError(
                    f"Fila {index} invalida para TVP '{param_name}': {'; '.join(details)}."
                )

            tvp_rows.append(tuple(row[row_by_lower[name.lower()]] for name in expected_names))
            continue

        if _is_row_sequence(row):
            if len(row) != len(expected_names):
                raise ValueError(
                    f"Fila {index} invalida para TVP '{param_name}': "
                    f"se esperaban {len(expected_names)} valores y llegaron {len(row)}."
                )
            tvp_rows.append(tuple(row))
            continue

        raise ValueError(
            f"Fila {index} invalida para TVP '{param_name}'. "
            "Cada fila debe ser dict, list o tuple."
        )

    return [param_meta["type_name"], param_meta["type_schema"], *tvp_rows]


def _summarize_param_value(value: Any, param_meta: Optional[dict[str, Any]] = None) -> Any:
    if param_meta and param_meta.get("is_table_type"):
        rows = max(len(value) - 2, 0) if _is_row_sequence(value) else 0
        return f"<TVP {param_meta['type_schema']}.{param_meta['type_name']} rows={rows}>"
    return value


def _prepare_sp_params(
    params: dict[str, Any],
    params_info: Optional[list[dict[str, Any]]] = None,
) -> tuple[str, list[Any], list[Any], list[str]]:
    metadata_by_param = {
        _normalize_param_name(param["name"]).lower(): param for param in (params_info or [])
    }

    named_parts: list[str] = []
    sql_params: list[Any] = []
    log_params: list[Any] = []
    params_used: list[str] = []
    seen_params: set[str] = set()

    for raw_name, value in params.items():
        param_name = _normalize_param_name(raw_name)
        if not param_name:
            raise ValueError("Los nombres de parametros no pueden estar vacios.")
        if param_name.lower() in seen_params:
            raise ValueError(f"Parametro duplicado despues de normalizar: '{param_name}'.")

        seen_params.add(param_name.lower())
        param_meta = metadata_by_param.get(param_name.lower())
        coerced_value = _coerce_tvp_value(value, param_meta) if param_meta and param_meta.get(
            "is_table_type"
        ) else value

        named_parts.append(f"@{param_name} = ?")
        sql_params.append(coerced_value)
        log_params.append(_summarize_param_value(coerced_value, param_meta))
        params_used.append(param_name)

    return ", ".join(named_parts), sql_params, log_params, params_used


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
    procedure : Nombre del stored procedure. Acepta "MiSP" o "schema.MiSP".
    params    : Dict {nombre_param: valor}. Omite parámetros opcionales.
                Nota: los nombres NO incluyen el '@'; se añade automáticamente.
    schema    : Schema SQL (default 'dbo').
    database  : Debe omitirse o coincidir con MSSQL_DATABASE.

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
    schema, procedure = _resolve_procedure_reference(procedure, schema)

    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    assert_configured_database(database, settings.database)

    params = params or {}
    sp_ref = f"[{schema}].[{procedure}]"
    needs_metadata = bool(params) and any(
        value is None or _looks_like_tvp_value(value) for value in params.values()
    )
    params_info: list[dict[str, Any]] = []

    # Construir EXEC con parámetros nombrados y capturar RETURN value
    if params:
        with get_connection() as conn:
            cursor = conn.cursor()
            if needs_metadata:
                params_info = _load_procedure_parameter_metadata(cursor, schema, procedure)

            named_params, sql_params, log_params, params_used = _prepare_sp_params(params, params_info)
            sql = f"DECLARE @ret INT; EXEC @ret = {sp_ref} {named_params}; SELECT @ret AS return_value"

            log_query(logger, "EXEC SP", sql, log_params)

            resultsets: list[dict[str, Any]] = []
            return_value = None
            cursor.execute(sql, sql_params)

            # Iterar todos los result sets
            while True:
                if cursor.description:
                    rs_cols = [col[0] for col in cursor.description]
                    rs_rows = rows_to_dicts(cursor)
                    if rs_cols == ["return_value"] and rs_rows:
                        return_value = rs_rows[0]["return_value"]
                    else:
                        resultsets.append({"columns": rs_cols, "rows": rs_rows})
                if not cursor.nextset():
                    break

        return {
            "resultsets": resultsets,
            "return_value": return_value,
            "procedure": f"{schema}.{procedure}",
            "params_used": params_used,
        }
    else:
        sql = f"DECLARE @ret INT; EXEC @ret = {sp_ref}; SELECT @ret AS return_value"
        sql_params = []
        log_params = []
        params_used = []

    log_query(logger, "EXEC SP", sql, log_params)

    resultsets: list[dict[str, Any]] = []
    return_value = None

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, sql_params)

        # Iterar todos los result sets
        while True:
            if cursor.description:
                rs_cols = [col[0] for col in cursor.description]
                rs_rows = rows_to_dicts(cursor)
                if rs_cols == ["return_value"] and rs_rows:
                    return_value = rs_rows[0]["return_value"]
                else:
                    resultsets.append({"columns": rs_cols, "rows": rs_rows})
            if not cursor.nextset():
                break

    return {
        "resultsets": resultsets,
        "return_value": return_value,
        "procedure": f"{schema}.{procedure}",
        "params_used": params_used,
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
    database    : Debe omitirse o coincidir con MSSQL_DATABASE.

    Retorna
    -------
    {"procedures": [{"name": ..., "schema": ..., "created": ..., "modified": ...}]}
    """
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    assert_configured_database(database, settings.database)

    sql = """
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
    database  : Debe omitirse o coincidir con MSSQL_DATABASE.

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
    assert_configured_database(database, settings.database)
    schema, procedure = _resolve_procedure_reference(procedure, schema)
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    with get_connection() as conn:
        cursor = conn.cursor()
        params_info = _load_procedure_parameter_metadata(cursor, schema, procedure)

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
    database   : Debe omitirse o coincidir con MSSQL_DATABASE.

    Retorna
    -------
    {"created": True, "procedure": "<schema>.<name>", "ddl": "<SQL ejecutado>"}
    """
    if not settings.is_op_allowed("ddl_sp"):
        raise PermissionError("La gestión de stored procedures (ddl_sp) no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    assert_configured_database(database, settings.database)

    sp_ref = f"[{schema}].[{procedure}]"
    ddl = f"CREATE PROCEDURE {sp_ref}\n{definition}"

    log_query(logger, "CREATE SP", sp_ref)

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
    database   : Debe omitirse o coincidir con MSSQL_DATABASE.

    Retorna
    -------
    {"altered": True, "procedure": "<schema>.<name>", "ddl": "<SQL ejecutado>"}
    """
    if not settings.is_op_allowed("ddl_sp"):
        raise PermissionError("La gestión de stored procedures (ddl_sp) no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    assert_configured_database(database, settings.database)

    sp_ref = f"[{schema}].[{procedure}]"
    ddl = f"ALTER PROCEDURE {sp_ref}\n{definition}"

    log_query(logger, "ALTER SP", sp_ref)

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
    database         : Debe omitirse o coincidir con MSSQL_DATABASE.
    allow_destructive: Debe ser True para ejecutar el DROP.

    Retorna
    -------
    {"dropped": True, "procedure": "<schema>.<name>"}
    """
    if not settings.is_op_allowed("ddl_sp"):
        raise PermissionError("La gestión de stored procedures (ddl_sp) no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    assert_configured_database(database, settings.database)
    if not allow_destructive:
        raise PermissionError(
            f"DROP PROCEDURE es una operación destructiva. "
            f"Pasa allow_destructive=True si estás seguro de eliminar '{schema}.{procedure}'."
        )

    sp_ref = f"[{schema}].[{procedure}]"
    ddl = f"DROP PROCEDURE IF EXISTS {sp_ref};"

    log_query(logger, "DROP SP", sp_ref)

    with get_connection() as conn:
        conn.cursor().execute(ddl)

    return {"dropped": True, "procedure": f"{schema}.{procedure}"}
