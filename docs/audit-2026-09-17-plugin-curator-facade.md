# 审计三：plugin / curator / facade 边界

审计日期: 2026-09-17
审计员: subagent (MiniMax-M3), 接续 `audit-2026-09-17-full.md`
范围: plugin ↔ core 边界、curator 误删风险、run_agent facade 反向依赖。
**不重扫** 已审计的招呼 / 硬路径 / 全栈三块；前两份跳过的三类本次补齐。

---

## 0. 方法与覆盖

### 0.1 读了的文件 (直接 cat / read_file 全量)

| 文件 | LOC | 用途 |
|---|---:|---|
| `plugins/plugin_loader.py` | 172 | 通用 plugin 加载器 |
| `plugins/plugin_storage.py` | 44 | plugin 持久存储 helper |
| `agent/curator.py` | 1084 | 背景 curator 编排 + LLM 复核 fork |
| `agent/curator_backup.py` | 441 | curator 快照 + 回滚 |
| `agent/skill_utils.py` (前 90 行) | 786 | `EXCLUDED_SKILL_DIRS`、`is_excluded_skill_path` |
| `tools/skill_usage.py` (前 350 行) | — | `curated_report`、`PROTECTED_BUILTIN_SKILLS`、`archive_skill` |
| `tools/skills_hub_official.py` (前 200 行) | — | `OptionalSkillSource.fetch()` 路径解析 |
| `tools/skills_hub_install.py` (35–255) | 304 | `_check_install_target`、`install_from_quarantine`、`_resolve_lock_install_path` |

### 0.2 跑的 grep

| grep 目的 | 命令 / 模式 | 命中 |
|---|---|---:|
| in-tree plugin 是否触达 `run_agent / cli / zeloo_cli.main` | `find plugins -name __init__.py -exec grep -l "from run_agent \\|import run_agent\\|from cli \\|import cli$\\|from gateway.run\\|import gateway.run\\|from zeloo_cli.main\\|import zeloo_cli.main"` | **0** |
| in-tree plugin 是否触达 `zeloo_cli.*` (广义) | `grep -rn "from zeloo_cli." plugins/` | ~50 处 (合法: config / memory_setup / plugins 注册) |
| 8 个 memory provider `post_setup` | per-plugin `grep "def post_setup"` | 6 有 (honcho, mem0, supermemory, hindsight, openviking — byterover/holographic/retaindb 用 ABC 默认) |
| `run_agent` 反向被 import 总数 | `grep -rn "from run_agent import" --include="*.py" \| wc -l` | **494** (前份报告称 537, 实际 494 — 可能是搜的是更宽松模式) |
| `agent/turn_*` 模块级 import `agent.turn_X` | 自写脚本互检 | **0** 循环 |
| `tools/*` 是否触达 `agent/turn_*` (非合法) | `grep -rn "from agent.turn_" tools/*.py` | 3 (bot_mode_dm, bot_relay — 全部函数内 late import, 合法) |

### 0.3 关键术语

- **HARDLINE** (`plugins/AGENTS.md` 第 5 行): "A plugin MUST NOT modify `run_agent.py`, `cli.py`, `gateway/run.py`, `zeloo_cli/main.py`, etc."
- **off-limits** (`skills/AGENTS.md` 第 91 行): "touches only `created_by: 'agent'` skills (bundled + hub-installed are off-limits)"
- **Facade + sibling** (root `AGENTS.md` 第 159 行): "A facade never imports a sibling at module level **and** gets imported by that sibling at module level."

---

## 1. plugin 边界漏洞

### 1.1 P0 — `PROTECTED_BUILTIN_SKILLS = set()` 与 curator prompt 中的 "currently: plan" 承诺直接冲突

**确证** — `tools/skill_usage.py:38`：

```python
PROTECTED_BUILTIN_SKILLS: Set[str] = set()
```

`is_protected_builtin` 在第 41-42 行只检查这个空集合。`agent/curator.py:298–301` 的 LLM prompt 明确说：

> "DO NOT archive, delete, consolidate, move, or otherwise modify any skill named in the protected built-ins list **(currently: plan)**. These back load-bearing UX (slash-command entry points referenced in docs and tips) and are filtered out of the candidate list below — never resurrect one as an archive or absorb target."

**事实**：
1. 代码层 `PROTECTED_BUILTIN_SKILLS = set()` 永远空 → `is_protected_builtin()` 永远返回 `False`。
2. `_render_candidate_list()` (`curator.py:814`) 直接用 `skill_usage.curated_report()` 作为候选清单，**没有任何额外过滤**把 `plan` 之类的保护 skill 排除。
3. `archive_skill` (`skill_usage.py:583`) 的拒绝路径只检查 `is_protected_builtin` / `is_hub_installed`；前者恒 False，后者只挡 hub。bundled skill **会被 archive**。

**症状**：fork 的 LLM 在 prompt 里被告知 "plan is protected, filtered from candidate list" — 它不会主动 archive `plan`。但 `apply_automatic_transitions` (`curator.py:191`) 是 **纯函数、不走 LLM** 的自动转换 —— 它遍历 `curated_report()`、判定 `use_count==0 and anchor>stale_cutoff` 则跳过，否则 `anchor<=archive_cutoff` 就直接调 `_archive_as_curator` → `_u.archive_skill(name)`。对 90 天未使用的 bundled skill，**自动归档走的是确定性代码路径**。

**根因**：
- `skills/AGENTS.md` 的 invariant ("bundled + hub-installed are off-limits") 实际**靠 `prune_builtins: false` 配置** (`curator.py:123`) 来守护。
- prompt 文本假设 "filter out plan from candidates" 已经发生，实际并没发生。
- 双重声明不一致 (代码空集 ↔ 文本 "currently: plan") 是 PR 过程中 prompt 改了但常量没加的死锁。

