# skills/AGENTS.md

## 本包职责

内置技能集（14 类别）。每个技能是 `SKILL.md` 文件定义的独立工作流。

## 技能加载

- 启动时扫描 `skills/` 下所有 `SKILL.md`
- 自动注册到技能注册表
- 支持按类别过滤加载

## 技能调用

1. Agent 判断当前任务是否适合某个技能
2. 加载技能描述注入 system prompt
3. Agent 按技能步骤执行任务
4. 任务完成后，Curator 评估是否值得固化

## 技能格式

```markdown
# skills/<category>/<name>/SKILL.md
---
name: skill-name
description: 一句话描述
author: Zeloo
tags: [tag1, tag2]
version: 1.0.0
---

# Skill Name

## Triggers（触发条件）
- "触发短语1"
- "触发短语2"

## Steps（执行步骤）
1. 步骤一
2. 步骤二
3. 步骤三

## Examples（示例）
...
```

## 注意事项

- 技能命名使用 kebab-case
- 描述不超过 50 字
- 每个技能至少 2 个触发短语
- 敏感信息不得写入技能内容