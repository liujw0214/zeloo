"""Unit tests for tools/database_tool.py.

Covers:
- DatabaseDriver enum
- DatabaseConnection dataclass
- parse_connection_string (URL and key=value formats)
- DatabaseTool CRUD on in-memory / SQLite databases
- list_tables / describe_table / list_databases / backup / explain_query
- close_all / connection caching
- @tool-decorated function registration
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from tools.database_tool import (  # noqa: E402
    DatabaseConnection,
    DatabaseDriver,
    DatabaseQueryResult,
    DatabaseTool,
    db_backup,
    db_describe_table,
    db_execute,
    db_explain,
    db_list_databases,
    db_list_tables,
    db_query,
    parse_connection_string,
)


# ─────────────────────────────────────────────────────────────────────────────
# Enum + dataclass
# ─────────────────────────────────────────────────────────────────────────────


class TestDatabaseDriver:
    def test_enum_values(self) -> None:
        assert DatabaseDriver.MYSQL.value == "mysql"
        assert DatabaseDriver.POSTGRESQL.value == "postgresql"
        assert DatabaseDriver.SQLITE.value == "sqlite"

    def test_enum_from_value(self) -> None:
        assert DatabaseDriver("mysql") is DatabaseDriver.MYSQL
        assert DatabaseDriver("postgresql") is DatabaseDriver.POSTGRESQL
        assert DatabaseDriver("sqlite") is DatabaseDriver.SQLITE

    def test_enum_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            DatabaseDriver("oracle")


class TestDatabaseConnection:
    def test_defaults(self) -> None:
        conn = DatabaseConnection(
            driver=DatabaseDriver.SQLITE,
            host="",
            port=0,
            database="",
            user="",
            password="",
        )
        assert conn.ssl is False

    def test_attributes(self) -> None:
        conn = DatabaseConnection(
            driver=DatabaseDriver.MYSQL,
            host="db.example.com",
            port=3306,
            database="app",
            user="alice",
            password="secret",
            ssl=True,
        )
        assert conn.host == "db.example.com"
        assert conn.port == 3306
        assert conn.database == "app"
        assert conn.user == "alice"
        assert conn.password == "secret"
        assert conn.ssl is True


class TestDatabaseQueryResult:
    def test_defaults(self) -> None:
        r = DatabaseQueryResult(rows=[], row_count=0)
        assert r.affected_rows == 0
        assert r.execution_time_ms == 0.0
        assert r.columns == []
        assert r.query == ""

    def test_attributes(self) -> None:
        r = DatabaseQueryResult(
            rows=[{"a": 1}],
            row_count=1,
            affected_rows=0,
            execution_time_ms=12.5,
            query="SELECT 1",
            columns=["a"],
        )
        assert r.rows == [{"a": 1}]
        assert r.columns == ["a"]


# ─────────────────────────────────────────────────────────────────────────────
# parse_connection_string
# ─────────────────────────────────────────────────────────────────────────────


class TestParseConnectionString:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_connection_string("")

    def test_sqlite_url_absolute(self) -> None:
        conn = parse_connection_string("sqlite:///tmp/test.db")
        assert conn.driver == DatabaseDriver.SQLITE
        assert conn.database.endswith("test.db")

    def test_sqlite_url_in_memory(self) -> None:
        conn = parse_connection_string("sqlite:///:memory:")
        assert conn.driver == DatabaseDriver.SQLITE

    def test_postgresql_url_full(self) -> None:
        conn = parse_connection_string(
            "postgresql://user:pass@localhost:5432/mydb"
        )
        assert conn.driver == DatabaseDriver.POSTGRESQL
        assert conn.host == "localhost"
        assert conn.port == 5432
        assert conn.user == "user"
        assert conn.password == "pass"
        assert conn.database == "mydb"

    def test_postgres_alias(self) -> None:
        conn = parse_connection_string("postgres://u:p@h:5432/db")
        assert conn.driver == DatabaseDriver.POSTGRESQL

    def test_mysql_url(self) -> None:
        conn = parse_connection_string("mysql://root:secret@db.local:3306/app")
        assert conn.driver == DatabaseDriver.MYSQL
        assert conn.host == "db.local"
        assert conn.port == 3306
        assert conn.user == "root"
        assert conn.password == "secret"
        assert conn.database == "app"

    def test_kv_format_mysql(self) -> None:
        conn = parse_connection_string(
            "driver=mysql,host=localhost,port=3306,database=mydb,user=root,password=secret"
        )
        assert conn.driver == DatabaseDriver.MYSQL
        assert conn.host == "localhost"
        assert conn.port == 3306
        assert conn.database == "mydb"

    def test_kv_format_postgres(self) -> None:
        conn = parse_connection_string("driver=postgresql,host=h,database=d,user=u")
        assert conn.driver == DatabaseDriver.POSTGRESQL
        assert conn.host == "h"
        assert conn.user == "u"

    def test_kv_format_sqlite(self) -> None:
        conn = parse_connection_string("driver=sqlite,database=foo.db")
        assert conn.driver == DatabaseDriver.SQLITE
        assert conn.database == "foo.db"

    def test_kv_missing_driver_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_connection_string("host=localhost,database=db")

    def test_kv_unknown_driver_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_connection_string("driver=oracle,host=localhost")

    def test_unsupported_scheme_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_connection_string("redis://localhost:6379")


# ─────────────────────────────────────────────────────────────────────────────
# DatabaseTool: SQLite CRUD
# ─────────────────────────────────────────────────────────────────────────────


class TestDatabaseToolSQLite:
    @pytest.fixture
    def tool(self) -> DatabaseTool:
        t = DatabaseTool()
        yield t
        t.close_all()

    def test_execute_create_and_insert(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/test.db"
        rc = tool.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
            conn_str,
        )
        assert rc == 0
        rc = tool.execute(
            "INSERT INTO users (name) VALUES (?)",
            conn_str,
            params=("alice",),
        )
        assert rc == 1

    def test_query_returns_rows(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/q.db"
        tool.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
            conn_str,
        )
        tool.execute("INSERT INTO users (name) VALUES (?)", conn_str, params=("alice",))
        tool.execute("INSERT INTO users (name) VALUES (?)", conn_str, params=("bob",))
        result = tool.query("SELECT * FROM users ORDER BY id", conn_str)
        assert result.row_count == 2
        assert "name" in result.columns

    def test_query_rejects_write(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/x.db"
        with pytest.raises(ValueError):
            tool.query("DROP TABLE nonexistent", conn_str)

    def test_list_tables(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/lt.db"
        tool.execute("CREATE TABLE t1 (id INTEGER)", conn_str)
        tool.execute("CREATE TABLE t2 (id INTEGER)", conn_str)
        tables = tool.list_tables(conn_str)
        assert "t1" in tables
        assert "t2" in tables

    def test_describe_table(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/desc.db"
        tool.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)",
            conn_str,
        )
        schema = tool.describe_table("users", conn_str)
        assert schema["table"] == "users"
        column_names = {c["name"] for c in schema["columns"]}
        assert "id" in column_names
        assert "name" in column_names
        assert "id" in schema["primary_key"]

    def test_list_databases_sqlite(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/db1.sqlite"
        dbs = tool.list_databases(conn_str)
        assert isinstance(dbs, list)
        assert len(dbs) == 1
        assert dbs[0].endswith("db1.sqlite")

    def test_backup_creates_file(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/b.db"
        tool.execute("CREATE TABLE t (id INTEGER)", conn_str)
        dest = tmp_path / "out.db"
        ok = tool.backup(conn_str, str(dest))
        assert ok is True
        assert dest.exists()
        assert dest.stat().st_size > 0

    def test_explain_query(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/e.db"
        tool.execute("CREATE TABLE t (id INTEGER)", conn_str)
        plan = tool.explain_query("SELECT * FROM t", conn_str)
        assert "plan" in plan
        assert plan["query"] == "SELECT * FROM t"

    def test_close_all(self, tool: DatabaseTool, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/c.db"
        tool.execute("CREATE TABLE t (id INTEGER)", conn_str)
        tool.close_all()
        # After close_all, internal cache should be empty.
        assert tool._connections == {}


# ─────────────────────────────────────────────────────────────────────────────
# @tool registration
# ─────────────────────────────────────────────────────────────────────────────


class TestDatabaseToolRegistration:
    def test_all_db_tools_registered(self) -> None:
        from tools.base import get_registry

        registry = get_registry()
        names = [
            "db_query",
            "db_execute",
            "db_list_tables",
            "db_describe_table",
            "db_list_databases",
            "db_backup",
            "db_explain",
        ]
        for name in names:
            assert name in registry.get_names(), f"{name} missing"

    def test_db_query_invocation(self, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/reg.db"
        # Use a dedicated tool so we don't pollute the module singleton.
        DatabaseTool().execute(
            "CREATE TABLE kv (k TEXT, v TEXT)", conn_str,
        )
        DatabaseTool().execute(
            "INSERT INTO kv VALUES (?, ?)", conn_str, params=("k", "v"),
        )
        result = db_query("SELECT * FROM kv", conn_str)
        assert result["row_count"] == 1
        assert result["rows"][0]["k"] == "k"

    def test_db_execute_invocation(self, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/reg2.db"
        # Re-use the dedicated tool to keep state isolated.
        DatabaseTool().execute("CREATE TABLE n (x INTEGER)", conn_str)
        out = db_execute("INSERT INTO n VALUES (42)", conn_str)
        assert out["affected_rows"] == 1

    def test_db_list_tables_invocation(self, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/reg3.db"
        DatabaseTool().execute("CREATE TABLE aaa (id INTEGER)", conn_str)
        out = db_list_tables(conn_str)
        assert "aaa" in out["tables"]

    def test_db_describe_table_invocation(self, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/reg4.db"
        DatabaseTool().execute(
            "CREATE TABLE ttt (id INTEGER PRIMARY KEY, label TEXT)", conn_str,
        )
        out = db_describe_table("ttt", conn_str)
        assert out["table"] == "ttt"

    def test_db_list_databases_invocation(self, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/reg5.db"
        out = db_list_databases(conn_str)
        assert "databases" in out
        assert isinstance(out["databases"], list)

    def test_db_backup_invocation(self, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/reg6.db"
        DatabaseTool().execute("CREATE TABLE bk (id INTEGER)", conn_str)
        dest = tmp_path / "bk.out"
        out = db_backup(conn_str, str(dest))
        assert out["success"] is True
        assert dest.exists()

    def test_db_explain_invocation(self, tmp_path: Path) -> None:
        conn_str = f"sqlite:///{tmp_path}/reg7.db"
        DatabaseTool().execute("CREATE TABLE ex (id INTEGER)", conn_str)
        out = db_explain("SELECT * FROM ex", conn_str)
        assert "plan" in out


# ─────────────────────────────────────────────────────────────────────────────
# Misc robustness
# ─────────────────────────────────────────────────────────────────────────────


class TestDatabaseToolMisc:
    def test_caches_connection(self, tmp_path: Path) -> None:
        tool = DatabaseTool()
        try:
            conn_str = f"sqlite:///{tmp_path}/cache.db"
            tool.execute("CREATE TABLE z (x INTEGER)", conn_str)
            tool.execute("INSERT INTO z VALUES (1)", conn_str)
            # Second call should reuse the cached connection.
            r = tool.query("SELECT COUNT(*) AS n FROM z", conn_str)
            assert r.row_count == 1
        finally:
            tool.close_all()

    def test_explain_already_prefixed(self, tmp_path: Path) -> None:
        tool = DatabaseTool()
        try:
            conn_str = f"sqlite:///{tmp_path}/expl.db"
            tool.execute("CREATE TABLE t (x INTEGER)", conn_str)
            plan = tool.explain_query("EXPLAIN SELECT * FROM t", conn_str)
            assert plan["query"] == "EXPLAIN SELECT * FROM t"
        finally:
            tool.close_all()

    def test_execute_with_invalid_sql_raises(self, tmp_path: Path) -> None:
        tool = DatabaseTool()
        try:
            conn_str = f"sqlite:///{tmp_path}/bad.db"
            with pytest.raises(Exception):
                tool.execute("THIS IS NOT SQL", conn_str)
        finally:
            tool.close_all()