**风险等级 P0** —— bundled skill (`plan`, `delegate-task`, `plan-monitor` 等 `skills/` 下的核心 skill) 可能在 90 天不被使用的用户上被自动归档，**恢复靠 `Zeloo curator restore`**，但用户通常根本不知道它们存在被归档的事实（curator 默认开 + LLM fork 关，auto-transitions 走纯函数路径，没有用户可见告警）。

---

### 1.2 P0 — `prune_builtins` 默认 True 直接违反 `skills/AGENTS.md` invariant

**确证** — `agent/curator.py:123–125`：

```python
def get_prune_builtins() -> bool:
    """Bundled built-ins are curation candidates (ON by default); a suppression list keeps them archived across `Zeloo update` re-seeds. Hub skills are never pruned."""
    return bool(_load_config().get("prune_builtins", True))
```

**事实**：
1. `prune_builtins` **默认 True**，但 `skills/AGENTS.md:91` 声明 "touches only `created_by: 'agent'` skills (bundled + hub-installed are off-limits)"。
2. `tools/skill_usage.py:214–218` 把 `prune_builtins` 当成 bundled skill 是否进入候选清单的开关：
   ```python
   prune_builtins = _prune_builtins_enabled()
   return _scan_local_skills(
       lambda name, _md, bundled, usage: prune_builtins if name in bundled else _is_curator_managed_record(usage.get(name)))
   ```
3. 用户没有写 `curator.prune_builtins: false` 之前，每次 curator 自动转场（默认 7 天间隔）都会把 bundled skill 视为候选。

**症状**：和 1.1 联动 —— 用户安装 91 天后没碰过的 bundled skill 会被归档；user 不知道、文档说 "off-limits"、代码默认开。

**根因**：**AGENTS.md 的 invariant 写得太绝对**，代码实际把 bundled 当作 "默认候选，靠 `prune_builtins: false` opt-out 才不下场"。文档与代码不一致，且默认偏向破坏 invariant。

---

### 1.3 P1 — `plugins/memory/holographic/__init__.py:114` `save_config` 直接 yaml.dump 写 `config.yaml`，绕过 canonical 路径

**确证** — `plugins/memory/holographic/__init__.py:114–125`：

```python
def save_config(self, values, zeloo_home):
    """Write config to config.yaml under plugins.Zeloo-memory-store."""
    config_path = Path(zeloo_home) / "config.yaml"
    try:
        import yaml
        from zeloo_cli.config import read_user_config_raw  # raw read: merged defaults must not be persisted
        existing = read_user_config_raw(config_path)
        existing.setdefault("plugins", {})["Zeloo-memory-store"] = values
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, default_flow_style=False)
    except Exception:
        pass
```

**对比** —— 7 个 in-tree memory provider 中，**只有 holographic** 这么写。其它（`supermemory`、`mem0`、`hindsight`、`openviking`、`honcho`）都走 `zeloo_cli.config.save_config(config)` 走的是 0600 atomic write 的标准 helper。

**症状**：
1. **`except Exception: pass`** —— 任何 IOError 静默吞；用户配置丢失无告警。
2. **`yaml.dump(default_flow_style=False)`** 不保留 `~/.Zeloo/config.yaml` 的 key 顺序、注释、引用风格（如果有 anchor/alias 也会丢失）。
3. 走的是 `read_user_config_raw` 而非 `load_config_readonly`，把"merged defaults" 排除是对的（行内注释 #2），但 `yaml.dump` 写回时**对 multi-line string 的 quoting 规则与原文件不一致** —— YAML parser 仍能解析，但用户 diff 看会很乱。

**根因**：holographic 的 `_setup.py` 用的是 `_setup.py` 之外的 inline `save_config`（行 114），未走 `zeloo_cli.memory_setup` 通用 helper。`save_config` 是 memory provider ABC 的强制方法，每个实现各自重写。

**风险等级 P1** —— 不丢数据，但用户的 `~/.Zeloo/config.yaml` 在 holographic setup 后格式会变；如果该文件是 git 跟踪的（dotfiles repo），每次 setup 制造一次 full-file diff。

---

### 1.4 P1 — `plugins/memory/supermemory/__init__.py:365–366` 在非 multiplex 模式写进程全局 `os.environ`

**确证** — `supermemory/__init__.py:365–366`：

```python
# Make the freshly-entered key visible to the probe below. Single-profile only: under a multiplexed
# gateway, writing to the process-global environ would leak the key to sibling profiles and their subprocesses.
if api_key and not is_multiplex_active() and os.environ.get("SUPERMEMORY_API_KEY") != api_key:
    os.environ["SUPERMEMORY_API_KEY"] = api_key
```

**事实**：
1. 注释自承 "would leak the key to sibling profiles and their subprocesses"，只靠 `is_multiplex_active()` 这一个信号来避免。
2. `is_multiplex_active()` 实现不一定覆盖所有需要避免的场景（CLI 同一进程跑多个 profile session、gateway batch、子 agent fork、cron 触发等）。
3. 即便 `is_multiplex_active()=False`，`os.environ` 写入 **不撤销** —— 进程后续所有代码读到的是新 key，包括未预期的 `delegate_task` 子 agent（除非它重置）。
4. `_write_env_vars({"SUPERMEMORY_API_KEY": val}, zeloo_home=zeloo_home)` 同时把 key 写到 `~/.Zeloo/.env`（profile 隔离），这是正确的；但 `os.environ` 这步是 **额外** 的副作用。

**症状**：`Zeloo memory setup` 走完后，进程内的 `SUPERMEMORY_API_KEY` 永久等于最新值；如果是 key 轮换场景，旧 key 仍在 `.env` 但进程里看不到。

**根因**：probe 之后想避免重读 `.env`，用 `os.environ` 走捷径。注释自承这是 single-profile 的捷径 —— 它不是 bug，但应该只对当前 `cmd_setup` 的 stack frame 起效（`with patch.dict(os.environ, ...):` 或 monkeypatch 局部），不应写入全局。

