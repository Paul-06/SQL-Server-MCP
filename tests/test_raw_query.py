"""
Tests para tools/raw_query.py:
- execute_raw_select básico con columnas y filas
- Parámetros (placeholders ?)
- Paginación: OFFSET/FETCH inyectado, has_more
- Validación de seguridad: rechaza INSERT, UPDATE, DELETE, DDL, EXEC
- Permite WITH...SELECT (CTEs)
- Respeta MSSQL_ALLOWED_OPS
- database override inyecta USE [db]
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_mock_connection, make_mock_cursor

MODULE = "tools.raw_query"


def _mock_settings(**kwargs):
    p = patch(f"{MODULE}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    return p


class TestExecuteRawSelect:
    def test_basic_select(self):
        mock_cursor = make_mock_cursor(
            columns=["Id", "Name"],
            rows=[[1, "Alice"], [2, "Bob"]],
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.raw_query import execute_raw_select
            result = execute_raw_select(sql="SELECT Id, Name FROM Users")
        p.stop()

        assert result["columns"] == ["Id", "Name"]
        assert len(result["rows"]) == 2
        assert result["page"] == 1
        assert result["has_more"] is False

    def test_with_params(self):
        mock_cursor = make_mock_cursor(
            columns=["Id", "Name"],
            rows=[[1, "Alice"]],
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.raw_query import execute_raw_select
            executed_params = []

            def capture_execute(sql, params=None):
                executed_params.append(params)
                return mock_cursor

            mock_cursor.execute.side_effect = capture_execute
            result = execute_raw_select(
                sql="SELECT Id, Name FROM Users WHERE Status = ?",
                params=["active"],
            )
        p.stop()

        assert result["columns"] == ["Id", "Name"]
        assert executed_params[0] == ["active"]

    def test_pagination_injects_offset_fetch(self):
        mock_cursor = make_mock_cursor(columns=["Id"], rows=[[1]])
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.raw_query import execute_raw_select
            executed_sqls = []

            def capture_execute(sql, params=None):
                executed_sqls.append(sql)
                return mock_cursor

            mock_cursor.execute.side_effect = capture_execute
            execute_raw_select(
                sql="SELECT Id FROM Users",
                page=2,
                page_size=10,
            )
        p.stop()

        assert "OFFSET 10 ROWS" in executed_sqls[0]
        assert "FETCH NEXT 11 ROWS ONLY" in executed_sqls[0]
        assert "ORDER BY (SELECT NULL)" in executed_sqls[0]

    def test_pagination_preserves_existing_order_by(self):
        mock_cursor = make_mock_cursor(columns=["Id"], rows=[[1]])
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.raw_query import execute_raw_select
            executed_sqls = []

            def capture_execute(sql, params=None):
                executed_sqls.append(sql)
                return mock_cursor

            mock_cursor.execute.side_effect = capture_execute
            execute_raw_select(
                sql="SELECT Id FROM Users ORDER BY Name DESC",
                page=1,
                page_size=5,
            )
        p.stop()

        sql = executed_sqls[0]
        assert "ORDER BY Name DESC" in sql
        assert "ORDER BY (SELECT NULL)" not in sql
        assert "OFFSET 0 ROWS" in sql
        assert "FETCH NEXT 6 ROWS ONLY" in sql

    def test_has_more_true(self):
        mock_cursor = make_mock_cursor(
            columns=["Id"],
            rows=[[1], [2], [3], [4], [5], [6]],
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.raw_query import execute_raw_select
            result = execute_raw_select(
                sql="SELECT Id FROM Users",
                page_size=5,
            )
        p.stop()

        assert len(result["rows"]) == 5
        assert result["has_more"] is True

    def test_database_override_injects_use(self):
        mock_cursor = make_mock_cursor(columns=["Id"], rows=[[1]])
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.raw_query import execute_raw_select
            executed_sqls = []

            def capture_execute(sql, params=None):
                executed_sqls.append(sql)
                return mock_cursor

            mock_cursor.execute.side_effect = capture_execute
            execute_raw_select(
                sql="SELECT Id FROM Users",
                database="Northwind",
            )
        p.stop()

        assert executed_sqls[0].startswith("USE [Northwind];")

    def test_rejects_insert(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="INSERT INTO T VALUES (1)")
        p.stop()

    def test_rejects_update(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="UPDATE T SET x = 1 WHERE id = 1")
        p.stop()

    def test_rejects_delete(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="DELETE FROM T WHERE id = 1")
        p.stop()

    def test_rejects_merge(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="MERGE T AS target USING S AS src ON 1=1 WHEN MATCHED THEN UPDATE SET x = 1;")
        p.stop()

    def test_rejects_exec(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="tool_execute_sp") as exc:
            execute_raw_select(sql="EXEC sp_help")
        assert 'procedure="sp_help"' in str(exc.value)
        assert 'schema="dbo"' in str(exc.value)
        p.stop()

    def test_rejects_execute(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="tool_execute_sp"):
            execute_raw_select(sql="EXECUTE sp_help")
        p.stop()

    def test_rejects_exec_with_schema_and_params_guidance(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="tool_execute_sp") as exc:
            execute_raw_select(sql="EXEC [GENERAL].[SP_LISTA_PAIS] @ID = '', @Activo = 1")
        assert 'procedure="SP_LISTA_PAIS"' in str(exc.value)
        assert 'schema="GENERAL"' in str(exc.value)
        assert '"ID": ...' in str(exc.value)
        assert '"Activo": ...' in str(exc.value)
        p.stop()

    def test_rejects_create_table(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="CREATE TABLE T (id INT)")
        p.stop()

    def test_rejects_alter_table(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="ALTER TABLE T ADD x INT")
        p.stop()

    def test_rejects_drop_table(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="DROP TABLE T")
        p.stop()

    def test_rejects_truncate(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="TRUNCATE TABLE T")
        p.stop()

    def test_rejects_grant(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="GRANT SELECT ON T TO user")
        p.stop()

    def test_rejects_revoke(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no permitidas"):
            execute_raw_select(sql="REVOKE SELECT ON T FROM user")
        p.stop()

    def test_rejects_non_select_start(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no comienza con SELECT/WITH"):
            execute_raw_select(sql="dbo.sp_help")
        p.stop()

    def test_allows_with_cte(self):
        mock_cursor = make_mock_cursor(
            columns=["Id", "Name"],
            rows=[[1, "Alice"]],
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.raw_query import execute_raw_select
            result = execute_raw_select(
                sql="WITH cte AS (SELECT * FROM Users) SELECT * FROM cte"
            )
        p.stop()

        assert result["columns"] == ["Id", "Name"]

    def test_allows_complex_sql(self):
        mock_cursor = make_mock_cursor(
            columns=["OrderId", "CustomerName", "Total"],
            rows=[[1, "Alice Corp", 150.0]],
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=mock_conn.__enter__.return_value):
            from tools.raw_query import execute_raw_select
            result = execute_raw_select(
                sql=(
                    "SELECT o.Id AS OrderId, c.Name AS CustomerName, "
                    "SUM(od.Quantity * od.UnitPrice) AS Total "
                    "FROM Orders o "
                    "JOIN Customers c ON o.CustomerID = c.CustomerID "
                    "JOIN OrderDetails od ON o.Id = od.OrderId "
                    "GROUP BY o.Id, c.Name "
                    "HAVING SUM(od.Quantity * od.UnitPrice) > ?"
                ),
                params=[100.0],
            )
        p.stop()

        assert len(result["rows"]) == 1
        assert result["rows"][0]["OrderId"] == 1

    def test_raises_on_permission_not_allowed(self):
        p = _mock_settings(is_op_allowed=False)
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="no está habilitada"):
            execute_raw_select(sql="SELECT 1 AS x")
        p.stop()

    def test_empty_sql_rejected(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="SQL vacío"):
            execute_raw_select(sql="   ")
        p.stop()

    def test_only_comment_rejected(self):
        p = _mock_settings()
        from tools.raw_query import execute_raw_select
        with pytest.raises(PermissionError, match="comienza con SELECT/WITH"):
            execute_raw_select(sql="-- solo un comentario")
        p.stop()
