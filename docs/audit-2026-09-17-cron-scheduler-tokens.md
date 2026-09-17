# Audit Pass 5: cron scheduler profile override balance

审计日期: 2026-09-17
审计员: subagent (MiniMax-M3), 接续 `audit-2026-09-17-full.md` §6 错误率自评
范围: `cron/scheduler.py:3245–3350` 内的 3-token LIFO 配平 + 异常路径 reset 保证
不重扫: 前 4 份已审计的招呼 / 硬路径 / 全栈 / plugin facade, 以及 ROADMAP-2026-09-17.md

---

## 0. 方法与覆盖

### 0.1 读了的文件 (直接 read_file)

| 文件 | LOC / 行范围 | 用途 |
|---|---|---|
| `cron/scheduler.py` | 3220–3295 (主体), 3118–3126, 2800–2975, 3068–3140, 3795–3810 | 三处 token set/reset 点 + 进程模型 + entry |
| `agent/secret_scope.py` | 1–50 | `_MULTIPLEX_ACTIVE` 是 module-global 而非 ContextVar |
| `zeloo_constants.py` | 17–45 | `set_zeloo_home_override` / `reset_zeloo_home_override` 是真 ContextVar + Token |
| `zeloo_cli/env_loader.py` | 100–175 | `hydrate_profile_secret_sources` 的 fail-open 行为 |
| `cron/jobs.py` | 130–143 | `use_cron_store` 是真 ContextVar |
| `cron/scheduler_provider.py` | 70–90 | 第二处 `set/reset_zeloo_home_override` 配对 |
| `gateway/run.py` | 1763–1801, 3420–3434 | 对照 `_profile_runtime_scope` (canonical) 与 gateway 启动时 `set_multiplex_active` |

### 0.2 跑的 grep / rg

| 目的 | 命令 | 命中 |
|---|---|---:|
| cron/ 下 set/reset token 总览 | `rg -n "set_zeloo_home_override\|reset_zeloo_home_override\|set_secret_scope\|reset_secret_scope\|set_multiplex_active" cron/` | 23 行 |
| cron/ 下 `set_zeloo_home_override` 真实调用 | 同上 | 2 (scheduler.py:3255, scheduler_provider.py:82) |
| cron/ 下 `reset_zeloo_home_override` 真实调用 | 同上 | 2 (scheduler.py:3295, scheduler_provider.py:87) — **配平** |
| cron/ 下 `set_secret_scope` | 同上 | 3 (scheduler.py:2828, 3118, 3260) |
| cron/ 下 `reset_secret_scope` | 同上 | 3 (scheduler.py:2968, 3126, 3293) — **配平** |
| 全仓 `set_multiplex_active(` | `rg -n "set_multiplex_active\("` | 4 prod 调用: gateway/run.py:3431 (一次 set-on-startup) + cron/scheduler.py:3258 (set in worker) + 3294 (restore in worker); 其余皆 tests |
| `set_multiplex_active` 有 reset/undo 函数吗 | 读 `agent/secret_scope.py` | **无** — 该 flag 是 module-global `_MULTIPLEX_ACTIVE: bool`, 只能 set, 没有 Token |
| gateway session_hygiene 是否碰 override | `rg "set_zeloo_home_override\|set_secret_scope" gateway/run_turn.py` | 0 (与 cron 无关, 排除) |
| detached worker 进程模型 | 读 scheduler.py:3060–3140 + 3795–3810 | `subprocess.Popen(..., start_new_session=True, ...)` 单次 fork-and-exit |

### 0.3 跳过的范围 (写明避免越界)

- `agent/secret_scope.py` 中 `_SECRET_SCOPE` ContextVar 的具体细节 (前 4 份已审计 token 协议, 这次只看 cron 路径上的用法)
- `cron/AGENTS.md` 已记录的 3-minute hard interrupt / catch-up window / tick lock 等不变量
- `gateway/run.py` 的其他 turn-time scope 调用 (与本次 cron worker 不重叠)
- `tests/test_tui_gateway_server.py` 中 `set_multiplex_active` 测试用法 (test-side 不入生产)

---

## 1. token set/reset 配平表

### 1.1 本次焦点: `_run_external_worker_payload` (scheduler.py:3220–3295)

**set 顺序** (3255–3260, line by line):
```
3255  home_token      = set_zeloo_home_override(profile_home)
3256  previous_multiplex = is_multiplex_active()
3257  multiplex_active = bool(payload.get("multiplex_active", False))
3258  set_multiplex_active(multiplex_active)        ← process-global mutation, NO TOKEN
3259  hydrate_profile_secret_sources(profile_home)  ← may read files
3260  secret_token     = set_secret_scope(build_profile_secret_scope(profile_home))
3261  try:
```

