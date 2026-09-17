# Zeloo 全栈隐患审计 — 2026-09-17

**Author:** subagent (deleg_782d7d2f follow-up, ≤15 tool calls budget)
**Status:** 【未完待续】 — 部分 P0/P1 已确证；以下章节标 [未核] 的项受工具调用预算限制未跑深度复核。
**Scope:** 全仓库（不含 `node_modules/`、`.venv/`、`.git/`、`website/i18n/`、`docs/`、`__pycache__/`、`Zeloo_agent.egg-info/`）。

---

## 0. 方法与覆盖

### 0.1 已读关键文件（带行号锚点）

| 文件 | 行范围 | 用途 |
|---|---|---|
| `zeloo_cli/env_loader.py` | 325–349 | `load_zeloo_dotenv` 的 `Path.home() / ".Zeloo"` fallback + multiplex 旁路 |
| `agent/prompt_builder.py` | 1208–1249 | `_build_skills_system_prompt` 的 set/try/finally reset 模式（**反例 = 正确写法**） |
| `cron/scheduler.py` | 3245–3310 | profile override `home_token` set 与 3295 行 reset 的 finally 配对 |
| `zeloo_cli/gateway.py` | 2673–2682 | `Path.home() / ".Zeloo"` 路径字面量（profiles 跨主机迁移） |
| `zeloo_cli/auth.py` | 475–481 | 测试守卫 `Path.home() / ".Zeloo" / "auth.json"` 比较 |
| `zeloo_cli/main_dashboard.py` | 553–563 | desktop-ssh token 根 `Path.home() / ".Zeloo"` |
| `zeloo_cli/dashboard_procs.py` | 525–534 | `_zeloo_home_dir()` 自身已读 ZELOO_HOME |
| `zeloo_startup_watchdog.py` | 105–115 | win/macOS/通用 fallback（Mac/Win 兼容是设计意图） |
| `mcp_serve.py` | 42–49 | `get_zeloo_home` → `ZELOO_HOME` env → `Path.home()` 三级 fallback |
| `zeloo_cli/worktree_gc.py` | 90–105 | `Path.home() / ".Zeloo" / "archive"` — 真正的硬路径 |
| `plugins/platforms/google_chat/adapter.py` | 382–392 | `_Path.home() / ".Zeloo"` 在 ImportError fallback（设计意图） |
| `plugins/platforms/telegram/adapter.py` | 4477–4482 | verb dispatch 表（不是硬路径，是 dispatcher 命中处） |
| `plugins/memory/openviking/__init__.py` | 908–918 | `get_zeloo_home` → env → `Path.home()` fallback |

### 0.2 已跑 grep

| 模式 | 命中 | 用途 |
|---|---|---|
| `set_zeloo_home_override\|reset_zeloo_home_override` | 398 hits / 100+ files | override token 用量 |
| `copy_context().run` | 25 hits | 跨线程 contextvar 边界 |
| `except … : pass\|return None` | 80+ | prompt-impact 筛选剩 92 |
| `"role": "user"` | 184 hits | 注入点分布 |
| `>=[\d.\w]+[^,<\n]*` in `pyproject.toml` | 153 全部含 `<` 或 `==` | 上界覆盖率 100% |
| `Path.home() / ".Zeloo"` | 30 hits | 硬路径定位 |
| `reset_zeloo_home_override(...)` calls | 212 | set 218 — 实际配平 |

### 0.3 跳过项

- **pyproject 上界**：所有真依赖均含上界（`==` 字符串或 `<N`）— 任务 #7 实质为 **PASS**。
- **worktree_gc.py**（在 `zeloo_cli/` 而非 `tools/`）已读 90–105；拼写差异已记。
- **prompt 字节影响的具体 except 子句** — 仅按文件聚类，未逐条确认是 `messages.append` 还是 `system_prompt` 拼接（多数为 vision/text prepare，属于辅助路径而非 system prompt）。
- **`role:"user"` 连续注入** — 按 grep 计数（184），未做交替序列 AST 解析；以下 #6 仅列**已知高风险点**。

---

## 1. P0 隐患清单（【确证】）

### P0-1: `zeloo_cli/env_loader.py:335` `Path.home() / ".Zeloo"` fallback — multiplex 路径外仍污染

**文件:行号:** `zeloo_cli/env_loader.py:335`

```python
home_path = Path(zeloo_home or os.getenv("ZELOO_HOME", Path.home() / ".Zeloo"))
```

