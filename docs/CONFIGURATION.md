# Zeloo Configuration Reference

> Complete guide to `config.yaml`, environment variables, and config
> migration. For CLI flags, see [`CLI_REFERENCE.md`](CLI_REFERENCE.md).

## Table of Contents

- [File Locations](#file-locations)
- [Schema Overview](#schema-overview)
- [Top-Level Sections](#top-level-sections)
- [Environment Variables](#environment-variables)
- [Migration](#migration)
- [Full Example](#full-example)

---

## File Locations

| Path | Purpose |
|------|---------|
| `~/.Zeloo/config.yaml` | Active user configuration |
| `~/.Zeloo/workspace/<name>/profile/config.yaml` | Per-workspace overrides |
| `/etc/Zeloo/config.yaml` | System-wide defaults (Linux) |
| `$(brew --prefix)/etc/Zeloo/config.yaml` | Homebrew defaults (macOS) |
| `./config.yaml` | Project-local override (highest precedence) |

Resolution order (highest → lowest):

```
CLI flag  >  env var  >  project-local  >  workspace profile  >  user  >  system
```

## Schema Overview

The schema is defined in `zeloo_cli.config_schema` as Pydantic models. The
top-level shape:

```python
class Config(BaseModel):
    llm:            LLMConfig
    agent:          AgentConfig
    memory:         MemoryConfig
    skills:         SkillsConfig
    browser:        BrowserConfig
    mcp:            MCPConfig
    telemetry:      TelemetryConfig
    security:       SecurityConfig
    workspace:      WorkspaceConfig
    gateway:        GatewayConfig        # optional
    terminal:       TerminalConfig       # optional
    voice:          VoiceConfig          # optional
    self_evolution: SelfEvolutionConfig  # optional
    curator:        CuratorConfig        # optional
    kanban:         KanbanConfig         # optional
    i18n:           I18NConfig           # optional
    oauth:          OAuthConfig          # optional
```

## Top-Level Sections

### `llm` (required)

```yaml
llm:
  model: gpt-4o
  provider: openai
  temperature: 0.0
  max_tokens: 4096
  base_url: null            # override OpenAI-compatible endpoint
  api_key: ${OPENAI_API_KEY}
  organization: null        # OpenAI org id, optional
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `model` | str | `gpt-4o` | Any registered model id |
| `provider` | str | `openai` | One of the 14 registered providers |
| `temperature` | float | `0.0` | `0.0`–`2.0` |
| `max_tokens` | int | `4096` | Per-response cap |
| `base_url` | str \| null | `null` | For self-hosted / proxied endpoints |
| `api_key` | str | env | Resolved from `OPENAI_API_KEY` etc. |

### `agent`

```yaml
agent:
  max_iterations: 90
  enable_tools: true
  enable_memory: true
  toolset_filter: []            # empty = all tools
  approval_policy: smart        # off | prompt | smart | strict
  smart_model_routing:
    enabled: false
    max_simple_chars: 160
    max_simple_words: 28
    cheap_provider: openai
    cheap_model: gpt-4o-mini
```

### `memory`

```yaml
memory:
  enabled: true
  provider: local              # local | honcho | mem0 | supermemory |
                               # openviking | byterover | hindsight |
                               # holographic | retaindb
  max_chars: 8000
  user_profile_enabled: true
  # provider-specific keys below
  honcho:
    app_name: zeloo
    user_id: default
```

### `skills`

```yaml
skills:
  enabled: true
  auto_install: false
  registry_url: https://skills.zeloo.io
  installed: []                # populated by `zeloo skills install`
```

### `browser`

```yaml
browser:
  backend: playwright          # playwright | firecrawl | browserbase |
                               # camofox | lightpanda
  headless: true
  timeout: 30
  user_data_dir: ~/.zeloo/browser
```

### `mcp`

```yaml
mcp:
  servers:
    - name: filesystem
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    - name: remote-api
      transport: http
      url: https://mcp.example.com/sse
      headers:
        Authorization: Bearer ${MCP_TOKEN}
      dangerous: false         # require explicit approval for writes
```

### `telemetry`

```yaml
telemetry:
  enabled: true
  otlp_endpoint: null          # e.g. https://otel.example.com:4318
  sample_ratio: 0.1
  redact_secrets: true
```

### `security`

```yaml
security:
  scanner:
    enabled: true
    modes: [secret, threat, output]
    on_threat: block           # block | warn | log
  sbom:
    enabled: true
    format: cyclonedx          # cyclonedx | spdx
    output_path: ~/.zeloo/sbom.json
```

### `workspace`

```yaml
workspace:
  root: ~/.Zeloo/workspace
  active: default
  default_tags: []
  snapshot:
    compression: zstd
    level: 19
    exclude:
      - "*.pyc"
      - ".venv/**"
      - "__pycache__/**"
```

### Optional sections

| Section | Default | Purpose |
|---------|---------|---------|
| `gateway` | `enabled: false` | HTTP / WS / platform gateways |
| `terminal` | `backend: local` | Shell execution backend |
| `voice` | `backend: console` | TTS/STT backend |
| `self_evolution` | `enabled: true` | Background review daemon |
| `curator` | `enabled: true` | Skill lifecycle manager |
| `kanban` | `enabled: false` | Multi-agent coordination |
| `i18n` | `default_language: en` | Locale loader |
| `oauth` | empty | OAuth client definitions |

## Environment Variables

Every field can be overridden via environment variable. The mapping rule:

```
zeloo_<section>_<field>     # uppercased, dots → underscores
```

Examples:

| YAML | Env var |
|------|---------|
| `llm.api_key` | `ZELOO_LLM_API_KEY` |
| `llm.model` | `ZELOO_LLM_MODEL` |
| `memory.enabled` | `ZELOO_MEMORY_ENABLED` |
| `mcp.servers[0].headers.Authorization` | `ZELOO_MCP_SERVERS_0_HEADERS_AUTHORIZATION` |

Inside string values, `${VAR}` references are resolved at load time:

```yaml
llm:
  api_key: ${OPENAI_API_KEY}
gateway:
  platforms:
    telegram:
      token: ${TELEGRAM_BOT_TOKEN}
```

Special variables:

| Var | Purpose |
|-----|---------|
| `ZELOO_HOME` | Override `~/.Zeloo` (used by tests) |
| `ZELOO_CONFIG` | Explicit path to `config.yaml` |
| `ZELOO_WORKSPACE` | Override the active workspace |
| `ZELOO_LOG_LEVEL` | `DEBUG` / `INFO` / `WARN` / `ERROR` |
| `ZELOO_NO_COLOR` | Disable ANSI colors |
| `ZELOO_OFFLINE` | Block all outbound network |
| `ZELOO_TELEMETRY_OFF` | Disable telemetry even if enabled in config |

## Migration

Zeloo ships a migration tool:

```bash
Zeloo config migrate [--from v0] [--to v2] [--dry-run]
```

| Version | Removed / changed | Migration |
|---------|-------------------|-----------|
| **v0** (legacy) | flat keys, no nesting | `zeloo config migrate --from v0` |
| **v1** (current) | nested sections, Pydantic | `zeloo config migrate --from v1` |
| **v2** (upcoming) | new `security.scanner.modes` array form | `zeloo config migrate --from v2` |

Each migration is idempotent and emits a diff before writing.

### Backwards-compat shims

For one minor version after a breaking change, the loader accepts the old
key and prints a `DeprecationWarning` pointing to the new key:

```yaml
# v0 (still accepted, prints warning)
model: gpt-4o
max_iterations: 90
```

becomes

```yaml
# v1 (preferred)
llm:
  model: gpt-4o
agent:
  max_iterations: 90
```

## Full Example

```yaml
# ~/.Zeloo/config.yaml
llm:
  model: claude-3-5-sonnet
  provider: anthropic
  temperature: 0.2
  max_tokens: 8192
  api_key: ${ANTHROPIC_API_KEY}

agent:
  max_iterations: 90
  enable_tools: true
  enable_memory: true
  approval_policy: smart
  smart_model_routing:
    enabled: true
    max_simple_chars: 160
    max_simple_words: 28
    cheap_provider: openai
    cheap_model: gpt-4o-mini

memory:
  enabled: true
  provider: local
  max_chars: 8000
  user_profile_enabled: true

skills:
  enabled: true
  auto_install: false

browser:
  backend: playwright
  headless: true
  timeout: 30

mcp:
  servers:
    - name: filesystem
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

telemetry:
  enabled: true
  otlp_endpoint: null
  sample_ratio: 0.1
  redact_secrets: true

security:
  scanner:
    enabled: true
    modes: [secret, threat, output]
    on_threat: block
  sbom:
    enabled: true
    format: cyclonedx
    output_path: ~/.zeloo/sbom.json

workspace:
  root: ~/.Zeloo/workspace
  active: default
  default_tags: []
  snapshot:
    compression: zstd
    level: 19
    exclude: ["*.pyc", ".venv/**", "__pycache__/**"]

gateway:
  enabled: true
  api:
    host: 0.0.0.0
    port: 8080
  session_idle_timeout: 3600
  platforms:
    telegram:
      enabled: true
      token: ${TELEGRAM_BOT_TOKEN}
      allowed_users: []

terminal:
  backend: local
  timeout: 30

voice:
  backend: console

self_evolution:
  background_review:
    enabled: true
    interval_minutes: 10

curator:
  enabled: true
  stale_after_days: 30
  archive_after_days: 90

i18n:
  default_language: en
```

## Validation

Run `Zeloo config validate --strict` to check the active config against the
schema. The validator returns:

| Code | Meaning |
|------|---------|
| `0` | Valid |
| `1` | Warnings (unknown keys) |
| `2` | Errors (missing required, wrong type) |

Example:

```bash
$ Zeloo config validate --strict
OK — 0 errors, 0 warnings
```

## Tips

1. **Start from the example.** Copy `config.yaml.example` and edit.
2. **Use `${VAR}` references** for secrets — never inline keys.
3. **Run `Zeloo doctor`** after editing — it catches typos.
4. **Commit a sanitized copy** to your repo for reproducibility (no secrets).
5. **Per-workspace overrides** beat per-user overrides for project-specific
   tuning.