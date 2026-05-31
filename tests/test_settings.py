"""
Tests para config/settings.py.

NOTA: Settings es un dataclass frozen cuyos defaults evalúan os.getenv()
en tiempo de definición de clase (no de instancia). Como el módulo ya fue
importado cuando los tests corren (con .env real), los tests de defaults
puros no son viables sin reload(). En su lugar probamos:

- Construcción explícita con kwargs
- connection_string format
- Security guards via construcción con kwargs
- Encoding y prefijos
"""

from __future__ import annotations

import pytest

from config.settings import Settings


class TestConstruction:
    def test_default_construction(self):
        s = Settings(server="test", port=9999, database="testdb")
        assert s.server == "test"
        assert s.port == 9999
        assert s.database == "testdb"

    def test_kwargs_override(self):
        s = Settings(server="a", port=1, database="b", username="u", password="p",
                     query_timeout=60, log_params=False)
        assert s.server == "a"
        assert s.port == 1
        assert s.database == "b"
        assert s.username == "u"
        assert s.password == "p"
        assert s.query_timeout == 60
        assert s.log_params is False

    def test_frozen_instance(self):
        s = Settings()
        with pytest.raises(Exception):
            s.server = "other"


class TestConnectionString:
    def test_basic_format(self):
        s = Settings(server="localhost", port=1433, database="master", username="sa", password="")
        cs = s.connection_string
        assert "DRIVER=" in cs
        assert "SERVER=localhost,1433" in cs
        assert "DATABASE=master" in cs
        assert "UID=sa" in cs
        assert "PWD=" in cs

    def test_custom_values(self):
        s = Settings(server="dev-box", port=14330, database="northwind", username="admin", password="Secret123!")
        cs = s.connection_string
        assert "SERVER=dev-box,14330" in cs
        assert "DATABASE=northwind" in cs
        assert "UID=admin" in cs
        assert "PWD=Secret123!" in cs


class TestSecurityGuards:
    def test_is_op_allowed_allows_configured(self):
        s = Settings(allowed_ops=frozenset(["select", "insert", "update"]))
        assert s.is_op_allowed("SELECT")
        assert s.is_op_allowed("insert")
        assert not s.is_op_allowed("delete")
        assert not s.is_op_allowed("ddl")

    def test_is_op_allowed_case_insensitive(self):
        s = Settings(allowed_ops=frozenset(["select", "insert", "ddl"]))
        assert s.is_op_allowed("select")
        assert s.is_op_allowed("Insert")
        assert s.is_op_allowed("DDL")

    def test_is_op_allowed_blocked_op(self):
        s = Settings(allowed_ops=frozenset(["select"]))
        assert not s.is_op_allowed("drop_table")

    def test_is_schema_allowed_empty_allows_all(self):
        s = Settings(allowed_schemas=frozenset())
        assert s.is_schema_allowed("dbo")
        assert s.is_schema_allowed("any_schema")

    def test_is_schema_allowed_restricted(self):
        s = Settings(allowed_schemas=frozenset(["dbo", "translations"]))
        assert s.is_schema_allowed("dbo")
        assert s.is_schema_allowed("translations")
        assert not s.is_schema_allowed("sales")


class TestEncodingSettings:
    def test_default_encoding(self):
        s = Settings(char_encoding="cp1252", write_encoding="cp1252")
        assert s.char_encoding == "cp1252"
        assert s.write_encoding == "cp1252"

    def test_custom_encoding(self):
        s = Settings(char_encoding="utf-8", write_encoding="utf-8")
        assert s.char_encoding == "utf-8"
        assert s.write_encoding == "utf-8"


class TestDdlTablePrefix:
    def test_ddl_table_prefix_default(self):
        s = Settings(ddl_table_prefix="")
        assert s.ddl_table_prefix == ""

    def test_ddl_table_prefix_custom(self):
        s = Settings(ddl_table_prefix="tbl_,cat_")
        assert s.ddl_table_prefix == "tbl_,cat_"


class TestSingletonSettings:
    """Pruebas contra el singleton real (con .env cargado)."""

    def test_singleton_exists(self):
        from config import settings
        assert hasattr(settings, "server")
        assert hasattr(settings, "database")

    def test_singleton_connection_string(self):
        from config import settings
        cs = settings.connection_string
        assert "DRIVER=" in cs
        assert "SERVER=" in cs

    def test_singleton_is_op_allowed(self):
        from config import settings
        assert callable(settings.is_op_allowed)