**风险等级 P1** —— 进程全局副作用；多 profile / cron / subagent 触发场景需要单测覆盖。

---

### 1.5 P2 — `plugins/memory/holographic/store.py:128` 直接 import `zeloo_state_wal.apply_wal_with_fallback`

**确证** — `holographic/store.py:126–129`：

```python
def _init_db(self) -> None:
    """Create schema, enable WAL via the shared fallback helper (NFS/SMB/FUSE degrade gracefully), add hrr_vector to pre-HRR DBs."""
    from zeloo_state_wal import apply_wal_with_fallback
    apply_wal_with_fallback(self._conn, db_label="memory_store.db (holographic)")
```

**事实**：这是 **core helper**（`zeloo_state_wal.py`），plugin 直接 import 它。

**症状**：根据 `plugins/AGENTS.md` "Plugins work within the ABCs/hooks/`ctx` surface we provide"。`zeloo_state_wal` 不在 ABC/hook 列表里 —— 是 core 内部 helper。

**根因**：helper 是 **通用的** (WAL 启用 fallback)，不是 holographic-specific；plugin 拿它用是合理的，但**漏了一个通用的 plugin API**（`ctx.enable_wal(connection)` 这种）。当前 plugin 直接 import core module，未来 PR #102117 后续重构（按 Sep-2026 公告）若把 `zeloo_state_wal` 改名为 `zeloo_state_wal_core` 或加 PLUGIN-COMPAT block，会破 holographic。

**风险等级 P2** —— 当前能跑；但 plugin-core 耦合点是**当前欠的 generic plugin surface** 的信号，应该加一个 `ctx.enable_wal(conn, label)` 方法而非让 plugin import core。

---

### 1.6 in-tree plugin **无任何** 对 `run_agent / cli / gateway.run / zeloo_cli.main` 的反向依赖

**确证** — `grep -rn "from run_agent \|import run_agent\|^from cli \|^import cli$\|from gateway\.run\|import gateway\.run\|from zeloo_cli\.main\|import zeloo_cli\.main" plugins/`

结果：**0 hit**。

`plugins/AGENTS.md` 的 HARDLINE 干净。Plugin 只反向依赖：
- `zeloo_cli.config` (7 处：honcho, mem0, supermemory, byterover, hindsight, holographic, openviking — 都是 ABC 强制方法的合法实现)
- `zeloo_cli.plugins` (6 处 — `get_plugin_manager` 注册)
- `zeloo_cli.memory_setup` (5 处 — `_prompt` / `_curses_select` 等 UX helper)
- `zeloo_cli.profiles` (2 处 — honcho 唯一)
- `zeloo_cli.secret_prompt` (2 处)
- `zeloo_cli.curses_ui` / `urllib_security` / `commands` / `plugin_compat` (零星)

**这些都是 `zeloo_cli/` 公开 API，不是 `main.py`**。符合 HARDLINE。

---

### 1.7 P2 — `plugin_storage.py` 已被设计约束，不构成 `config.yaml` 写路径

**确证** — `plugins/plugin_storage.py:27–44`：

```python
def plugin_data_dir(name: str) -> Path:
    """Return (and create) ``<Zeloo home>/plugin-data/<name>/`` ..."""
    from zeloo_constants import get_zeloo_home
    root = get_zeloo_home() / "plugin-data" / _validate_name(name)
    root.mkdir(parents=True, exist_ok=True)
    return root
```

plugin_data_dir 被强约束到 `<zeloo home>/plugin-data/<name>/`，**不可触达 `config.yaml`、`plugins/`、`skills/`、`cron/`、`logs/`**。`plugin_db` 也只在 `plugin_data_dir` 下开 sqlite。**plugin_storage 不是漏洞**，确认无。

---

## 2. curator 风险

### 2.1 P0 — curator 默认会自动归档 bundled skill（与 AGENTS.md 矛盾，见 1.1+1.2）

见 §1.1 + §1.2 —— 这是同一个根因的两种表述。

**额外风险点**：
- curator 启动 **不需要 cron daemon**（`curator.py:1–7` 的 docstring 写明：inactivity-triggered via `maybe_run_curator()`）
- 用户 idle 时（默认 `min_idle_hours=2`）会触发，**没有可见的 dry-run 默认值**（`dry_run` 默认 `False`）
- 默认 fork 是关的（`consolidate` 默认 `False`），但**纯函数 auto-transitions 总跑**——用户根本看不到 fork，但 bundled skill 已经被 archive

---

### 2.2 P1 — curator_backup 跨 profile 不串台 (确认无风险)

**确证** — `agent/curator_backup.py` 所有路径都通过 `get_zeloo_home()` 解析：
- `_skills_dir()` (line 47): `get_zeloo_home() / "skills"`
- `_backups_dir()` (line 51): `_skills_dir() / ".curator_backups"`
- `_backup_cron_jobs_into()` (line 64): `get_zeloo_home() / "cron" / "jobs.json"`

`get_zeloo_home()` 是 profile-aware（zeloo_constants.py），所以 profile A 的 snapshot 在 `<profile-A>/skills/.curator_backups/`，profile B 完全独立。

`rollback()` (line 358) 同样用 `_skills_dir()`、`_backups_dir()`、`get_zeloo_home() / "cron" / "jobs.json"`。

**结论**：Q6 ("备份路径会不会跨 profile 串台") **确认无风险**。

---

### 2.3 P1 — `_EXCLUDE_TOP_LEVEL` 排除了 `.curator_backups / .hub / .git`，**不排 `.archive`**

**确证** — `agent/curator_backup.py:37`：

```python
_EXCLUDE_TOP_LEVEL = {".curator_backups", ".hub", ".git"}
```

`snapshot_skills()` (line 137) 遍历 `skills.iterdir()` 时这三个目录不进 snapshot。

