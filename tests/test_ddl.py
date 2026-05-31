"""
Tests para tools/ddl.py:
- create_table, drop_table, alter_table, execute_ddl_raw
- Seguridad: ddl_table_prefix, permisos, guardia destructiva
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_mock_connection

MODULE = "tools.ddl"


def _mock_settings(**kwargs):
    """Parchea todo el objeto settings en el módulo target."""
    p = patch(f"{MODULE}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    mock.is_schema_allowed.return_value = kwargs.get("is_schema_allowed", True)
    mock.ddl_table_prefix = kwargs.get("ddl_table_prefix", "")
    return p


class TestCreateTable:
    def test_create_table_basic(self):
        mock_cursor = MagicMock()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import create_table
            result = create_table(table="TestTable", columns=[
                {"name": "ID", "type": "INT", "nullable": False, "primary_key": True, "identity": True},
                {"name": "Nombre", "type": "VARCHAR(100)"},
            ])
        p.stop()

        assert result["created"] is True
        assert "IDENTITY(1,1)" in result["ddl"]
        assert "PRIMARY KEY" in result["ddl"]

    def test_create_table_ddl_table_prefix_restriction(self):
        p = _mock_settings(ddl_table_prefix="tbl_")
        from tools.ddl import create_table
        with pytest.raises(PermissionError, match="prefijo"):
            create_table(table="bad_name", columns=[{"name": "ID", "type": "INT"}])
        p.stop()

    def test_create_table_raises_on_permission(self):
        p = _mock_settings(is_op_allowed=False)
        from tools.ddl import create_table
        with pytest.raises(PermissionError, match="DDL no están habilitadas"):
            create_table(table="T", columns=[{"name": "ID", "type": "INT"}])
        p.stop()


class TestDropTable:
    def test_drop_table_without_allow_destructive_raises(self):
        p = _mock_settings()
        from tools.ddl import drop_table
        with pytest.raises(PermissionError, match="destructiva"):
            drop_table(table="AuditLog")
        p.stop()

    def test_drop_table_success(self):
        mock_cursor = MagicMock()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import drop_table
            result = drop_table(table="TestTable", allow_destructive=True)
        p.stop()

        assert result["dropped"] is True

    def test_drop_table_sql_structure(self):
        executed_sql: list[str] = []

        def execute_side(sql: str):
            executed_sql.append(sql)

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = execute_side
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import drop_table
            drop_table(table="MiTabla", schema="dbo", allow_destructive=True)
        p.stop()

        assert "DROP TABLE IF EXISTS" in executed_sql[0]
        assert "[dbo].[MiTabla]" in executed_sql[0]


class TestAlterTable:
    def test_alter_table_add_column(self):
        mock_cursor = MagicMock()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import alter_table
            result = alter_table(table="MiTabla", action="ADD", column_name="Email", column_type="VARCHAR(100)")
        p.stop()

        assert result["altered"] is True
        assert "ADD [Email]" in result["ddl"]

    def test_alter_table_invalid_action(self):
        p = _mock_settings()
        from tools.ddl import alter_table
        with pytest.raises(ValueError, match="no soportada"):
            alter_table(table="T", action="DROP", column_name="x")
        p.stop()


class TestExecuteDdlRaw:
    def test_destructive_blocked(self):
        p = _mock_settings()
        from tools.ddl import execute_ddl_raw
        with pytest.raises(PermissionError, match="destructivas"):
            execute_ddl_raw("DROP TABLE dbo.X")
        p.stop()

    def test_destructive_allowed_with_flag(self):
        mock_cursor = MagicMock()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import execute_ddl_raw
            result = execute_ddl_raw("DROP TABLE IF EXISTS dbo.X", allow_destructive=True)
        p.stop()

        assert result["executed"] is True

    def test_truncate_blocked(self):
        p = _mock_settings()
        from tools.ddl import execute_ddl_raw
        with pytest.raises(PermissionError, match="destructivas"):
            execute_ddl_raw("TRUNCATE TABLE dbo.X")
        p.stop()

    def test_safe_ddl_allows(self):
        mock_cursor = MagicMock()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import execute_ddl_raw
            result = execute_ddl_raw("CREATE INDEX idx_x ON dbo.X (id)")
        p.stop()

        assert result["executed"] is True
