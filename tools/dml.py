"""
tools/dml.py
------------
Herramientas DML: insert_record, bulk_insert, update_record, delete_record.
Toda operación de escritura se ejecuta dentro de una transacción explícita
con rollback automático en caso de error.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import get_connection, log_query, rows_to_dicts, settings

logger = logging.getLogger(__name__)


# ── INSERT individual ─────────────────────────────────────────────────────────

def insert_record(
    table: str,
    data: dict[str, Any],
    schema: str = "dbo",
    return_generated: bool = True,
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Inserta un registro en la tabla indicada.

    Parámetros
    ----------
    table            : Nombre de la tabla.
    data             : Dict {columna: valor} con los campos a insertar.
    schema           : Schema SQL (default 'dbo').
    return_generated : Si True, retorna la fila recién insertada con su PK.
    database         : Overridea la base de datos del .env.

    Retorna
    -------
    Dict con la fila insertada (si return_generated=True) o {"inserted": 1}.
    """
    if not settings.is_op_allowed("insert"):
        raise PermissionError("La operación INSERT no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")

    cols = list(data.keys())
    col_clause = ", ".join(f"[{c}]" for c in cols)
    placeholder_clause = ", ".join("?" for _ in cols)
    db_prefix = f"[{database}]." if database else ""
    table_ref = f"{db_prefix}[{schema}].[{table}]"

    sql = f"INSERT INTO {table_ref} ({col_clause}) VALUES ({placeholder_clause})"
    if return_generated:
        sql += "; SELECT SCOPE_IDENTITY() AS generated_id"

    params = list(data.values())

    log_query(logger, "INSERT", sql, params)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        if return_generated:
            # Avanzar al result set de SCOPE_IDENTITY() si el INSERT no produce filas
            if cursor.description is None:
                cursor.nextset()
            row = cursor.fetchone()
            generated_id = row[0] if row else None
            return {"inserted": 1, "generated_id": generated_id}
        return {"inserted": 1, "message": "Registro insertado correctamente."}


# ── INSERT masivo (bulk) ──────────────────────────────────────────────────────

