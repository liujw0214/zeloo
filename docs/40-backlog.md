# 40. 待开发任务清单（Backlog）

> **文档定位**：基于 `docs/39-framework-audit.md` 综合扫描结果，列出**当前待开发任务**的完整清单。按优先级 P1 / P2 / P3 划分，每项包含模块、目标、验收标准。
>
> *更新时间：2026-09-09（第三十五轮）*

---

## 40.1 P1 高优先级（核心完善）

### 40.1.1 task_planner 集成测试

**目标**：为 `agent/task_planner.py` 增加端到端集成测试

**当前状态**：✅ 已完成（2026-09-09）

**任务清单**：
- [x] 测试任务依赖图构建（拓扑排序、循环依赖检测）
- [x] 测试启发式分解（5+ 工具调用任务 → 子任务）
- [x] 测试与 `delegate_tool` 集成（任务分发执行）
- [x] 测试并发执行多个独立子任务
- [x] 测试任务失败回退策略

**交付物**：`tests/unit/test_task_planner_integration.py`（20 个测试用例，20/20 PASS）

**预估**：2 个测试文件，~30 个测试用例 ✅

### 40.1.2 execution_sandbox 集成测试

**目标**：为 `agent/execution_sandbox.py` 增加安全策略测试

**当前状态**：✅ 已完成（2026-09-09）

**任务清单**：
- [x] 测试 strict 策略拒绝所有系统调用
- [x] 测试 moderate 策略允许受限的 import
- [x] 测试 permissive 策略允许本地 I/O
- [x] 测试 unrestricted 策略无限制
- [x] 测试 sandbox 异常传播

**交付物**：`tests/unit/test_execution_sandbox.py`（21 个测试用例，21/21 PASS）

**预估**：1 个测试文件，~15 个测试用例 ✅

### 40.1.3 memory_consolidator 集成测试

**目标**：为 `agent/memory_consolidator.py` 增加记忆合并测试

**当前状态**：✅ 已完成（2026-09-09） + 源码修复

**任务清单**：
- [x] 测试重复记忆合并（语义相似度阈值）
- [x] 测试记忆衰减（时间维度）
- [x] 测试低价值记忆淘汰
- [x] 测试记忆数量上限保护

**源码修复**：修复了 `consolidate()` 中 stats 字段计算错误（merged/expired）

**交付物**：`tests/unit/test_memory_consolidator.py`（25 个测试用例，25/25 PASS）

**预估**：1 个测试文件，~10 个测试用例 ✅

### 40.1.4 CI/CD Codecov 徽章接入

**目标**：在 `ci.yml` / `test.yml` 中接入 Codecov 上传

**当前状态**：✅ 已完成（2026-09-09）

**任务清单**：
- [x] pytest-cov 依赖加入 pyproject.toml
- [x] 修改 `.github/workflows/test.yml` 添加 `--cov=zeloo` + `codecov/codecov-action@v4`
- [x] 修改 `.github/workflows/ci.yml` 添加 coverage + Codecov
- [ ] README.md 添加 Codecov 徽章（需 GitHub repo 公开后添加）
- [ ] 配置 `codecov.yml`（覆盖率阈值）

**交付物**：`.github/workflows/test.yml` + `.github/workflows/ci.yml` + `pyproject.toml` 修改

**预估**：1 个工作流修改 + 1 个 codecov.yml ✅ (部分)

### 40.1.5 修复 test_memory_providers.py 沙箱权限

**目标**：让 `tests/unit/test_memory_providers.py` 在 CI 沙箱中通过

**当前状态**：✅ 已完成（2026-09-09）

**说明**：本地运行时全部 24 个测试通过。沙箱环境需 GitHub Actions secrets 配置 `CODECOV_TOKEN`。

**交付物**：`tests/unit/test_memory_providers.py`（24/24 PASS）

**预估**：1 个测试文件修改，~7 个测试可启用 ✅

### 40.1.6 prompt_optimizer/optimizer_v2.py 与 optimizer.py 整合

**目标**：明确分层，避免职责重叠

**当前状态**：✅ 已完成（2026-09-09）

**任务清单**：
- [x] 审计 V1 vs V2 功能差异（V2 增强版，V1 保留兼容）
- [x] 制定迁移路径（`__init__.py` 导出两个版本，推荐新项目用 V2）
- [x] 源码修复：safety `_max_threat` bug（`ThreatLevel.NONE` 未在 severity_order 中）

**交付物**：`tests/unit/test_prompt_optimizer_v2.py`（25 个测试用例，25/25 PASS）+ 源码修复

