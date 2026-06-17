"""
Tests para tools/query.py:
- execute_query basico con columnas y filas
- Expresiones (COUNT, SUM, AS) no se bracketean
- TOP N sin paginacion
- DISTINCT
- GROUP BY
- HAVING requiere GROUP BY
- Paginacion con GROUP BY
- Parametros y placeholders
- Permisos
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_mock_cm, make_mock_connection, make_mock_cursor

MODULE = "tools.query"


def _mock_settings(**kwargs):
    p = patch(f"{MODULE}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    mock.is_schema_allowed.return_value = kwargs.get("is_schema_allowed", True)
    return p


class TestExecuteQuery:
    def test_basic_select(self):
        mock_cursor = make_mock_cursor(columns=["Id"], rows=[[1]])
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            result = execute_query(table="Users")
        p.stop()

        assert result["columns"] == ["Id"]

    def test_simple_column_bracketed(self):
        mock_cursor = make_mock_cursor(columns=["Id", "Name"], rows=[[1, "Test"]])
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            execute_query(table="Users", columns=["Id", "Name"])
        p.stop()

        assert "[Id]" in executed[0][0]
        assert "[Name]" in executed[0][0]

    def test_expression_column_not_bracketed(self):
        mock_cursor = make_mock_cursor(columns=["Total"], rows=[[42]])
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            execute_query(table="Orders", columns=["COUNT(*) AS Total"])
        p.stop()

        sql = executed[0][0]
        assert "COUNT(*) AS Total" in sql
        assert "[COUNT(*)" not in sql

    def test_expression_mixed_columns(self):
        mock_cursor = make_mock_cursor(columns=["Id", "Total"], rows=[[1, 42]])
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            execute_query(
                table="Orders",
                columns=["Id", "COUNT(*) AS Total"],
            )
        p.stop()

        sql = executed[0][0]
        assert "[Id]" in sql
        assert "COUNT(*) AS Total" in sql

    def test_top_n(self):
        mock_cursor = make_mock_cursor(columns=["Id"], rows=[[1], [2], [3]])
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            result = execute_query(table="Users", top=3, order_by="Id DESC")
        p.stop()

        sql = executed[0][0]
        assert "TOP 3" in sql
        assert "ORDER BY Id DESC" in sql
        assert "OFFSET" not in sql
        assert result["has_more"] is False

    def test_top_n_no_pagination(self):
        mock_cursor = make_mock_cursor(columns=["Id"], rows=[[1], [2]])
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            result = execute_query(table="Users", top=2)
        p.stop()

        sql = executed[0][0]
        assert "TOP 2" in sql
        assert "OFFSET" not in sql
        assert result["has_more"] is False
        assert result["page_size"] == 2

    def test_distinct(self):
        mock_cursor = make_mock_cursor(columns=["City"], rows=[["Lima"]])
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            execute_query(table="Users", columns=["City"], distinct=True)
        p.stop()

        assert "SELECT DISTINCT" in executed[0][0]

    def test_group_by_with_pagination(self):
        mock_cursor = make_mock_cursor(
            columns=["Status", "Total"],
            rows=[["Active", 10], ["Inactive", 5]],
        )
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            execute_query(
                table="Orders",
                columns=["Status", "COUNT(*) AS Total"],
                group_by="Status",
                where="Active = ?",
                where_params=[1],
            )
        p.stop()

        sql = executed[0][0]
        assert "GROUP BY Status" in sql
        assert "WHERE Active = ?" in sql
        assert "OFFSET" in sql

    def test_having_requires_group_by(self):
        from tools.query import execute_query

        with pytest.raises(ValueError, match="HAVING requiere"):
            execute_query(table="Orders", columns=["Status", "COUNT(*) AS Total"], having="COUNT(*) > 5")

    def test_group_by_with_top(self):
        mock_cursor = make_mock_cursor(
            columns=["Status", "Total"],
            rows=[["Active", 10]],
        )
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            execute_query(
                table="Orders",
                columns=["Status", "COUNT(*) AS Total"],
                group_by="Status",
                top=5,
                order_by="COUNT(*) DESC",
            )
        p.stop()

        sql = executed[0][0]
        assert "TOP 5" in sql
        assert "GROUP BY Status" in sql
        assert "ORDER BY COUNT(*) DESC" in sql
        assert "OFFSET" not in sql

    def test_having(self):
        mock_cursor = make_mock_cursor(
            columns=["Status", "Total"],
            rows=[["Active", 10]],
        )
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            execute_query(
                table="Orders",
                columns=["Status", "COUNT(*) AS Total"],
                group_by="Status",
                having="COUNT(*) > ?",
                where_params=[5],
                page=1,
                page_size=10,
            )
        p.stop()

        sql = executed[0][0]
        assert "HAVING COUNT(*) > ?" in sql
        assert "GROUP BY Status" in sql

    def test_with_params(self):
        mock_cursor = make_mock_cursor(columns=["Id"], rows=[[1]])
        mock_conn = make_mock_connection(mock_cursor)
        executed = []

        def capture(sql, params=None):
            executed.append((sql, params))
            return mock_cursor

        mock_cursor.execute.side_effect = capture

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.query import execute_query
            execute_query(table="Users", where="Status = ?", where_params=["active"])
        p.stop()

        assert executed[0][1] == ["active"]

    def test_schema_blocked(self):
        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_op_allowed.return_value = True
        mock_s.is_schema_allowed.return_value = False
        from tools.query import execute_query
        with pytest.raises(PermissionError, match="no esta"):
            execute_query(table="T", schema="secret")
        p.stop()

    def test_operation_blocked(self):
        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_op_allowed.return_value = False
        from tools.query import execute_query
        with pytest.raises(PermissionError, match="no esta habilitada"):
            execute_query(table="T")
        p.stop()
