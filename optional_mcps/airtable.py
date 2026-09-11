"""Airtable MCP server — exposes Airtable API as MCP tools over stdio JSON-RPC.

Airtable API reference: https://airtable.com/developers/web/api/introduction

Supported tools:
- list_bases          — List all accessible bases
- list_tables         — List all tables in a base
- list_records        — Paginated record listing with filtering/sorting
- get_record          — Retrieve a single record by ID
- create_record       — Create a new record
- update_record       — Update specific fields of a record
- delete_record       — Delete a record
- search_records      — Full-text search within a table
"""

from __future__ import annotations

import os
from typing import Any

from optional_mcps.base import MCPServer, make_tool

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False

AIRTABLE_API_BASE = "https://api.airtable.com/v0"
AIRTABLE_META_BASE = "https://api.airtable.com/v0/meta/bases"


def _get_headers() -> dict[str, str]:
    token = os.environ.get("AIRTABLE_API_KEY", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _fmt_record(record: dict) -> str:
    fields = record.get("fields", {})
    return (
        f"id={record['id']}\n"
        + f"createdTime={record.get('createdTime','')}\n"
        + "\n".join(f"  {k}={v!r}" for k, v in fields.items())
    )


class AirtableServer(MCPServer):
    name = "airtable"
    version = "1.0.0"

    if _HTTPX_AVAILABLE:

        @make_tool(
            name="airtable_list_bases",
            description="List all Airtable bases the API token can access",
            input_schema={"type": "object", "properties": {}},
        )
        def airtable_list_bases(self) -> str:
            headers = _get_headers()
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(AIRTABLE_META_BASE, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            bases: list[dict] = data.get("bases", [])
            if not bases:
                return "No bases found."
            lines = [f"{b['id']}  {b['name']}  ({b.get('permissionLevel','?')})" for b in bases]
            return "Bases:\n" + "\n".join(lines)

        @make_tool(
            name="airtable_list_tables",
            description="List all tables in an Airtable base",
            input_schema={
                "type": "object",
                "properties": {
                    "base_id": {"type": "string"},
                },
                "required": ["base_id"],
            },
        )
        def airtable_list_tables(self, base_id: str) -> str:
            headers = _get_headers()
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(f"{AIRTABLE_META_BASE}/bases/{base_id}/tables", headers=headers)
                resp.raise_for_status()
                data = resp.json()
            tables: list[dict] = data.get("tables", [])
            if not tables:
                return f"No tables found in base {base_id}."
            lines = [f"{t['id']}  {t['name']}  fields={len(t.get('fields',[]))}" for t in tables]
            return "Tables:\n" + "\n".join(lines)

        @make_tool(
            name="airtable_list_records",
            description="List records from a table with optional pagination, filtering, sorting",
            input_schema={
                "type": "object",
                "properties": {
                    "base_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "page_size": {"type": "integer", "default": 100},
                    "offset": {"type": "string"},
                    "filter_by_formula": {"type": "string"},
                    "sort_field": {"type": "string"},
                    "sort_direction": {"type": "string", "default": "asc"},
                },
                "required": ["base_id", "table_name"],
            },
        )
        def airtable_list_records(
            self,
            base_id: str,
            table_name: str,
            page_size: int = 100,
            offset: str | None = None,
            filter_by_formula: str | None = None,
            sort_field: str | None = None,
            sort_direction: str = "asc",
        ) -> str:
            headers = _get_headers()
            params: dict[str, Any] = {"pageSize": page_size}
            if offset:
                params["offset"] = offset
            if filter_by_formula:
                params["filterByFormula"] = filter_by_formula
            if sort_field:
                params["sort[0][field]"] = sort_field
                params["sort[0][direction]"] = sort_direction
            httpx.QueryParams({}).update(
                {k: v for k, v in params.items() if v is not None}
            )
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(
                    f"{AIRTABLE_API_BASE}/{base_id}/{table_name}",
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
            records: list[dict] = data.get("records", [])
            next_offset = data.get("offset", "")
            if not records:
                return f"No records found in {table_name}."
            result = "\n\n".join(_fmt_record(r) for r in records[:5])
            if len(records) > 5:
                result += f"\n\n... and {len(records) - 5} more records"
            if next_offset:
                result += f"\n\nNext offset: {next_offset}"
            return result

        @make_tool(
            name="airtable_get_record",
            description="Retrieve a single record by its ID",
            input_schema={
                "type": "object",
                "properties": {
                    "base_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "record_id": {"type": "string"},
                },
                "required": ["base_id", "table_name", "record_id"],
            },
        )
        def airtable_get_record(
            self, base_id: str, table_name: str, record_id: str
        ) -> str:
            headers = _get_headers()
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(
                    f"{AIRTABLE_API_BASE}/{base_id}/{table_name}/{record_id}",
                    headers=headers,
                )
                resp.raise_for_status()
                record = resp.json()
            return _fmt_record(record)

        @make_tool(
            name="airtable_create_record",
            description="Create a new record in a table",
            input_schema={
                "type": "object",
                "properties": {
                    "base_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "fields": {"type": "object"},
                },
                "required": ["base_id", "table_name", "fields"],
            },
        )
        def airtable_create_record(
            self, base_id: str, table_name: str, fields: dict
        ) -> str:
            headers = _get_headers()
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{AIRTABLE_API_BASE}/{base_id}/{table_name}",
                    headers=headers,
                    json={"fields": fields},
                )
                resp.raise_for_status()
                record = resp.json()
            return "Created: " + _fmt_record(record)

        @make_tool(
            name="airtable_update_record",
            description="Update specific fields of an existing record (partial update)",
            input_schema={
                "type": "object",
                "properties": {
                    "base_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "record_id": {"type": "string"},
                    "fields": {"type": "object"},
                },
                "required": ["base_id", "table_name", "record_id", "fields"],
            },
        )
        def airtable_update_record(
            self, base_id: str, table_name: str, record_id: str, fields: dict
        ) -> str:
            headers = _get_headers()
            with httpx.Client(timeout=30.0) as client:
                resp = client.patch(
                    f"{AIRTABLE_API_BASE}/{base_id}/{table_name}/{record_id}",
                    headers=headers,
                    json={"fields": fields},
                )
                resp.raise_for_status()
                record = resp.json()
            return "Updated: " + _fmt_record(record)

        @make_tool(
            name="airtable_delete_record",
            description="Delete a single record by ID",
            input_schema={
                "type": "object",
                "properties": {
                    "base_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "record_id": {"type": "string"},
                },
                "required": ["base_id", "table_name", "record_id"],
            },
        )
        def airtable_delete_record(
            self, base_id: str, table_name: str, record_id: str
        ) -> str:
            headers = _get_headers()
            with httpx.Client(timeout=30.0) as client:
                resp = client.delete(
                    f"{AIRTABLE_API_BASE}/{base_id}/{table_name}/{record_id}",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            return f"Deleted record {record_id}: {data.get('deleted', False)}"

        @make_tool(
            name="airtable_search_records",
            description="Full-text search within a table",
            input_schema={
                "type": "object",
                "properties": {
                    "base_id": {"type": "string"},
                    "table_name": {"type": "string"},
                    "query": {"type": "string", "description": "Search term"},
                    "max_records": {"type": "integer", "default": 20},
                },
                "required": ["base_id", "table_name", "query"],
            },
        )
        def airtable_search_records(
            self,
            base_id: str,
            table_name: str,
            query: str,
            max_records: int = 20,
        ) -> str:
            headers = _get_headers()
            params = {
                "filterByFormula": f"SEARCH(\"{query}\", {{}})",
                "pageSize": min(max_records, 100),
            }
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(
                    f"{AIRTABLE_API_BASE}/{base_id}/{table_name}",
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
            records: list[dict] = data.get("records", [])
            if not records:
                return f"No records matching '{query}' found."
            result = "\n\n".join(_fmt_record(r) for r in records)
            return f"Found {len(records)} record(s):\n\n" + result

        TOOLS = [
            airtable_list_bases,
            airtable_list_tables,
            airtable_list_records,
            airtable_get_record,
            airtable_create_record,
            airtable_update_record,
            airtable_delete_record,
            airtable_search_records,
        ]
    else:
        TOOLS = []


server = AirtableServer(name="airtable", version="1.0.0")
server.tools = AirtableServer.TOOLS
if __name__ == "__main__":
    server.run()
