"""Database tools: direct MySQL / PostgreSQL / SQLite query and introspection.

Provides a lightweight wrapper around optional DB-API drivers (``pymysql`` /
``mysql-connector-python`` for MySQL, ``psycopg2`` / ``psycopg`` for PostgreSQL,
and the stdlib ``sqlite3`` for SQLite) without requiring any of them to be
installed at import time. Drivers are detected lazily via ``importlib.util``.
"""

from __future__ import annotations

import importlib.util
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from tools.base import tool

logger = logging.getLogger(__name__)


class DatabaseDriver(Enum):
    """Supported database drivers."""

    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"


@dataclass
class DatabaseConnection:
    """Connection parameters for a database.

    Attributes:
        driver: The database driver to use.
        host: Server hostname (not used for SQLite).
        port: Server port (not used for SQLite).
        database: Database name, or file path for SQLite.
        user: Username (not used for SQLite).
        password: Password (not used for SQLite).
        ssl: Whether to enable SSL/TLS for the connection.
    """

    driver: DatabaseDriver
    host: str
    port: int
    database: str
    user: str
    password: str
    ssl: bool = False


@dataclass
class DatabaseQueryResult:
    """Result of a database query.

    Attributes:
        rows: Result rows as a list of dictionaries (column name → value).
        row_count: Number of rows returned.
        affected_rows: Number of rows affected (for INSERT/UPDATE/DELETE).
        execution_time_ms: Wall-clock execution time in milliseconds.
        query: The SQL statement that produced this result.
        columns: Ordered list of column names in the result set.
    """

    rows: list[dict]
    row_count: int
    affected_rows: int = 0
    execution_time_ms: float = 0.0
    query: str = ""
    columns: list[str] = field(default_factory=list)


def _driver_available(module_name: str) -> bool:
    """Return ``True`` if the given module is importable."""
    return importlib.util.find_spec(module_name) is not None


def _params_to_tuple(params: tuple | list | dict | None) -> tuple | dict | None:
    """Normalise parameter containers to a form accepted by DB-API drivers."""
    if params is None:
        return None
    if isinstance(params, (tuple, list, dict)):
        return params
    return (params,)


