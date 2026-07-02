"""Helpers para mantener el MCP dentro de la base configurada."""

from __future__ import annotations

from typing import Optional


def assert_configured_database(database: Optional[str], configured_database: str) -> None:
    """
    Permite omitir database o repetir la base configurada, pero bloquea overrides.

    El servidor MCP abre la conexion directamente contra MSSQL_DATABASE. Agregar
    USE o referencias de tres partes puede producir errores con ciertos drivers
    y tambien evita que la configuracion sea la fuente unica de verdad.
    """
    if database is None or not str(database).strip():
        return

    requested = str(database).strip().strip("[]")
    configured = str(configured_database).strip().strip("[]")

    if requested.lower() != configured.lower():
        raise PermissionError(
            "El MCP solo puede usar la base configurada en MSSQL_DATABASE "
            f"('{configured}'). Recibido: '{requested}'."
        )
