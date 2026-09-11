# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Round 65–78: Hermes v0.16.0 Alignment)

#### CLI Subcommands

35 subcommands implemented and registered through `cli.py`/`__main__.py`:

| Category | Subcommands |
|----------|-------------|
| Core chat | `chat`, `tui`, `serve`, `z` |
| Admin | `setup`, `config`, `auth`, `login`, `logout`, `verify` |
| Status | `status`, `doctor`, `sync`, `sessions`, `logs`, `metrics` |
| Tools | `tools`, `skills`, `mcp`, `browser`, `plugins`, `hooks` |
| Memory | `memory`, `journey`, `goals` |
| Providers | `model`, `fallback` |
| Workspaces | `workspace`, `profile`, `worktree`, `init`, `export`, `import`, `reset` |
| Ops | `install`, `uninstall`, `update`, `repair`, `backup`, `dump`, `secrets` |
| Helper | `version`, `dashboard`, `usage` |
| Aliases | `version` → plugins/cron/fallback sub-views |

#### Provider System

- **14 LLM providers** registered in `agent/providers/`:
  `deepseek`, `groq`, `mistral`, `ollama`, `openrouter`, `azure`,
  `fireworks`, `together`, `bedrock`, `local`, plus the base
  `openai`/`anthropic` adapters and a generic HTTP adapter.
- **16 Auth providers** in `zeloo_cli/auth/`:
  `anthropic`, `openai`, `google`, `github`, `discord`, `xai`,
  plus device-code flows for codex/nous and OAuth extensions.

#### Tool Ecosystem (80+ tools)

| Group | Modules |
|-------|---------|
| Browser | `browser_tool`, `browser_tools`, `browser_camofox`, `browser_cdp_tool`, `browser_cloud`, `browser_origin`, `browser_vision`, `browser_snapshot`, `real_profile`, `lightpanda` |
| MCP | `mcp_tool`, `mcp_oauth`, `mcp_oauth_device`, `mcp_oauth_manager`, `mcp_tool_common`, `mcp_tool_config`, `mcp_tool_handlers`, `mcp_discovery_auto` |
| Approval | `approval`, `approval_context`, `approval_floors`, `approval_prompt`, `approval_smart`, `human_wait` |
| File ops | `file_operations`, `file_state`, `file_tools`, `file_tools_paths`, `path_safety` |
| Delegation | `delegate_tool`, `advanced_toolkit` |
| Code exec | `code_exec`, `code_kernel`, `shell_tool`, `ssh_tool`, `database_tool`, `clipboard_tool` |
| Integrations | Discord, Slack, Telegram, Feishu, WhatsApp, HomeAssistant, GitHub, Spotify, Notion, Linear, Jira (in `tools/integrations/`) |
| Voice / Media | `voice_tool`, `image_tools`, `web_tools`, `kanban_tools`, `todo_tools`, `memory_tool`, `skills_tool`, `cron_tool`, `workspace_tools`, `journey_tracker` |
| Security | `output_scan`, `threat_patterns`, `secret_scanner` (in `agent/`) |

#### Agent Capabilities

- **Task Compactor** (`agent/task_compactor.py`) — merges parallel subtasks.
- **Context Rotator** (`agent/context_rotator.py`) — sliding-window rotation.
- **Token-Aware Trimmer** (`agent/conversation_loop.py`) — token-budget aware trimming.
- **Reflection Engine** (`agent/reflection_engine.py`) — self-critique loop.
- **Hierarchical Planner** (`agent/task_planner.py`) — multi-level plans with Kanban backend.
- **Tool Semantic Search** (`agent/tool_recommender.py`) — embedding-based tool ranking.
- **Background Tasks** (`agent/background_tasks.py`, `agent/background_review.py`).
- **Memory Compressor** (`agent/memory_compressor.py`).
- **Memory GC** (`agent/memory_gc.py`) — automatic stale-entry cleanup.
- **Cost Optimizer** (`agent/cost_optimizer.py`) + **Cost Tracker** (`agent/cost_tracker.py`).
- **Credential Pool** (`agent/credential_pool.py`) with encrypted on-disk store (`agent/credential_crypto.py`).
- **Provider Router** (`agent/provider_router.py`) with YAML-configurable fallback chain (`agent/fallback_config.py`).
- **Smart Model Routing** + **Auxiliary Client** (`agent/auxiliary_client.py`).
- **Rate Limiter** (`agent/rate_limiter.py`), **Error Classifier** (`agent/error_classifier.py`), **Error Tracker** (`agent/error_tracker.py`).
- **Insights** (`agent/insights.py`), **Analytics** (`agent/agent_analytics.py`), **Audit Log** (`agent/audit_log.py`).
- **Checkpoint/Replay** (`agent/checkpoint.py`, `agent/replay.py`).
- **Skill Hot Reload** (`agent/skill_hot_reload.py`), **Skill Webhooks** (`agent/skill_webhooks.py`), **Skill Utils** (`agent/skill_utils.py`).
- **Curator** (`agent/curator.py`) — active/stale/archived lifecycle.
- **Kanban** (`agent/kanban.py`) — multi-agent coordination.
- **i18n** (`agent/i18n.py`), **Display** (`agent/display.py`).
- **System Prompt** builder (`agent/system_prompt.py`), **Prompt Builder** (`agent/prompt_builder.py`).
- **Context Engine** (`agent/context_engine.py`), **Context Breakdown** (`agent/context_breakdown.py`).
- **E-Stop** (`agent/estop.py`), **Execution Sandbox** (`agent/execution_sandbox.py`).
- **Memory Manager / Providers** (`agent/memory_manager.py`, `agent/memory_providers.py`).
- **OAuth** (`agent/oauth.py`).
- **Runtime CWD** tracking (`agent/runtime_cwd.py`), **Turn Finalizer** (`agent/turn_finalizer.py`), **Agent Init** (`agent/agent_init.py`), **Constants** (`agent/zeloo_constants.py`).