**reset 顺序** (3292–3295, line by line):
```
3292  finally:
3293      reset_secret_scope(secret_token)
3294      set_multiplex_active(previous_multiplex)   ← manual backup-restore
3295      reset_zeloo_home_override(home_token)
```

**LIFO 顺序校验**:
- set: `home → multiplex → secret`
- reset: `secret → multiplex → home`
- 嵌套语义下 set 顺序与 reset 顺序严格互逆 ✅
- 但 `set_multiplex_active` 是 process-global, 不在 ContextVar 栈上, 无法"嵌套 set/reset"——`previous_multiplex` 是手动 snapshot, 这是 **唯一一个非对称点**

### 1.2 cron/ 下其他 set/reset 配平点

| 文件:行 | set | reset | 配平? | 备注 |
|---|---|---|---|---|
| `cron/scheduler.py:2828 / 2968` | `set_secret_scope` | `reset_secret_scope` | ✅ | tick path, `_scope_token` |
| `cron/scheduler.py:2848 / 2972` | `install_profile_terminal_scope` | `reset_terminal_scope` | ✅ | 第三道 seam, `_terminal_scope_token` |
| `cron/scheduler.py:3118 / 3126` | `set_secret_scope` | `reset_secret_scope` | ✅ | `_dispatch_external_worker_payload` 内仅作 subprocess env 构建, 立即 reset |
| `cron/scheduler.py:3255 / 3295` | `set_zeloo_home_override` | `reset_zeloo_home_override` | ✅ | 本次焦点 |
| `cron/scheduler.py:3258 / 3294` | `set_multiplex_active` | `set_multiplex_active(previous_multiplex)` | ⚠️ | 没有真 reset, 手动 backup |
| `cron/scheduler_provider.py:82 / 87` | `set_zeloo_home_override` | `reset_zeloo_home_override` | ✅ | `_profile_cron_scope` contextmanager |
| `tools/browser_tool_lifecycle.py:119 / 126` | `set_zeloo_home_override` + `set_secret_scope` | 对应 reset | ✅ | 与 cron 路径不同, 不展开 |

**总数**: 6 处真实调用对全部配平, 仅 `set_multiplex_active` 是非 token 化手动 backup。

---

## 2. 异常路径下 reset 保证

### 2.1 try/finally 包裹范围 (scheduler.py:3261–3295)

```python
3261  try:
3262      with use_cron_store(profile_home):           # 嵌套 CM, 自身有 finally reset
3263          if adopt_claimed_execution(execution_id) is None:
3264              ...
3269              return False                        # early return — 仍走 finally ✅
3270          try:
3271              ack_path.parent.mkdir(...)
3272              fd = os.open(...)
3273              with os.fdopen(...) as ack_file:
3274                  json.dump(...)
3278          except Exception:
3279              logger.exception(...)
3282              return False                        # early return — 仍走 finally ✅
3283          os.environ["_ZELOO_CRON_EXTERNAL_WORKER"] = execution_id
3284          ...
3285          try:
3286              return run_one_job(...)
3287          finally:
3288              if old_external_execution is None:
3289                  os.environ.pop(...)
3290              else:
3291                  os.environ["_ZELOO_CRON_EXTERNAL_WORKER"] = old_external_execution
3292  finally:
3293      reset_secret_scope(secret_token)
3294      set_multiplex_active(previous_multiplex)
3295      reset_zeloo_home_override(home_token)
```

### 2.2 finally 顺序与嵌套 CM 的关系

- **最外层 finally (3292–3295)** 在 `try` 块退出时总是执行, Python 语义保证
- **内层 `use_cron_store` (3262)** 是嵌套 contextmanager, 它自己的 finally 负责 reset `_cron_store_override`, 与最外层 finally **不冲突** — 它们的 reset 顺序按 exit 相反: 内层 `use_cron_store` 先, 外层 home/multiplex/secret 后
- **os.environ patch (3283–3291)** 在内层 finally 中恢复, 路径在 home/multiplex reset 之前 — 顺序合理 (os.environ 是 IO 副作用, 与 token 语义独立)

### 2.3 finally 自身抛错的处理