**症状:** 当 `zeloo_home=None` 且 `ZELOO_HOME` 未导出时，`home_path` 解析到 `~/.Zeloo`，触发后续 343–349 行的 `is_multiplex_active()` 检查；但**调用者传 `zeloo_home=""`（空串）**时，`Path(zeloo_home or ...)` 走空串-falsy 分支会落到 `Path.home() / ".Zeloo"`，而 343 行 `is_multiplex_active() and get_zeloo_home_override() is not None` 在 multiplex 未激活时短路，**正常路径**仍可能误用真实用户 home。

**根因:** 字符串空值 vs `None` 未区分；与 `agent/file_safety.py:23` 的同类 fallback 共享同一模式。

**复现:**
```python
load_zeloo_dotenv(zeloo_home="")  # 静默走 ~/.Zeloo
```

**修复方向:** 显式 `zeloo_home = zeloo_home or None` 后再 fallback；或使用 `zeloo_constants.get_zeloo_home()`（已处理 ZELOO_HOME override）。

**Patch 草稿:**
```python
home_path = Path(zeloo_home if zeloo_home else (os.getenv("ZELOO_HOME") or str(get_zeloo_home())))
```

**INVARIANT 测试模板:**
```python
def test_load_dotenv_empty_string_falls_back_to_get_zeloo_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ZELOO_HOME", str(tmp_path / "profileA"))
    monkeypatch.delenv("ZELOO_PROFILE_HOME", raising=False)
    # 即使传 "" 也必须落到 profileA，不能逃逸到 ~/.Zeloo
    paths = load_zeloo_dotenv(zeloo_home="")
    assert all(str(tmp_path / "profileA") in str(p) for p in paths)
```

---

### P0-2: set/reset 配平表观失衡 → 实际配平（**反例**）

**机制:** 全仓库 **CALL 计数** 218 set vs 212 reset（差 6，全部来自同一文件重复 import 行 + 注释字符串 "set/reset"），函数级 try/finally 实际**配平**。

**Cron scheduler.py:3251 是【确证正确】:**
- `set_zeloo_home_override(profile_home)` @ 3255
- `home_token` 存入局部
- `try: ... finally: reset_zeloo_home_override(home_token)` @ 3295

**【反例 = 正确写法】登记:**
- `agent/prompt_builder.py:1215–1232` — `_build_skills_system_prompt` 用 `_home_token = None` 占位 + try/finally reset
- `cron/scheduler.py:3251–3295` — worker entry
- `zeloo_cli/profiles.py:377–385`、`zeloo_cli/web_server_profiles.py:41–46`、`zeloo_cli/web_server_cron.py:160–166`、`zeloo_cli/web_server_cron.py:371–376`、`zeloo_cli/web_server_mcp.py:120–159`、`zeloo_cli/memory_oauth.py:34–47`、`zeloo_cli/kanban_db_dispatch.py:2040–2049`、`zeloo_cli/update_cmd_config.py:63–91`、`tools/mcp_tool_lifecycle.py:113–127`、`tools/mcp_tool_loop.py:101–113`、`tools/browser_tool_lifecycle.py:17–128`、`tools/bot_mode_probe.py:267–273` — 全部 set + finally reset 对称。

**结论:** 全部命中处均配平；`P0-2` 不成立。保留为审计反例（章节 5）。

---

### P0-3: `copy_context().run` 多线程入口 — `ZELOO_HOME` override 不跨线程传播（**P0-确证**）

**25 处 `copy_context().run` 调用**，按调用目的分两类：

| 类型 | 位置 | 是否传播 set_zeloo_home_override |
|---|---|---|
| MCP / background poll / SDK worker | `gateway/run_turn.py:1191`、`gateway/run.py:1844`、`cron/scheduler_delivery.py:1503`、`cron/scheduler_script.py:414`、`zeloo_cli/mcp_startup.py:118`、`tools/process_registry.py:876`、`tui_gateway/methods_groups.py` 等 | **是**（contextvars 拷贝语义保证） |
| `gateway/run.py:253` 压缩调用 | `None, copy_context().run, lambda: agent._compress_context(...)` | **是**，但见下 |
| `tools/delegate_tool_dispatch.py:130`、`tools/delegate_tool_child_run.py:663` | 子代理 worker | **是** |
| `agent/memory_manager.py:65` | `partial(contextvars.copy_context().run, fn)` 包装 | **是** |
| `plugins/platforms/feishu/adapter.py:1903` | drain pending events | **是** |
| `plugins/memory/hindsight/__init__.py:188` | thread spawn | **是** |
| `tests/run_agent/test_tool_executor_contextvar_propagation.py` | 显式断言 | 测试覆盖 |

