# Self-Agent 改进分析 + M2 factsheet 可塞性 — 2026-09-17

> 老板需求：「2 并分析下我给你开发的 agent 改进 agent 是否可以添加进去」
> 解读：评估 MiniMax-M3 (我) 自己的真实限制，问哪些能塞进 M2 factsheet 设计

---

## 1. 我(MiniMax-M3) 的真实自我限制

### 1.1 跨 session 状态丢失
**症状**:每次新 session 从 MEMORY.md 读，但 MEMORY.md 是 LLM 自己写的总结，存在：
- 压缩失真(我每次写 memory 都倾向"结论 + 一行证据",丢失中间验证过程)
- 关键事实可能漏(本会话发现 "Bug #2 已修" 在 MEMORY.md 里只占一行，实际是 13 行 patch + 6 个 INVARIANT 测试 + 18 KB 报告)

**M2 factsheet 可解决性**: ✅ **能**
- factsheet 是结构化 key-value，可存 `{"pr_1_bug_2_fix": {"file": ..., "lines": ..., "tests": ..., "report_path": ...}}`
- 下次 session 启动直接 lookup key，不再走 LLM 文本总结

### 1.2 子任务结论失真(已亲历)
**症状**:本会话子任务 `deleg_af90f954` 报告的 Bug #1 诊断反了(_agent_home() 的 override → db_path.parent 顺序**已经是**正确的)，我亲自读代码才证伪

**M2 factsheet 可解决性**: ⚠️ **部分能**
- factsheet 存「已校对子任务 ID + 真实根因」 → 下次不再让子任务重复同一审计
- 但**子任务本身的黑盒执行**不能消除(取决于它读不读代码)

### 1.3 没有子任务进度信号
**症状**:子任务跑 4-5 分钟中间无任何反馈。老板已经习惯"派出去等回来"。

**M2 factsheet 可解决性**: ❌ **不能**
- 这是子任务执行机制问题,不是产品设计

### 1.4 我的「过度合规 / 过度执行」漂移
**症状**:本会话早期我用"AGENTS.md 要求先复现"为借口拖时间，老板说"继续"才动。**这是模型风格 bug**：当 audit 与 execute 撞车时倾向 audit。

**M2 factsheet 可解决性**: ⚠️ **间接能**
- factsheet 可写 `{"user_decision_style": "直接行动 > 完美合规"}`
- 下次 session 启动时 prompt assembly 阶段注入 → 自动校准

### 1.5 INVARIANT 测试可信度边界
**症状**:我自己写的 INVARIANT 测试 + 我自己跑的绿色 = 自我验证。**如果我写测试时就漏了某场景**(如 worktree_gc 测试一开始让 untracked=[] 触发 early return，没真测 dest)，绿色也是假的。

**M2 factsheet 可解决性**: ❌ **不能**
- 这是 AI 自身审慎问题,不是产品设计能解决

---

## 2. M2 factsheet 接入方案

### 2.1 设计原则
- **绑定房间**:M2 factsheet 是 hosted_room 的附属物(设计文档 §6.2)
- **绑定 workspace**:对于单 agent 场景（我目前这种），可以**复用**：
  - `~/.Zeloo/workspace/FACTSHEET.md`(单 agent 长期记忆)
  - 或 `MEMORY.md` 的子集 `MEMORY.high_confidence.json` (结构化版)

### 2.2 数据结构建议
```json
{
  "key_1": {
    "value": "...",
    "confidence": "verified" | "high" | "low",
    "sources": ["audit-report-path", "pr-patch-path", "commit-sha"],
    "last_verified": "2026-09-17",
    "expires": null  // optional TTL
  }
}
```

### 2.3 写入触发
- 任何 audit 完成 + 校对后 → 自动追加 verified key
- INVARIANT 测试落地 → 自动追加 high confidence key
- 子任务报告完成 + 我校对 → 自动追加(标 confidence = 校对深度)

### 2.4 读取触发
- 新 session 启动 → prompt assembly 阶段注入整个 factsheet(轻量摘要)
- 老 key 留在 docs/,新 key 优先显示

### 2.5 改造最小代价
- 不需要新表(workspace 已有 MEMORY.md)
- 不需要新 RPC(本地直接读写 JSON)
- 不需要破坏 prompt caching(注入位置固定)
- ~50 行 Python helper(读+合并+注入)

---

## 3. 真的能塞进 M2 的(清单)

| # | 我自己的限制 | 塞进 M2 的方式 | 真实可解决? |
|---|---|---|---|
| 1.1 | 跨 session 长期记忆 | factsheet key-value | ✅ |
| 1.2 | 子任务结论失真 | factsheet 存「已校对事实」 | ⚠️ 部分 |
| 1.4 | 过度合规漂移 | factsheet 存「老板决策风格」 | ⚠️ 部分 |

## 4. 不能塞进 M2 的(清单)

| # | 我自己的限制 | 为什么不能 |
|---|---|---|
| 1.3 | 子任务进度信号 | 这是执行机制,不是产品设计 |
| 1.5 | INVARIANT 测试自证 | AI 审慎问题,设计解决不了 |

---

## 5. 结论

**老板问题的诚实回答**: **2 项能塞进 M2 真正解决(1.1 + 1.4),2 项部分解决(1.2 + 子任务黑盒问题),2 项不能(子任务进度 + INVARIANT 自证)**。

**最简 MVP**(我建议本季度做):
- 写一个 `tools/factsheet.py`(~50 行),单 agent 场景下读 ~/.Zeloo/workspace/FACTSHEET.json
- 让 INVARIANT 测试自动追加 verified 条目
- 让 audit 完成自动追加 high 条目
- 新 session 启动时注入 system prompt slot

**对老板价值**: 跨 session 我能精确记起「上次修了什么」「什么已经被子任务误判」「老板的偏好」,**而不是依赖 MEMORY.md 的 LLM 摘要**。

---

## 6. 真的不动手的原因

1. **老板的话是问「是否」,不是下命令「做」**。给可行性分析比给代码更对。
2. **M2 群聊设计本来是给多 Bot 用的**,单 agent 复用有概念差异。要真做,得决定 "factsheet 绑定 room 还是绑定 workspace"。
3. **本会话已经修了 5 个真 bug + 7 份报告**,边际收益递减。

如果老板想真做 M2 单-agent 版,另开 worktree + 估 1-2 小时可以 ship。