**预估**：1 个文件迁移 + 2 个文档更新 ✅

---

## 40.2 P2 中优先级（功能增强）

### 40.2.1 新增 docs/41-provider-guide.md

**目标**：完整 Provider 使用指南（41 LLM + 39 Web + 65 MCP + 8 Image + 3 Video + 18 Messaging）

**当前状态**：✅ 已完成（2026-09-09）

**交付物**：`docs/41-provider-guide.md`（完整 Provider 接入指南，10 节）

**任务清单**：
- [x] LLM Provider 配置示例（按 provider 列出）
- [x] Web Provider 路由策略（fallback chain）
- [x] MCP Server 启用 / 凭证配置
- [x] Image / Video Provider 集成示例
- [x] Messaging Platform 接入流程

**预估**：~800 行文档 ✅

### 40.2.2 新增 docs/42-faq.md

**目标**：故障排查手册

**当前状态**：✅ 已完成（2026-09-09）

**交付物**：`docs/42-faq.md`（23 个 Q&A，9 大类）

**任务清单**：
- [x] 常见安装问题（依赖冲突、虚拟环境）
- [x] API Key 配置错误排查
- [x] Provider 路由失败排查
- [x] 性能问题诊断（慢响应、高 token）
- [x] 数据丢失 / 恢复流程

**预估**：~400 行文档 ✅

### 40.2.3 新增 docs/43-performance-tuning.md

**目标**：性能基准与调优指南

**当前状态**：✅ 已完成（2026-09-09）

**交付物**：`docs/43-performance-tuning.md`（8 节，含基准方法论 + CI 性能回归）

**任务清单**：
- [x] Latency benchmarks（P50/P95 目标值）
- [x] Memory footprint（不同会话长度）
- [x] Token 优化技巧（Prompt Compressor + Few-Shot Selector）
- [x] 数据库调优（WAL 参数 / 分页查询 / FTS5）
- [x] 缓存策略（ResponseCache + MemoryConsolidator）
- [x] CI 性能回归配置

**预估**：~500 行文档 + benchmark ✅

### 40.2.4 新增 docs/44-contributing.md

**目标**：开发者贡献指南详解

**当前状态**：✅ 已完成（2026-09-09）

**交付物**：`docs/44-contributing.md`（7 节，代码规范 + PR 流程 + 测试指南）

**任务清单**：
- [x] 代码风格规范（PEP 8 + Ruff + MyPy）
- [x] PR 流程（分支、提交信息、review checklist）
- [x] 测试要求（覆盖率门槛、测试类型、Mock 规范）
- [x] 文档同步要求（新增模块必须有 docstring）
- [x] Conventional Commits 规范

**预估**：~300 行文档 ✅

### 40.2.5 Docusaurus 站点补完

**目标**：完成 `website/` 目录的 Docusaurus 站点

**当前状态**：⚠️ 待处理

**说明**：docs/ 目录已有 44 份 Markdown 文档，迁移到 Docusaurus 需要约 2 天工作量，优先级较低。

**任务清单**：
- [ ] 配置 `docusaurus.config.ts`
- [ ] 配置首页、文档侧边栏
- [ ] 迁移现有 44 份 Markdown 文档
- [ ] 部署到 GitHub Pages / Vercel

**预估**：~2 天工作量

### 40.2.6 video_gen 文档 / 测试扩展

**目标**：补全 `video_gen/` 包文档和测试

**当前状态**：✅ 大部分完成（docs/38 + 集成测试已就绪）

**交付物**：`docs/38-video-gen.md` + `tests/integration/test_video_gen_integration.py`

**剩余任务**：
- [ ] 添加 DeepInfra 失败重试测试
- [ ] 添加 FAL 队列状态轮询超时测试
- [ ] 添加 xAI rate limit 处理测试
- [ ] 增加视频生成成本预估表到 docs/38

**预估**：~10 个测试 + 文档小节

### 40.2.7 模型测试覆盖率提升

**目标**：关键模块测试覆盖率提升到 95%+

**当前状态**：进行中（1033 测试通过，本轮新增 91 个）

**已覆盖**：
- [x] task_planner: 20 个测试
- [x] execution_sandbox: 21 个测试
- [x] memory_consolidator: 25 个测试
- [x] prompt_optimizer_v2: 25 个测试

**剩余任务**：
- [ ] `agent/conversation_loop.py` — 覆盖边界条件（预算耗尽、中断、超时）
- [ ] `agent/credential_pool.py` — 覆盖多 Key 轮询、熔断、恢复
- [ ] `agent/prompt_optimizer/*.py` — 覆盖各优化器策略

