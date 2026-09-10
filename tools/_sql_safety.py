"""Guards shared by tools that execute caller-provided SQL."""

from __future__ import annotations

import re


_CREATE_SCHEMA_PATTERN = re.compile(r"\bCREATE\s+SCHEMA\b", re.IGNORECASE)


def reject_direct_schema_creation(sql: str) -> None:
    """Force CREATE SCHEMA through the structured MCP tool."""
    without_comments = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    without_comments = re.sub(r"--[^\r\n]*", " ", without_comments)

    if _CREATE_SCHEMA_PATTERN.search(without_comments):
        raise PermissionError(
            "CREATE SCHEMA debe ejecutarse mediante tool_create_schema "
            "para aplicar las validaciones de seguridad."
        )