def bulk_insert(
    table: str,
    rows: list[dict[str, Any]],
    schema: str = "dbo",
    database: Optional[str] = None,
    batch_size: int = 500,
    transactional: bool = True,
) -> dict[str, Any]:
    """
    Inserta múltiples registros de forma eficiente usando executemany.
    Ideal para cargar traducciones u otros catálogos masivos.

    Parámetros
    ----------
    table         : Nombre de la tabla.
    rows          : Lista de dicts, todos deben tener las mismas claves.
    schema        : Schema SQL (default 'dbo').
    database      : Overridea la base de datos del .env.
    batch_size    : Filas por lote (default 500, máx recomendado 1000).
    transactional : Si True (default), todo se ejecuta en una sola transacción
                    atómica. Si False, cada lote se commitea individualmente
                    (los errores no afectan lotes anteriores).

    Retorna
    -------
    {"inserted": N, "batches": M, "errors": []}
    """
    if not settings.is_op_allowed("insert"):
        raise PermissionError("La operación INSERT no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    if not rows:
        return {"inserted": 0, "batches": 0, "errors": []}

    cols = list(rows[0].keys())
    col_clause = ", ".join(f"[{c}]" for c in cols)
    placeholder_clause = ", ".join("?" for _ in cols)
    db_prefix = f"[{database}]." if database else ""
    table_ref = f"{db_prefix}[{schema}].[{table}]"

    sql = f"INSERT INTO {table_ref} ({col_clause}) VALUES ({placeholder_clause})"
    errors: list[str] = []
    total_inserted = 0
    batches = 0

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            if transactional:
                # Modo transaccional: todos los lotes se ejecutan primero,
                # luego se commitean juntos. Si alguno falla, rollback total.
                for i in range(0, len(rows), batch_size):
                    batch = rows[i : i + batch_size]
                    params_batch = [list(r.values()) for r in batch]
                    try:
                        cursor.fast_executemany = True
                        cursor.executemany(sql, params_batch)
                    except Exception:
                        cursor.fast_executemany = False
                        try:
                            cursor.executemany(sql, params_batch)
                        except Exception as exc:
                            raise RuntimeError(
                                f"Transacción cancelada — todas las filas revertidas. "
                                f"Error en lote {batches + 1} (filas {i}-{i + len(batch)}): {exc}"
                            )
                    total_inserted += len(batch)
                    batches += 1
            else:
                # Modo no transaccional: cada lote se commitea individualmente
                for i in range(0, len(rows), batch_size):
                    batch = rows[i : i + batch_size]
                    params_batch = [list(r.values()) for r in batch]
                    try:
                        cursor.fast_executemany = True
                        cursor.executemany(sql, params_batch)
                        conn.commit()
                        total_inserted += len(batch)
                        batches += 1
                        logger.info("[BULK INSERT] lote %d: %d filas insertadas.", batches, len(batch))
                    except Exception as exc:
                        conn.rollback()
                        try:
                            cursor.fast_executemany = False
                            cursor.executemany(sql, params_batch)
                            conn.commit()
                            total_inserted += len(batch)
                            batches += 1
                            logger.info("[BULK INSERT] lote %d: %d filas (fallback slow).", batches, len(batch))
                        except Exception as exc2:
                            conn.rollback()
                            errors.append(f"Lote {batches + 1} (filas {i}-{i + len(batch)}): {exc}")
                            logger.error("[BULK INSERT] Error en lote %d: %s", batches + 1, exc2)

    except RuntimeError as e:
        errors.append(str(e))
        # total_inserted se queda en el valor que tenía antes del error
        # (si el error fue en el lote 2, total_inserted tiene el lote 1).
        # En modo transactional, eso no es correcto — debe ser 0.
        if transactional:
            total_inserted = 0
            batches = 0

    return {"inserted": total_inserted, "batches": batches, "errors": errors}


# ── UPDATE ────────────────────────────────────────────────────────────────────

def update_record(
    table: str,
    fields: dict[str, Any],
    where: str,
    where_params: list[Any],
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Actualiza registros que cumplan la condición WHERE.

    Parámetros
    ----------
    table        : Nombre de la tabla.
    fields       : Dict {columna: nuevo_valor} de campos a actualizar.
    where        : Condición WHERE en T-SQL usando '?' como placeholder.
                   Ejemplo: "id = ? AND activo = ?"
    where_params : Valores para los '?' del WHERE.
    schema       : Schema SQL (default 'dbo').
    database     : Overridea la base de datos del .env.

    Retorna
    -------
    {"updated": N}  — N = filas afectadas.
    """
    if not settings.is_op_allowed("update"):
        raise PermissionError("La operación UPDATE no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    if not fields:
        raise ValueError("El dict 'fields' no puede estar vacío.")
    if not where or not where.strip():
        raise ValueError("Se requiere una condición WHERE para UPDATE (seguridad).")

    set_clause = ", ".join(f"[{c}] = ?" for c in fields)
    db_prefix = f"[{database}]." if database else ""
    sql = f"UPDATE {db_prefix}[{schema}].[{table}] SET {set_clause} WHERE {where}"
    params = list(fields.values()) + list(where_params)

    log_query(logger, "UPDATE", sql, params)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return {"updated": cursor.rowcount}


# ── DELETE ────────────────────────────────────────────────────────────────────

def delete_record(
    table: str,
    where: str,
    where_params: list[Any],
    schema: str = "dbo",
    database: Optional[str] = None,
) -> dict[str, Any]:
    """
    Elimina registros que cumplan la condición WHERE.

    ⚠️  WHERE es obligatorio para prevenir DELETE sin filtro accidental.

    Parámetros
    ----------
    table        : Nombre de la tabla.
    where        : Condición WHERE usando '?' como placeholder.
    where_params : Valores para los '?' del WHERE.
    schema       : Schema SQL (default 'dbo').
    database     : Overridea la base de datos del .env.

    Retorna
    -------
    {"deleted": N}  — N = filas eliminadas.
    """
    if not settings.is_op_allowed("delete"):
        raise PermissionError("La operación DELETE no está habilitada.")
    if not settings.is_schema_allowed(schema):
        raise PermissionError(f"Schema '{schema}' no permitido.")
    if not where or not where.strip():
        raise ValueError("Se requiere una condición WHERE para DELETE (seguridad).")

    db_prefix = f"[{database}]." if database else ""
    sql = f"DELETE FROM {db_prefix}[{schema}].[{table}] WHERE {where}"
    params = list(where_params)

    log_query(logger, "DELETE", sql, params)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return {"deleted": cursor.rowcount}