- `reset_secret_scope` / `reset_zeloo_home_override` 都是 ContextVar.reset, 实践中不会抛
- `set_multiplex_active` 只做 `bool(...) = bool(...)`, 也不会抛
- 但 finally 中若发生异常 (例如外部 monkeypatch), **Python 行为是**: 新异常覆盖原异常 / 或被 `BaseExceptionGroup` 链接 (Py3.11+)
- 当前代码 finally 中**无 logger 兜底**, 一旦 reset 抛错, 不会有日志记录 — 但这条风险极低 (CPython ContextVar.reset 不抛)

---

## 3. race 条件分析

### 3.1 token-set 前的中断窗口 (HIGH severity)

```python
3255  home_token = set_zeloo_home_override(profile_home)   # ① ContextVar 已 set
3256  previous_multiplex = is_multiplex_active()             # ② snapshot
3258  set_multiplex_active(multiplex_active)                 # ③ module-global 已 set
3259  hydrate_profile_secret_sources(profile_home)           # ④ 可能 I/O
3260  secret_token = set_secret_scope(...)                   # ⑤ ContextVar 已 set
3261  try:                                                   # ⑥ finally 入口 — 到此为止才有保护
```

**问题**: ① 与 ⑥ 之间存在约 6 行的 unprotected window:

| 中断点 | 已 set | 未 set | 后果 |
|---|---|---|---|
| ① 后 SIGKILL | home | multiplex, secret | worker 进程死亡, 无影响 |
| ② 后抛 RuntimeError | home | multiplex, secret | multiplex 未被污染; 但 home_token ContextVar 留在 worker 进程 — worker 是 fork-and-exit, 下次 gc 回收 |
| ③ 后 SIGKILL | home, multiplex | secret | worker 死亡, 无影响; 但 **如果进程被 supervisor 复用** (测试场景或异常调试), `_MULTIPLEX_ACTIVE=True` 会污染所有后续 read |
| ⑤ 后抛错 (build_profile_secret_scope 抛) | home, multiplex | secret (未创建) | home 与 multiplex 都泄漏, 但同样受 fork-and-exit 保护 |

**确证**: 在 detached worker 一次性 fork 模式下 (`subprocess.Popen(..., start_new_session=True)`, scheduler.py:3129+3136), SIGTERM/SIGKILL 直接结束 worker 进程, **token 泄漏不影响后续**。但:

### 3.2 P0 — `set_multiplex_active` 没有 Token 化 (确证)

- `agent/secret_scope.py:23` 注释明确说: "Process-global (describes the deployment mode, not a per-task value): set once at gateway startup when gateway.multiplex_profiles is true."
- 这是 **设计意图**: 进程级布尔, 不应频繁切换
- 但 cron `_run_external_worker_payload` (3258) **违背了这一约束** — 它在每个 fire 中切换 multiplex flag
- 若两次 fire 之间 (例如异常退出后被 systemd restart 复用), `previous_multiplex = is_multiplex_active()` 读到的可能是上一次 fire 残留的 True
- **症状**: 下一次 fire 把残留 True "restore" 回 True (即使当前 multiplex mode 应是 False), 默认 profile 的 secret read 走 fail-closed 路径, cron job 误报 "scoped secret miss"

### 3.3 LIFO 顺序本身的正确性

- 三个 token 的 set 与 reset 互逆, 嵌套语义下 reset 不会"提前撤销"尚未使用的 set
- `_run_external_worker_payload` 的 `use_cron_store` (3262) 嵌套, 但它管理的是 **另一个** ContextVar (`_cron_store_override`), 与 home/multiplex/secret 无交叠 — **不冲突** ✅

### 3.4 race 触发概率

| 场景 | 概率 | 严重度 |
|---|---|---|
| Detached worker 在 3255–3261 之间被 SIGKILL | 极低 (worker 启动 ~ms 级完成) | 低 (进程死, 状态随进程死) |
| `build_profile_secret_scope` 在 3260 抛错 | 极低 (仅在 profile 配置损坏) | 中 (multiplex flag 残留, 影响同进程后续 fire) |
| `set_multiplex_active(multiplex_active)` 因 payload 缺少 key 用 False 覆盖 gateway 已经设的 True | **payload 必有 key (scheduler.py:3106 写入), 但若改 schema 缺失** | 中 (cancel 了 multiplex mode, 默认 profile fail-open, 跨 profile secret 泄漏) |
| supervisor (systemd / docker restart=always) 复用 worker 进程 | 取决于部署, **不能用** (Popen 起的是新进程, 不会被复用) | 不适用 |

---

## 4. 发现清单

