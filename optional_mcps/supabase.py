"""Supabase MCP server — exposes Supabase PostgreSQL as MCP tools over stdio JSON-RPC."""

from __future__ import annotations

import os

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


def _get_headers() -> dict[str, str]:
    anon_key = os.environ.get("SUPABASE_KEY", "")
    return {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
    }


def _supabase_get(path: str, params: dict | None = None) -> dict | list:
    url = os.environ.get("SUPABASE_URL", "")
    headers = _get_headers()
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url + path, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


def _supabase_post(path: str, json_data: dict) -> dict | list:
    url = os.environ.get("SUPABASE_URL", "")
    anon_key = os.environ.get("SUPABASE_KEY", "")
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url + path, headers=headers, json=json_data)
        resp.raise_for_status()
        return resp.json()


def _fmt_row(row: dict) -> str:
    items = list(row.items())[:8]
    parts = [f"{k}={repr(v)[:80]}" for k, v in items]
    return ", ".join(parts)


if _HTTPX_AVAILABLE:

    @make_tool(
        name="supabase_list_tables",
        description="List tables in a schema",
        input_schema={
            "type": "object",
            "properties": {
                "schema": {"type": "string", "default": "public"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    )
    def supabase_list_tables(schema: str = "public", limit: int = 20) -> str:
        data = _supabase_get(f"/rest/v1/{schema}", {"limit": limit})
        rows = data if isinstance(data, list) else []
        if not rows:
            return f"No tables found in schema '{schema}'"
        return f"Rows ({len(rows)} in {schema}:\n" + "\n".join(
            _fmt_row(r) for r in rows[:limit]
        )

    @make_tool(
        name="supabase_select",
        description="Select rows from a table",
        input_schema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "filters": {"type": "object", "description": "Column=value filters"},
                "columns": {"type": "string", "default": "*"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["table"],
        },
    )
    def supabase_select(
        table: str, filters: dict | None = None, columns: str = "*", limit: int = 20
    ) -> str:
        params = {"select": columns, "limit": limit}
        if filters:
            for k, v in filters.items():
                params[f"{k}=eq.{v}"] = None
        data = _supabase_get(f"/rest/v1/{table}", params)
        rows = data if isinstance(data, list) else []
        if not rows:
            return f"No rows in {table}"
        return f"Rows ({len(rows)} in {table}:\n" + "\n".join(_fmt_row(r) for r in rows)

    @make_tool(
        name="supabase_insert",
        description="Insert a row into a table",
        input_schema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "values": {"type": "object"},
            },
            "required": ["table", "values"],
        },
    )
    def supabase_insert(table: str, values: dict) -> str:
        result = _supabase_post(f"/rest/v1/{table}", values)
        if isinstance(result, list) and result:
            return f"Inserted: {_fmt_row(result[0])}"
        return f"Result: {result}"

    @make_tool(
        name="supabase_auth_signup",
        description="Sign up a new user",
        input_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["email", "password"],
        },
    )
    def supabase_auth_signup(email: str, password: str) -> str:
        payload = {"email": email, "password": password}
        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_KEY", "")
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{url}/auth/v1/signup", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        uid = data.get("id", "?")
        return f"Signed up: {email} (id={uid})"

    @make_tool(
        name="supabase_auth_signin",
        description="Sign in an existing user with email/password",
        input_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["email", "password"],
        },
    )
    def supabase_auth_signin(email: str, password: str) -> str:
        payload = {"email": email, "password": password}
        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_KEY", "")
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{url}/auth/v1/token?grant_type=password",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        access_token = data.get("access_token", "")
        user_id = (data.get("user") or {}).get("id", "?")
        return f"Signed in: {email} (id={user_id}, token={access_token[:20]}...)"

    @make_tool(
        name="supabase_update",
        description="Update rows in a table matching the given filters",
        input_schema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "filters": {"type": "object", "description": "Column=value filters"},
                "values": {"type": "object", "description": "New column values"},
            },
            "required": ["table", "filters", "values"],
        },
    )
    def supabase_update(table: str, filters: dict, values: dict) -> str:
        params: dict = {"Prefer": "return=representation"}
        for k, v in filters.items():
            params[f"{k}=eq.{v}"] = None
        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_KEY", "")
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.patch(
                f"{url}/rest/v1/{table}", headers=headers, params=params, json=values
            )
            resp.raise_for_status()
            data = resp.json()
        rows = data if isinstance(data, list) else []
        return f"Updated {len(rows)} row(s) in {table}:\n" + "\n".join(
            _fmt_row(r) for r in rows
        ) if rows else f"Updated 0 rows in {table}"

    @make_tool(
        name="supabase_delete",
        description="Delete rows from a table matching the given filters",
        input_schema={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "filters": {"type": "object", "description": "Column=value filters"},
            },
            "required": ["table", "filters"],
        },
    )
    def supabase_delete(table: str, filters: dict) -> str:
        params: dict = {"Prefer": "return=representation"}
        for k, v in filters.items():
            params[f"{k}=eq.{v}"] = None
        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_KEY", "")
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.delete(
                f"{url}/rest/v1/{table}", headers=headers, params=params
            )
            resp.raise_for_status()
            data = resp.json() if resp.content else []
        rows = data if isinstance(data, list) else []
        return f"Deleted {len(rows)} row(s) from {table}"

    @make_tool(
        name="supabase_storage_upload",
        description="Upload a file to Supabase Storage",
        input_schema={
            "type": "object",
            "properties": {
                "bucket": {"type": "string"},
                "path": {"type": "string", "description": "Object path within the bucket"},
                "content_base64": {"type": "string", "description": "Base64-encoded file content"},
                "content_type": {"type": "string", "default": "application/octet-stream"},
            },
            "required": ["bucket", "path", "content_base64"],
        },
    )
    def supabase_storage_upload(
        bucket: str, path: str, content_base64: str, content_type: str = "application/octet-stream"
    ) -> str:
        import base64

        try:
            content = base64.b64decode(content_base64)
        except Exception as e:
            return f"Invalid base64: {e}"
        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_KEY", "")
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{url}/storage/v1/object/{bucket}/{path}",
                headers=headers,
                content=content,
            )
            resp.raise_for_status()
        return f"Uploaded {len(content)} bytes to {bucket}/{path}"

    @make_tool(
        name="supabase_storage_download",
        description="Download a file from Supabase Storage as base64",
        input_schema={
            "type": "object",
            "properties": {
                "bucket": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["bucket", "path"],
        },
    )
    def supabase_storage_download(bucket: str, path: str) -> str:

        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_KEY", "")
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{url}/storage/v1/object/{bucket}/{path}", headers=headers
            )
            resp.raise_for_status()
            content = resp.content
        return f"Downloaded {len(content)} bytes from {bucket}/{path}"

    @make_tool(
        name="supabase_rpc",
        description="Call a Postgres function via the Supabase RPC endpoint",
        input_schema={
            "type": "object",
            "properties": {
                "function_name": {"type": "string"},
                "args": {"type": "object", "default": {}},
            },
            "required": ["function_name"],
        },
    )
    def supabase_rpc(function_name: str, args: dict | None = None) -> str:
        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_KEY", "")
        headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{url}/rest/v1/rpc/{function_name}",
                headers=headers,
                json=args or {},
            )
            resp.raise_for_status()
            data = resp.json()
        return f"RPC {function_name} result: {data}"

    TOOLS: list = [
        supabase_list_tables,
        supabase_select,
        supabase_insert,
        supabase_update,
        supabase_delete,
        supabase_auth_signup,
        supabase_auth_signin,
        supabase_storage_upload,
        supabase_storage_download,
        supabase_rpc,
    ]

else:
    TOOLS = []


def main() -> None:
    server = MCPServer(name="supabase", version="1.0.0", tools=TOOLS)
    server.run()


if __name__ == "__main__":
    main()
