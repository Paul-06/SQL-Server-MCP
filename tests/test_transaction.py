"""
Tests para tools/dml.py — modo transactional en bulk_insert.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_mock_connection, make_mock_cm

MODULE = "tools.dml"


def _mock_settings(**kwargs):
    p = patch(f"{MODULE}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    mock.is_schema_allowed.return_value = kwargs.get("is_schema_allowed", True)
    return p


class TestBulkInsertTransactional:
    def test_transactional_success_all_batches(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.dml import bulk_insert
            result = bulk_insert(
                table="AuditLog",
                rows=[{"x": i} for i in range(100)],
                batch_size=50,
                transactional=True,
            )
        p.stop()

        assert result["inserted"] == 100
        assert result["batches"] == 2
        assert result["errors"] == []

    def test_transactional_rollback_on_error(self):
        call_count = [0]

        def executemany_side(sql, params_batch):
            call_count[0] += 1
            # Lote 1 ok (call 1), lote 2 falla tanto en fast (call 2) como slow (call 3)
            if call_count[0] >= 2:
                raise Exception("DB error en lote 2")
            return None

        mock_cursor = MagicMock()
        mock_cursor.executemany.side_effect = executemany_side
        mock_cursor.description = None
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.dml import bulk_insert
            result = bulk_insert(
                table="AuditLog",
                rows=[{"x": i} for i in range(100)],
                batch_size=50,
                transactional=True,
            )
        p.stop()

        assert result["inserted"] == 0
        assert len(result["errors"]) == 1
        assert "Transacción cancelada" in result["errors"][0]

    def test_non_transactional_continues_after_error(self):
        call_count = [0]

        def executemany_side(sql, params_batch):
            call_count[0] += 1
            # Lote 1 falla tanto fast (call 1) como slow (call 2)
            if call_count[0] <= 2:
                raise Exception("Error en lote 1")
            return None

        mock_cursor = MagicMock()
        mock_cursor.executemany.side_effect = executemany_side
        mock_cursor.description = None
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.dml import bulk_insert
            result = bulk_insert(
                table="AuditLog",
                rows=[{"x": i} for i in range(100)],
                batch_size=50,
                transactional=False,
            )
        p.stop()

        assert result["inserted"] == 50
        assert len(result["errors"]) == 1

    def test_non_transactional_success_all(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.dml import bulk_insert
            result = bulk_insert(
                table="AuditLog",
                rows=[{"x": i} for i in range(50)],
                transactional=False,
            )
        p.stop()

        assert result["inserted"] == 50


TXN_MODULE = "tools.transaction"


def _mock_txn_settings(**kwargs):
    p = patch(f"{TXN_MODULE}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    mock.is_schema_allowed.return_value = kwargs.get("is_schema_allowed", True)
    return p


class TestExecuteTransaction:
    def test_single_statement(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.rowcount = 5
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        with patch(f"{TXN_MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.transaction import execute_transaction
            result = execute_transaction(
                statements=[{"sql": "UPDATE Products SET UnitPrice = ? WHERE CategoryID = ?", "params": [10, 1]}]
            )

        assert result["success"] is True
        assert result["error"] is None
        assert result["results"][0]["rows_affected"] == 5

    def test_multiple_statements_atomic(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.rowcount = 1
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        with patch(f"{TXN_MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.transaction import execute_transaction
            result = execute_transaction(statements=[
                {"sql": "UPDATE Products SET UnitPrice = 20 WHERE ProductID = 1"},
                {"sql": "INSERT INTO AuditLog (TableName) VALUES ('Products')"},
            ])

        assert result["success"] is True
        assert len(result["results"]) == 2

    def test_rollback_on_error(self):
        call_count = [0]

        def execute_side(sql, params=None):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("Error en segundo statement")
            mock_cursor = MagicMock()
            mock_cursor.description = None
            mock_cursor.rowcount = 1
            return None

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = execute_side
        mock_cursor.description = None
        mock_cursor.rowcount = 0
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        with patch(f"{TXN_MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.transaction import execute_transaction
            result = execute_transaction(statements=[
                {"sql": "UPDATE Products SET UnitPrice = 20 WHERE ProductID = 1"},
                {"sql": "UPDATE Products SET UnitPrice = 30 WHERE ProductID = 2"},
            ])

        assert result["success"] is False
        assert result["error"] is not None
        assert "Error en segundo statement" in result["error"]

    def test_empty_statements(self):
        from tools.transaction import execute_transaction
        result = execute_transaction(statements=[])
        assert result["success"] is True
        assert result["error"] is None
        assert result["results"] == []

    def test_select_returns_results(self):
        mock_cursor = MagicMock()
        mock_cursor.description = [("ProductID", None, None, None, None, None, None),
                                   ("ProductName", None, None, None, None, None, None)]
        mock_cursor.fetchall.return_value = [(1, "Chai")]
        mock_cursor.rowcount = -1
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        with patch(f"{TXN_MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.transaction import execute_transaction
            result = execute_transaction(statements=[
                {"sql": "SELECT ProductID, ProductName FROM Products WHERE ProductID = 1"}
            ])

        assert result["success"] is True
        assert len(result["results"][0]["rows"]) == 1
        assert result["results"][0]["columns"] == ["ProductID", "ProductName"]

    def test_statement_without_params(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.rowcount = 3
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        with patch(f"{TXN_MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.transaction import execute_transaction
            result = execute_transaction(statements=[
                {"sql": "DELETE FROM AuditLog WHERE AuditID < 10"}
            ])

        assert result["success"] is True
        assert result["results"][0]["rows_affected"] == 3