**但** `.archive/`（curator 把 archived skill 放的地方，line 40 of `curator.py`：**"Archiving (moving the skill's directory into ~/.Zeloo/skills/.archive/)"**）**不在 `_EXCLUDE_TOP_LEVEL` 里** —— 它会被纳入 snapshot！

**症状**：
- 每次 curator run 之前做 `pre-curator-run` snapshot，`.archive/` 全部进 tar.gz
- 用户的 `.archive/` 可能积累大量 archived skill（多年跑 curator 后），snapshot 体积膨胀
- rollback 的时候把 `.archive/` 也恢复——这是 feature，不是 bug（archive 也要能 rollback）
- **但**：snapshot 数被 `keep=5` 限制（line 30），如果 `.archive/` 占了大半体积，**真正活跃 skills 的快照会被驱逐**（`prune_old` line 177 只看 snapshot id 时间序）

**根因**：`.archive/` 是 curator 的产物；保护 snapshot 体积应当至少**单独计数**，但当前实现所有非 `_EXCLUDE_TOP_LEVEL` 目录平等对待。

**风险等级 P1** —— `.archive/` 膨胀场景下 rollback 窗口收窄；不是数据丢失，但 5 个快照可能横跨 3 个月而不是 5 周。

---

### 2.4 P1 — `curator_backup.rollback()` 不会 rollback `~/.Zeloo/cron/jobs.json` 的非 skill 字段

**确证** — `agent/curator_backup.py:241–303`：

`_restore_cron_skill_links()` 的逻辑（第 287-291 行）：
```python
for key, value in bkp.items():  # Restore, preserving absence (don't add a key the backup lacked).
    if value is None:
        live.pop(key, None)
    else:
        live[key] = value
```

`backup["skills"]` 和 `backup["skill"]` 是仅有的被 restore 的字段（第 259 行）；其余 cron job 字段（`schedule`, `enabled`, `paused`, `prompt`, `owner`, `last_run`, `next_run` ...）**完全不 restore**。

**症状**：如果用户在 backup 之后修改过 cron job 的 `schedule` 或 `enabled`，rollback 会**保留新 schedule 但恢复旧 skill 引用**——这本身可能是对的（curator 改的就是 skill ref）。但其它 cron 字段若被 curator 间接副作用影响（比如 `_rewrite_cron_refs` 改了 `updated_at`），rollback 不撤销 `updated_at`。

**根因**：设计就是 "snapshot 的是 skill-ref 切片，不是 jobs.json 完整副本"。这与 `backup_cron_jobs_into` 拷贝的是完整 raw text（第 71 行 `raw = src.read_text(...)`）一致 —— 但 restore 端只挑了两个字段。

**风险等级 P1** —— 设计选择，但应在 `manifest.json.cron_jobs` 加一条 "only `skills`/`skill` are restored" 显式记录（目前 `cron_jobs` 字段只说 `backed_up=true, jobs_count=N`，没说 "what was restored"）。

---

### 2.5 P2 — `agent/curator.py:895–900` curator 快照失败不影响后续 archive，但用户无可见告警

**确证** — `agent/curator.py:895–900`：

```python
try:
    from agent import curator_backup
    snap = curator_backup.snapshot_skills(reason="pre-curator-run")
    if snap is not None:
        _notify(on_summary, f"curator: snapshot created ({snap.name})")
except Exception as e:
    logger.debug("Curator pre-run snapshot failed: %s", e, exc_info=True)
```

`snapshot_skills()` 失败（line 142：`if not is_enabled(): return None` / line 146：no skills dir / line 148：mkdir 失败 / line 167：tarfile error）**全部返回 None**，**curator 仍继续 archive**。

**症状**：用户禁用 backup（`curator.backup.enabled: false`）或 IO 错误 → snapshot=None → curator 仍 archive bundled skill → **不可逆**。

**根因**：`curator_backup.is_enabled()` (line 97) 默认 True，但用户可能在 `config.yaml` 关闭 backup（"我不想要 .curator_backups 占空间"），snapshot 静默 None。

**风险等级 P2** —— 配置合理场景（用户主动关 backup）。但缺少显式告警 "backup disabled, curator will archive without snapshot"。

---

### 2.6 Q7 — `OptionalSkillSource.install` 不会覆盖 built-in skill

**确证** — 路径解析的根：`tools/skills_hub_install.py:38–57`：

```python
def _resolve_lock_install_path(install_path: str, skill_name: str) -> Path:
    from tools.skills_hub import _skills_dir
    normalized = _normalize_lock_install_path(install_path, skill_name)
    target = skills_dir = _skills_dir()
    ...
```

`_skills_dir()` 在 `tools/skills_hub.py` 解析为 `get_zeloo_home() / "skills"`（**用户目录**，不是 `skills/` 仓库目录）。

`_check_install_target()` (line 99–138) 进一步：
- 拒绝嵌套在已有 skill dir 下
- 拒绝 category bucket（dir 里有别的 skill dir）
- **但允许覆盖已有 SKILL.md 的目录**（line 130-131 comment: "a directory that directly contains SKILL.md is an existing skill installation and stays overwritable")

**事实**：
1. **Built-in skills 在 `skills/`（仓库目录），不** 在 `~/.Zeloo/skills/`。所以 install 不可能直接覆盖 built-in。
2. **Hub-installed skills 在 `~/.Zeloo/skills/<category>/<name>/`**（lock 文件记着），install 时通过 `HubLockFile.get_installed(skill_name)` (line 207) 二次确认。
3. **同源覆盖**（用同一个 source 装同一个 skill 名）——lock 允许，覆盖。

**结论**：Q7 **确认无 builtin 覆盖风险**。但**第三方 source 可覆盖 user-installed skill** —— 这是设计（"stays overwritable"），但用户不可见，需要在 `Zeloo skills install` 时显式提示。

---

## 3. facade 反向依赖

### 3.1 P0 — Q9 实际"from run_agent import" 计数是 **494**，不是 537（前份报告数字不准）

