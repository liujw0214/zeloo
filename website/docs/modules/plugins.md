---
id: modules-plugins
title: Plugins
sidebar_label: Plugins
---

# Plugins

Zeloo plugins extend the agent at runtime via hooks.

## Hook points

- `pre_tool_call` — before any tool executes
- `post_tool_call` — after tool returns
- `pre_llm_call` — before LLM call
- `post_llm_call` — after LLM response
- `on_session_start` / `on_session_end`

## Plugin format

```python
from plugins import hook

@hook("post_tool_call")
async def log_tool(tool_name: str, args: dict, result: dict) -> None:
    print(f"[plugin] {tool_name} returned {len(str(result))} chars")
```

## Loading

Plugins auto-load from `~/.Zeloo/plugins/`. See `plugins/manager.py`.