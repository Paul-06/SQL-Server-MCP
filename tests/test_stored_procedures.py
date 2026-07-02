"""
Tests para tools/stored_procedures.py:
- execute_sp (con/sin parámetros, RETURN value, múltiples resultsets)
- soporte TVP automático
- list_stored_procedures, describe_stored_procedure
- create_sp, alter_sp, drop_sp
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    make_mock_cm,
    make_mock_connection,
    make_mock_cursor,
    make_scripted_cursor,
)

MODULE = "tools.stored_procedures"

PARAM_COLUMNS = [
    "parameter_id",
    "name",
    "type",
    "max_length",
    "is_output",
    "has_default",
    "precision",
    "scale",
    "is_table_type",
    "type_schema",
    "type_name",
]

TVP_COLUMNS = [
    "parameter_name",
    "tvp_type_schema",
    "tvp_type_name",
    "ordinal",
    "name",
    "type_schema",
    "type_name",
    "base_type",
    "max_length",
    "precision",
    "scale",
    "nullable",
]


def _mock_settings(**kwargs):
    p = patch(f"{MODULE}.settings")
    mock = p.start()
    mock.is_op_allowed.return_value = kwargs.get("is_op_allowed", True)
    mock.is_schema_allowed.return_value = kwargs.get("is_schema_allowed", True)
    return p


def _tvp_param_rows(name: str = "@Items") -> list[list]:
    return [[1, name, "OrderItemType", -1, 0, 0, 0, 0, 1, "dbo", "OrderItemType"]]


def _tvp_column_rows(name: str = "@Items") -> list[list]:
    return [
        [name, "dbo", "OrderItemType", 1, "ProdCode", "dbo", "int", "int", 4, 10, 0, 0],
        [name, "dbo", "OrderItemType", 2, "Qty", "dbo", "int", "int", 4, 10, 0, 0],
    ]


def _make_tvp_cursor(
    exec_columns: list[str] | None = None,
    exec_rows: list[list] | None = None,
    nextsets: list[dict] | None = None,
    param_name: str = "@Items",
) -> MagicMock:
    return make_scripted_cursor(
        [
            {"columns": PARAM_COLUMNS, "rows": _tvp_param_rows(param_name)},
            {"columns": TVP_COLUMNS, "rows": _tvp_column_rows(param_name)},
            {
                "columns": exec_columns or ["Total"],
                "rows": exec_rows or [[42]],
                "nextsets": nextsets or [],
            },
        ]
    )


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
        assert result["params_used"] == []

    def test_execute_sp_with_scalar_params_and_name_normalization(self):
        mock_cursor = make_mock_cursor(columns=["Total"], rows=[[42]])
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            result = execute_sp(procedure="sp_GetById", params={"@Id": 5})
        p.stop()

        executed_sql, executed_params = mock_cursor.execute.call_args.args
        assert "@Id = ?" in executed_sql
        assert executed_params == [5]
        assert result["params_used"] == ["Id"]

    def test_execute_sp_accepts_qualified_procedure_name(self):
        mock_cursor = make_mock_cursor(columns=["Total"], rows=[[42]])
        mock_cursor.nextset.return_value = None
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            result = execute_sp(procedure="[GENERAL].[sp_GetById]", params={"Id": 5})
        p.stop()

        executed_sql = mock_cursor.execute.call_args.args[0]
        assert "EXEC @ret = [GENERAL].[sp_GetById] @Id = ?" in executed_sql
        assert result["procedure"] == "GENERAL.sp_GetById"

    def test_execute_sp_return_value_captured(self):
        mock_cursor = make_mock_cursor(columns=["return_value"], rows=[[42]])
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

    def test_execute_sp_tvp_from_dict_rows(self):
        mock_cursor = _make_tvp_cursor(
            nextsets=[{"columns": ["return_value"], "rows": [[0]]}]
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            result = execute_sp(
                procedure="sp_SaveItems",
                params={
                    "Items": [
                        {"ProdCode": 1, "Qty": 2},
                        {"Qty": 5, "ProdCode": 3},
                    ]
                },
            )
        p.stop()

        _, executed_params = mock_cursor.execute.call_args_list[-1].args
        assert executed_params == [["OrderItemType", "dbo", (1, 2), (3, 5)]]
        assert result["params_used"] == ["Items"]
        assert result["return_value"] == 0

    def test_execute_sp_tvp_from_list_rows(self):
        mock_cursor = _make_tvp_cursor()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            execute_sp(
                procedure="sp_SaveItems",
                params={"Items": [[1, 2], [3, 4]]},
            )
        p.stop()

        _, executed_params = mock_cursor.execute.call_args_list[-1].args
        assert executed_params == [["OrderItemType", "dbo", (1, 2), (3, 4)]]

    def test_execute_sp_tvp_from_tuple_rows(self):
        mock_cursor = _make_tvp_cursor()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            execute_sp(
                procedure="sp_SaveItems",
                params={"Items": [(1, 2), (3, 4)]},
            )
        p.stop()

        _, executed_params = mock_cursor.execute.call_args_list[-1].args
        assert executed_params == [["OrderItemType", "dbo", (1, 2), (3, 4)]]

    def test_execute_sp_tvp_empty_rows(self):
        mock_cursor = _make_tvp_cursor()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            execute_sp(procedure="sp_SaveItems", params={"Items": []})
        p.stop()

        _, executed_params = mock_cursor.execute.call_args_list[-1].args
        assert executed_params == [["OrderItemType", "dbo"]]

    def test_execute_sp_tvp_mixed_with_scalar_param(self):
        mock_cursor = make_scripted_cursor(
            [
                {
                    "columns": PARAM_COLUMNS,
                    "rows": [
                        [1, "@IdCliente", "int", 4, 0, 0, 10, 0, 0, "sys", "int"],
                        [2, "@Items", "OrderItemType", -1, 0, 0, 0, 0, 1, "dbo", "OrderItemType"],
                    ],
                },
                {"columns": TVP_COLUMNS, "rows": _tvp_column_rows()},
                {"columns": ["Total"], "rows": [[1]]},
            ]
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            result = execute_sp(
                procedure="sp_SaveItems",
                params={"IdCliente": 99, "Items": [{"ProdCode": 1, "Qty": 2}]},
            )
        p.stop()

        executed_sql, executed_params = mock_cursor.execute.call_args_list[-1].args
        assert "@IdCliente = ?, @Items = ?" in executed_sql
        assert executed_params == [99, ["OrderItemType", "dbo", (1, 2)]]
        assert result["params_used"] == ["IdCliente", "Items"]

    def test_execute_sp_tvp_rejects_missing_columns(self):
        mock_cursor = _make_tvp_cursor()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            with pytest.raises(ValueError, match="faltan columnas: Qty"):
                execute_sp(
                    procedure="sp_SaveItems",
                    params={"Items": [{"ProdCode": 1}]},
                )
        p.stop()

        assert mock_cursor.execute.call_count == 2

    def test_execute_sp_tvp_rejects_extra_columns(self):
        mock_cursor = _make_tvp_cursor()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            with pytest.raises(ValueError, match="sobran columnas: Precio"):
                execute_sp(
                    procedure="sp_SaveItems",
                    params={"Items": [{"ProdCode": 1, "Qty": 2, "Precio": 9}]},
                )
        p.stop()

        assert mock_cursor.execute.call_count == 2

    def test_execute_sp_tvp_rejects_inconsistent_row_length(self):
        mock_cursor = _make_tvp_cursor()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            with pytest.raises(ValueError, match="se esperaban 2 valores y llegaron 1"):
                execute_sp(
                    procedure="sp_SaveItems",
                    params={"Items": [[1]]},
                )
        p.stop()

        assert mock_cursor.execute.call_count == 2

    def test_execute_sp_tvp_rejects_none(self):
        mock_cursor = _make_tvp_cursor()
        mock_conn = make_mock_connection(mock_cursor)

        p = _mock_settings()
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import execute_sp

            with pytest.raises(ValueError, match="no acepta None"):
                execute_sp(
                    procedure="sp_SaveItems",
                    params={"Items": None},
                )
        p.stop()

        assert mock_cursor.execute.call_count == 2


class TestListStoredProcedures:
    def test_list_basic(self):
        mock_cursor = make_mock_cursor(
            columns=["schema", "name", "created", "modified"],
            rows=[["dbo", "sp_Test", "", ""]],
        )
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
        mock_cursor = make_mock_cursor(
            columns=PARAM_COLUMNS,
            rows=[[1, "@Id", "int", 4, 0, 0, 10, 0, 0, "sys", "int"]],
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_schema_allowed.return_value = True
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import describe_stored_procedure

            result = describe_stored_procedure(procedure="sp_Test")
        p.stop()

        assert result["total_params"] == 1
        assert result["optional_params"] == 0
        assert result["parameters"][0]["is_table_type"] == 0
        assert result["parameters"][0]["tvp_columns"] == []

    def test_describe_includes_tvp_metadata_and_qualified_name(self):
        mock_cursor = make_scripted_cursor(
            [
                {"columns": PARAM_COLUMNS, "rows": _tvp_param_rows()},
                {"columns": TVP_COLUMNS, "rows": _tvp_column_rows()},
            ]
        )
        mock_conn = make_mock_connection(mock_cursor)

        p = patch(f"{MODULE}.settings")
        mock_s = p.start()
        mock_s.is_schema_allowed.return_value = True
        with patch(f"{MODULE}.get_connection", return_value=make_mock_cm(mock_conn)):
            from tools.stored_procedures import describe_stored_procedure

            result = describe_stored_procedure(procedure="sales.sp_SaveItems")
        p.stop()

        assert result["procedure"] == "sales.sp_SaveItems"
        assert result["parameters"][0]["is_table_type"] == 1
        assert result["parameters"][0]["type_schema"] == "dbo"
        assert result["parameters"][0]["type_name"] == "OrderItemType"
        assert result["parameters"][0]["tvp_columns"][0]["name"] == "ProdCode"
        assert result["parameters"][0]["tvp_columns"][1]["name"] == "Qty"


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