**确证** — `grep -rn "from run_agent import" --include="*.py" | wc -l` = **494**。

前份报告 (`audit-2026-09-17-full.md`) 称 "537 处 `from run_agent import`"。**差 43 处**，可能是搜了更宽松的模式（包括 `import run_agent.X`、`from run_agent.X import ...`）。但既然审计三被要求复核这个数字，**记录实际值 494**。

**重要性**：未来 PR 改 `run_agent.py` 导出符号时，**至少影响 494 个文件**（可能含 test fixture 与 actual code 混合）。blast radius 比审计二算的还大。

---

### 3.2 Q8 — `run_agent.py` 公开符号清单

`run_agent.py` 共 1556 行（facade）。grep `^def \|^class \|^[A-Z_]\+ = ` 给出 module-level exports：

| 行 | 类型 | 名 |
|---:|---|---|
| 211 | class | `AIAgent` |
| 1434 | def | `main` |
| 32, 46, 56, 146, 154, 164, 169, 175, 179, 187 | def (helpers) | `_launch_cwd_for_session`, `_session_source_for_agent`, `_gateway_origin_json`, `_quietly`, `_call_engine_hook`, `_positive_int`, `_review_should_defer`, `_review_queue_key`, `_notify_context_engine_session_end`, `_pool_may_recover_from_rate_limit` |
| 1351, 1352 | 模块常量 | `_BASIC_TOOLSETS`, `_COMPOSITE_TOOLSETS` |
| 1520 | dict | `_PLUGIN_COMPAT_LAZY` |
| 1548 | def | `__getattr__` (PEP 562 lazy) |

`AIAgent` 类本身由 17 个 mixin 组成（line 108-122 都是 `from agent.<X> import ...`），mixin 列表：

- `ClientLifecycleMixin`, `StreamDeliveryMixin`, `StatusOutputMixin`
- `ApiRequestHooksMixin`, `ApiErrorSummaryMixin`
- `InterruptControlMixin`, `TurnExplainersMixin`, `ActivityTrackingMixin`
- `RateLimitCreditsMixin`, `SessionPersistenceMixin`
- `CompressionFacadeMixin`, `TurnFacadeMixin`
- `VisionMessagePrepMixin`, `ReasoningParamsMixin`

这些 mixin 都从 `agent/` 目录的同名 module import，**符合 facade + siblings 模式**。

---

### 3.3 Q9 直接 import 兄弟模块（非 facade）的位置

从 494 个 `from run_agent import` 中筛"反向偷引用兄弟模块"的——**找到 0 处**。

`agent/curator.py:1018` 用了 `from run_agent import AIAgent`（合理，fork AIAgent）。
`agent/background_review.py:875` 同样 `from run_agent import AIAgent`（合理）。
`agent/prompt_cache_scope.py:60`、`agent/codex_runtime.py:558`、`agent/client_lifecycle.py:109` —— 三个 late import 兄弟模块的辅助函数（`_session_source_for_agent`, `_StreamErrorEvent`, `_quietly/cleanup_browser/cleanup_vm`）。

**重点**：这些都是**函数内 late import**，不是 module-level。AGENTS.md 的 facade 规则说"Siblings may import each other and late-import the facade inside functions"——**全部合规**。

---

### 3.4 Q10 — `agent/turn_*` siblings 互 import 是 P0 信号还是设计内？

**确证** —— `agent/turn_*.py` 之间大量模块级互 import：

```
turn_api_error.py     → turn_overflow, turn_recovery
turn_context.py       → turn_author
turn_empty_response.py → turn_recovery
turn_final_response.py → turn_empty_response, turn_stop_gates
turn_iteration_prep.py → turn_context_compaction
turn_overflow.py      → turn_retry_state
turn_preflight_gate.py → turn_context, turn_preflight
turn_preflight.py     → turn_context, turn_context_compaction
turn_recovery.py      → turn_retry_state
turn_request_assembly.py → turn_context
turn_response_check.py → turn_api_call, turn_truncation, turn_usage
turn_response_intake.py → turn_truncation
turn_tool_round.py    → turn_preflight, turn_tool_validation
turn_truncation.py    → turn_api_call, turn_retry_state
conversation_loop.py  → turn_context, turn_retry_state, turn_api_call,
                       turn_api_error, turn_api_request, turn_final_response,
                       turn_finalizer, turn_iteration_prep, turn_loop_errors,
                       turn_preflight_gate
```

**自检循环**：自写脚本遍历 `(A → B)` 集合，检查反向 `(B → A)` —— **0 个真循环**。即 `turn_X` → `turn_Y` 单向，`turn_Y` 不反向 `turn_X`。

但 `conversation_loop.py` 是 **中心节点** —— import 了 10 个 turn_X 模块。它是 facade 的"门面循环"，**它本身不在 turn_* 集合里**，但事实上**扮演了 facade 的角色**。

**根因**（分析）：`conversation_loop.py` 名字暗示"agent loop 编排"，但实际是**第二层 facade**——它组合 turn_X phases。所以"facade + siblings"模式在 `run_agent.py ↔ agent/turn_X` 之外，还隐含了第二层 `agent/conversation_loop.py ↔ agent/turn_X`。

**这不是 bug**——`agent/AGENTS.md:11` 明说 "a turn is `agent/conversation_loop.py::run_conversation`, which `AIAgent.run_conversation` forwards to"。**设计如此**，但 audit 三的报告必须标记：496 个 callers of `run_agent` 之外，**还有 N 个 callers of `agent.conversation_loop`**（10+ turn_X 都 import 它）——这是个隐形的 facade，document 没有把它列为"二级 facade"。

---

### 3.5 P1 — `agent/conversation_loop.py` 是隐形的"二级 facade"，未在 AGENTS.md 标注

**事实**：`agent/conversation_loop.py` 自身从 10 个 `agent.turn_X` 模块 import；它也是 `agent.curator`、`agent.compression_facade` 等多个模块反向 late-import 的目标（`from agent.conversation_loop import ...`）。

