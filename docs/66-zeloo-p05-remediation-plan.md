# Plan: Zeloo 0.5% 缺口修复计划

## Approach
对 Zeloo 与 Hermes Agent v0.16.0 之间剩余 0.5% 缺口进行分优先级修复，覆盖 Auth 层、Agent 层、Tools 层、Provider 层、MCP 层、Config 层共 16 个缺口项。

---

## Phase 1: P0 — Auth 层 Provider Auth 补全

**Status**: pending

**Tasks**:
- [ ] `zeloo_cli/auth/deepseek_auth.py` — DeepSeek API Key + OAuth 认证
- [ ] `zeloo_cli/auth/groq_auth.py` — Groq API Key 认证
- [ ] `zeloo_cli/auth/mistral_auth.py` — Mistral API Key 认证
- [ ] `zeloo_cli/auth/ollama_auth.py` — Ollama 本地认证（无需认证 or API Key）
- [ ] `zeloo_cli/auth/azure_auth.py` — Azure AD OAuth + API Key
- [ ] `zeloo_cli/auth/local_auth.py` — Local Provider 认证
- [ ] `zeloo_cli/auth/fireworks_auth.py` — Fireworks AI API Key
- [ ] `zeloo_cli/auth/together_auth.py` — Together AI API Key
- [ ] `zeloo_cli/auth/bedrock_auth.py` — AWS Bedrock IAM 认证
- [ ] `zeloo_cli/auth/openrouter_auth.py` — OpenRouter API Key
- [ ] `zeloo_cli/auth/__init__.py` — 导入全部 17 个 auth 模块
- [ ] 生成 Auth 层单元测试（每个模块 5-10 个测试）

---

## Phase 2: P1-A — Tools 层导出修复

**Status**: pending

**Tasks**:
- [ ] `tools/__init__.py` — 添加 `journey_tracker` 工具导出
- [ ] `tools/__init__.py` — 添加 MCP OAuth 工具导出（mcp_oauth/mcp_oauth_device/mcp_oauth_manager）
- [ ] `tools/__init__.py` — 添加 `profile_distribution` 工具导出
- [ ] `tools/__init__.py` — 添加 P1 新增工具导出（file_operations/file_operations_batch/delegate_tool_*/code_execution_*）

---

## Phase 3: P1-B — Tools 层新工具开发

**Status**: pending

**Tasks**:
- [ ] `tools/database_tool.py` — MySQL/PostgreSQL 直接查询工具（无需 MCP）
  - `db_query(query, connection_string)` — 执行 SQL 查询
  - `db_execute(query, connection_string)` — 执行 DML/DDL
  - `db_list_tables(database)` — 列出表
  - `db_describe_table(table, database)` — 表结构
  - `db_backup(database, dest)` — 数据库备份
- [ ] `tools/shell_enhance.py` — Shell 增强工具
  - `shell_interactive(command)` — 交互式 shell
  - `shell_stream(command)` — 流式输出
  - `shell_background(command)` — 后台执行
  - `shell_bg_result(job_id)` — 获取后台任务结果
  - `shell_bg_list()` — 列出后台任务
- [ ] `tools/clipboard_tool.py` — 剪贴板工具
  - `clipboard_read()` — 读取剪贴板
  - `clipboard_write(text)` — 写入剪贴板
  - `clipboard_history()` — 剪贴板历史（最近 20 条）
- [ ] `tools/ssh_tool.py` — SSH 执行工具
  - `ssh_execute(host, command, user, key_path)` — 远程执行
  - `ssh_upload(local_path, remote_path, host, user, key_path)` — 上传文件
  - `ssh_download(remote_path, local_path, host, user, key_path)` — 下载文件

---

## Phase 4: P1-C — Agent 层增强

**Status**: pending

**Tasks**:
- [ ] `agent/memory_compressor.py` — Memory 压缩器
  - `MemoryCompressor` — 基于重要性和时间衰减的记忆压缩
  - `compress(old_memory)` — 返回压缩后的记忆
  - 支持 TF-IDF 和 embedding 相似度去重
- [ ] `agent/memory_gc.py` — Memory 垃圾回收器
  - `MemoryGarbageCollector` — 清理低价值记忆
  - `gc_collect(threshold)` — 收集可删除记忆
  - `gc_list_candidates()` — 列出待清理记忆
  - `gc_restore(memory_id)` — 恢复误删记忆
- [ ] `agent/cost_optimizer.py` — 成本优化器
  - `CostOptimizer` — 基于历史使用模式的模型切换策略
  - `suggest_downgrade(task_type)` — 建议降级到便宜模型
  - `suggest_upgrade(task_type)` — 建议升级到更强模型
  - `get_current_cost_report()` — 当前成本报告
  - `set_budget_limit(monthly_limit)` — 设置月度预算

---

## Phase 5: P1-D — Provider 层增强

**Status**: pending

