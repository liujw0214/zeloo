# Zeloo Architecture

> High-level system architecture for the Zeloo self-hosted AI agent runtime.

## Table of Contents

- [Overview](#overview)
- [Layer Diagram](#layer-diagram)
- [Data Flow](#data-flow)
- [Key Modules by Layer](#key-modules-by-layer)
- [Extension Points](#extension-points)

---

## Overview

Zeloo is organized as **four cooperating layers**:

1. **Interface Layer** — CLI, TUI, HTTP API, platform gateways.
2. **Agent Loop Layer** — conversation loop, planning, reflection, memory.
3. **Tool & Integration Layer** — 80+ tools (browser, MCP, code exec, files,
   integrations), plugins, skills.
4. **Provider & Auth Layer** — LLM providers (14), auth providers (16),
   credential pool, fallback router.

The entire stack is single-binary, single-process by default, but each layer
can be deployed independently (e.g. HTTP gateway on one host, providers on
another).

## Layer Diagram

```
+-----------------------------------------------------------------------+
|                       INTERFACE LAYER                                 |
|                                                                       |
|   +-----------+   +---------+   +-----------+   +-----------------+   |
|   |  CLI      |   |   TUI   |   | HTTP API  |   | 17 platform     |   |
|   | (cli.py)  |   | (Textual|   | (FastAPI) |   | gateways        |   |
|   |           |   |  + Rich)|   |  :8080    |   | (slack, tg,     |   |
|   +-----------+   +---------+   +-----------+   |  discord, ...)  |   |
|         |             |              |          +-----------------+   |
+---------|-------------|--------------|---------------------|----------+
          v             v              v                     v
+-----------------------------------------------------------------------+
|                       AGENT LOOP LAYER                                |
|                                                                       |
|   +--------------+   +-------------+   +--------------------------+   |
|   | Conversation |   | Hierarchical|   |  Context Engine           |   |
|   | Loop         |<->| Planner     |<->|  (rotator, compactor,    |   |
|   | (turn final, |   | (Kanban)    |   |   trimmer, breakdown)    |   |
|   |  token-aware)|   +-------------+   +--------------------------+   |
|   +------+-------+                                                   |
|          |                                                           |
|          v                                                           |
|   +--------------+   +-------------+   +--------------------------+   |
|   | Reflection   |   | Task        |   |  Memory Manager           |   |
|   | Engine       |   | Compactor   |   |  (providers, GC,          |   |
|   +--------------+   +-------------+   |   compressor, curator)    |   |
|                                        +--------------------------+   |
|                          +---------------------+                      |
|                          | Background Review   |                      |
|                          | (self-evolution)    |                      |
|                          +---------------------+                      |
+---------|------------|------------|---------------------|--------------+
          v            v            v                     v
+-----------------------------------------------------------------------+
|                  TOOL & INTEGRATION LAYER                             |
|                                                                       |
|  +----------+  +----------+  +----------+  +-----------+  +----------+ |
|  | Browser  |  |   MCP    |  |  Code    |  |    File   |  |   Voice  | |
|  | 5 backs  |  | stdio+   |  |  Exec    |  |    Ops    |  |   /      | |
|  |          |  |  http+   |  |  + SSH   |  |  + State  |  |   Image  | |
|  |          |  |  oauth   |  |  + Shell |  |           |  |          | |
|  +----------+  +----------+  +----------+  +-----------+  +----------+ |
|                                                                       |
|  +----------+  +----------+  +----------+  +-----------+              |
|  | Approval |  | Delegate |  | Cron     |  |  17       |              |
|  | (smart + |  |  /       |  |  Tool    |  |  Integr.  |              |
|  |  floors) |  |  Kanban  |  |          |  |  (GH, Nt, |              |
|  +----------+  +----------+  +----------+  |   Jira..) |              |
|                                            +-----------+              |
|  Plugins  ──>  Hooks  ──>  Skills (21 SKILL.md workflows)             |
+---------|------------|------------|---------------------|--------------+
          v            v            v                     v
+-----------------------------------------------------------------------+
|                  PROVIDER & AUTH LAYER                                |
|                                                                       |
|   +-------------------+        +-----------------------+              |
|   | 14 LLM Providers  |        | 16 Auth Providers     |              |
|   | openai, anthropic, |        | oauth, device, token, |              |
|   | deepseek, groq,    |        | key file             |              |
|   | ollama, fireworks,|        +-----------------------+              |
|   | together, bedrock,|                                              |
|   | ...               |        +-----------------------+              |
|   +-------------------+        | Credential Pool       |              |
|            |                   | (encrypted, rotation, |              |
|            v                   |  cooldown)            |              |
|   +-------------------+        +-----------------------+              |
|   | Provider Router   |                                               |
|   | (fallback chain   |        +-----------------------+              |
|   |  + smart routing) |        | Security Scanner      |              |
|   +-------------------+        | (secret/threat/output)|              |
|                                +-----------------------+              |
+-----------------------------------------------------------------------+
```

## Data Flow

A typical user request flows through the layers as follows:

```
User
 │  (typed prompt, voice, slack message, http POST)
 v
Interface Layer  ──> parse, attach session, attach profile
 │
 v
Agent Loop Layer ──> build system prompt, hydrate memory,
 │                   run hierarchical planner, dispatch subtasks
 v
Tool & Integration Layer ──> execute tool calls (browser, code, file,
 │                            mcp, integration) — possibly recursively
 v
Provider & Auth Layer ──> select provider via Router, sign request,
 │                         stream tokens back
 v
Agent Loop Layer ──> reflection, compaction, finalize turn
 │
 v
Interface Layer ──> render response (markdown / TUI widget / HTTP chunk)
 │
 v
User
```

### Key invariants

- The **conversation loop** owns the canonical state — all other layers are
  pure functions of it.
- Tools are **side-effecting** but always return a `ToolResult` (success /
  failure / partial) so the loop can reason about them.
- Providers are **stateless adapters** — credentials live in the credential
  pool, never in the provider module.

## Key Modules by Layer

### 1. Interface Layer

| Module | Purpose |
|--------|---------|
| `cli.py` / `__main__.py` | Argparse root, dispatches to subcommands |
| `tui_gateway/` | Textual TUI renderer |
| `gateway/api_server.py` | FastAPI OpenAI-compatible HTTP server |
| `gateway/websocket.py` | Bidirectional WS gateway |
| `gateway/sse.py` | Server-sent events streaming |
| `gateway/platforms/*.py` | Per-platform adapters (17 files) |

### 2. Agent Loop Layer

| Module | Purpose |
|--------|---------|
| `agent/conversation_loop.py` | Main turn loop, token-aware trimming |
| `agent/task_planner.py` | Hierarchical planner with Kanban backend |
| `agent/reflection_engine.py` | Self-critique / retry on failure |
| `agent/context_engine.py` | Unified context composition |
| `agent/context_rotator.py` | Sliding-window rotation |
| `agent/task_compactor.py` | Merges parallel subtasks |
| `agent/turn_finalizer.py` | Last-mile response shaping |
| `agent/memory_manager.py` | Read/write persistent memory |
| `agent/memory_compressor.py` | LLM-driven summarization |
| `agent/memory_gc.py` | Stale-entry cleanup |
| `agent/curator.py` | Active/stale/archived skill lifecycle |
| `agent/background_review.py` | Self-evolution daemon |
| `agent/background_tasks.py` | Async task supervisor |
| `agent/system_prompt.py` | 3-layer prompt builder (stable/context/volatile) |
| `agent/prompt_builder.py` | Domain-specific prompt fragments |
| `agent/cost_optimizer.py` | Choose cheap model for trivial turns |
| `agent/cost_tracker.py` | Per-token / per-request accounting |
| `agent/rate_limiter.py` | Token-bucket per provider |
| `agent/error_classifier.py` | Distinguish transient / fatal / auth errors |
| `agent/error_tracker.py` | Aggregate error metrics |
| `agent/checkpoint.py` / `replay.py` | Snapshot / restore agent state |
| `agent/estop.py` | Emergency-stop switch |
| `agent/execution_sandbox.py` | Per-tool sandbox isolation |
| `agent/agent_analytics.py` | Run-level metrics |
| `agent/agent_init.py` | Bootstrapping |
| `agent/i18n.py` | Locale loading |

### 3. Tool & Integration Layer

| Module group | Purpose |
|--------------|---------|
| `tools/browser_*` | 5+ browser backends (playwright, firecrawl, browserbase, camofox, lightpanda) |
| `tools/mcp_*` | MCP stdio + HTTP + OAuth + device-code + auto-discovery |
| `tools/file_*` | File ops, state, paths, path-safety guard |
| `tools/code_exec.py` / `code_kernel.py` / `shell_tool.py` / `ssh_tool.py` | Code execution |
| `tools/database_tool.py` | SQL queries |
| `tools/approval*.py` | Approval floors, smart prompts, human-wait |
| `tools/delegate_tool.py` | Sub-agent delegation |
| `tools/cron_tool.py` | Schedule tool calls |
| `tools/skills_tool.py` | Skill invocation |
| `tools/memory_tool.py` | Memory write tool |
| `tools/voice_tool.py` / `image_tools.py` / `web_tools.py` | Media |
| `tools/kanban_tools.py` / `todo_tools.py` / `journey_tracker.py` | Coordination |
| `tools/integrations/` | 10+ platform integrations (GH, Notion, Linear, Jira, Slack, Discord, Telegram, Feishu, WhatsApp, HomeAssistant, Spotify) |
| `tools/registry.py` | Tool registry & dispatcher |
| `plugins/` | Plugin loader + hook system |
| `skills/` | 21 SKILL.md workflow documents |
| `terminal/` | Terminal backends (local, docker, ssh, modal, daytona, vercel_sandbox, singularity) |

### 4. Provider & Auth Layer

| Module | Purpose |
|--------|---------|
| `agent/providers/base.py` | Abstract `BaseProvider` |
| `agent/providers/_http.py` | Generic OpenAI-compatible HTTP adapter |
| `agent/providers/{deepseek,groq,mistral,ollama,openrouter,azure,fireworks,together,bedrock,local}.py` | Provider adapters |
| `agent/provider_router.py` | Selection + fallback chain |
| `agent/fallback_config.py` | YAML-driven fallback config |
| `agent/credential_pool.py` | Encrypted pool, rotation, cooldown |
| `agent/credential_crypto.py` | Fernet-based at-rest encryption |
| `agent/oauth.py` | Generic OAuth2 client |
| `zeloo_cli/auth/` | 16 auth strategies |
| `security/scanner.py` | Secret + threat + output scanner |
| `security/sbom.py` | CycloneDX + SPDX generator |

## Extension Points

| Hook | Where | How to extend |
|------|-------|---------------|
| **CLI subcommand** | `cli.py` | Decorate with `@cli.command()` |
| **Tool** | `tools/` | Subclass `ToolBase`, register via `@tool` decorator |
| **LLM provider** | `agent/providers/` | Subclass `BaseProvider`, register via `PROVIDER_REGISTRY` |
| **Auth provider** | `zeloo_cli/auth/` | Subclass `BaseAuth`, register via `AUTH_REGISTRY` |
| **Platform gateway** | `gateway/platforms/` | Implement `BasePlatform.run()` |
| **MCP server** | `mcp_serve.py` or external | Standard MCP protocol |
| **Skill** | `skills/<name>/SKILL.md` | Markdown + frontmatter |
| **Plugin** | `plugins/` | Drop-in module exporting `setup(agent)` |
| **Hook** | `plugins/hooks.py` | Register callback for an event name |
| **Memory backend** | `agent/memory_providers.py` | Subclass `BaseMemoryProvider` |
| **Terminal backend** | `terminal/` | Subclass `TerminalBase` |
| **Image / Video gen** | `image_gen/` / `video_gen/` | Subclass `BaseImageGen` / `BaseVideoGen` |
| **Web search** | `web_providers/` | Subclass `BaseWebProvider` |

---

## Deployment Topologies

```
                  +-------------------+
                  |    Single Box     |
                  |  CLI + Agent +    |
                  |  Tools + Provider |
                  +-------------------+

              OR

   +-----------+       +---------------+       +-----------+
   |  Gateway  | <---> |  Agent Loop   | <---> |  Provider |
   |  (HTTP,   |       |  (worker)     |       |  Cluster  |
   |   WS, SSE)|       +---------------+       +-----------+
   +-----------+              |
                              v
                       +-------------+
                       | MCP Servers |
                       +-------------+
```

Both topologies share the same code; only the process boundaries differ.