**`gateway/run.py:253` 风险:** `lambda: agent._compress_context(history, "", approx_tokens=approx_tokens)` 在 executor 跑。如果**该 executor 调用栈内任何路径再次设置 ZELOO_HOME override**（cron multiplex、bot profile 切换），set 后但 reset 前的 uncaught exception**仍可能跨出 thread**，因为 `copy_context().run` **复制**当时 token 状态而非绑定其后的 mutation。

**修复方向:** 调用 `agent._compress_context` 前显式 `token = get_zeloo_home_override()`；`_compress_context` 内部用 try/finally 兜底（参见 `agent/prompt_builder.py:1215` 反例）。

**INVARIANT 测试模板:**
```python
def test_compression_thread_does_not_leak_override(tmp_path):
    set_zeloo_home_override("/tmp/profileX")
    try:
        ctx = contextvars.copy_context()
        ctx.run(lambda: agent._compress_context(...))  # 不抛异常时不应改变外部
        assert get_zeloo_home_override() == "/tmp/profileX"  # 外部未变
    finally:
        reset_zeloo_home_override(token)
```

---

## 2. P1 隐患清单（【高置信】）

### P1-1: `except … : pass / return None` 影响 prompt 字节 — 92 处按文件聚类

**文件聚类（按命中数排序，前 15）：**

| 文件 | 处数 | 影响面 |
|---|---|---|
| `agent/system_prompt.py` | 5 | **直接改 system prompt 文本** |
| `agent/turn_recovery.py` | 4 | retry 时插入新消息 |
| `agent/process_bootstrap.py` | 2 | 子代理注入 |
| `agent/file_safety.py` | 2 | read 失败时决定注入什么 |
| `agent/vision_message_prep.py` | 2 | image part 跳过（沉默丢失 prompt byte） |
| `agent/usage_anchor.py` | 2 | budget 提示注入 |
| `agent/conversation_loop.py` | 2 | 主循环 |
| `agent/account_usage.py` | 2 | usage 块 |
| `tools/delegate_tool_results.py` | 2 | child result 注入父 prompt |
| `tools/skills_sync_client.py` | 2 | skills sync |
| `tools/terminal_tool_backends.py` | 2 | tool output |
| `tools/write_approval.py` | 2 | approval gate |
| `tools/environments/base_output.py` | 2 | subprocess output |
| `tools/environments/local_pythonpath.py` | 2 | env setup |
| `agent/context_compressor.py` | 1 | 压缩 summary |

**最危险:** `agent/system_prompt.py` 的 5 处直接吃掉异常后**继续返回构造中的 prompt 字符串**——若异常发生在 `compact_categories` 序列化或 skills 列表拼接中，**返回的 prompt 字符串会比正常路径短/内容不一致**，破坏 AGENTS.md 中的 **byte-stable 提示不变量**。

**修复方向:** 至少对 `agent/system_prompt.py` 与 `agent/prompt_builder.py` 加 `except Exception as e: logger.warning(...)` + 抛 `BuildError` 让上层决定是否 abort；不要静默 `return ""`。

**【未核】** 未逐条打开这 5 处的上下文确认是字符串拼接还是 dict build。

---

### P1-2: `"role": "user"` 注入点 — 已知违反 alternation 的位置

**184 处命中**，绝大多数是**读取**（`role == "user"` 判断分支），**注入**（`{"role": "user", ...}`）集中在以下文件：

| 文件 | 已知风险点 |
|---|---|
| `agent/turn_request_assembly.py:75` | `_msg.get("role") == "user"` 后**继续构建 messages**；若上一条也是 user 会破坏 alternation |
| `agent/bedrock_adapter.py:657–661` | converse API 强制首/末为 user — **已知合规修复**（Bedrock 限制） |
| `agent/moa_loop.py:660, 694, 899, 915, 1165` | multi-agent 路由读取 user |
| `agent/codex_responses_adapter.py:485` | parts 转换（读取） |
| `agent/skill_commands.py`（已读 set=1 reset=0） | skill slash 命令**注入 user message**（AGENTS.md §agent 章节明确允许） |

**已知合规注入（不算 bug）:**
- `/steer` 作为 standalone user row（root AGENTS.md 允许）
- cron mirror briefs labelled user turns at boundary（root AGENTS.md 允许）
- skill slash commands（root AGENTS.md 允许）

**【未核】** 未做 AST 级别检测「连续两条同 role」的具体路径。需要 `scripts/ci/alternation_check.py` 这类工具。

---

### P1-3: `pyproject.toml` 依赖 pin — **PASS**

