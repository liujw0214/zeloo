"""MCP server base framework — reusable stdio JSON-RPC 2.0 server."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., str]


@dataclass(init=False)
class MCPServer:
    name: str = ""
    version: str = "1.0.0"
    tools: list[MCPTool] = field(default_factory=list)

    def __init__(self, name: str = "", version: str = "1.0.0", tools: list = None) -> None:  # noqa: A002
        self.name = name or self.__class__.name
        self.version = version or self.__class__.version
        self.tools = tools if tools is not None else []

    def _build_tools_response(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
            }
            for t in self.tools
        ]

    def _handle_request(self, req: dict[str, Any]) -> dict[str, Any] | None:
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.name, "version": self.version},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self._build_tools_response()},
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            for tool in self.tools:
                if tool.name == tool_name:
                    try:
                        result_text = tool.handler(**arguments)
                        content = [{"type": "text", "text": result_text}]
                        return {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {"content": content},
                        }
                    except Exception as e:
                        content = [{"type": "text", "text": f"Error: {e}"}]
                        return {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {"content": content, "isError": True},
                        }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
            }

        if method.startswith("notifications/"):
            return None

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _read_message(self) -> dict[str, Any] | None:
        try:
            line = sys.stdin.readline()
            if not line:
                return None
            return json.loads(line.strip())
        except (json.JSONDecodeError, EOFError):
            return None

    def _write_message(self, msg: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()

    def run(self) -> None:
        while True:
            req = self._read_message()
            if req is None:
                break
            resp = self._handle_request(req)
            if resp is not None:
                self._write_message(resp)


def make_tool(*args, **kwargs):
    """Decorator factory for MCP tools.

    Supports three invocation styles:

    1. Parameterised (preferred for explicit schemas):
        @make_tool("name", "description", {"type": "object", ...})
        def my_tool(...): ...

    2. Bare (auto-derive from function signature + docstring):
        @make_tool
        def my_tool(x: int, y: str = "default") -> str:
            '''Short description.'''
            ...

    3. Direct application (decorator used without parens):
        @make_tool
        def my_tool(...): ...
        # equivalent to make_tool()(my_tool)
    """
    if len(args) == 3 and not kwargs:
        name, description, input_schema = args

        def explicit_decorator(handler: Callable[..., str]) -> MCPTool:
            return MCPTool(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=handler,
            )
        return explicit_decorator

    # @make_tool(name=..., description=..., input_schema=...) — keyword-only form
    if not args and {"name", "description", "input_schema"} & set(kwargs.keys()):
        name = kwargs.get("name")
        description = kwargs.get("description", "")
        input_schema = kwargs.get("input_schema", {"type": "object", "properties": {}})

        def kw_decorator(handler: Callable[..., str]) -> MCPTool:
            return MCPTool(
                name=name or handler.__name__,
                description=description,
                input_schema=input_schema,
                handler=handler,
            )
        return kw_decorator

    if len(args) == 1 and callable(args[0]) and not kwargs:
        # @make_tool  (used directly on a function, equivalent to @make_tool())
        return _auto_tool(args[0])

    if not args and not kwargs:
        # @make_tool()  (with parens)
        def auto_decorator(handler: Callable[..., str]) -> MCPTool:
            return _auto_tool(handler)
        return auto_decorator

    raise TypeError(
        "make_tool must be called either with (name, description, schema) "
        f"or with no arguments; got args={args!r} kwargs={kwargs!r}"
    )


def _auto_tool(handler: Callable[..., str]) -> MCPTool:
    """Derive an MCPTool from a function's signature and docstring."""
    import inspect

    sig = inspect.signature(handler)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        # Skip *args/**kwargs — they're not part of the MCP contract
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = param.annotation
        # Default annotation if missing
        if annotation is inspect._empty:
            annotation = str
        schema = _py_type_to_json_schema(annotation)
        # If a default value is provided, mark the property optional
        if param.default is inspect._empty:
            required.append(pname)
        else:
            schema["default"] = param.default
        properties[pname] = schema

    # First non-empty line of the docstring becomes the description
    doc = inspect.getdoc(handler) or ""
    description = doc.split("\n", 1)[0].strip() if doc else handler.__name__

    input_schema = {
        "type": "object",
        "properties": properties,
    }
    if required:
        input_schema["required"] = required

    return MCPTool(
        name=handler.__name__,
        description=description,
        input_schema=input_schema,
        handler=handler,
    )


# Mapping from common Python types to JSON-Schema fragments
_PY_TYPE_MAP: dict[Any, dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    list: {"type": "array", "items": {"type": "string"}},
    dict: {"type": "object"},
}


def _py_type_to_json_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python annotation into a basic JSON-Schema fragment.

    Handles primitive types and ``Optional[X]`` / ``X | None`` unions.
    Anything unknown is returned as ``{"type": "string"}`` so the schema
    remains valid JSON.
    """
    import typing

    if annotation in _PY_TYPE_MAP:
        return dict(_PY_TYPE_MAP[annotation])
    # Optional[X] / X | None
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _py_type_to_json_schema(args[0])
    # typing.List[X] / list[X]
    if origin in (list, list):
        inner_args = typing.get_args(annotation)
        items = _py_type_to_json_schema(inner_args[0]) if inner_args else {"type": "string"}
        return {"type": "array", "items": items}
    # typing.Dict[K, V]
    if origin in (dict, dict):
        return {"type": "object"}
    return {"type": "string"}