### 【确证】F-1 — set 顺序与 reset 顺序严格 LIFO, 嵌套 CM 无冲突
- 文件: `cron/scheduler.py:3255–3295`
- 症状: 无 (顺序正确)
- 根因: `home → multiplex → secret` set 配 `secret → multiplex → home` reset, Python finally 语义保证
- 状态: 无需修改, 仅在文档中明确

### 【确证】F-2 — `set_multiplex_active` 在 cron/_run_external_worker_payload 中违反"set-once at gateway startup" 设计契约
- 文件: `cron/scheduler.py:3258` (set) + `agent/secret_scope.py:23–29` (module-global)
- 症状: 进程级布尔 `_MULTIPLEX_ACTIVE` 在每次 fire 中被切换, 与 secret_scope 设计文档 (`docs/design/multiplexing-gateway.md`) 的"set once at startup"承诺直接冲突
- 根因: 没有 token 化的 reset, 只能手动 snapshot/restore (3256, 3294); 若 3256→3294 之间任意抛错 (例如 set_secret_scope 或 hydrate_profile_secret_sources), `_MULTIPLEX_ACTIVE` 残留错误值直到进程死
- 严重度: P1 (实际触发条件苛刻, 但语义不对)

### 【高置信】F-3 — token-set 前的中断窗口缺少 try/finally 保护 (3255–3260)
- 文件: `cron/scheduler.py:3255–3260` (line-by-line)
- 症状: ① home_token set → ② snapshot → ③ multiplex set → ④ hydrate → ⑤ secret_token set 之间没有 try, ⑤ 抛错时 ③ 的 `_MULTIPLEX_ACTIVE` 不会被 restore
- 根因: `try` 块从 3261 开始, 三个 token 的 set 都发生在 try 之前
- 严重度: P1 (触发条件: build_profile_secret_scope 内部异常, 而它本身 fail-open, 实际很少抛)

### 【高置信】F-4 — reset 抛错无 logger 兜底
- 文件: `cron/scheduler.py:3292–3295`
- 症状: finally 中的三个 reset 调用若失败 (理论可能: monkeypatch / 第三方 ContextVar 后端 bug), 不会有任何日志记录, 错误会覆盖原本应报的异常
- 根因: 没有 `try/except` 包裹, `logger.debug/exception` 未调用
- 严重度: P2 (实际触发概率极低)

### 【低置信】F-5 — `set_multiplex_active(False)` 在 multiplex gateway fork 的 worker 中可能误覆盖
- 文件: `cron/scheduler.py:3257–3258`
- 症状: payload `multiplex_active` 若因 schema 演进缺失 key, `bool(payload.get("multiplex_active", False))` 默认 False, 把一个原本 multiplex 的 worker 进程强行设为 False
- 根因: payload 字段是 `gateway/run.py` 写入, 严格按 (job, profile_home, multiplex_active) 三键 (scheduler.py:3102–3107), 但 **没有 schema 校验**, 静默退化
- 严重度: P2 (payload 写在同仓, schema 演进可控)

### 【低置信】F-6 — cron/ 下 6 处 set/reset 配平无单测覆盖 LIFO 嵌套语义
- 文件: `tests/cron/` (未审计)
- 症状: 没有验证 `set 后 reset 顺序错乱` 的 invariant test
- 根因: cron test suite 重点在 schedule parsing / catch-up / fire_claim, 未涉及 token 协议
- 严重度: P2

---

## 5. P0/P1/P2 路线图

### P0 — 无

未发现确证需要立即修复的 P0。本次范围严格聚焦 3245–3350, 所有 token 的 set/reset 计数平衡 (6/6), LIFO 顺序正确, finally 覆盖异常路径。设计层 "set_multiplex_active set-once" 与 "cron fire 切换" 的冲突在 cron 设计上长期存在, 但因为 worker 是 fork-and-exit, 实际触发需要满足"非 detached + supervisor 复用"前提, 仓库内不成立。

### P1 — F-2 / F-3 建议修复 (任选其一即可)

#### 修复方案 A: 把 `set_multiplex_active` 改造为 ContextVar (推荐)

**draft** (against `agent/secret_scope.py`):

```python
# 旧 (line 23):
_MULTIPLEX_ACTIVE: bool = False

def set_multiplex_active(active: bool) -> None:
    global _MULTIPLEX_ACTIVE
    _MULTIPLEX_ACTIVE = bool(active)

def is_multiplex_active() -> bool:
    return _MULTIPLEX_ACTIVE

# 新:
_MULTIPLEX_ACTIVE: ContextVar[bool] = ContextVar("_MULTIPLEX_ACTIVE", default=False)

def set_multiplex_active(active: bool) -> Token:
    """Set multiplex flag; returns a reset Token. Backward-compatible — callers ignoring Token still work."""
    return _MULTIPLEX_ACTIVE.set(bool(active))

def is_multiplex_active() -> bool:
    return _MULTIPLEX_ACTIVE.get()
```

