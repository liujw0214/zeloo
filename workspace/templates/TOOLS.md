# TOOLS.md — 工具定义与权限策略

<!--
定义本工作区中哪些工具可用、权限级别和使用策略。
此文件控制 Agent 的工具访问范围。
-->

## 工具集策略

本工作区启用的工具集：

| 工具集 | 启用 | 说明 |
|--------|------|------|
| web | ✅ | 搜索和获取网页内容 |
| terminal | ✅ | 在工作区作用域内执行 Shell 命令 |
| file | ✅ | 在工作区内读写文件 |
| browser | ⚠️ | 需要用户明确确认 |
| code_execution | ✅ | Python 沙箱执行 |
| delegation | ✅ | 子 Agent 委托 |
| memory | ✅ | 读写工作区记忆 |
| skills | ✅ | 加载和调用工作区技能 |
| cron | ✅ | 调度周期性任务 |
| kanban | ✅ | 看板任务管理 |
| optional_skill:* | ✅ | 专业领域技能工具 |

## 危险工具

以下工具标记为 `dangerous=True`，需要额外谨慎：

- `shell` — 可执行任意命令
- `delegate_task` — 启动子 Agent
- `workspace_archive` — 创建压缩快照
- `workspace_delete` — 永久删除工作区数据

**策略**：执行危险工具前必须获得用户确认，除非用户已明确要求。

## 工具结果限制

- 最大结果字符数：10,000（超出部分截断）
- 最大文件读取大小：1 MB（二进制文件跳过）
- Shell 命令超时：60 秒（可按需调整）

## 限制模式

本工作区禁止以下模式：

- 在 `TERMINAL_CWD` 之外写入文件
- 包含 `sudo`、`rm -rf /`、`chmod 777` 的 Shell 命令
- 使用硬编码凭证的 API 调用
- 无连接池的数据库连接
