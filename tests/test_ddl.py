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
    mock.ddl_schema_owner = kwargs.get("ddl_schema_owner", "mcp_agent_role")
    mock.database = kwargs.get("database", "master")
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


class TestCreateSchema:
    def test_create_schema_basic(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import create_schema
            result = create_schema(schema="Reporting")
        p.stop()

        assert result["created"] is True
        assert result["schema"] == "Reporting"
        assert result["owner"] == "mcp_agent_role"
        assert "CREATE SCHEMA [Reporting] AUTHORIZATION [mcp_agent_role]" in result["ddl"]
        assert mock_cursor.execute.call_count == 2
        assert mock_cursor.execute.call_args_list[0].args[1] == ["Reporting"]

    def test_create_schema_is_idempotent(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [42]
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import create_schema
            result = create_schema(schema="Reporting", if_not_exists=True)
        p.stop()

        assert result["created"] is False
        assert result["schema"] == "Reporting"
        assert mock_cursor.execute.call_count == 1

    def test_create_schema_requires_ddl(self):
        p = _mock_settings(is_op_allowed=False)
        from tools.ddl import create_schema
        with pytest.raises(PermissionError, match="DDL no están habilitadas"):
            create_schema(schema="Reporting")
        p.stop()

    def test_create_schema_requires_allowed_schema(self):
        p = _mock_settings(is_schema_allowed=False)
        from tools.ddl import create_schema
        with pytest.raises(PermissionError, match="no permitido"):
            create_schema(schema="Secret")
        p.stop()

    def test_create_schema_rejects_other_database(self):
        p = _mock_settings(database="TumiCloud")
        from tools.ddl import create_schema
        with pytest.raises(PermissionError, match="base configurada"):
            create_schema(schema="Reporting", database="OtherDb")
        p.stop()

    def test_create_schema_escapes_identifier(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.ddl import create_schema
            result = create_schema(schema="safe]name")
        p.stop()

        assert "CREATE SCHEMA [safe]]name] AUTHORIZATION [mcp_agent_role];" == result["ddl"]

    @pytest.mark.parametrize("schema", ["", "   ", "a" * 129])
    def test_create_schema_rejects_invalid_identifier(self, schema):
        p = _mock_settings()
        from tools.ddl import create_schema
        with pytest.raises(ValueError):
            create_schema(schema=schema)
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

    def test_create_schema_must_use_structured_tool(self):
        p = _mock_settings()
        from tools.ddl import execute_ddl_raw
        with pytest.raises(PermissionError, match="tool_create_schema"):
            execute_ddl_raw("CREATE /* bypass */ SCHEMA Reporting")
        p.stop()
