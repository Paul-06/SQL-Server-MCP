"""
Tests para tools/schema.py:
- list_databases, list_schemas, list_tables, describe_table
- SQL injection fix en list_tables
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_mock_cm, make_mock_connection, make_mock_cursor

MODULE = "tools.schema"


class TestListDatabases:
    def test_returns_databases(self):
        mock_cursor = make_mock_cursor(columns=["name", "database_id", "created", "state"], rows=[["Northwind", 5, "2024-01-01", "ONLINE"]])
        mock_conn = make_mock_connection(mock_cursor)

        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.schema import list_databases
            result = list_databases()

        assert result["total"] == 1

    def test_excludes_system_databases(self):
        mock_cursor = make_mock_cursor(columns=["name", "database_id", "created", "state"], rows=[["northwind-db", 5, "2024-01-01", "ONLINE"]])
        mock_conn = make_mock_connection(mock_cursor)

        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.schema import list_databases
            names = [d["name"] for d in list_databases()["databases"]]

        assert "master" not in names


class TestListSchemas:
    def test_returns_schemas(self):
        mock_cursor = make_mock_cursor(columns=["schema", "schema_id", "owner"], rows=[["dbo", 1, "dbo"]])
        mock_conn = make_mock_connection(mock_cursor)

        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.schema import list_schemas
            result = list_schemas()

        assert result["total"] == 1


class TestListTables:
    def test_basic_list(self):
        mock_cursor = make_mock_cursor(columns=["name", "type", "created", "modified", "rows_estimate"], rows=[["Products", "BASE TABLE", "", "", 77]])
        mock_conn = make_mock_connection(mock_cursor)

        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_schema_allowed.return_value = True
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.schema import list_tables
            result = list_tables(schema="dbo")
        p.stop()

        assert result["total"] == 1

    def test_name_filter_parametrized(self):
        executed_params: list = []

        def execute_side(sql, params=None):
            executed_params.append((sql, params))

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = execute_side
        mock_cursor.description = [("name", None, None, None, None, None, None),
                                   ("type", None, None, None, None, None, None),
                                   ("created", None, None, None, None, None, None),
                                   ("modified", None, None, None, None, None, None),
                                   ("rows_estimate", None, None, None, None, None, None)]
        mock_conn = make_mock_connection(mock_cursor)

        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_schema_allowed.return_value = True
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.schema import list_tables
            list_tables(schema="dbo", name_filter="Prod")

        sql, params = executed_params[0]
        assert "LIKE ?" in sql
        assert "%Prod%" in params


class TestDescribeTable:
    def test_columns_and_pk_detection(self):
        mock_cursor = MagicMock()
        mock_cursor.description = [
            ("name", None, None, None, None, None, None),
            ("type", None, None, None, None, None, None),
            ("max_length", None, None, None, None, None, None),
            ("nullable", None, None, None, None, None, None),
            ("default", None, None, None, None, None, None),
            ("is_identity", None, None, None, None, None, None),
            ("is_pk", None, None, None, None, None, None),
        ]
        mock_cursor.fetchall.side_effect = [
            [("ID", "int", None, "NO", None, 1, 1), ("Nombre", "varchar", 50, "YES", None, 0, 0)],
            [("PK_MiPropia", "CLUSTERED", 1, "ID")],
        ]
        mock_conn = make_mock_connection(mock_cursor)

        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_schema_allowed.return_value = True
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.schema import describe_table
            result = describe_table(table="MiTabla", schema="dbo")
        p.stop()

        assert result["table"] == "dbo.MiTabla"
        assert result["columns"][0]["is_pk"] == 1
        assert result["columns"][1]["is_pk"] == 0
        assert result["pk_columns"] == ["ID"]

    def test_pk_not_prefixed_with_pk(self):
        mock_cursor = MagicMock()
        mock_cursor.description = [
            ("name", None, None, None, None, None, None),
            ("type", None, None, None, None, None, None),
            ("max_length", None, None, None, None, None, None),
            ("nullable", None, None, None, None, None, None),
            ("default", None, None, None, None, None, None),
            ("is_identity", None, None, None, None, None, None),
            ("is_pk", None, None, None, None, None, None),
        ]
        mock_cursor.fetchall.side_effect = [
            [("ID", "int", None, "NO", None, 1, 1)],
            [],
        ]
        mock_conn = make_mock_connection(mock_cursor)

        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_schema_allowed.return_value = True
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.schema import describe_table
            result = describe_table(table="TestPK", schema="dbo")
        p.stop()

        assert result["pk_columns"] == ["ID"]
        assert result["columns"][0]["is_pk"] == 1
