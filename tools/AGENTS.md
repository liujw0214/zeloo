# tools/AGENTS.md

## 本包职责

Agent 工具注册系统：负责将所有可调用工具注册到 Agent 运行时。

## 核心模块

### 基础架构
- `base.py`：Tool 装饰器和基类
- `__init__.py`：工具注册表（统一导出所有工具）
- `registry.py`：工具注册表核心
- `advanced_toolkit.py`：高级工具集
- `path_safety.py`：路径安全检查
- `output_scan.py`：敏感信息扫描

### 浏览器工具（browser_tool_*）
- `browser_tool.py`：浏览器自动化核心（27 个工具：navigate/screenshot/click/type 等）
- `browser_tool_install.py`：Playwright/Chrome 检测和安装
- `browser_tool_session.py`：多会话管理
- `browser_tool_lifecycle.py`：生命周期钩子
- `browser_supervisor.py`：进程监管和崩溃恢复
- `browser_cdp_tool.py`：Chrome DevTools Protocol 封装
- `browser_tools.py`：基础浏览器工具

### MCP 工具（mcp_tool_*）
- `mcp_tool.py`：MCP 核心客户端（MCPServerTask / MCPClient）
- `mcp_tool_discovery.py`：MCP 服务器发现
- `mcp_tool_handlers.py`：MCP 工具调用处理
- `mcp_tool_lifecycle.py`：MCP 服务器生命周期
- `mcp_tool_config.py`：MCP 配置解析
- `mcp_tool_common.py`：MCP 公共常量和工具函数

### 审批系统（approval_*）
- `approval.py`：审批核心（危险命令检测/审批/YOLO 模式）
- `approval_context.py`：审批上下文和环境检测
- `approval_detection.py`：危险命令模式检测（正则规则库）
- `approval_floors.py`：审批底线规则（白名单/黑名单）
- `approval_prompt.py`：交互式审批提示 UI
- `approval_gateway_wait.py`：Gateway 审批等待循环

### 业务工具
- `shell_tool.py`：Shell 执行
- `file_tools.py`：文件操作
- `code_exec.py`：代码执行
- `web_tools.py`：网页抓取
- `image_tools.py`：图像处理
- `voice_tool.py`：语音工具（TTS/STT）
- `kanban_tools.py`：看板
- `cron_tool.py`：定时任务
- `memory_tool.py`：记忆工具
- `skills_tool.py`：技能工具
- `todo_tools.py`：待办工具
- `workspace_tools.py`：工作区工具
- `delegate_tool.py`：委派任务

### 辅助工具
- `threat_patterns.py`：威胁模式库
- `optional_skill_tools.py`：可选技能桥接
- `code_exec_sandbox.py`：代码执行沙箱

## 注意事项

- 所有工具必须使用 `@tool` 装饰器注册
- 工具函数必须是纯函数（无全局状态依赖）
- 危险操作（shell_exec/file_write）必须经过 path_safety 检查
- 所有输出必须经过 `output_scan.py` 清理敏感信息
- 浏览器/MCP/审批系统支持 session 隔离
