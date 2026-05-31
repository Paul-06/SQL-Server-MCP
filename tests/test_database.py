"""
Tests para config/database.py:
- ConnectionPool: acquire, release, close_all
- TimeoutError cuando el pool está lleno
- get_connection context manager
- rows_to_dicts
"""

from __future__ import annotations

from queue import Empty, Queue
from unittest.mock import MagicMock, patch

import pytest

from config.database import ConnectionPool, get_connection, get_pool, rows_to_dicts


class TestConnectionPool:
    def test_acquire_creates_new_connection(self):
        pool = ConnectionPool("dsn", pool_size=5)
        with patch.object(pool, "_new_connection", return_value=MagicMock()) as mock_new:
            conn = pool.acquire()
            mock_new.assert_called_once()
            assert conn is mock_new.return_value
            assert pool._created == 1

    def test_acquire_reuses_from_queue(self):
        pool = ConnectionPool("dsn", pool_size=5)
        existing = MagicMock()
        pool._pool.put(existing)
        conn = pool.acquire()
        assert conn is existing
        assert pool._created == 0

    def test_release_returns_to_pool(self):
        pool = ConnectionPool("dsn", pool_size=5)
        conn = MagicMock()
        pool.release(conn)
        assert pool._pool.qsize() == 1
        assert pool._pool.get_nowait() is conn

    def test_release_closes_when_pool_full(self):
        pool = ConnectionPool("dsn", pool_size=1)
        conn1 = MagicMock()
        conn2 = MagicMock()
        pool.release(conn1)  # fills the pool
        pool.release(conn2)  # should close conn2 since pool is full
        conn2.close.assert_called_once()

    def test_close_all_drains_pool(self):
        pool = ConnectionPool("dsn", pool_size=3)
        c1, c2 = MagicMock(), MagicMock()
        pool._pool.put(c1)
        pool._pool.put(c2)
        pool.close_all()
        c1.close.assert_called_once()
        c2.close.assert_called_once()
        assert pool._pool.empty()

    def test_acquire_timeout_raises_timeout_error(self):
        pool = ConnectionPool("dsn", pool_size=1)
        pool._created = 1  # pool full
        pool._pool.get = MagicMock(side_effect=Empty)

        with pytest.raises(TimeoutError, match="Pool de conexiones agotado"):
            pool.acquire()


class TestGetConnection:
    def test_get_connection_context_commits_on_success(self):
        conn = MagicMock()
        with patch("config.database.get_pool") as mock_get_pool:
            pool = MagicMock()
            pool.acquire.return_value = conn
            mock_get_pool.return_value = pool

            with get_connection() as ctx:
                assert ctx is conn

            conn.commit.assert_called_once()
            pool.release.assert_called_once_with(conn)

    def test_get_connection_rollbacks_on_error(self):
        conn = MagicMock()
        with patch("config.database.get_pool") as mock_get_pool:
            pool = MagicMock()
            pool.acquire.return_value = conn
            mock_get_pool.return_value = pool

            with pytest.raises(ValueError, match="test error"):
                with get_connection() as ctx:
                    assert ctx is conn
                    raise ValueError("test error")

            conn.rollback.assert_called_once()
            pool.release.assert_called_once_with(conn)

    def test_rollback_failure_absorbed(self):
        conn = MagicMock()
        conn.rollback.side_effect = Exception("rollback fail")
        with patch("config.database.get_pool") as mock_get_pool:
            pool = MagicMock()
            pool.acquire.return_value = conn
            mock_get_pool.return_value = pool

            with pytest.raises(ValueError, match="test"):
                with get_connection():
                    raise ValueError("test")

            conn.rollback.assert_called_once()
            pool.release.assert_called_once()


class TestGetPool:
    def test_get_pool_singleton(self):
        with patch("config.database.ConnectionPool") as mock_pool_cls:
            mock_pool_cls.return_value = "pool_instance"
            pool1 = get_pool()
            pool2 = get_pool()
            assert pool1 is pool2
            mock_pool_cls.assert_called_once()

    def test_get_pool_thread_safe(self):
        from config.database import _pool as global_pool
        import config.database
        config.database._pool = None
        with patch("config.database.ConnectionPool") as mock_pool_cls:
            mock_pool_cls.return_value = "pool_instance"
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=10) as exe:
                futures = [exe.submit(get_pool) for _ in range(20)]
                results = [f.result() for f in futures]

            assert all(r == "pool_instance" for r in results)
            mock_pool_cls.assert_called_once()
        config.database._pool = None


class TestRowsToDicts:
    def test_rows_to_dicts_basic(self):
        cursor = MagicMock()
        cursor.description = [("id", None, None, None, None, None, None),
                              ("name", None, None, None, None, None, None)]
        cursor.fetchall.return_value = [(1, "Alice"), (2, "Bob")]

        result = rows_to_dicts(cursor)
        assert result == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

    def test_rows_to_dicts_empty(self):
        cursor = MagicMock()
        cursor.description = None
        cursor.fetchall.return_value = []
        result = rows_to_dicts(cursor)
        assert result == []
