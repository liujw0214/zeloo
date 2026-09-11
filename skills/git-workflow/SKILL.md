---
name: git-workflow
description: Git 版本控制规范操作，涵盖分支、提交、合并、冲突解决
platforms: [cli, tui, api]
toolsets: [terminal, file]
---

# Git Workflow 技能

当用户涉及版本控制操作（分支、提交、合并、rebase、冲突解决）时激活本技能。

## 分支策略

- **main**：生产分支，保护分支，仅通过 PR 合并
- **develop**：开发集成分支
- **feature/<name>**：功能开发分支
- **fix/<name>**：Bug 修复分支
- **release/<version>**：发布准备分支

## 提交规范

提交信息格式：`<type>(<scope>): <subject>`

| type | 说明 |
|------|------|
| feat | 新功能 |
| fix | Bug 修复 |
| docs | 文档变更 |
| refactor | 重构（非功能变更） |
| test | 测试相关 |
| chore | 构建/工具链 |

示例：
```
feat(auth): add OAuth device flow
fix(shell): reject pipe-to-destructive commands
docs(skills): add code-review skill
```

## 操作流程

### 新建功能分支
1. `git checkout develop`
2. `git pull origin develop`
3. `git checkout -b feature/<name>`
4. 开发 + 频繁提交
5. `git push origin feature/<name>`

### 合并回 develop
1. `git checkout develop`
2. `git pull origin develop`
3. `git merge --no-ff feature/<name>`
4. 解决冲突（如有）
5. `git push origin develop`

### 冲突解决
1. `git status` 查看冲突文件
2. 手动解决 `<<<<<<<` `=======` `>>>>>>>` 标记
3. `git add <file>`
4. `git commit`（merge 时）或 `git rebase --continue`

## 安全规则
- 绝不直接 push 到 main
- 提交前检查是否包含敏感信息（API key、密码）
- 大文件不入库（使用 .gitignore）
- 合并前确保测试通过