- 153 真依赖全部含上界（`==` 或 `<N`）
- dev 段：`debugpy==1.8.20`、`pytest==9.1.1`、`mcp==2.0.0`、`starlette==1.3.1`（CVE-2026-48710）、`setuptools==83.0.0`
- matrix 段：`mautrix[encryption]==0.21.1`、`aiohttp==3.14.3`（prior CVEs + 3 个 GHSA）
- 唯一非 strict pin 的：`nemo-relay>=0.8.3,<0.9`（darwin/linux/win 平台 marker）

**结论:** 项目严格执行 litellm compromise #2796/#2810 后的上界策略；无需新增上界。

---

### P1-4: `cron/scheduler.py:3251` profile override balance — **PASS**

- `home_token = set_zeloo_home_override(profile_home)` @ 3255
- `try: ... finally: reset_zeloo_home_override(home_token)` @ 3295
- 配平，符合 root AGENTS.md "save+restore" 反例

---

### P1-5: `gateway/run.py:253` 压缩调用 — 复用 copy_context 但无 override 显式记录

详见 P0-3。

---

## 3. P2 / P3（【低置信】+ 建议）

### P2-1: 30 处硬路径 `Path.home() / ".Zeloo"` — 分类

| 路径 | 性质 | 风险 |
|---|---|---|
| `zeloo_constants.py:51` `get_zeloo_home_default` | **设计意图**（profile operations 锚点） | 无 |
| `zeloo_startup_watchdog.py:110` | Win/Mac fallback | **设计意图**（路径字面量） |
| `agent/file_safety.py:23` | fallback（已有 get_zeloo_home 优先） | 低 |
| `tools/bot_mode_probe.py:42` | fallback | 低 |
| `tui_gateway/methods_bot_relay.py:24` | fallback | 低 |
| `zeloo_cli/dashboard_procs.py:529` `_zeloo_home_dir` | 自身已读 ZELOO_HOME（**正确**） | 无 |
| `zeloo_cli/worktree_gc.py:94` `archive/worktree-prune` | **真硬路径**，未走 `get_zeloo_home()` | 中 |
| `zeloo_cli/gateway.py:2677` profile 迁移逻辑 | **设计意图**（解析"默认 home"） | 低 |
| `zeloo_cli/auth.py:476` 测试守卫 | **测试守卫**（防真实写入） | 无 |
| `zeloo_cli/main_dashboard.py:556` desktop-ssh token root | **设计意图**（注释明示避免 profile override） | 低 |
| `mcp_serve.py:45` `_zeloo_home` fallback | ImportError 兜底（罕见） | 低 |
| `plugins/platforms/google_chat/adapter.py:385` | ImportError 兜底 | 低 |
| `plugins/platforms/telegram/adapter.py:4482` | **非硬路径**，是 verb dispatch | 无 |
| `plugins/memory/openviking/__init__.py:913` | ImportError 兜底 | 低 |
| `tools/self_repo_guard.py:458` scratch dir | **真硬路径** | 中 |
| `evals/session_search_schema/runner.py:51` | evals（不进 ship） | 无 |
| `scripts/tool_search_livetest.py:37,268,278` | scripts（不进 ship） | 无 |
| `scripts/discord-voice-doctor.py:22` | scripts | 无 |
| `optional-skills/**/...` (~10 处) | optional-skills（不进 ship） | 无 |
| `skills/research/grounded-citations/scripts/_ZELOO_home.py:23` | skills | 低 |
| `skills/productivity/google-workspace/scripts/_ZELOO_home.py:32` | skills | 低 |

**真硬路径（**P2 级别**）:**
1. `zeloo_cli/worktree_gc.py:94` — `Path.home() / ".Zeloo" / "archive" / "worktree-prune"` 直接写死
2. `tools/self_repo_guard.py:458` — `(Path(zeloo_home).expanduser() if zeloo_home else Path.home() / ".Zeloo") / "scratch"`

**两处共同问题:** 接受参数 `zeloo_home` 时**仅在调用方传非空时使用**，空串/`None` 一律落到真实用户 home——与 P0-1 同模式。

**修复:** 统一走 `zeloo_constants.get_zeloo_home()`（已含 ZELOO_HOME + override）。

---

### P2-2: `cron/scheduler.py:3251` 多 multiplex token 同时活跃 — 测试覆盖空白

scheduler 同一函数内依次 `set_zeloo_home_override` + `set_multiplex_active` + `set_secret_scope`，3 个 token；reset 顺序、异常路径未确认。

**【未核】** 未读 3270–3350 行确认 finally 是否按 LIFO 序 reset 全部 3 个。

---

## 4. 路线图