**Tasks**:
- [ ] `agent/providers/model_updater.py` — 模型列表自动更新
  - `ModelUpdater` — 定时从 provider API 获取最新模型
  - `update_all()` — 更新所有 provider 模型
  - `update_provider(provider_name)` — 更新单个 provider
  - `get_latest_models(provider_name)` — 获取最新模型列表
  - 使用定时任务或按需更新机制

---

## Phase 6: P1-E — MCP 层增强

**Status**: pending

**Tasks**:
- [ ] `tools/mcp_discovery_auto.py` — MCP 自动发现
  - `MCPAutoDiscovery` — 自动扫描已安装 MCP server
  - `scan_npm_global()` — 扫描 npm 全局包
  - `scan_pip_global()` — 扫描 pip 全局包
  - `scan_local()` — 扫描本地项目
  - `auto_register_found()` — 自动注册发现的 server

---

## Phase 7: P2 — CLI 子命令 & Config 层

**Status**: pending

**Tasks**:
- [ ] `zeloo_cli/subcommands/fallback.py` — Fallback Chain CLI
  - `fallback list` — 列出所有 chain
  - `fallback add <name> <providers...>` — 添加 chain
  - `fallback remove <name>` — 删除 chain
  - `fallback set-model <pattern> <chain>` — 设置模型 chain
  - `fallback validate` — 验证配置
- [ ] `config_schema.py` — Config YAML Schema 验证
  - `ConfigSchema` — Pydantic 模型验证 config.yaml
  - `validate_config(path)` — 验证配置文件
  - `migrate_to_schema(config_dict)` — 迁移到 schema

---

## Phase 8: Verification & Documentation

**Status**: pending

**Tasks**:
- [ ] 全部新模块导入验证
- [ ] 完整测试套件运行（预期 2100+ tests）
- [ ] 更新 `docs/65-zeloo-hermes-v016-alignment.md` 对齐度到 100%
- [ ] 更新 `docs/66-zeloo-p05-remediation-plan.md` 标记所有完成项

---

## 缺口详情与修复策略

### Auth 层（10 个缺失的 Provider Auth）

| Provider | 认证方式 | 实现策略 |
|---|---|---|
| deepseek | API Key (`DEEPSEEK_API_KEY` env) + OAuth | 参考现有 xai_auth.py 模式 |
| groq | API Key (`GROQ_API_KEY` env) | 简单 API Key 认证 |
| mistral | API Key (`MISTRAL_API_KEY` env) | 简单 API Key 认证 |
| ollama | 本地（无需认证）或 API Key | Ollama 原生认证 |
| azure | Azure AD OAuth + API Key | Azure 特定 OAuth 2.0 |
| local | 本地（无需认证） | 空认证 |
| fireworks | API Key (`FIREWORKS_API_KEY` env) | 简单 API Key |
| together | API Key (`TOGETHER_API_KEY` env) | 简单 API Key |
| bedrock | AWS IAM (access_key/secret_key/session_token) | AWS SigV4 签名 |
| openrouter | API Key (`OPENROUTER_API_KEY` env) | 简单 API Key |

### Tools 层导出问题

当前 `tools/__init__.py` 导出了部分模块，但 P1/P2 新增的模块未加入：
- `journey_tracker` — 10 个工具函数
- `mcp_oauth*` — 3 个模块
- `profile_distribution` — 5 个工具函数
- `file_operations*` — 9 个模块
- `delegate_tool*` — 6 个模块
- `code_execution*` — 3 个模块

### Agent 层缺失组件

| 组件 | 功能 | 现有基础 |
|---|---|---|
| `memory_compressor.py` | 记忆压缩 | `memory_consolidator.py` |
| `memory_gc.py` | 记忆垃圾回收 | `memory.py` |
| `cost_optimizer.py` | 成本优化策略 | `cost_tracker.py` |

### 配置验证

| 组件 | 现有基础 | 目标 |
|---|---|---|
| Config Schema | `config_migrations.py` 迁移框架 | Pydantic 严格验证 |

---

## 工作量估算

| Phase | 模块数 | 测试数（估算） |
|---|---|---|
| P0 Auth | 10 个 | 50-80 |
| P1-A Tools 导出 | 1 个文件修改 | - |
| P1-B Tools 新工具 | 4 个 | 30-50 |
| P1-C Agent 增强 | 3 个 | 20-30 |
| P1-D Provider | 1 个 | 10-15 |
| P1-E MCP | 1 个 | 10-15 |
| P2 CLI/Config | 2 个 | 15-20 |
| **合计** | **22 个** | **135-230** |

---

## 验收标准

- [ ] 全部 17 个 Auth Provider 认证模块就绪
- [ ] `tools/__init__.py` 导出完整
- [ ] 4 个新 Tools 模块导入正常
- [ ] 3 个 Agent 增强模块导入正常
- [ ] Model Updater 可获取最新模型列表
- [ ] MCP 自动发现可扫描 npm/pip 全局包
- [ ] Fallback CLI 子命令可用
- [ ] Config Schema Pydantic 验证可用
- [ ] 完整测试套件 2100+ tests 通过
- [ ] 对齐度达到 **100%**
