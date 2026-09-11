# tui_gateway/AGENTS.md

## 本包职责

TUI 网关运行时，处理终端界面的事件路由、Agent 回调、计费显示。

## 核心组件

- `agent_callbacks.py`：Agent 状态变更回调
- `billing_view.py`：计费视图显示
- `change_watcher.py`：文件变更监视
- `compute_host.py`：计算主机管理

## 注意事项

- TUI 网关仅处理事件路由，不执行业务逻辑
- 所有 Agent 调用通过 `agent_callbacks.py` 回调
- 计费视图实时更新，不缓存