# 自动创建子 agent — 设计文档

> 老板问题：「可以自动创建子 agent 吗?如果不能,如何实现?」
> 答: **不能**(没有 tool 暴露)。本文档描述实现路径。

---

## 1. 现状

| 能力 | 现状 |
|---|---|
| `Zeloo profile create <name>`(CLI 手动) | ✅ 存在(`zeloo_cli/profiles.py:820` `create_profile()`) |
| Agent 通过 tool 创建新 profile | ❌ **没暴露** |
| `delegate_task`(复用现有 profile 跑子任务) | ✅ 存在 |
| 自动给新 profile 注入 SOUL/IDENTITY | ⚠️ 部分(bootstrap 默认 SOUL,IDENTITY 不自动生成) |

**结论**:底层能力全有,只缺** agent-facing tool 接口**。

---

## 2. 实现路径

### 2.1 最简方案(~150 行 + 测试)

**加 1 个 tool**:`tools/agent_create.py` + tool 注册:

```python
def create_agent_profile(
    name: str,
    *,
    soul_md: str | None = None,       # 默认用 DEFAULT_SOUL_MD
    identity: dict | None = None,     # {"name": "...", "style": "..."}
    user_md: str | None = None,       # 默认用 DEFAULT_USER_MD
    clone_from: str | None = None,    # 从哪个 profile 复制
    memory_md: str | None = None,     # 默认空白
) -> dict:
    """Create a new agent profile and return its config.

    Sandbox: agent can ONLY create profiles under ~/.Zeloo/profiles/
    (NOT under root, NOT outside the user's home).
    """
```

**tool 注册**(在 `model_tools.py`/`toolsets.py`):
- 默认**禁用** —— 用户必须在 `~/.Zeloo/config.yaml` 显式开启
  ```yaml
  tools:
    enabled: [agent_create, ...]  # opt-in
  ```

**安全护栏**:
- profile name 必须匹配 `[a-z][a-z0-9-]{1,32}`(防路径穿越)
- 拒绝创建名 = `default`(保留 profile)
- 创建后自动写 `factsheet` 条目(可审计)
- `ZELOO_SAFETY=strict` 时整个 tool 不加载

### 2.2 测试(必须)

- INVARIANT 1: tool 能创建 profile + SOUL.md 写入正确
- INVARIANT 2: 拒绝 `name=default` 或包含 `..`/`/` 的名字
- INVARIANT 3: 默认 `tool disabled` —— 未授权 agent 调不到
- INVARIANT 4: 创建后 agent 自己能用(`delegate_task` 到新 profile)
- INVARIANT 5: factsheet 自动追加 audit 条目

### 2.3 估工时

| 步骤 | 行数估 | 时间估 |
|---|---|---|
| tools/agent_create.py 实现 | ~100 | 1-2h |
| model_tools 注册 + 权限护栏 | ~30 | 1h |
| INVARIANT 测试 | ~150 | 1h |
| 集成测试(真在 gateway 上调一次) | ~50 | 1h |
| **总计** | ~330 | **4-5h** |

### 2.4 与 M1 群聊的关系

如果 M1 群聊 M1.2 driver emit 完成,**新 agent 自动创建 + 群聊邀请** 可以组合:
- Agent A 说"我需要研究助手"
- 自动创建 `~/.Zeloo/profiles/researcher/`(SOUL/IDENTITY 由调用方指定)
- 自动 invite 到当前 hosted_room
- Driver emit `agent.joined` 事件让其他成员看到

这是**老板想要的真"自动子 agent"**,估工时 **4-5h + M1.2 5-6h = 10-11h** 1 个 session。

---

## 3. 不在本设计内(老板可能想问)

| 问题 | 现状 |
|---|---|
| Agent 自主决定**何时**创建子 agent? | ✅ 模型本身能做 —— 有 tool 后会自己调 |
| Agent 创建子 agent 后**自主删除**? | ❌ 设计稿里没 delete tool,推荐手动 |
| 多 agent **同时运行**同一任务? | ❌ 需要 cron multiplex(已有)+ profile spawn 协调 |
| Agent 创建的子 agent **自动继承 SOUL/IDENTITY**? | ❌ 默认 clone_from 走现有 clone logic |

---

## 4. 老板选项

| 选项 | 内容 | 估工时 |
|---|---|---|
| **A** | 仅加 `agent_create` tool(无群聊联动) | 4-5h |
| **B** | A + 群聊 invite 联动 | 10-11h |
| **C** | A + 自动 SOUL/IDENTITY 生成(LLM 生成) | 6-8h |
| **D** | 仅做设计文档,不实现 | 0h(本文档已完成) |

---

## 5. 真风险

1. **身份滥用**:Agent 自己生成 SOUL 可能编造"我是研发经理,工资 50k"等不当内容
   → 缓解:创建时强制 `require_owner_approval=True`(主 agent 不能完全自动)
2. **资源耗尽**:Agent 自动 spawn 几十个子 profile 占满磁盘
   → 缓解:`max_profiles` 配置项 + 启动时检查
3. **安全边界**:Agent 写到 `~/.Zeloo/` 之外
   → 缓解:`name` 正则 + 路径锚定(已在设计中)