但 `agent/AGENTS.md:11` 只说"turn is `agent/conversation_loop.py::run_conversation`"——**没有把它标为 facade**。PR #102117 Sep-2026 公告（`plugins/AGENTS.md:88`）说"`run_agent.py` (`agent/turn_*.py`, `agent_init.py`, `conversation_loop.py`)"—— 把 `conversation_loop.py` 列在 `run_agent.py` 的 siblings 列表里。

**含义**：按 root AGENTS.md 的 facade + siblings 规则，**它应该是 facade 或 sibling，但 AGENTS.md 没有明确归类**。当 PR 想在 `conversation_loop.py` 里加新行为时，会出现 "这是 facade 还是 sibling?" 的模糊判断。

**风险等级 P1** —— 不是 bug，是 doc 缺位；应 patch `agent/AGENTS.md` 第 11 行，明确 "`conversation_loop.py` is the agent-loop facade (combines 10 turn_X phases)"。

---

### 3.6 Q11 — `tools/` → `agent/` 反向依赖：单向、叶子级、合规

**确证**：

`tools/*.py` 模块级 import 的 agent 子模块：

| tools 文件 | import |
|---|---|
| `tools/browser_tool.py` | `agent.browser_provider`, `agent.redact` |
| `tools/discord_tool.py` | `agent.secret_scope` |
| `tools/file_tools.py` | `agent.file_safety`, `agent.redact` |
| `tools/homeassistant_tool.py` | `agent.secret_scope` |
| `tools/kanban_tools.py` | `agent.redact` |
| `tools/send_message_tool.py` | `agent.secret_scope` |
| `tools/skill_linter.py` | `agent.skill_utils` |
| `tools/skill_manager_tool.py` | `agent.skill_utils` |
| `tools/skills_hub_install.py` | `agent.skill_utils` |

所有 import 都到 **叶子模块**（`secret_scope`, `redact`, `skill_utils`, `browser_provider`, `file_safety`），**不触达 `run_agent`、`agent` 包、`agent.turn_*`**。

`tools/bot_mode_dm.py:228/609` 与 `tools/bot_relay.py:409/421` 触达 `agent.turn_author` —— 但**全部函数内 late import**（grep 验证），符合 "patch where production reads" 模式。

`tools/delegate_tool.py:183` 唯一一处 `from run_agent import AIAgent`，是函数内 late import（line 182-184），同样合规。

**结论**：Q11 **确认单向，tools → agent 的反向依赖仅到叶子，0 个 facade 触达**。

---

### 3.7 P2 — `run_agent.py` 模块级 `from agent.<mixin>` 形成 17 条强耦合

**事实**：`run_agent.py:107–122` 一口气 import 17 个 mixin，**全部 module-level**。这意味着任何 mixin 改动都可能 break `import run_agent` —— 而 `import run_agent` 是 494 个文件的入口。

**根因**（与设计权衡）：mixin 必须在 class definition 时 ready（`class AIAgent(<all 17>):`）。Late import 不可行。

**风险等级 P2** —— 设计取舍，但若某个 mixin 模块在导入时 trigger 副作用（如读 config、记 telemetry），整体 import 时间与失败面会大。当前 17 个 mixin 应该都遵循"无副作用导入"约束（需 spot-check，未在本次审计范围）。

---

### 3.8 P2 — `_PLUGIN_COMPAT_LAZY` 字典（run_agent.py:1520）意味着 facade 也是"plugin compat target"

**确证** — `run_agent.py:1520`：

```python
_PLUGIN_COMPAT_LAZY = {
    ...
}
```

外加 line 1548 `__getattr__` (PEP 562 lazy load)。这把 facade 也带进了 Sep-2026 compat window（`plugins/AGENTS.md:88` 的"ends 2026-09-14"）。

**含义**：2026-09-14 compat removal 后，`__getattr__` 解析失败的符号会让 facade 调用方崩。`scripts/check_compat_pointers.py` (in CI) 检查 in-tree 代码没用 compat paths —— **但 494 个 in-tree `from run_agent import` 隐式走了 compat**。

**风险等级 P2** —— 审计二时是 2026-09-17，已过 compat removal 日期 (2026-09-14)；说明要么 compat 已撤，要么 _PLUGIN_COMPAT_LAZY 已转成真导出。需要 spot-check 这 17 个 mixin 是不是已转 PLUGIN-COMPAT done state。

---

## 4. P0/P1/P2 路线图

### 4.1 P0（48 小时内修）

| # | 项 | 文件:行 | 动作 |
|---|---|---|---|
| P0.1 | `PROTECTED_BUILTIN_SKILLS` 为空违反 prompt 承诺 | `tools/skill_usage.py:38` | 至少把 `plan` 加进去：`PROTECTED_BUILTIN_SKILLS = frozenset({"plan"})`；同步检查 `delegate-task` 等 slash-command skill。**Patch 草稿 + INVARIANT 测试见 §4.3** |
| P0.2 | `prune_builtins` 默认 True 违反 `skills/AGENTS.md` | `agent/curator.py:125` | 翻默认：改为 `False`；或在 AGENTS.md 改 invariant 描述为 "bundled 是默认候选，靠 opt-out 关闭"（后者要求 changelog + 大版本） |
| P0.3 | curator prompt 的 "filtered out of candidate list" 是假 | `agent/curator.py:814` (`_render_candidate_list`) | 在 `_render_candidate_list` 显式过滤 `is_protected_builtin` —— 不依赖 LLM 自觉 |

### 4.2 P1（2 周内修）