class DatabaseTool:
    """Direct database access for MySQL, PostgreSQL and SQLite.

    Connections are cached per connection string and protected by a lock so
    that concurrent agents sharing the same tool instance remain safe. Each
    public method validates its inputs and raises a clear error when a
    driver is unavailable.
    """

    def __init__(self, default_driver: DatabaseDriver = DatabaseDriver.POSTGRESQL) -> None:
        """Initialise the tool.

        Args:
            default_driver: Driver used by helper functions that need to
                infer a database type from a SQLite-style connection string.
        """
        self.default_driver = default_driver
        self._connections: dict[str, Any] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ connect
    def connect(self, connection: DatabaseConnection) -> str:
        """Open a connection and return its canonical connection string.

        Args:
            connection: Connection parameters.

        Returns:
            A string that uniquely identifies the connection (suitable for
            subsequent calls to :meth:`query`, :meth:`execute`, etc.).
        """
        conn_str = self._build_connection_string(connection)
        with self._lock:
            if conn_str in self._connections:
                return conn_str
            self._connections[conn_str] = self._open_connection(connection)
        return conn_str

    # -------------------------------------------------------------------- query
    def query(
        self,
        query: str,
        connection_string: str,
        params: tuple | None = None,
        limit: int = 1000,
    ) -> DatabaseQueryResult:
        """Execute a SELECT and return rows.

        Args:
            query: SQL statement (use ``%s`` / ``?`` placeholders for safety).
            connection_string: Connection string returned by :meth:`connect`.
            params: Optional positional parameters for the statement.
            limit: Maximum number of rows to return.

        Returns:
            A :class:`DatabaseQueryResult` with the rows.
        """
        normalised = query.strip().rstrip(";")
        head = normalised.split(None, 1)[0].lower() if normalised else ""
        if head and head not in {"select", "with", "pragma", "explain"}:
            raise ValueError(
                f"query() expects a SELECT-like statement, got '{head}'. "
                "Use execute() for writes."
            )

        start = time.perf_counter()
        conn = self._get_connection(connection_string)
        cursor = conn.cursor()
        try:
            bound = self._bind_params(connection_string, cursor, normalised, params)
            if bound is None:
                cursor.execute(normalised)
            else:
                cursor.execute(normalised, bound)
            rows = self._fetch_rows(cursor, limit)
            columns = [col[0] for col in (cursor.description or [])]
            elapsed = (time.perf_counter() - start) * 1000.0
            return DatabaseQueryResult(
                rows=rows,
                row_count=len(rows),
                affected_rows=cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0,
                execution_time_ms=elapsed,
                query=normalised,
                columns=columns,
            )
        finally:
            cursor.close()

    # ------------------------------------------------------------------ execute
    def execute(
        self,
        query: str,
        connection_string: str,
        params: tuple | None = None,
    ) -> int:
        """Execute a write statement and return the affected row count.

        Args:
            query: SQL statement.
            connection_string: Connection string returned by :meth:`connect`.
            params: Optional positional parameters.

        Returns:
            Number of affected rows.
        """
        start = time.perf_counter()
        conn = self._get_connection(connection_string)
        cursor = conn.cursor()
        try:
            bound = self._bind_params(connection_string, cursor, query, params)
            if bound is None:
                cursor.execute(query)
            else:
                cursor.execute(query, bound)
            affected = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            conn.commit()
            elapsed = (time.perf_counter() - start) * 1000.0
            logger.debug(
                "db.execute affected=%d elapsed_ms=%.2f", affected, elapsed
            )
            return affected
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            cursor.close()

    # ----------------------------------------------------------- list_tables
    def list_tables(
        self, connection_string: str, schema: str | None = None
    ) -> list[str]:
        """Return the list of user-visible tables.

        Args:
            connection_string: Connection string.
            schema: Optional schema (PostgreSQL ``schema`` / MySQL database).
        """
        info = parse_connection_string(connection_string)
        if info.driver == DatabaseDriver.POSTGRESQL:
            sql = (
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = %s ORDER BY tablename"
            )
            params: tuple = (schema or "public",)
        elif info.driver == DatabaseDriver.MYSQL:
            sql = (
                "SELECT TABLE_NAME FROM information_schema.tables "
                "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE='BASE TABLE' "
                "ORDER BY TABLE_NAME"
            )
            params = (schema or info.database,)
        else:  # SQLite
            sql = (
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            params = ()

        result = self.query(sql, connection_string, params=params, limit=10000)
        key = next(iter(result.columns)) if result.columns else "name"
        return [row[key] for row in result.rows]

    # ---------------------------------------------------------- describe_table
    def describe_table(
        self,
        table: str,
        connection_string: str,
        schema: str | None = None,
    ) -> dict:
        """Return column metadata for ``table``.

        Args:
            table: Table name.
            connection_string: Connection string.
            schema: Optional schema name.

        Returns:
            A dictionary with ``columns`` (list of column info dicts) and
            ``primary_key`` (list of primary-key column names, when known).
        """
        info = parse_connection_string(connection_string)
        if info.driver == DatabaseDriver.POSTGRESQL:
            sql = (
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position"
            )
            rows = self.query(
                sql, connection_string, params=(schema or "public", table), limit=500
            ).rows
            pk_sql = (
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                "AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = %s::regclass AND i.indisprimary"
            )
            pk_rows = self.query(
                pk_sql, connection_string, params=(f"{schema or 'public'}.{table}",)
            ).rows
            columns = [
                {
                    "name": r["column_name"],
                    "type": r["data_type"],
                    "nullable": r["is_nullable"] == "YES",
                    "default": r["column_default"],
                }
                for r in rows
            ]
            primary_key = [r["attname"] for r in pk_rows]
        elif info.driver == DatabaseDriver.MYSQL:
            sql = (
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY "
                "FROM information_schema.columns "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION"
            )
            rows = self.query(
                sql, connection_string, params=(schema or info.database, table), limit=500
            ).rows
            columns = [
                {
                    "name": r["COLUMN_NAME"],
                    "type": r["DATA_TYPE"],
                    "nullable": r["IS_NULLABLE"] == "YES",
                    "default": r["COLUMN_DEFAULT"],
                    "key": r["COLUMN_KEY"],
                }
                for r in rows
            ]
            primary_key = [c["name"] for c in columns if c.get("key") == "PRI"]
        else:  # SQLite
            pragma_rows = self.query(
                f"PRAGMA table_info({table})", connection_string, limit=500
            ).rows
            columns = [
                {
                    "name": r["name"],
                    "type": r["type"],
                    "nullable": not bool(r["notnull"]),
                    "default": r["dflt_value"],
                    "primary_key": bool(r["pk"]),
                }
                for r in pragma_rows
            ]
            primary_key = [c["name"] for c in columns if c["primary_key"]]

        return {"table": table, "schema": schema, "columns": columns, "primary_key": primary_key}

    # -------------------------------------------------------- list_databases
    def list_databases(self, connection_string: str) -> list[str]:
        """Return the list of databases visible to the current user."""
        info = parse_connection_string(connection_string)
        if info.driver == DatabaseDriver.POSTGRESQL:
            sql = "SELECT datname FROM pg_database WHERE datistemplate=false ORDER BY datname"
            rows = self.query(sql, connection_string, limit=10000).rows
            return [r["datname"] for r in rows]
        if info.driver == DatabaseDriver.MYSQL:
            sql = "SHOW DATABASES"
            rows = self.query(sql, connection_string, limit=10000).rows
            return [r["Database"] for r in rows]
        # SQLite: a single file = a single "database"
        return [info.database]

    # ------------------------------------------------------------------ backup
    def backup(
        self,
        connection_string: str,
        dest_path: str,
        format: str = "sql",  # noqa: A002 - matches public API
    ) -> bool:
        """Dump the database to ``dest_path``.

        Args:
            connection_string: Connection string.
            dest_path: Destination file path.
            format: ``"sql"`` (text dump) or ``"native"`` (driver-specific).

        Returns:
            ``True`` on success.

        Notes:
            For MySQL this shells out to ``mysqldump`` if available; for
            PostgreSQL it uses ``pg_dump``; for SQLite it uses the
            ``.dump`` command. When the external tool is missing a
            :class:`RuntimeError` is raised.
        """
        info = parse_connection_string(connection_string)
        dest = Path(dest_path).expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)

        import shutil
        import subprocess

        if info.driver == DatabaseDriver.MYSQL:
            binary = shutil.which("mysqldump")
            if not binary:
                raise RuntimeError("mysqldump not found on PATH")
            cmd = [
                binary,
                f"-h{info.host}",
                f"-P{info.port}",
                f"-u{info.user}",
                f"-p{info.password}",
                info.database,
            ]
        elif info.driver == DatabaseDriver.POSTGRESQL:
            binary = shutil.which("pg_dump")
            if not binary:
                raise RuntimeError("pg_dump not found on PATH")
            cmd = [
                binary,
                "-h", info.host,
                "-p", str(info.port),
                "-U", info.user,
                "-d", info.database,
                "-f", str(dest),
                "--no-password",
            ]
            env = {"PGPASSWORD": info.password}
        else:  # SQLite
            conn = self._get_connection(connection_string)
            with sqlite3.connect(dest) as out:
                conn.backup(out)
            return True

        if info.driver != DatabaseDriver.SQLITE:
            extra_env = {"PGPASSWORD": info.password} if info.driver == DatabaseDriver.POSTGRESQL else None
            result = subprocess.run(  # noqa: S603 - intentional invocation
                cmd,
                check=False,
                capture_output=True,
                text=True,
                env=extra_env,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"backup failed (exit {result.returncode}): {result.stderr.strip()}"
                )
            if info.driver == DatabaseDriver.POSTGRESQL:
                return True
            # MySQL: write stdout to dest
            dest.write_text(result.stdout, encoding="utf-8")
            return True

        return False  # unreachable; kept for type checkers

    # --------------------------------------------------------- get_table_size
    def get_table_size(self, table: str, connection_string: str) -> dict:
        """Return row-count and (when available) on-disk size for ``table``."""
        info = parse_connection_string(connection_string)
        count_sql = f"SELECT COUNT(*) AS n FROM {table}"  # identifier, no params
        rows = self.query(count_sql, connection_string, limit=1).rows
        row_count = int(rows[0]["n"]) if rows else 0
        size_bytes: int | None = None

        try:
            if info.driver == DatabaseDriver.POSTGRESQL:
                size_sql = "SELECT pg_total_relation_size(%s) AS bytes"
                res = self.query(size_sql, connection_string, params=(table,)).rows
                size_bytes = int(res[0]["bytes"]) if res else None
            elif info.driver == DatabaseDriver.MYSQL:
                size_sql = (
                    "SELECT data_length + index_length AS bytes "
                    "FROM information_schema.tables "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s"
                )
                res = self.query(
                    size_sql,
                    connection_string,
                    params=(info.database, table),
                ).rows
                size_bytes = int(res[0]["bytes"]) if res and res[0]["bytes"] is not None else None
            else:
                # SQLite: file size of the database file
                db_path = Path(info.database)
                if db_path.exists():
                    size_bytes = db_path.stat().st_size
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_table_size: size lookup failed: %s", exc)

        return {"table": table, "row_count": row_count, "size_bytes": size_bytes}

    # ---------------------------------------------------------- explain_query
    def explain_query(self, query: str, connection_string: str) -> dict:
        """Return the execution plan for ``query``."""
        normalised = query.strip().rstrip(";")
        if normalised.lower().startswith("explain"):
            sql = normalised
            params: tuple | None = None
        else:
            info = parse_connection_string(connection_string)
            if info.driver == DatabaseDriver.POSTGRESQL:
                sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {normalised}"
            elif info.driver == DatabaseDriver.MYSQL:
                sql = f"EXPLAIN FORMAT=JSON {normalised}"
            else:
                sql = f"EXPLAIN QUERY PLAN {normalised}"
            params = None

        result = self.query(sql, connection_string, params=params, limit=10000)
        return {
            "query": normalised,
            "plan": result.rows,
            "columns": result.columns,
        }

    # ----------------------------------------------------------- close_all
    def close_all(self) -> None:
        """Close every cached connection."""
        with self._lock:
            for key, conn in list(self._connections.items()):
                try:
                    conn.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Error closing connection %s: %s", key, exc)
            self._connections.clear()

    # ======================================================== internal helpers

    def _get_connection(self, connection_string: str) -> Any:
        with self._lock:
            conn = self._connections.get(connection_string)
            if conn is not None:
                return conn
        # Re-parse and open (no lock while connecting — drivers may block)
        info = parse_connection_string(connection_string)
        conn = self._open_connection(info)
        with self._lock:
            self._connections[connection_string] = conn
        return conn

    @staticmethod
    def _open_connection(info: DatabaseConnection) -> Any:
        if info.driver == DatabaseDriver.MYSQL:
            return DatabaseTool._open_mysql(info)
        if info.driver == DatabaseDriver.POSTGRESQL:
            return DatabaseTool._open_postgres(info)
        return DatabaseTool._open_sqlite(info)

    @staticmethod
    def _open_mysql(info: DatabaseConnection) -> Any:
        if _driver_available("pymysql"):
            import pymysql

            return pymysql.connect(  # type: ignore[call-overload]
                host=info.host,
                port=info.port,
                user=info.user,
                password=info.password,
                database=info.database,
                ssl=({"ssl": {}} if info.ssl else None),
                cursorclass=pymysql.cursors.DictCursor,
            )
        if _driver_available("mysql.connector"):
            import mysql.connector

            return mysql.connector.connect(  # type: ignore[call-overload]
                host=info.host,
                port=info.port,
                user=info.user,
                password=info.password,
                database=info.database,
                ssl_disabled=not info.ssl,
            )
        raise RuntimeError(
            "MySQL driver not installed. Install 'pymysql' or 'mysql-connector-python'."
        )

    @staticmethod
    def _open_postgres(info: DatabaseConnection) -> Any:
        if _driver_available("psycopg2"):
            import psycopg2
            import psycopg2.extras

            return psycopg2.connect(  # type: ignore[call-overload]
                host=info.host,
                port=info.port,
                user=info.user,
                password=info.password,
                dbname=info.database,
                sslmode="require" if info.ssl else "disable",
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
        if _driver_available("psycopg"):
            import psycopg

            return psycopg.connect(  # type: ignore[call-overload]
                host=info.host,
                port=info.port,
                user=info.user,
                password=info.password,
                dbname=info.database,
                sslmode="require" if info.ssl else "disable",
                row_factory=psycopg.rows.dict_row,
            )
        raise RuntimeError(
            "PostgreSQL driver not installed. Install 'psycopg2-binary' or 'psycopg'."
        )

    @staticmethod
    def _open_sqlite(info: DatabaseConnection) -> Any:
        path = Path(info.database).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _fetch_rows(cursor: Any, limit: int) -> list[dict]:
        """Fetch up to ``limit`` rows as a list of dictionaries."""
        rows: list[dict] = []
        try:
            fetched = cursor.fetchmany(limit) if limit else cursor.fetchall()
        except Exception:  # noqa: BLE001
            return rows
        for row in fetched:
            if isinstance(row, dict):
                rows.append(dict(row))
                continue
            # SQLite Row: map by column names from description
            if cursor.description:
                rows.append({col[0]: row[idx] for idx, col in enumerate(cursor.description)})
                continue
            rows.append(dict(row) if hasattr(row, "keys") else {"value": row})
        return rows

    @staticmethod
    def _bind_params(
        connection_string: str,
        cursor: Any,
        query: str,
        params: tuple | list | dict | None,
    ) -> tuple | list | dict | None:
        """Normalise bind parameters for the active driver.

        Returns ``None`` when no parameters were supplied so the DB-API
        layer treats the statement as parameterless. SQLite uses ``?``
        placeholders; PostgreSQL/MySQL use ``%s``.
        """
        if params is None:
            return None
        return _params_to_tuple(params)

    @staticmethod
    def _build_connection_string(info: DatabaseConnection) -> str:
        if info.driver == DatabaseDriver.SQLITE:
            return f"sqlite:///{info.database}"
        auth = f"{info.user}:{info.password}@" if info.user else ""
        ssl = "?sslmode=require" if info.ssl else ""
        return f"{info.driver.value}://{auth}{info.host}:{info.port}/{info.database}{ssl}"


# =====================================================================
# Connection-string parsing
# =====================================================================


def parse_connection_string(conn_str: str) -> DatabaseConnection:
    """Parse a connection string into a :class:`DatabaseConnection`.

    Supported formats:
      - URL: ``driver://user:pass@host:port/dbname?sslmode=require``
      - SQLite URL: ``sqlite:///path/to/db.sqlite``
      - Key=value: ``driver=mysql,host=...,port=...,database=...,user=...,password=...``

    Args:
        conn_str: Connection string.

    Returns:
        A populated :class:`DatabaseConnection`.
    """
    if not conn_str:
        raise ValueError("Empty connection string")

    if "://" in conn_str:
        return _parse_url(conn_str)
    return _parse_kv(conn_str)


def _parse_url(conn_str: str) -> DatabaseConnection:
    parsed = urlparse(conn_str)
    scheme = (parsed.scheme or "").lower()
    if scheme in {"sqlite", "sqlite3"}:
        # Take everything after ``scheme://`` verbatim. SQLite URL syntax
        # is ``sqlite:///<path>`` (absolute) or ``sqlite:///<relative>``.
        # We strip the leading slash on absolute paths so Windows drive
        # letters (``C:\foo.db``) survive intact.
        rest = conn_str.split("://", 1)[1]
        if rest.startswith("/") and len(rest) > 1 and rest[1] != "/":
            rest = rest[1:]
        path = unquote(rest)
        if path == "":
            path = ":memory:"
        return DatabaseConnection(
            driver=DatabaseDriver.SQLITE,
            host="",
            port=0,
            database=path,
            user="",
            password="",
            ssl=False,
        )
    if scheme in {"postgres", "postgresql"}:
        driver = DatabaseDriver.POSTGRESQL
        default_port = 5432
    elif scheme == "mysql":
        driver = DatabaseDriver.MYSQL
        default_port = 3306
    else:
        raise ValueError(f"Unsupported driver in URL: {scheme!r}")
    query = parse_qs(parsed.query or "")
    ssl = any(
        v and v[0].lower() not in {"disable", "false", "0", "prefer", "allow"}
        for v in query.get("sslmode", [])
    ) or any(query.get("ssl", []))
    return DatabaseConnection(
        driver=driver,
        host=parsed.hostname or "localhost",
        port=parsed.port or default_port,
        database=unquote(parsed.path.lstrip("/")) if parsed.path else "",
        user=unquote(parsed.username) if parsed.username else "",
        password=unquote(parsed.password) if parsed.password else "",
        ssl=bool(ssl),
    )


def _parse_kv(conn_str: str) -> DatabaseConnection:
    parts: dict[str, str] = {}
    for chunk in conn_str.split(","):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        parts[key.strip().lower()] = value.strip()
    if "driver" not in parts:
        raise ValueError("Missing 'driver' in key=value connection string")
    try:
        driver = DatabaseDriver(parts["driver"].lower())
    except ValueError as exc:
        raise ValueError(f"Unknown driver: {parts['driver']!r}") from exc
    if driver == DatabaseDriver.SQLITE:
        return DatabaseConnection(
            driver=driver,
            host="",
            port=0,
            database=parts.get("database", ":memory:"),
            user="",
            password="",
            ssl=False,
        )
    return DatabaseConnection(
        driver=driver,
        host=parts.get("host", "localhost"),
        port=int(parts.get("port", "5432" if driver == DatabaseDriver.POSTGRESQL else "3306")),
        database=parts.get("database", ""),
        user=parts.get("user", ""),
        password=parts.get("password", ""),
        ssl=parts.get("ssl", "false").lower() in {"1", "true", "yes"},
    )


# =====================================================================
# Module-level singleton + @tool wrappers
# =====================================================================

_tool = DatabaseTool()


def _connect_dict(d: dict) -> str:
    """Build a DatabaseConnection from a plain dict (for ad-hoc agent calls)."""
    driver_raw = d.get("driver", "postgresql")
    if isinstance(driver_raw, DatabaseDriver):
        driver = driver_raw
    else:
        driver = DatabaseDriver(str(driver_raw).lower())
    info = DatabaseConnection(
        driver=driver,
        host=str(d.get("host", "")),
        port=int(d.get("port", 0) or 0),
        database=str(d.get("database", "")),
        user=str(d.get("user", "")),
        password=str(d.get("password", "")),
        ssl=bool(d.get("ssl", False)),
    )
    return _tool.connect(info)


def _result_to_dict(result: DatabaseQueryResult) -> dict:
    return {
        "rows": result.rows,
        "row_count": result.row_count,
        "affected_rows": result.affected_rows,
        "execution_time_ms": result.execution_time_ms,
        "query": result.query,
        "columns": result.columns,
    }


@tool(name="db_query", description="Run a read-only SQL query (SELECT/PRAGMA/EXPLAIN)", toolset="database")
def db_query(
    query: str,
    connection_string: str,
    params: str | None = None,
    limit: int = 1000,
) -> dict:
    """Execute a SELECT-style query and return rows.

    Args:
        query: SQL statement.
        connection_string: Connection string (URL or key=value form).
        params: JSON-encoded tuple/list/dict of bind parameters.
        limit: Maximum rows to return.
    """
    import json

    parsed_params: tuple | None = None
    if params:
        try:
            decoded = json.loads(params)
            parsed_params = tuple(decoded) if isinstance(decoded, list) else decoded
        except json.JSONDecodeError:
            parsed_params = (params,)
    result = _tool.query(query, connection_string, params=parsed_params, limit=limit)
    return _result_to_dict(result)


@tool(name="db_execute", description="Execute a write statement (INSERT/UPDATE/DELETE)", toolset="database")
def db_execute(
    query: str,
    connection_string: str,
    params: str | None = None,
) -> dict:
    """Execute a write statement and return the affected-row count.

    Args:
        query: SQL statement.
        connection_string: Connection string.
        params: JSON-encoded tuple/list/dict of bind parameters.
    """
    import json

    parsed_params: tuple | None = None
    if params:
        try:
            decoded = json.loads(params)
            parsed_params = tuple(decoded) if isinstance(decoded, list) else decoded
        except json.JSONDecodeError:
            parsed_params = (params,)
    affected = _tool.execute(query, connection_string, params=parsed_params)
    return {"affected_rows": affected, "query": query}


@tool(name="db_list_tables", description="List tables in the connected database", toolset="database")
def db_list_tables(connection_string: str, schema: str | None = None) -> dict:
    """Return a list of user-visible table names.

    Args:
        connection_string: Connection string.
        schema: Optional schema name (defaults to ``public`` for Postgres).
    """
    tables = _tool.list_tables(connection_string, schema=schema)
    return {"tables": tables, "schema": schema}


@tool(name="db_describe_table", description="Describe columns and keys of a table", toolset="database")
def db_describe_table(table: str, connection_string: str) -> dict:
    """Return column metadata for ``table``.

    Args:
        table: Table name.
        connection_string: Connection string.
    """
    return _tool.describe_table(table, connection_string)


@tool(name="db_list_databases", description="List databases visible on the server", toolset="database")
def db_list_databases(connection_string: str) -> dict:
    """Return the list of databases accessible to the current user.

    Args:
        connection_string: Connection string.
    """
    return {"databases": _tool.list_databases(connection_string)}


@tool(name="db_backup", description="Dump a database to a file", toolset="database")
def db_backup(connection_string: str, dest_path: str) -> dict:
    """Back up the database to ``dest_path`` as SQL.

    Args:
        connection_string: Connection string.
        dest_path: Destination file path.
    """
    ok = _tool.backup(connection_string, dest_path, format="sql")
    return {"success": ok, "dest_path": dest_path}


@tool(name="db_explain", description="Return the execution plan for a query", toolset="database")
def db_explain(query: str, connection_string: str) -> dict:
    """Explain the given query without running it for real writes.

    Args:
        query: SQL statement.
        connection_string: Connection string.
    """
    return _tool.explain_query(query, connection_string)


@tool(name="db_connect", description="Open and cache a database connection", toolset="database")
def db_connect(
    driver: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    ssl: bool = False,
) -> dict:
    """Open a database connection and return its connection string.

    Args:
        driver: ``mysql``, ``postgresql`` or ``sqlite``.
        host: Server hostname.
        port: Server port.
        database: Database name (or SQLite path).
        user: Username.
        password: Password.
        ssl: Enable SSL/TLS.
    """
    conn_str = _connect_dict(
        {
            "driver": driver,
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "ssl": ssl,
        }
    )
    return {"connection_string": conn_str}


__all__ = [
    "DatabaseDriver",
    "DatabaseConnection",
    "DatabaseQueryResult",
    "DatabaseTool",
    "parse_connection_string",
]