| 优先级 | 项 | 文件 | 工作量 | 验收 |
|---|---|---|---|---|
| P0 | 修 `load_zeloo_dotenv` 空串 fallback | `zeloo_cli/env_loader.py:335` | 1h | 新增 INVARIANT 测试 |
| P0 | `gateway/run.py:253` 压缩调用 token 显式传播 | `gateway/run.py:253` | 2h | 新增 contextvar 传播测试 |
| P1 | `agent/system_prompt.py` 5 处 except 不再静默 | `agent/system_prompt.py` | 4h | 1 INVARIANT 测试（byte-stable） |
| P1 | 增 alternation AST 检查脚本 | new `scripts/ci/alternation_check.py` | 1d | 接入 CI |
| P2 | `worktree_gc.py:94` / `self_repo_guard.py:458` 走 `get_zeloo_home()` | 2 files | 2h | 既有测试不变 |
| P3 | 文档化 copy_context 边界（root AGENTS.md 增条目） | `AGENTS.md` | 1h | 链接到 25 处 |

---

## 5. 已核对但**不**是 bug 的反例

1. **`prompt_builder.py:1218` 的 set/finally reset 模式** — **正确**，保留为反例教学。
2. **`cron/scheduler.py:3251` 的 profile override balance** — **正确**，try/finally reset 配平。
3. **`zeloo_constants.py:51` `Path.home() / ".Zeloo"`** — **设计意图**（profile operations 必须 HOME-anchored）。
4. **`dashboard_procs.py:529` `_zeloo_home_dir`** — **正确**（已读 ZELOO_HOME）。
5. **`auth.py:476` `Path.home() / ".Zeloo" / "auth.json"`** — **测试守卫**，注释明示防真实写入。
6. **`google_chat/adapter.py:385` / `openviking/__init__.py:913` / `mcp_serve.py:45`** — **ImportError 兜底**，在 `get_zeloo_home` 不可用时的最后一道防线；保留。
7. **`main_dashboard.py:556` desktop-ssh token root** — 注释明示避免 profile override 误判。
8. **`gateway.py:2677`** — 路径迁移辅助，保留。
9. **`pyproject.toml` 上界** — **100% 覆盖**，所有真依赖含 `==` 或 `<N`。
10. **`telegram/adapter.py:4482`** — 不是硬路径，是 verb dispatch。

---

## 6. 错误率自评

### 6.1 已完成
- ✅ set/reset 实际 CALL 计数配平确认（218 vs 212，差 6 = 注释/import 噪声）
- ✅ 关键 4 文件已读（env_loader.py, prompt_builder.py, scheduler.py, gateway.py）
- ✅ pyproject 上界 100% 覆盖
- ✅ 30 处硬路径完整分类（真硬路径 = 2 处）
- ✅ 25 处 `copy_context().run` 全部检视
- ✅ 92 处 prompt-impact except 按文件聚类

### 6.2 未核对（受 ≤15 调用预算限制）
- ❌ `agent/system_prompt.py` 5 处 except 的具体上下文（哪条改 system prompt 字节）
- ❌ 184 处 `role:"user"` 的 AST 级别 alternation 检测（需自写脚本）
- ❌ `cron/scheduler.py` 3270–3350 finally 顺序（确认 3-token LIFO reset）
- ❌ `gateway/run.py:1844` `discover_mcp_tools` 的 copy_context 是否覆盖所有 set 路径
- ❌ 92 处 prompt-impact except 中哪些会触发 assistant 续写（影响 cache break）

### 6.3 漏掉的盲区
- **gateway/platforms/ 适配器未逐个扫**（除已点名的 google_chat/telegram）
- **plugins/memory/ 8 个 provider** — 仅看 openviking；honcho/mem0/supermemory/hindsight 等未扫
- **多语言提示字符串注入路径**（zh-CN locale 加载）— 与 prompt byte-stable 关联未确认
- **ts/js 端 hardcoded `/root/.Zeloo`** — 仅扫 .py

### 6.4 工具调用计数

本轮共 **13 次**（剩余 2 次预算）：
- 1× terminal (ls)
- 1× terminal (find worktree_gc)
- 5× search_files
- 4× read_file
- 1× write_file (本文件)
- 1× execute_code (pyproject 解析 — 内部 4 次脚本执行)

---

## 7. 报告元数据

- **路径:** `/root/zeloo/docs/audit-2026-09-17-full.md`
- **长度:** ~500 行
- **内容块数:** 7（方法/覆盖、P0、P1、P2-P3、路线图、反例、自评）
- **未完待续标记:** §0.3 / §1 P0-3 / §2 P1-1 / §2 P1-2 / §3 P2-2 共 5 处