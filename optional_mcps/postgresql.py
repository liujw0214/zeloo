"""PostgreSQL MCP Server — run SQL queries and manage tables."""

from __future__ import annotations

import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool


def _get_conn() -> Any:
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "postgres"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )


@make_tool(
    name="postgres_run_query",
    description="Execute a read-only SQL query on PostgreSQL",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "SQL SELECT query"},
            "limit": {"type": "integer", "description": "Max rows (default 100)", "default": 100},
        },
        "required": ["query"],
    },
)
def postgres_run_query(query: str, limit: int = 100) -> str:
    conn = _get_conn()
    cursor = conn.cursor()
    safe_query = query.strip().upper()
    if not safe_query.startswith("SELECT"):
        return "Error: only SELECT queries are allowed."
    if "LIMIT" not in safe_query:
        query = f"{query.rstrip(';')} LIMIT {limit}"
    cursor.execute(query)
    rows = cursor.fetchall()
    cols = [desc[0] for desc in cursor.description] if cursor.description else []
    cursor.close()
    conn.close()

    lines = [" | ".join(str(c) for c in cols)]
    lines.append("-" * len(lines[0]))
    for row in rows:
        lines.append(" | ".join(str(v) for v in row))
    return f"{len(rows)} rows returned.\n" + "\n".join(lines)


@make_tool(
    name="postgres_list_tables",
    description="List all tables in a PostgreSQL schema",
    input_schema={
        "type": "object",
        "properties": {
            "schema": {
                "type": "string",
                "description": "Schema name (default public)",
                "default": "public",
            },
        },
    },
)
def postgres_list_tables(schema: str = "public") -> str:
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        (schema,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return "\n".join(f"  {r[0]}" for r in rows) if rows else f"No tables in schema '{schema}'."


@make_tool(
    name="postgres_describe_table",
    description="Describe table schema (columns, types, constraints)",
    input_schema={
        "type": "object",
        "properties": {
            "table": {"type": "string", "description": "Table name"},
            "schema": {
                "type": "string",
                "description": "Schema name (default public)",
                "default": "public",
            },
        },
        "required": ["table"],
    },
)
def postgres_describe_table(table: str, schema: str = "public") -> str:
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    lines = ["Column         | Type           | Nullable | Default"]
    lines.append("-" * 65)
    for col, dtype, nullable, default in rows:
        lines.append(f"{col:<16}| {dtype:<16}| {nullable:<8}| {default or ''}")
    return "\n".join(lines) if lines else f"Table '{table}' not found."


@make_tool(
    name="postgres_explain_query",
    description="Get query execution plan (EXPLAIN ANALYZE)",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "SQL query to explain"},
        },
        "required": ["query"],
    },
)
def postgres_explain_query(query: str) -> str:
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute(f"EXPLAIN (FORMAT TEXT, ANALYZE) {query}")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return "\n".join(r[0] for r in rows)


class PostgreSQLServer(MCPServer):
    name = "postgresql"
    version = "1.0.0"
    TOOLS = [
        postgres_run_query,
        postgres_list_tables,
        postgres_describe_table,
        postgres_explain_query,
    ]


if __name__ == "__main__":
    server = PostgreSQLServer(tools=PostgreSQLServer.TOOLS)
    server.run()
