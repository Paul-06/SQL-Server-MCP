"""
Tests para tools/stored_procedures.py:
- execute_sp (con/sin parámetros, RETURN value, múltiples resultsets)
- list_stored_procedures, describe_stored_procedure
- create_sp, alter_sp, drop_sp
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_mock_cm, make_mock_connection, make_mock_cursor

MODULE = "tools.stored_procedures"


def _mock_settings(**kwargs):
    p = patch(f"{MODULE}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    mock.is_schema_allowed.return_value = kwargs.get("is_schema_allowed", True)
    return p


class TestExecuteSp:
    def test_execute_sp_no_params(self):
        mock_cursor = make_mock_cursor(columns=["Id", "Name"], rows=[[1, "Test"]])
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp
            result = execute_sp(procedure="sp_Test")
        p.stop()

        assert len(result["resultsets"]) == 1

    def test_execute_sp_with_params(self):
        mock_cursor = make_mock_cursor(columns=["Total"], rows=[[42]])
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp
            result = execute_sp(procedure="sp_GetById", params={"Id": 5})
        p.stop()

        assert result["params_used"] == ["Id"]

    def test_execute_sp_return_value_captured(self):
        mock_cursor = MagicMock()
        mock_cursor.description = [("return_value", None, None, None, None, None, None)]
        mock_cursor.fetchall.return_value = [(42,)]
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp
            result = execute_sp(procedure="sp_WithReturn", params={"Input": 21})
        p.stop()

        assert result["return_value"] == 42

    def test_execute_sp_multiple_resultsets(self):
        mock_cursor = MagicMock()
        mock_cursor.description = [("Col1", None, None, None, None, None, None)]
        mock_cursor.fetchall.return_value = [("A",)]

        call_count = [0]
        def nextset_side():
            call_count[0] += 1
            if call_count[0] == 1:
                mock_cursor.description = [("Col2", None, None, None, None, None, None)]
                mock_cursor.fetchall.return_value = [("B",)]
                return True
            return None

        mock_cursor.nextset.side_effect = nextset_side
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp
            result = execute_sp(procedure="sp_Multi")
        p.stop()

        assert len(result["resultsets"]) == 2

    def test_execute_sp_raises_on_permission(self):
        p = _mock_settings(is_op_allowed=False)
        from tools.stored_procedures import execute_sp
        with pytest.raises(PermissionError, match="stored procedures no está habilitada"):
            execute_sp(procedure="sp_X")
        p.stop()


class TestListStoredProcedures:
    def test_list_basic(self):
        mock_cursor = make_mock_cursor(columns=["schema", "name", "created", "modified"], rows=[["dbo", "sp_Test", "", ""]])
        mock_conn = make_mock_connection(mock_cursor)

        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_schema_allowed.return_value = True
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import list_stored_procedures
            result = list_stored_procedures(schema="dbo")
        p.stop()

        assert result["total"] == 1


class TestDescribeStoredProcedure:
    def test_describe_with_optional_params(self):
        mock_cursor = make_mock_cursor(columns=["name", "type", "max_length", "is_output", "has_default"], rows=[["@Id", "int", 4, 0, 0], ["@Name", "varchar", 50, 0, 1]])
        mock_conn = make_mock_connection(mock_cursor)

        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_schema_allowed.return_value = True
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import describe_stored_procedure
            result = describe_stored_procedure(procedure="sp_Test")
        p.stop()

        assert result["total_params"] == 2
        assert result["optional_params"] == 1


class TestCreateAlterDropSp:
    def test_create_sp(self):
        mock_cursor = MagicMock()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import create_sp
            result = create_sp(procedure="sp_Nuevo", definition="@Id INT AS BEGIN SELECT @Id END")
        p.stop()

        assert result["created"] is True
        assert "CREATE PROCEDURE" in result["ddl"]

    def test_alter_sp(self):
        mock_cursor = MagicMock()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import alter_sp
            result = alter_sp(procedure="sp_Nuevo", definition="@Id INT AS BEGIN SELECT @Id END")
        p.stop()

        assert result["altered"] is True
        assert "ALTER PROCEDURE" in result["ddl"]

    def test_drop_sp_without_destructive_raises(self):
        p = _mock_settings()
        from tools.stored_procedures import drop_sp
        with pytest.raises(PermissionError, match="destructiva"):
            drop_sp(procedure="sp_X")
        p.stop()

    def test_drop_sp_success(self):
        mock_cursor = MagicMock()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import drop_sp
            result = drop_sp(procedure="sp_X", allow_destructive=True)
        p.stop()

        assert result["dropped"] is True