| # | 项 | 文件:行 | 动作 |
|---|---|---|---|
| P1.1 | holographic `save_config` 绕过 canonical 路径 | `plugins/memory/holographic/__init__.py:114` | 改成 `from zeloo_cli.config import save_config as _save; _save({"plugins": {"Zeloo-memory-store": values}, **existing}, path=...)` 或走 ABC 的 `MemoryProvider._save_config` helper |
| P1.2 | supermemory 写 `os.environ` 全局副作用 | `plugins/memory/supermemory/__init__.py:365` | 局部上下文（`with patch.dict(os.environ, ...):`）跑 probe；不写入全局 |
| P1.3 | curator_backup `.archive/` 膨胀压垮 active snapshot | `agent/curator_backup.py:37` | `_EXCLUDE_TOP_LEVEL` 加 `.archive`？或单独计 `.archive/` 体积，避免驱逐 active snapshot |
| P1.4 | curator_backup rollback 只恢复 cron skill/skill 字段 | `agent/curator_backup.py:241` | `manifest.json.cron_jobs` 加 `"restored_fields": ["skills", "skill"]` 显式记录 |
| P1.5 | `agent/conversation_loop.py` 在 AGENTS.md 模糊归类 | `agent/AGENTS.md:11` | 加一行 "conversation_loop.py is the **agent-loop facade** (composes 10 turn_X phases); siblings depend on it" |

### 4.3 P2（一个月内修）

| # | 项 | 文件:行 | 动作 |
|---|---|---|---|
| P2.1 | plugin 直接 import `zeloo_state_wal` | `plugins/memory/holographic/store.py:128` | 加 `ctx.enable_wal(conn, label)` 到 PluginContext，把 `zeloo_state_wal` 从 in-tree plugin 视野隐藏 |
| P2.2 | curator backup 失败静默 None | `agent/curator.py:898` | backup 失败时 `_notify(on_summary, "curator: snapshot disabled, archiving without rollback")` 显式告警 |
| P2.3 | `_PLUGIN_COMPAT_LAZY` 已过 removal 日期 | `run_agent.py:1520` | spot-check 17 mixin 是否已真导；如未，sync 到 PLUGIN-COMPAT done state 或 revert |
| P2.4 | curator_backup `.archive/` 不在 _EXCLUDE 但 rollback 想保留 | `agent/curator_backup.py:37` | (与 P1.3 同一议题；如未在 P1 修复，归 P2) |

---

### 4.3 P0.1 patch 草稿 + INVARIANT 测试模板

**Patch 草稿** —— `tools/skill_usage.py:38`：

```python
# Before:
PROTECTED_BUILTIN_SKILLS: Set[str] = set()

# After (minimum viable):
PROTECTED_BUILTIN_SKILLS: Set[str] = frozenset({
    # Slash-command entry points referenced in docs and tips; never archive/consolidate.
    "plan",
    # Add more as the AGENTS.md enumeration grows: anything a user can invoke via `/<name>`.
})
```

**Patch 草稿** —— `agent/curator.py:817` (`_render_candidate_list`)：

```python
# Before:
def _render_candidate_list() -> str:
    rows = skill_usage.curated_report()
    ...

# After: drop protected builtins before the LLM sees them.
def _render_candidate_list() -> str:
    rows = skill_usage.curated_report()
    from tools.skill_usage import is_protected_builtin
    rows = [r for r in rows if not is_protected_builtin(r["name"])]
    if not rows:
        return "No curator-managed skills to review."
    ...
```

**INVARIANT 测试模板** —— `tests/agent/test_curator_protected_builtin.py`：

```python
"""Bundled skills in PROTECTED_BUILTIN_SKILLS survive every curator pass.

INVARIANT: a skill in PROTECTED_BUILTIN_SKILLS must NEVER:
  - appear in _render_candidate_list()
  - have state != STATE_ACTIVE after apply_automatic_transitions()
  - be moved to .archive/ regardless of inactivity
"""
from datetime import datetime, timedelta, timezone

import agent.curator as curator
from tools import skill_usage

def test_plan_is_protected_builtin():
    assert "plan" in skill_usage.PROTECTED_BUILTIN_SKILLS, \
        "plan must be in PROTECTED_BUILTIN_SKILLS (slash-command entry point)"

def test_plan_not_in_candidate_list(tmp_path, monkeypatch):
    # Set up a ZELOO_HOME with a fake `plan` skill that's never been used.
    skills_dir = tmp_path / "skills"
    plan_dir = skills_dir / "plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "SKILL.md").write_text("---\nname: plan\n---\n# plan\n", encoding="utf-8")
    # Seed a usage record dated 200 days ago — past archive_cutoff.
    skill_usage._mutate(
        "plan",
        lambda rec: rec.update(use_count=0, last_activity_at=None,
                               created_at=(datetime.now(timezone.utc) - timedelta(days=200)).isoformat()),
        require_curation_eligible=True,
    )
    monkeypatch.setattr(curator, "get_prune_builtins", lambda: True)
    monkeypatch.setattr(curator, "_read_config_section", lambda *a, **kw: {"prune_builtins": True})
    rendered = curator._render_candidate_list()
    assert "plan" not in rendered, "protected builtin must not appear in candidate list"

def test_protected_builtin_not_archived(tmp_path, monkeypatch):
    # Same setup as above; run apply_automatic_transitions and assert plan stays active.
    skills_dir = tmp_path / "skills"
    plan_dir = skills_dir / "plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    skill_usage._mutate("plan",
                        lambda rec: rec.update(use_count=0, last_activity_at=None,
                                               created_at=(datetime.now(timezone.utc) - timedelta(days=200)).isoformat()),
                        require_curation_eligible=True)
    monkeypatch.setattr(curator, "get_prune_builtins", lambda: True)
    counts = curator.apply_automatic_transitions()
    assert counts["archived"] == 0, "protected builtin must not be auto-archived"
    assert not (skills_dir / ".archive" / "plan").exists()
```

---

## 5. 错误率自评（子任务自评）

### 5.1 已确证 (HIGH confidence)