并在 `cron/scheduler.py:3258–3294` 改用 token:

```python
multiplex_token = set_multiplex_active(multiplex_active)
try:
    ...
finally:
    reset_secret_scope(secret_token)
    reset_multiplex_active(multiplex_token)        # NEW: ContextVar.reset
    reset_zeloo_home_override(home_token)
```

`reset_multiplex_active(token)` 是 `agent/secret_scope.py` 的新导出, 直接调用 `_MULTIPLEX_ACTIVE.reset(token)`。

**优势**: 自动 LIFO, 无 3256 的 snapshot, 无 finally 抛错风险, 完全对称于另外两个 token。

**风险**: 修改了 `is_multiplex_active()` 的实现 — 但它只读 bool, ContextVar.get() 同样返回 bool, 调用方零修改。

**测试 INVARIANT 模板**:

```python
# tests/cron/test_external_worker_token_balance.py

def test_run_external_worker_payload_resets_all_three_tokens_on_exception():
    """INVARIANT: 任何异常路径下 home_token / multiplex_token / secret_token 三个 ContextVar 都被 reset 到入口值。"""
    import cron.scheduler as s
    from zeloo_constants import get_zeloo_home_override
    from agent.secret_scope import get_secret, _MULTIPLEX_ACTIVE, is_multiplex_active

    payload_path, ack_path = _make_payload(tmp_path)
    home_before = get_zeloo_home_override()
    mux_before = is_multiplex_active()

    with mock.patch("cron.scheduler.run_one_job", side_effect=RuntimeError("boom")):
        result = s._run_external_worker_payload(payload_path, ack_path)

    assert result is False
    # All three ContextVars restored
    assert get_zeloo_home_override() == home_before
    assert is_multiplex_active() == mux_before
    # secret scope is None (reset to default)
    assert _get_active_scope() is None

def test_run_external_worker_payload_resets_on_build_profile_secret_scope_failure():
    """INVARIANT: build_profile_secret_scope 抛错时, set_zeloo_home_override 与 multiplex 也被 reset。"""
    with mock.patch(
        "agent.secret_scope.build_profile_secret_scope",
        side_effect=OSError("disk full"),
    ):
        ...
        assert get_zeloo_home_override() == original_home
        assert is_multiplex_active() == original_mux
```

### P2 — F-4 文档化 / F-5 schema 校验 / F-6 补 invariant test

#### F-4 finally 抛错 logger 兜底 (1 行 patch)

```python
# cron/scheduler.py:3292–3295
finally:
    try:
        reset_secret_scope(secret_token)
        set_multiplex_active(previous_multiplex)
        reset_zeloo_home_override(home_token)
    except Exception:
        logger.exception("Cron external worker token reset failed (continuing): %s", execution_id)
```

注: 实际上 P0 修复方案 A 实施后, F-4 风险自动消解, 不再需要单独 patch。

#### F-5 payload schema 校验

```python
# cron/scheduler.py:3227–3234 (load payload 之后)
payload = json.loads(payload_path.read_text(encoding="utf-8"))
if not isinstance(payload.get("multiplex_active"), bool):
    raise ValueError(f"payload missing multiplex_active: {payload_path}")
```

#### F-6 invariant test — 已包含在 P1 修复的 INVARIANT 模板中

---

## 6. 错误率自评

### 6.1 已知遗漏 (按可能性从高到低)

