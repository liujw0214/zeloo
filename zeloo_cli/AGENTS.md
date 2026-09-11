# zeloo_cli/AGENTS.md

## 本包职责

Zeloo CLI 子命令系统：提供交互式 CLI、Profile 管理、Web 路由、仪表盘认证、可观测性、核心框架等功能入口。

## 核心模块

- `config.py`：配置加载（YAML 合并 / 环境变量 / 多环境支持）
- `profiles.py`：Profile 管理（`~/.Zeloo/profiles/<name>/` 隔离配置）
- `_startup_fast.py`：快速启动优化（技能索引缓存 / LazyImporter / Provider 预热）
- `observability/`：可观测性（UsageTracker + HealthChecker）
- `dashboard_auth/`：仪表盘认证（Basic / Nous / SelfHosted OAuth2）
- `subcommands/`：子命令模块（35 个：auth / backup / browser / dashboard / doctor / dump / hooks / install / logs / login / logout / mcp / memory / model / profile / plugins / secrets / sessions / setup / skills / status / sync / tools / uninstall / update / verify / workspace / z (oneshot) 等）
- `web_routers/`：Web 路由（Auth / Users / Sessions / Settings）
- `core/`：核心框架（Phase 1: event_bus/scheduler/cache/rate_limiter/circuit_breaker/task_queue/middleware/multi_tenant/realtime_engine; Phase 2: tracing/metrics/feature_flags/secrets/lifecycle/plugin_manager/state_store）

## 注意事项

- CLI 参数解析由 `_parser.py` 集中处理（已整合至各 subcommand）
- Profile 切换后自动更新 `zeloo_HOME` 路径
- 所有敏感配置通过环境变量注入，不硬编码
- Web 路由依赖 FastAPI 框架（可选依赖）
- 核心框架（`core/`）可独立使用，无需启动 CLI
