"""
config/database.py
------------------
Pool de conexiones a SQL Server usando pyodbc.
Expone get_connection() como context manager para que
cada tool abra/cierre conexiones de forma segura.
"""

from __future__ import annotations

import logging
import queue
import threading
from contextlib import contextmanager
from typing import Generator

import pyodbc

from .settings import settings

logger = logging.getLogger(__name__)


class ConnectionPool:
    """
    Pool de conexiones pyodbc thread-safe con tamaño configurable.
    Las conexiones se crean bajo demanda y se reciclan al devolverlas.
    """

    def __init__(self, dsn: str, pool_size: int) -> None:
        self._dsn = dsn
        self._pool: queue.Queue[pyodbc.Connection] = queue.Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._created = 0
        self._max = pool_size

    def _new_connection(self) -> pyodbc.Connection:
        conn = pyodbc.connect(self._dsn, autocommit=False)
        # Configuración recomendada para SQL Server
        conn.setdecoding(pyodbc.SQL_CHAR, encoding=settings.char_encoding)
        conn.setdecoding(pyodbc.SQL_WCHAR, encoding="utf-16le")
        conn.setencoding(encoding=settings.write_encoding)
        if settings.query_timeout > 0:
            conn.timeout = settings.query_timeout
        logger.debug("Nueva conexión creada al pool.")
        return conn

    def acquire(self) -> pyodbc.Connection:
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self._max:
                    conn = self._new_connection()
                    self._created += 1
                    return conn
            # Si el pool está lleno, esperar hasta 30 s
            try:
                return self._pool.get(timeout=30)
            except queue.Empty:
                raise TimeoutError(
                    "Pool de conexiones agotado. "
                    f"Todas las {self._max} conexiones están en uso y ninguna se liberó en 30s. "
                    "Aumenta MSSQL_POOL_SIZE o revisa fugas de conexiones."
                )

    def release(self, conn: pyodbc.Connection) -> None:
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            conn.close()

    def close_all(self) -> None:
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break


# Pool global
_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(settings.connection_string, settings.pool_size)
    return _pool


@contextmanager
def get_connection() -> Generator[pyodbc.Connection, None, None]:
    """
    Context manager que entrega una conexión del pool
    y la devuelve automáticamente al salir (con o sin error).

    Uso:
        async with get_connection() as conn:
            cursor = conn.cursor()
            ...
    """
    pool = get_pool()
    conn = pool.acquire()
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        pool.release(conn)


def rows_to_dicts(cursor: pyodbc.Cursor) -> list[dict]:
    """Convierte el resultado de un cursor en lista de dicts."""
    columns = [col[0] for col in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def test_connection() -> bool:
    """Prueba rápida de conectividad al arrancar el servidor."""
    try:
        with get_connection() as conn:
            conn.cursor().execute("SELECT 1")
        logger.info("✅ Conexión a SQL Server exitosa.")
        return True
    except Exception as exc:
        logger.error("❌ No se pudo conectar a SQL Server: %s", exc)
        return False