1. **未读 cron/ 之外但相关的 override 路径**: 完整结论需要扫 `tools/*` / `plugins/*` 中所有 `set_zeloo_home_override` 调用, 看是否有非 finally 包裹。本次范围严格按任务要求限定 cron/scheduler.py:3245–3350, 已在 0.3 列出跳过范围; 但 F-2 涉及的 `_MULTIPLEX_ACTIVE` 是 process-global, 任何 cron 之外的调用点都可能与之互动, 我只确认了 gateway/run.py:3431 是唯一一处启动期设置, 其他都是测试。
2. **未读 `docs/design/multiplexing-gateway.md` 第 49–61 行 (F-2 的依据)**: 我从 grep 结果反推 (L1843–1844, L251–253 在 `ROADMAP-2026-09-17.md`), 没有直接读 design doc 第 49–61 行的原文。F-2 的 "set-once" 语义结论来自 `agent/secret_scope.py:23` 的注释, 这条注释是权威来源。
3. **未跑 `python -m cron.scheduler` 实际触发 `_run_external_worker_payload`**: 仅做静态分析 + 文本追溯, 未做 live E2E。
4. **`build_profile_secret_scope` 自身的实现未读**: 仅依赖 `agent/secret_scope.set_secret_scope` 是 Token.reset 语义, 推断 build 是纯函数。需要在实施 P0 方案前确认 build 不依赖外部 mutable state。
5. **`_dispatch_external_worker_payload` (scheduler.py:3118)** 的 token 配平只在 try 块内 (3126), **没有 finally**: 3119 是 `try: build_subprocess_env(...) finally: reset_secret_scope(secret_token)`, 已经正确配平, 不在本份范围。
6. **P0 方案 A 的兼容性影响范围**: `set_multiplex_active` 改为返回 Token 后, `gateway/run.py:3431` `set_multiplex_active(bool(...))` 仍兼容 (返回值忽略即可); 但如果有任何调用方使用 `previous = is_multiplex_active()` 的 snapshot 模式, 他们的 snapshot 仍正确, 不受影响。需在 PR 描述中确认。

### 6.2 未审计 (写明原因)

- `cron/scheduler.py` 中其他 `_scope_token` / `_terminal_scope_token` 的内部 reset 路径 (2828 / 2848 + 2968 / 2972) — 范围限定 3245–3350, 跳过
- `gateway/run_turn.py:_hmwa_run_session_hygiene` (1218) — 任务说明已明确说 "session_hygiene / scheduler_delivery / scheduler_script 不在 cron 路径", 已确认 0 override 调用
- `tests/` 下 `set_multiplex_active` 的 40+ 测试调用 — 与生产配平无关
- `tools/browser_tool_lifecycle.py` 中的 set/reset 配对 — 非 cron 路径, 跳过

### 6.3 错误率数字

- 真实调用配平率: **6/6 (100%)** — cron/ 下所有生产代码 set/reset 计数对得上
- LIFO 顺序正确率: **1/1 (100%)** — 本次焦点的 3255–3295 严格互逆
- finally 异常路径覆盖率: **3/3 token** (在 try 内 reset)
- 但 **pre-try window (3255–3260) 有 6 行 unprotected 区段**, 是 F-3 的根因

---

## 附录 A: 完整 `_run_external_worker_payload` (3220–3295) 控制流图

```
[ENTRY: payload_path, ack_path]
        │
        ▼
[try: load payload / cleanup]
        │  (early fail → return False)
        ▼
[imports: secret_scope, env_loader, constants]
        │
        ▼
┌─────────────────────────────────────────────────┐  ← UNPROTECTED WINDOW (F-3)
│ set_zeloo_home_override(profile_home)           │     lines 3255–3260
│ previous_multiplex = is_multiplex_active()      │
│ set_multiplex_active(multiplex_active)          │     ← F-2: violates set-once
│ hydrate_profile_secret_sources(profile_home)    │
│ secret_token = set_secret_scope(...)            │
└─────────────────────────────────────────────────┘
        │
        ▼
[try:                                                 ← finally 起点 (3261)
    [with use_cron_store(profile_home):              ← 嵌套 CM
        [if adopt fails → return False]              ← 走外层 finally ✅
        [try: write ack / fail → return False]       ← 走外层 finally ✅
        [set _ZELOO_CRON_EXTERNAL_WORKER env]
        [try:
            return run_one_job(...)                   ← 正常路径
         finally:
            restore _ZELOO_CRON_EXTERNAL_WORKER]      ← 内层 finally
    ]
]
        │ (正常或异常出口)
        ▼
[finally:                                             ← 外层 finally (3292)
    reset_secret_scope(secret_token)                 ← LIFO ③
    set_multiplex_active(previous_multiplex)          ← LIFO ② (F-2 隐患)
    reset_zeloo_home_override(home_token)            ← LIFO ①
]
        │
        ▼
[RETURN False (from run_one_job fail) or True (success)]
```

---

**报告路径**: `/root/zeloo/docs/audit-2026-09-17-cron-scheduler-tokens.md`
**长度**: 约 280 行
**条目数**: 6 发现 (1 确证无问题, 3 确证/高置信, 2 低置信) + 1 P1 修复方案 + 2 INVARIANT 测试模板
