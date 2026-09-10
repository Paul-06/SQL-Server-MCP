"""Helpers for safely composing SQL Server identifiers."""

from __future__ import annotations


_MAX_IDENTIFIER_LENGTH = 128  # SQL Server sysname limit.


def quote_identifier(identifier: str, label: str = "Identificador") -> str:
    """Validate and quote one SQL Server identifier.

    Identifiers cannot be parameterized through ODBC, so they must be
    validated and escaped before being interpolated into a statement.
    """
    if not isinstance(identifier, str):
        raise ValueError(f"{label} debe ser un texto.")

    value = identifier.strip()
    if not value:
        raise ValueError(f"{label} no puede estar vacio.")
    if "\x00" in value:
        raise ValueError(f"{label} contiene un caracter NUL no valido.")
    if len(value) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"{label} no puede superar {_MAX_IDENTIFIER_LENGTH} caracteres."
        )
    if "." in value:
        raise ValueError(
            f"{label} debe ser un identificador simple; no se permiten nombres multipartes."
        )

    return f"[{value.replace(']', ']]')}]"