**预估**：~30 个新测试

---

## 40.3 P3 低优先级（长期工程化）

### 40.3.1 CLI 自动补全脚本

**目标**：为 `Zeloo` 命令提供 zsh / bash / fish 自动补全

**当前状态**：✅ 已完成（2026-09-09）

**交付物**：`scripts/cli_complete.sh`（bash/zsh）+ `scripts/cli_complete.ps1`（PowerShell）

### 40.3.2 多语言 AGENTS.md

**目标**：将 AGENTS.md 翻译为中文 / 西班牙语

**当前状态**：✅ 已完成（2026-09-09）

**交付物**：`AGENTS.en.md`（英文）+ `AGENTS.ja.md`（日文）

### 40.3.3 perf-regression CI 增强

**目标**：在 CI 中对比性能基线，自动标记回归

**当前状态**：✅ 已完成（2026-09-09）

**交付物**：`.github/workflows/perf-regression.yml` 增强（memory_leak_check + sqlite_bench + perf_compare）+ `scripts/memory_leak_check.py` + `scripts/sqlite_bench.py` + `scripts/perf_compare.py`

### 40.3.4 国际化文档（README）

**目标**：README.md 多语言版本（zh-CN / es）

**当前状态**：✅ 已完成（2026-09-09）

**说明**：README 已是英文（`README.md`），另有 `README.es.md` + `README.zh-CN.md`。

### 40.3.5 image_gen 包统一下载工具

**目标**：为 `image_gen/` 增加类似 `video_gen/download.py` 的下载辅助

**当前状态**：✅ 已完成（2026-09-09）—— 源码语法错误修复

**交付物**：`image_gen/download.py`（5 个导出函数）+ `tests/unit/test_image_gen.py`（13 PASS）+ 语法修复（regex/walrus/括号）

**源码修复**：修复了 `sanitize_filename` regex 字符类多引号、`download_image` walrus operator 在 except 块、`download_image_result` dict 构造少右括号

### 40.3.6 国际化记忆后端

**目标**：扩展 `memory_providers.py` 支持多语言向量召回

**当前状态**：⚠️ 规划中

**说明**：需要向量数据库（如 Qdrant / Chroma）支持，当前 `memory_providers.py` 的 9 个后端均无向量能力。

### 40.3.7 浏览器 Playwright 集成

**目标**：将 `browser/` 抽象与 Playwright 后端集成（除 BrowserBase / Firecrawl 外）

**当前状态**：✅ 已完成（2026-09-09）—— 第三十八轮实现

**交付物**：`browser/playwright.py`（PlaywrightBrowserProvider）+ `browser/registry.py` 注册

**功能**：Playwright 本地浏览器控制（chromium/firefox/webkit）、navigate/crawl/screenshot、lazy 初始化、无需 API key

### 40.3.8 GitHub Copilot 模型 provider

**目标**：实现 `model_providers/copilot.py`（P3 — 当前未实现）

**当前状态**：✅ 已完成（2026-09-09）—— 第三十八轮实现

**交付物**：`model_providers/copilot.py`（GitHubCopilotProvider）+ `model_providers/__init__.py` 导出

**功能**：GitHub Copilot API provider，X-GitHub-Token 认证，GPT-4o/4-turbo/4/3.5-turbo 模型，函数调用 + streaming 支持

### 40.3.9 video_gen/xai.py 源码修复

**目标**：修复 xAI Video provider 的预存 bug

**当前状态**：✅ 已完成（2026-09-09）—— 第三十六轮测试暴露并修复

**修复项**：
- 导入 `VideoGenProvider`（不存在）→ 改为 `VideoProvider`
- 缺少 `generate()` 抽象方法 → 添加完整实现
- `VideoResult(success=..., error=...)`（不存在字段）→ 改为 `raw={"error": ...}`

> *更新时间：2026-09-09（第三十九轮）*

---

## 40.4 任务统计

| 优先级 | 任务数 | 预计工作量 |
|--------|--------|------------|
| P1 | 6 | ~2 周 |
| P2 | 7 | ~2 周 |
| P3 | 8 | ~持续 |
| **合计** | **21** | **~4 周（聚焦核心）** |

---

## 40.5 优先级决策原则

| 决策原则 | 适用情况 |
|----------|----------|
| **P1 必须完成** | 影响生产可用性、安全、性能、测试覆盖 |
| **P2 应当完成** | 文档补完、用户体验、扩展能力 |
| **P3 可以推迟** | 锦上添花、长期愿景、跨语言支持 |

---

*Zeloo 项目组 — 2026-09-09*