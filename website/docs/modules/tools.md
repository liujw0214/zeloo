---
id: modules-tools
title: Tools
sidebar_label: Tools
---

# Tools

40+ built-in tools auto-discovered from `tools/` via the `@tool` decorator.

## Categories

- **File operations** — `read_file`, `write_file`, `edit_file`, `list_dir`
- **Web** — `web_search`, `web_fetch`, `browser_navigate`
- **Shell** — `shell_exec`, `shell_run_async`
- **Code execution** — `python_run`, `javascript_run`
- **Image generation** — `image_generate`
- **Video generation** — `video_generate`
- **MCP** — `mcp_call`, `mcp_list_tools`
- **OAuth** — `oauth_authorize`
- **Skills** — `skill_list`, `skill_load`

## Adding custom tools

```python
from tools import tool

@tool(name="my_tool", description="Do something useful")
def my_tool(arg1: str, arg2: int = 0) -> dict:
    return {"result": arg1 * arg2}
```

Tools are auto-registered on import. See `tools/registry.py` for details.