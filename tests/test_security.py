"""
Tests de seguridad:
- SQL injection en parámetros
- Operaciones destructivas bloqueadas
- Permisos por operación y schema
- WHERE obligatorio en UPDATE/DELETE
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_mock_cm, make_mock_connection


def _mock_settings_for(module: str, **kwargs):
    p = patch(f"{module}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    mock.is_schema_allowed.return_value = kwargs.get("is_schema_allowed", True)
    return p


class TestSqlInjection:
    def test_list_tables_name_filter_parametrized(self):
        from tools.schema import list_tables
        executed_params: list = []

        def capture_execute(sql, params=None):
            executed_params.append((sql, params))

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = capture_execute
        mock_cursor.description = None
        mock_conn = make_mock_connection(mock_cursor)

        with patch("tools.schema.get_connection", return_value=make_mock_cm(mock_conn)), \
             patch("tools.schema.settings") as mock_s:
            mock_s.is_schema_allowed.return_value = True
            from tools.schema import list_tables
            list_tables(schema="dbo", name_filter="' OR 1=1; --")

        sql, params = executed_params[0]
        assert "' OR 1=1; --" not in sql
        assert params[-1] == "%' OR 1=1; --%"

    def test_update_record_where_parametrized(self):
        from tools.dml import update_record
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = capture
        mock_cursor.rowcount = 0
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings_for("tools.dml")
        with patch("tools.dml.get_connection", return_value=make_mock_cm(mock_conn)):
            update_record(table="Users", fields={"Name": "Admin'--"}, where="id = ?", where_params=[1])
        p.stop()

        sql, params = executed[0]
        assert "Admin'--" not in sql
        assert "Admin'--" in params

    def test_delete_record_where_parametrized(self):
        from tools.dml import delete_record
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = capture
        mock_cursor.rowcount = 0
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings_for("tools.dml")
        with patch("tools.dml.get_connection", return_value=make_mock_cm(mock_conn)):
            delete_record(table="Users", where="id = ?", where_params=[5])
        p.stop()

        sql, params = executed[0]
        assert 5 in params


class TestDestructiveOperations:
    def test_drop_table_blocked_without_flag(self):
        p = _mock_settings_for("tools.ddl")
        from tools.ddl import drop_table
        with pytest.raises(PermissionError, match="destructiva"):
            drop_table(table="X")
        p.stop()

    def test_drop_sp_blocked_without_flag(self):
        p = _mock_settings_for("tools.stored_procedures")
        from tools.stored_procedures import drop_sp
        with pytest.raises(PermissionError, match="destructiva"):
            drop_sp(procedure="sp_X")
        p.stop()

    def test_execute_ddl_raw_blocks_drop(self):
        p = _mock_settings_for("tools.ddl")
        from tools.ddl import execute_ddl_raw
        with pytest.raises(PermissionError, match="destructivas"):
            execute_ddl_raw("DROP TABLE dbo.X")
        p.stop()

    def test_execute_ddl_raw_blocks_truncate(self):
        p = _mock_settings_for("tools.ddl")
        from tools.ddl import execute_ddl_raw
        with pytest.raises(PermissionError, match="destructivas"):
            execute_ddl_raw("TRUNCATE TABLE dbo.X")
        p.stop()


class TestMandatoryWhere:
    def test_update_empty_where_raises(self):
        from tools.dml import update_record
        with pytest.raises(ValueError, match="WHERE"):
            update_record(table="T", fields={"x": 1}, where="", where_params=[])

    def test_update_whitespace_where_raises(self):
        from tools.dml import update_record
        with pytest.raises(ValueError, match="WHERE"):
            update_record(table="T", fields={"x": 1}, where="   ", where_params=[])

    def test_delete_empty_where_raises(self):
        from tools.dml import delete_record
        with pytest.raises(ValueError, match="WHERE"):
            delete_record(table="T", where="", where_params=[])

    def test_delete_whitespace_where_raises(self):
        from tools.dml import delete_record
        with pytest.raises(ValueError, match="WHERE"):
            delete_record(table="T", where="   ", where_params=[])


class TestPermissions:
    def test_select_blocked(self):
        p = _mock_settings_for("tools.query", is_op_allowed=False)
        from tools.query import execute_query
        with pytest.raises(PermissionError, match="SELECT no está habilitada"):
            execute_query(table="T")
        p.stop()

    def test_insert_blocked(self):
        p = _mock_settings_for("tools.dml", is_op_allowed=False)
        from tools.dml import insert_record
        with pytest.raises(PermissionError):
            insert_record(table="T", data={"x": 1})
        p.stop()

    def test_update_blocked(self):
        p = _mock_settings_for("tools.dml", is_op_allowed=False)
        from tools.dml import update_record
        with pytest.raises(PermissionError):
            update_record(table="T", fields={"x": 1}, where="id=1", where_params=[])
        p.stop()

    def test_delete_blocked(self):
        p = _mock_settings_for("tools.dml", is_op_allowed=False)
        from tools.dml import delete_record
        with pytest.raises(PermissionError):
            delete_record(table="T", where="id=1", where_params=[])
        p.stop()

    def test_ddl_blocked(self):
        p = _mock_settings_for("tools.ddl", is_op_allowed=False)
        from tools.ddl import create_table
        with pytest.raises(PermissionError):
            create_table(table="T", columns=[{"name": "ID", "type": "INT"}])
        p.stop()

    def test_exec_sp_blocked(self):
        p = _mock_settings_for("tools.stored_procedures", is_op_allowed=False)
        from tools.stored_procedures import execute_sp
        with pytest.raises(PermissionError):
            execute_sp(procedure="sp_X")
        p.stop()

    def test_schema_not_allowed(self):
        p = _mock_settings_for("tools.query", is_schema_allowed=False)
        from tools.query import execute_query
        with pytest.raises(PermissionError, match="no est.*en la lista"):
            execute_query(table="T", schema="secret")
        p.stop()
