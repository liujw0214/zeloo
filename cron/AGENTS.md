# cron/AGENTS.md

## 本包职责

定时任务调度系统：负责管理 cron 风格的后台任务。

## 核心模块

- `scheduler.py`：调度器核心
- `__init__.py`：公共 API 导出
- `cron_tool.py`：提供给 Agent 的 cron 工具

## 注意事项

- 所有定时任务必须使用 UTC 时间存储
- 任务执行失败必须记录到 audit_log
- 长时间任务必须支持取消
- 调度器重启后必须从持久化状态恢复