#### Gateway Enhancements

- Middleware chain (`gateway/middleware.py`): RateLimit / Auth / Logging / CORS.
- **SSE streaming** (`gateway/sse.py`).
- **Prometheus metrics** (`gateway/metrics.py`).
- **WebSocket gateway** (`gateway/websocket.py`).
- API server (`gateway/api_server.py`) with FastAPI router.
- Session manager (`gateway/session.py`), run loop (`gateway/run.py`).
- Voice sub-system (`gateway/voice.py`), status endpoint (`gateway/status.py`).
- **17 platform adapters** in `gateway/platforms/`:
  feishu, slack, telegram, discord, whatsapp, signal, sms, wecom, dingtalk,
  teams, matrix, google_chat, irc, line, qqbot, mattermost, home_assistant.

#### Core Cross-Cutting

- Retry decorator with **4 strategies** (immediate / linear / exponential / custom).
- Timeout policy + bulkhead isolation.
- Dead Letter Queue for failed tasks.
- Structured logging throughout.

#### Security

- Unified scanner (`security/scanner.py`): `secret + threat + output` triple-pass.
- SBOM generator (`security/sbom.py`): **CycloneDX + SPDX** output.

#### Skills

- 21 `SKILL.md` workflow documents under `skills/`:
  api-design, caveman, code-review, db-schema, debugging, file-todos,
  planning, ponytail, refactor, reflect, rtk, test-gen (plus meta).

#### Deployment

- **k8s manifests** (`k8s/`): 8 files
  (`configmap`, `deployment`, `hpa`, `ingress`, `pvc`, `secret`,
   `service`, `servicemonitor`).
- **Helm Chart** (`helm/zeloo/`): 10 files (Chart.yaml + values.yaml + templates).
- **systemd / launchd / Windows services** (`packaging/install.ps1`,
  `packaging/uninstall.ps1`, `packaging/aur/PKGBUILD`,
  `packaging/homebrew/zeloo.rb`, `packaging/rpm/zeloo.spec`).
- **Docker multi-stage** (`Dockerfile`, `docker-compose.yml`,
  `docker-compose.prod.yml`, `docker/Caddyfile`, `docker/prometheus.yml`).

#### CI/CD

- 17 GitHub workflows under `.github/workflows/`:
  `ci`, `docs`, `lint`, `test`, `sbom`, `sign`, `slsa`,
  plus CodeQL, Scorecard, SLSA provenance, cosign signing.

### Changed

- Renamed `security.py` → `security_legacy.py` + introduced `security/` package
  (`__init__.py`, `scanner.py`, `sbom.py`). A backwards-compat shim re-exports
  the legacy symbols.
- `tools/__init__.py` now exports **80+ modules** through a curated `__all__`.
- `agent/__init__.py` exports the full public surface.
- `cli.py` refactored into per-domain command modules.
- `pyproject.toml` adds `tui`, `browser`, `mcp`, `voice`, `computer-use`
  optional-dependency groups.
- Provider router now reads `fallback_config.yaml` instead of hard-coded chain.

### Fixed

- `ProviderRouter` fallback chain support via YAML configuration
  (`agent/fallback_config.py`).
- `ConversationLoop` memory leak prevention via context rotator + token trimmer.
- OAuth token refresh race condition in `mcp_oauth_manager`.
- TUI snapshot rendering flicker on Windows terminals.
- Provider timeout regression when `max_iterations > 80`.
- Various bug fixes documented in inline git history
  (search `git log --grep=Round`).

## [0.1.0] - 2026-09-11

### Added

- Initial release with Round 65 baseline.
- Basic Hermes Agent v0.16.0 alignment (~62%).
- Core agent loop, single provider, single tool, single CLI command.
- Apache-2.0 license.

---

## Versioning Notes

- Versions follow SemVer: `MAJOR.MINOR.PATCH`.
- `MAJOR` bump reserved for breaking config/CLI changes.
- `MINOR` aligns with Hermes Agent upstream minor releases.
- `PATCH` carries bug fixes and doc updates only.
- Round numbers (`Round 65`, `Round 78`, …) track the internal
  multi-week delivery cadence and are recorded in `[Unreleased]` until
  the next minor release cut.