"""
config/settings.py
------------------
Configuración central del servidor MCP para SQL Server.
Lee variables de entorno (o archivo .env) y expone un objeto
Settings tipado que el resto del proyecto consume.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import FrozenSet

# Carga .env si existe (sin dependencia de python-dotenv si no está instalado)
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


def _bool(val: str) -> bool:
    return val.strip().lower() in ("1", "true", "yes", "on")


def _set(val: str) -> FrozenSet[str]:
    return frozenset(v.strip().lower() for v in val.split(",") if v.strip())


@dataclass(frozen=True)
class Settings:
    # ── Conexión ──────────────────────────────────────────────
    server: str = os.getenv("MSSQL_SERVER", "localhost")
    port: int = int(os.getenv("MSSQL_PORT", "1433"))
    database: str = os.getenv("MSSQL_DATABASE", "master")
    username: str = os.getenv("MSSQL_USERNAME", "sa")
    password: str = os.getenv("MSSQL_PASSWORD", "")
    driver: str = os.getenv("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server")
    encrypt: str = os.getenv("MSSQL_ENCRYPT", "yes")
    trust_cert: str = os.getenv("MSSQL_TRUST_CERT", "no")
    timeout: int = int(os.getenv("MSSQL_TIMEOUT", "30"))
    pool_size: int = int(os.getenv("MSSQL_POOL_SIZE", "5"))
    char_encoding: str = os.getenv("MSSQL_CHAR_ENCODING", "cp1252")

    # ── Seguridad ─────────────────────────────────────────────
    allowed_ops: FrozenSet[str] = field(
        default_factory=lambda: _set(
            os.getenv("MSSQL_ALLOWED_OPS", "select,insert,update,delete,exec_sp,ddl")
        )
    )
    allowed_schemas: FrozenSet[str] = field(
        default_factory=lambda: _set(os.getenv("MSSQL_ALLOWED_SCHEMAS", ""))
    )
    ddl_table_prefix: str = os.getenv("MSSQL_DDL_TABLE_PREFIX", "")

    # ── Logging ───────────────────────────────────────────────
    log_queries: bool = _bool(os.getenv("MSSQL_LOG_QUERIES", "true"))
    log_level: str = os.getenv("MSSQL_LOG_LEVEL", "INFO")

    # ── Cadena de conexión pyodbc ─────────────────────────────
    @property
    def connection_string(self) -> str:
        return (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server},{self.port};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
            f"PWD={self.password};"
            f"Encrypt={self.encrypt};"
            f"TrustServerCertificate={self.trust_cert};"
            f"Connection Timeout={self.timeout};"
        )

    def is_op_allowed(self, op: str) -> bool:
        return op.lower() in self.allowed_ops

    def is_schema_allowed(self, schema: str) -> bool:
        """Si allowed_schemas está vacío, se permiten todos."""
        if not self.allowed_schemas:
            return True
        return schema.lower() in self.allowed_schemas


# Singleton — el resto del proyecto importa esto directamente
settings = Settings()
