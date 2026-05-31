import logging
from typing import Any, Optional

from .settings import settings
from .database import get_connection, rows_to_dicts, test_connection


def log_query(logger: logging.Logger, label: str, sql: str, params: Optional[list[Any]] = None) -> None:
    """Loggea una query SQL. Omite params si MSSQL_LOG_PARAMS=false."""
    if not settings.log_queries:
        return
    if settings.log_params and params is not None:
        logger.info("[%s] %s | params=%s", label, sql, params)
    else:
        logger.info("[%s] %s", label, sql)


__all__ = ["settings", "get_connection", "rows_to_dicts", "test_connection", "log_query"]