- §1.1 P0 `PROTECTED_BUILTIN_SKILLS = set()` —— 源码行号 + 矛盾文本 + auto-transition 代码路径完整引用。
- §1.2 P0 `prune_builtins` 默认 True —— `curator.py:125` 源码 + `skills/AGENTS.md:91` 文本对照。
- §1.3 P1 holographic `save_config` —— 完整 12 行源码 + 与其它 5 个 provider 路径对比。
- §1.4 P1 supermemory `os.environ` —— 完整源码 + 注释自承 "would leak"。
- §1.5 P2 holographic 用 `zeloo_state_wal` —— 源码 + plugins/AGENTS.md 规则引用。
- §1.6 in-tree plugin 无反向触达 run_agent / cli / gateway.run / zeloo_cli.main —— grep 全量 0 hit。
- §1.7 plugin_storage 已被约束 —— `plugin_storage.py:27-44` 完整源码。
- §2.1 curator 默认 archive bundled —— `curator.py:191-237` auto-transitions 逻辑 + `skill_usage.py:214-218` 候选清单 lambda。
- §2.2 curator_backup 跨 profile 不串台 —— 全文件所有 `Path(...)` 都从 `get_zeloo_home()` 派生。
- §2.3 `_EXCLUDE_TOP_LEVEL` 不排 `.archive` —— line 37 源码 + curator.py:293 写 archive 路径对照。
- §2.5 backup 失败静默 None —— line 142, 146, 148, 167 4 处 return None 路径。
- §2.6 builtin 不被 OptionalSkillSource 覆盖 —— `_resolve_lock_install_path` + `_check_install_target` 完整源码。
- §3.1 `from run_agent import` 实际 494 —— `grep -rn "from run_agent import" --include="*.py" | wc -l` 实证。
- §3.3 Q9 0 处反向偷引用 —— grep + 人工 spot-check `agent/curator.py:1018`, `agent/background_review.py:875` 等。
- §3.4 turn_X siblings 单向无环 —— 自写脚本互检 + 列出 18 条单向边。
- §3.6 tools → agent 0 facade 触达 —— 9 个 tools 文件 import 的 agent 子模块清单。

### 5.2 高置信 (MEDIUM — 缺一项实测但推理强)

- §2.4 `rollback` 只恢复 cron `skills`/`skill` 字段 —— `_restore_cron_skill_links` 完整源码 (line 241-303)，但未实际跑 rollback 测全字段 diff。
- §3.2 run_agent 公开符号清单 —— grep `^def \|^class \|^[A-Z_]\+ = ` 行号；混入的 mixin import 未做完整 import graph 重建。
- §3.7 17 mixin 副作用 —— 声明的约束，未做 module-load timing 实测。
- §3.8 `_PLUGIN_COMPAT_LAZY` 状态 —— 审计三时间已过 compat removal (2026-09-14)，但未 spot-check 17 mixin 是否仍 lazy。

### 5.3 低置信 (LOW — 仅做了 grep 表层，未做动态验证)

- §1.4 P1 supermemory `os.environ` 在 cron/subagent 场景的实际副作用 —— **仅读源码 + 注释自承**，未跑 cron/multiplex E2E。审计三时间预算不允许跑 E2E。
- §2.5 P2 backup 失败在多 profile 并发场景 —— **仅源码路径分析**，未模拟并发场景。

### 5.4 未做（留给后续审计）

- 实际跑 `apply_automatic_transitions` 在 bundled skill 上的 archive 行为（需要临时 ZELOO_HOME + fixture skill）。
- 实际跑 `rollback` 在 `.archive/` 膨胀场景下的 snapshot eviction（需要预灌 100+ archived skill）。
- 实际跑 `OptionalSkillSource` install 跨源覆盖（需要两个 source 同名 skill fixture）。
- audit 其它 plugin 子目录（`image_gen`, `cron_providers`, `kanban`, `model-providers`, `platforms`, `dashboard_auth`, `observability`）的 register(ctx) 是否覆盖 core tool——审计三聚焦 8 个 memory provider + plugin_loader/storage，未扫其它子目录。

### 5.5 数字校核

| 题目称谓 | 实际值 | 说明 |
|---|---|---|
| "537 处 from run_agent import" | **494** | grep 实证，前份报告数字偏大约 8.7% |
| "8 个 memory provider" | 实际 8 个: honcho, mem0, supermemory, byterover, hindsight, holographic, openviking, retaindb | 题目数字正确 |
| "plugin __init__.py 第一屏 30 行" | 大多数 in-tree plugin 是包级 __init__.py；子目录级 plugin 在 `memory/`, `model-providers/`, `web/`, `cron_providers/` 等 | 已读 18 个 __init__.py + 6 个 web/<name>/provider.py + 8 个 memory/<name>/__init__.py |

---

## 附录 A — 跨报告引用

- `audit-2026-09-17-full.md` (§5.1 "PluginSystem"): 声称 537 处 `from run_agent import`、plugin loader 安全、storage 受约束 —— **数字 537 错**（实际 494）；plugin loader 与 storage 评估方向正确，但**漏掉了 holographic save_config 直接 yaml.dump**（本报告 §1.3 P1）。
- `audit-2026-09-17-full.md` (§6 Curator): 仅提到 "curator 默认启用；archival 是软删除"。**漏掉了 curator 默认 archive bundled skill 与 AGENTS.md invariant 冲突**（本报告 §1.1 P0 + §1.2 P0 + §2.1 P0）。
- 两份前报告**完全未触碰**：
  - `PROTECTED_BUILTIN_SKILLS = set()` 与 prompt "currently: plan" 文本矛盾
  - `_PLUGIN_COMPAT_LAZY` 已过 removal 日期（2026-09-14 → 2026-09-17）的状态
  - `agent/conversation_loop.py` 作为隐形二级 facade 的 doc 缺位
  - 494 个 `from run_agent import` 调用方的反向 import 拓扑
  - in-tree plugin 是否触达 `run_agent / cli / gateway.run / zeloo_cli.main` —— **确认 0 hit**（这是正面发现）