# Zeloo API Reference

> Module-level reference for the Zeloo runtime libraries.
> For end-user CLI usage, see [`CLI_REFERENCE.md`](CLI_REFERENCE.md).
> For configuration, see [`CONFIGURATION.md`](CONFIGURATION.md).

## Table of Contents

- [Auth (`zeloo_cli.auth`)](#auth-zeloo_cliauth)
- [Config (`zeloo_cli.config_*`)](#config-zeloo_cliconfig_)
- [Core (`zeloo_cli.core.*`)](#core-zeloo_clicore)
- [Providers (`agent.providers.*`)](#providers-agentproviders)
- [Tools (`tools.*`)](#tools-tools)
- [Gateway (`gateway.*`)](#gateway-gateway)
- [Security (`security.*`)](#security-security)
- [Workspace (`workspace.*`)](#workspace-workspace)
- [Memory (`agent.memory_*`)](#memory-agentmemory_)
- [Cron (`cron.*`)](#cron-cron)

---

## Auth (`zeloo_cli.auth`)

```python
from zeloo_cli.auth import BaseAuth, AUTH_REGISTRY, TokenStore
```

### `BaseAuth`

```python
class BaseAuth(Protocol):
    name: str
    def login(self, **kwargs) -> AuthSession: ...
    def logout(self) -> None: ...
    def refresh(self, session: AuthSession) -> AuthSession: ...
    def session(self) -> AuthSession | None: ...
```

Subclass to add a new auth provider.

### `AUTH_REGISTRY`

```python
AUTH_REGISTRY: dict[str, type[BaseAuth]] = {
    "anthropic": AnthropicAuth,
    "openai":    OpenAIAuth,
    "google":    GoogleAuth,
    "github":    GitHubAuth,
    "discord":   DiscordAuth,
    "xai":       XAIAuth,
    # ... 16 total
}
```

### `TokenStore`

Encrypted on-disk store (`~/.zeloo/oauth_tokens.json`, mode `0600`).

```python
store = TokenStore(path="~/.zeloo/oauth_tokens.json", key=fernet_key)
store.put("openai", AuthSession(access=..., refresh=..., expires=...))
session = store.get("openai")
store.delete("openai")
```

---

## Config (`zeloo_cli.config_*`)

Five cooperating modules:

| Module | Purpose |
|--------|---------|
| `zeloo_cli.config_loader` | Read YAML / env / CLI overrides |
| `zeloo_cli.config_schema` | Pydantic models for every section |
| `zeloo_cli.config_migrate` | v0 → v1 → v2 migrations |
| `zeloo_cli.config_validate` | Strict validation + friendly error messages |
| `zeloo_cli.config_watch` | Hot-reload on file change |

### Example

```python
from zeloo_cli.config_loader import load_config
cfg = load_config("~/.Zeloo/config.yaml")
print(cfg.llm.model, cfg.agent.max_iterations)
```

---

## Core (`zeloo_cli.core.*`)

21 modules exposing the runtime kernel (Phase 1: infrastructure, Phase 2: observability/security/extension).

| Module | Purpose |
|--------|---------|
| `core.event_bus` | Typed publish/subscribe event system (`EventBus`, `Event`, `Subscription`) |
| `core.scheduler` | Background task scheduler (`Scheduler`, `ScheduledTask`) |
| `core.cache` | LRU + TTL cache (`Cache`, `CacheEntry`, `TTLCache`) |
| `core.rate_limiter` | Token-bucket / sliding-window rate limiting (`RateLimiter`, `RateLimitResult`, `RateLimitStrategy`) |
| `core.circuit_breaker` | Resilient service call protection (`CircuitBreaker`, `CircuitState`, `CircuitStats`) |
| `core.task_queue` | Async task queue with worker pool (`TaskQueue`, `Task`, `TaskResult`, `TaskStatus`) |
| `core.middleware` | Request/response middleware pipeline (`Middleware`, `MiddlewareChain`, `RequestContext`, `ResponseContext`) |
| `core.multi_tenant` | Tenant isolation and routing (`Tenant`, `TenantContext`, `TenantManager`) |
| `core.realtime_engine` | WebSocket/SSE realtime push (`RealtimeEngine`, `SubscriptionChannel`) |
| `core.tracing` | OpenTelemetry-compatible distributed tracing (`Tracer`, `Span`) |
| `core.metrics` | Counters, gauges, histograms (`MetricsCollector`, `MetricPoint`, `HistogramStats`) |
| `core.feature_flags` | Runtime feature toggles and A/B testing (`FeatureFlagManager`, `FeatureFlag`, `FlagState`) |
| `core.secrets` | Encrypted credential storage with rotation (`SecretManager`, `Secret`) |
| `core.lifecycle` | Application startup/shutdown orchestration (`LifecycleManager`, `LifecycleHook`, `LifecyclePhase`) |
| `core.plugin_manager` | Dynamic plugin loading (`PluginManager`, `PluginInfo`, `PluginState`) |
| `core.state_store` | Key-value state with TTL and atomic ops (`StateStore`, `StateEntry`) |
| `core.retry` | Retry strategies (`RetryStrategy` + `with_retry(...)` helper) |
| `core.timeout` | Timeout context manager (`Timeout`) |
| `core.bulkhead` | Per-resource isolation (`Bulkhead`) |
| `core.dead_letter_queue` | Dead-letter queue for failed tasks (`DeadLetterQueue`) |
| `core.structured_logging` | Structured JSON logger (`get_logger`, `JsonFormatter`) |

### Example — retry helper

```python
from zeloo_cli.core.retry import with_retry, RetryStrategy

@with_retry(strategy=RetryStrategy.EXPONENTIAL, max_attempts=5, base=0.5)
async def call_provider(req):
    return await provider.complete(req)
```

---

## Providers (`agent.providers.*`)

### `BaseProvider`

```python
class BaseProvider(Protocol):
    name: str
    async def complete(self, request: ChatRequest) -> ChatResponse: ...
    async def stream(self, request: ChatRequest) -> AsyncIterator[Chunk]: ...
    def count_tokens(self, text: str) -> int: ...
```

### Built-in providers (14)

| Provider | Module | Use it for |
|----------|--------|-----------|
| `openai` | `agent/providers/_http.py` (default) | GPT-4o, o1, ... |
| `anthropic` | `agent/providers/_http.py` | Claude 3.x |
| `deepseek` | `agent/providers/deepseek.py` | DeepSeek-V3 |
| `groq` | `agent/providers/groq.py` | Llama 3 on Groq |
| `mistral` | `agent/providers/mistral.py` | Mistral Large |
| `ollama` | `agent/providers/ollama.py` | Local Llama / Qwen |
| `openrouter` | `agent/providers/openrouter.py` | Aggregator |
| `azure` | `agent/providers/azure.py` | Azure OpenAI |
| `fireworks` | `agent/providers/fireworks.py` | Fireworks AI |
| `together` | `agent/providers/together.py` | Together AI |
| `bedrock` | `agent/providers/bedrock.py` | AWS Bedrock |
| `local` | `agent/providers/local.py` | Generic OpenAI-compatible |
| `cohere` | `model_providers/cohere.py` | Cohere |
| `gemini` | `model_providers/gemini.py` | Google Gemini |
| `xai` | `model_providers/xai.py` | Grok |

### `ProviderRouter`

```python
from agent.provider_router import ProviderRouter
router = ProviderRouter.from_yaml("~/.zeloo/fallback.yaml")
resp = await router.complete(req)   # auto-fallback on failure
```

---

## Tools (`tools.*`)

All tools subclass `tools.base.ToolBase` and are auto-registered via the
`@tool` decorator.

### Categories

| Category | Modules |
|----------|---------|
| Browser | `browser_tool`, `browser_tools`, `browser_camofox`, `browser_cdp_tool`, `browser_cloud`, `browser_origin`, `browser_vision`, `browser_snapshot`, `real_profile`, `lightpanda` |
| MCP | `mcp_tool`, `mcp_oauth`, `mcp_oauth_device`, `mcp_oauth_manager`, `mcp_tool_common`, `mcp_tool_config`, `mcp_tool_handlers`, `mcp_discovery_auto` |
| Approval | `approval`, `approval_context`, `approval_floors`, `approval_prompt`, `approval_smart`, `human_wait` |
| File ops | `file_operations`, `file_state`, `file_tools`, `file_tools_paths`, `path_safety` |
| Delegation | `delegate_tool`, `advanced_toolkit` |
| Code exec | `code_exec`, `code_kernel`, `shell_tool`, `ssh_tool`, `database_tool`, `clipboard_tool` |
| Integrations | `integrations/` (10+ platforms) |
| Voice / Media | `voice_tool`, `image_tools`, `web_tools` |
| Coordination | `kanban_tools`, `todo_tools`, `journey_tracker` |
| Memory | `memory_tool` |
| Skills | `skills_tool`, `cron_tool` |
| Workspace | `workspace_tools` |

### Writing a custom tool

```python
from tools.base import ToolBase, tool

@tool(name="my_tool", description="Reverse a string")
class ReverseTool(ToolBase):
    def run(self, text: str) -> str:
        return text[::-1]
```

---

## Gateway (`gateway.*`)

| Module | Purpose |
|--------|---------|
| `gateway.api_server` | FastAPI OpenAI-compatible server |
| `gateway.run` | Process supervisor |
| `gateway.session` | Session manager (TTL + idle eviction) |
| `gateway.websocket` | WebSocket gateway |
| `gateway.sse` | Server-Sent Events streaming |
| `gateway.middleware` | RateLimit / Auth / Logging / CORS chain |
| `gateway.metrics` | Prometheus exposition |
| `gateway.status` | `/healthz`, `/readyz` |
| `gateway.voice` | Voice sub-system |
| `gateway.platforms/` | 17 platform adapters |

### Example — mounting a custom route

```python
from gateway.api_server import app

@app.get("/v1/custom")
async def custom_endpoint():
    return {"ok": True}
```

---

## Security (`security.*`)

### `security.scanner`

```python
from security.scanner import Scanner, ScanMode

scanner = Scanner(mode=ScanMode.SECRET | ScanMode.THREAT | ScanMode.OUTPUT)
findings = scanner.scan_text("AKIA...rest of secret...")
for f in findings:
    print(f.severity, f.location, f.recommendation)
```

Three scan passes:

| Pass | What it detects |
|------|-----------------|
| `SECRET` | API keys, tokens, passwords, private keys |
| `THREAT` | Prompt injection, jailbreak, exfiltration |
| `OUTPUT` | Toxic content, PII, copyrighted text |

### `security.sbom`

```python
from security.sbom import generate_sbom, Format

cyclonedx = generate_sbom(Format.CYCLONEDX, root=".")
spdx      = generate_sbom(Format.SPDX,      root=".")
```

---

## Workspace (`workspace.*`)

| Module | Purpose |
|--------|---------|
| `workspace.manager` | Create / list / switch / archive |
| `workspace.snapshot` | `.tar.zst` snapshots |
| `workspace.importer` | Import from bundle |
| `workspace.templates` | `SOUL.md` / `USER.md` templates |

### Example

```python
from workspace.manager import WorkspaceManager

mgr = WorkspaceManager("~/.Zeloo/workspace")
mgr.create("alpha", from_="default", tags=["client-x"])
mgr.switch("alpha")
mgr.archive("alpha", label="pre_delete")
```

---

## Memory (`agent.memory_*`)

| Module | Purpose |
|--------|---------|
| `agent.memory_manager` | High-level facade |
| `agent.memory_providers` | Pluggable backends |
| `agent.memory_compressor` | LLM summarization |
| `agent.memory_gc` | Stale-entry cleanup |

### Backends

| Provider | Class |
|----------|-------|
| Local (SQLite) | `LocalMemoryProvider` |
| Honcho | `HonchoMemoryProvider` |
| Mem0 | `Mem0MemoryProvider` |
| Supermemory | `SupermemoryMemoryProvider` |
| OpenViking | `OpenVikingMemoryProvider` |
| Byterover | `ByteroverMemoryProvider` |
| Hindsight | `HindsightMemoryProvider` |
| Holographic | `HolographicMemoryProvider` |
| RetainDB | `RetainDBMemoryProvider` |

### Example

```python
from agent.memory_providers import LocalMemoryProvider
mem = LocalMemoryProvider(path="~/.zeloo/memory.db")
mem.write("user", "Prefers dark mode")
hits = mem.search("preferences", limit=5)
```

---

## Cron (`cron.*`)

```python
from cron.scheduler import Scheduler

sched = Scheduler()
sched.add("0 8 * * *", "morning_briefing", prompt="Summarize today's tasks")
sched.run_forever()
```

CLI shortcuts live under `Zeloo cron` (see `CLI_REFERENCE.md`).

---

## Conventions

- **Type hints**: every public function is fully annotated.
- **Async-first**: I/O-bound APIs are `async def`.
- **Pydantic models**: every request / response / config is a model.
- **Backwards compat**: deprecated symbols keep working for ≥1 minor version
  with a `DeprecationWarning`.
- **Logging**: use `core.structured_logging.get_logger(__name__)` — never `print()`.

## Versioning

The public API follows [Semantic Versioning](https://semver.org/).
Breaking changes are announced in [`CHANGELOG.md`](../CHANGELOG.md).