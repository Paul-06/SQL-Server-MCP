"""
Tests para tools/dml.py:
- insert_record (con y sin return_generated)
- bulk_insert (con/sin tildes, fallback fast_executemany)
- update_record (con WHERE obligatorio)
- delete_record (con WHERE obligatorio)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_mock_connection, make_mock_cursor

MODULE = "tools.dml"


def _mock_settings(**kwargs):
    p = patch(f"{MODULE}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    mock.is_schema_allowed.return_value = kwargs.get("is_schema_allowed", True)
    return p


class TestInsertRecord:
    def test_insert_basic(self):
        mock_cursor = make_mock_cursor(columns=["generated_id"], rows=[[42]], fetchone_result=[42])
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import insert_record
            result = insert_record(table="AuditLog", data={"TableName": "Test", "Action": "INSERT"})
        p.stop()

        assert result["inserted"] == 1
        assert result["generated_id"] == 42

    def test_insert_no_return_generated(self):
        mock_cursor = make_mock_cursor()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import insert_record
            result = insert_record(table="AuditLog", data={"TableName": "Test"}, return_generated=False)
        p.stop()

        assert result["inserted"] == 1
        assert "message" in result

    def test_insert_multi_statement_nextset(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.nextset.return_value = True
        mock_cursor.fetchone.side_effect = [[99]]
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import insert_record
            result = insert_record(table="AuditLog", data={"TableName": "Test"})
        p.stop()

        assert result["inserted"] == 1

    def test_insert_sql_includes_scope_identity(self):
        executed_sql: list[str] = []

        def execute_side(sql, params=None):
            executed_sql.append(sql)

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = execute_side
        mock_cursor.description = [("generated_id", None, None, None, None, None, None)]
        mock_cursor.fetchone.return_value = [1]
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import insert_record
            insert_record(table="T", data={"x": 1})
        p.stop()

        assert "SCOPE_IDENTITY()" in executed_sql[0]

    def test_insert_raises_on_permission(self):
        p = _mock_settings(is_op_allowed=False)
        from tools.dml import insert_record
        with pytest.raises(PermissionError, match="INSERT no está habilitada"):
            insert_record(table="T", data={"x": 1})
        p.stop()

    def test_insert_raises_on_schema_not_allowed(self):
        p = _mock_settings(is_schema_allowed=False)
        from tools.dml import insert_record
        with pytest.raises(PermissionError, match="no permitido"):
            insert_record(table="T", data={"x": 1}, schema="secret")
        p.stop()


class TestBulkInsert:
    def test_bulk_insert_basic(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import bulk_insert
            result = bulk_insert(table="AuditLog", rows=[
                {"TableName": "T1", "Action": "INSERT"},
                {"TableName": "T2", "Action": "UPDATE"},
            ])
        p.stop()

        assert result["inserted"] == 2
        assert result["batches"] == 1

    def test_bulk_insert_empty_returns_early(self):
        from tools.dml import bulk_insert
        result = bulk_insert(table="T", rows=[])
        assert result["inserted"] == 0

    def test_bulk_insert_with_tildes(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import bulk_insert
            result = bulk_insert(table="AuditLog", rows=[
                {"TableName": "Órdenes", "ChangedBy": "María José"},
                {"TableName": "Proveedores", "ChangedBy": "Francisca Núñez"},
            ])
        p.stop()

        assert result["inserted"] == 2

    def test_bulk_insert_fallback_on_encoding_error(self):
        call_count = [0]

        def executemany_side(sql, params_batch):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Invalid character value for cast specification")
            return None

        mock_cursor = MagicMock()
        mock_cursor.executemany.side_effect = executemany_side
        mock_cursor.description = None
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import bulk_insert
            result = bulk_insert(table="AuditLog", rows=[{"TableName": "Test", "ChangedBy": "José"}])
        p.stop()

        assert result["inserted"] == 1

    def test_bulk_insert_both_fail_report_error(self):
        def executemany_side(sql, params_batch):
            raise Exception("DB error")

        mock_cursor = MagicMock()
        mock_cursor.executemany.side_effect = executemany_side
        mock_cursor.description = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import bulk_insert
            result = bulk_insert(table="AuditLog", rows=[{"TableName": "T", "Action": "X"}])
        p.stop()

        assert result["inserted"] == 0
        assert len(result["errors"]) == 1

    def test_bulk_insert_reuses_single_connection(self):
        mock_cursor = MagicMock()
        mock_cursor.description = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value) as mock_get:
            from tools.dml import bulk_insert
            bulk_insert(table="T", rows=[{"x": i} for i in range(100)], batch_size=50)
        p.stop()

        assert mock_get.call_count == 1

    def test_bulk_insert_raises_on_permission(self):
        p = _mock_settings(is_op_allowed=False)
        from tools.dml import bulk_insert
        with pytest.raises(PermissionError):
            bulk_insert(table="T", rows=[{"x": 1}])
        p.stop()

    def test_bulk_insert_raises_on_schema_not_allowed(self):
        p = _mock_settings(is_schema_allowed=False)
        from tools.dml import bulk_insert
        with pytest.raises(PermissionError):
            bulk_insert(table="T", rows=[{"x": 1}], schema="secret")
        p.stop()


class TestUpdateRecord:
    def test_update_basic(self):
        mock_cursor = make_mock_cursor(rowcount=3)
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import update_record
            result = update_record(table="AuditLog", fields={"ChangedBy": "Admin"}, where="AuditID = ?", where_params=[1])
        p.stop()

        assert result["updated"] == 3

    def test_update_requires_where(self):
        from tools.dml import update_record
        with pytest.raises(ValueError, match="WHERE"):
            update_record(table="T", fields={"x": 1}, where="", where_params=[])

    def test_update_requires_fields(self):
        from tools.dml import update_record
        with pytest.raises(ValueError, match="fields"):
            update_record(table="T", fields={}, where="id=1", where_params=[])


class TestDeleteRecord:
    def test_delete_basic(self):
        mock_cursor = make_mock_cursor(rowcount=2)
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.dml import delete_record
            result = delete_record(table="AuditLog", where="AuditID = ?", where_params=[1])
        p.stop()

        assert result["deleted"] == 2

    def test_delete_requires_where(self):
        from tools.dml import delete_record
        with pytest.raises(ValueError, match="WHERE"):
            delete_record(table="T", where="", where_params=[])
