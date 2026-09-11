# 04. 工具系统与 MCP

## 4.1 工具自动发现

Zeloo 的工具系统采用**约定优于配置**的自动发现机制，无需手动注册。

### 4.1.1 发现规则

- 工具实现放在 `tools/` 目录下
- 每个工具是一个 Python 模块，导出一个符合 `Tool` 协议的对象
- 模块导入时自动注册到全局 `ToolRegistry`

```python
# tools/file_read.py
from typing import Any
from core.tools import Tool, tool

@tool(name="file_read", description="Read a file's contents")
def file_read(path: str, max_length: int = 10000) -> str:
    """Read a file and return its contents."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read(max_length)
```

### 4.1.2 注册流程

```
启动 AIAgent
  │
  ▼
discover_builtin_tools()
  ├─► 扫描 tools/ 目录
  ├─► 导入所有 .py 模块
  ├─► @tool 装饰器触发注册
  └─► 生成 tool_schemas (JSON Schema)
  │
  ▼
按工具集分发 (toolsets)
  │
  ▼
按平台过滤可用工具
```

### 4.1.3 Tool 数据类与注册表

`tools/base.py` 定义了实际的 `Tool` 数据类和 `ToolRegistry`：

```python
from tools.base import Tool, ToolRegistry, get_registry, tool, discover_builtin_tools

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict          # JSON Schema
    execute: Callable[..., Any]
    dangerous: bool = False
    confirmation_required: bool = False
    toolset: str = ""

    def to_openai_schema(self) -> dict:
        """导出为 OpenAI function-calling schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
```

**ToolRegistry**：

```python
registry = get_registry()
registry.register(my_tool)       # 注册工具
registry.get("file_read")         # 按名称获取
registry.get_all()               # 全部工具
registry.get_names()             # 工具名集合
registry.get_schemas()           # 所有 OpenAI schema
```

**@tool 装饰器**：自动从函数签名生成 JSON Schema：

```python
@tool(name="file_read", description="Read a file", dangerous=False, toolset="file")
def file_read(path: str, max_length: int = 10000) -> str:
    """Read file contents."""
    ...

# 等价于手动构造：
# Tool(name="file_read", description="Read file contents",
#      parameters={"type":"object","properties":{"path":...},...},
#      execute=file_read, toolset="file")
```

**类型映射**：`str → string`、`int → integer`、`bool → boolean`、`float → number`，无注解默认为 `string`。

**自动发现**：

```python
discover_builtin_tools()  # 扫描 tools/ 目录，导入所有模块触发 @tool 注册
```

## 4.2 工具集（Toolsets）

工具按逻辑分组为工具集，可按平台独立启停。

### 4.2.1 内置工具集

工具集分类：

| 工具集 | 工具示例 | 说明 |
|--------|----------|------|
| `web` | web_search, web_fetch | 网络搜索与抓取 |
| `terminal` | shell | 终端命令执行 |
| `file` | file_read, file_write, file_edit | 文件操作 |
| `browser` | browser_navigate, browser_click, browser_screenshot | 浏览器自动化（需 Playwright） |
| `code_execution` | execute_code | Python 沙箱执行（dangerous 工具） |
| `delegation` | delegate_task, clarify | 子代理委托与澄清 |
| `skills` | skill_view, skill_manage | 技能管理 |
| `memory` | memory, session_search | 记忆与会话搜索 |
| `todo` | todo_add, todo_list, todo_complete, todo_remove | 任务管理 |
| `cron` | cron_add, cron_list, cron_remove | 定时任务调度 |
| `voice` | voice_tts, voice_stt | 语音合成与转录 |
| `kanban` | kanban_create, kanban_complete, kanban_show, kanban_assign, kanban_heartbeat | 多智能体看板 |
| `image` | image_generate | 图片生成（默认禁用） |

### 4.2.2 条件可用（check_fn）

工具可声明条件可用性函数，仅在条件满足时才注册到 Agent。

```python
@tool(name="browser_navigate", description="...", toolset="browser")
def browser_navigate(url: str) -> str:
    ...

# 仅在安装了 playwright 时注册
browser_navigate.check_fn = lambda: importlib.util.find_spec("playwright") is not None
```

未满足 `check_fn` 的工具不会出现在 `tool_schemas` 中，Agent 无法调用。

### 4.2.3 审批工具（Approval）

危险工具需要用户确认才能执行，支持自动审批与手动审批。

```python
@tool(
    name="shell_unsafe",
    description="Execute shell command without sandbox",
    dangerous=True,
    confirmation_required=True,
)
def shell_unsafe(command: str) -> str:
    ...
```

审批流程：
1. Agent 请求执行 `shell_unsafe`
2. 系统检查 `confirmation_required` 标记
3. 若启用自动审批（`zeloo_DANGEROUS_POLICY=auto`），直接执行
4. 否则弹出确认提示，用户同意后执行

### 4.2.4 工具集分发

```python
# toolset_distributions.py
zeloo_CORE_TOOLS = {
    "web": ["web_search", "web_fetch"],
    "terminal": ["shell"],
    "file": ["file_read", "file_write", "file_edit"],
    # ...
}

def get_toolset_for_tool(tool_name: str) -> Optional[str]:
    for toolset, tools in zeloo_CORE_TOOLS.items():
        if tool_name in tools:
            return toolset
    return None
```

### 4.2.5 平台过滤

不同平台启用不同工具集：

```python
PLATFORM_TOOLSETS = {
    "cli": ["web", "terminal", "file", "browser", "code_execution", "skills", "memory", "todo"],
    "telegram": ["web", "file", "skills", "memory"],  # 无 terminal
    "discord": ["web", "file", "skills", "memory"],
    "api": ["web", "file", "code_execution", "skills", "memory"],
}
```

## 4.3 MCP（Model Context Protocol）集成

### 4.3.1 双传输支持

| 传输方式 | 适用场景 | 实现 |
|----------|----------|------|
| `stdio` | 本地 MCP 服务器 | 子进程 stdin/stdout |
| `http` | 远程 MCP 服务器 | HTTP/SSE 长连接 |

### 4.3.2 配置格式

```yaml
# config.yaml
mcp:
  servers:
    - name: filesystem
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    - name: github
      transport: http
      url: https://mcp.github.com
      headers:
        Authorization: Bearer ${GITHUB_TOKEN}
```

### 4.3.3 工具过滤

每个 MCP 服务器可配置工具过滤：

```yaml
mcp:
  servers:
    - name: github
      transport: http
      url: https://mcp.github.com
      tool_filter:
        include: ["create_issue", "list_repos"]
        exclude: ["delete_repo"]
```

### 4.3.4 与内置工具统一

MCP 工具由 `mcp/manager.py` 的 `MCPServerManager.load_and_register` 加载，
注册到同一个 `ToolRegistry`，对 Agent Loop 透明。工具名统一加 `mcp_` 前缀以避免冲突：

```python
from mcp.manager import MCPServerManager

manager = MCPServerManager()
n = manager.load_and_register(config)   # returns count of registered tools
# tool names appear as "mcp_<server_tool_name>" in the registry
```

## 4.4 子代理委托（Subagent Delegation）

### 4.4.1 设计原则

- **零知识隔离**：子代理仅接收 goal + context，不共享主 Agent 状态
- **并发执行**：默认并发 3 个子代理
- **自动注入上下文**：子代理自动注入项目上下文文件链

### 4.4.2 delegate_task 工具

```python
@tool(name="delegate_task", description="Delegate a task to a subagent")
def delegate_task(goal: str, context: str = "", max_iterations: int = 30) -> str:
    subagent = AIAgent(
        model=self.model,
        system_prompt=None,  # 子代理重新构建，仅注入 goal + context
        tools=self._subagent_tools(),  # 受限工具集
        max_iterations=max_iterations,
    )
    result = subagent.run_conversation(f"{goal}\n\nContext: {context}")
    return result
```

### 4.4.3 子代理工具集

子代理默认使用受限工具集，避免危险操作：

- 包含：file_read, web_search, web_fetch, skill_view, memory
- 排除：shell, file_write, file_edit, delegate_task（防止递归）

## 4.5 代码执行沙箱

### 4.5.1 execute_code 工具

```python
@tool(name="execute_code", description="Execute Python code in a sandbox")
def execute_code(code: str, timeout: int = 30) -> dict:
    return sandbox.execute(code, timeout=timeout)
```

### 4.5.2 沙箱特性

- Python 代码在隔离进程中执行
- 脚本内部可调用 Zeloo 自身工具（通过 RPC）
- 超时自动终止（默认 30s）
- 资源限制：CPU、内存、文件系统访问范围

### 4.5.3 使用场景

将多步工作流折叠为单次 LLM 回合：

```python
# Agent 生成的代码
from zeloo_tools import file_read, web_fetch

docs = file_read("docs/")
contents = [web_fetch(url) for url in docs]
# 处理逻辑...
```

## 4.6 工具安全

### 4.6.1 工具结果清洗

所有工具返回结果在注入 messages 前经过清洗：

- 去除潜在的 prompt injection 模式
- 截断过长输出（默认 10000 字符）
- 二进制内容编码为 base64

### 4.6.2 危险工具标记

```python
@tool(name="shell", description="Execute a shell command", dangerous=True)
def shell(command: str) -> str:
    ...
```

标记为 `dangerous=True` 的工具：
- 在 system prompt 中明确告知 Agent
- 执行前可配置需要用户确认
- 日志中单独记录

## 4.7 Web 工具与 Auxiliary Client

### 4.7.1 web_fetch 工具

`web_fetch` 工具抓取指定 URL 并返回清洗后的可读文本。当 Auxiliary Client 启用时，
它会调用辅助 LLM 从 HTML 中提取正文（去除导航、广告、模板噪声）；否则回退到简单的
HTML 标签剥离。

```python
@tool(name="web_fetch", description="Fetch a URL and return its clean text content", toolset="web")
def web_fetch(url: str, max_chars: int = 4000) -> str:
    ...
```

### 4.7.2 Auxiliary Client（辅助 LLM 客户端）

Zeloo 提供一个独立的轻量级 LLM 客户端，用于处理
低复杂度、高频次的子任务（网页正文提取、图片描述、文本摘要），不占用主模型的
迭代预算，也不共享主对话上下文。

**配置**（`config.yaml`）：

```yaml
auxiliary:
  enabled: true
  provider: openai
  model: gpt-4o-mini
  base_url: null
  max_tokens: 1024
  temperature: 0.0
```

**核心能力**：
- `complete(prompt, system=...)` — 单轮补全
- `summarize(text, max_chars=500)` — 文本摘要
- `extract_text(html_or_text)` — 网页正文提取
- `describe_image(image_url)` — 图片描述（需 vision 模型）

未启用时所有方法为安全空操作，不会报错。

## 4.8 图片生成工具（image_generate）

`image_generate` 工具基于文本 prompt 生成图片，使用 OpenAI 兼容的 Images API（DALL-E 等）。
该工具位于 `image` 工具集，已在所有平台（cli/tui/telegram/discord/api）默认启用。
工具本身通过 `image_generation.enabled` 配置控制是否真正可用，未配置时返回提示信息。

### 4.8.1 启用方式

在 `config.yaml` 中启用并配置：

```yaml
image_generation:
  enabled: true
  provider: openai
  model: dall-e-3
  size: 1024x1024        # 1024x1024 / 1024x1792 / 1792x1024
  quality: standard       # standard / hd
  base_url: null
```

在 profile 的 `toolsets` 中加入 `"image"`：

```yaml
gateway:
  profiles:
    default:
      toolsets: ["core", "image"]
```

### 4.8.2 多 Provider 故障转移

支持配置 `fallback_providers`，当主 provider 失败（限流、网络错误等）时自动依次尝试备用 provider：

```yaml
image_generation:
  enabled: true
  provider: openai
  model: dall-e-3
  fallback_providers:
    - name: together
      model: flux-1-schnell
      api_key: ${TOGETHER_API_KEY}
      base_url: https://api.together.xyz/v1
```

- `api_key` 支持 `${ENV_VAR}` 语法从环境变量读取
- 每个 fallback 可独立指定 `model` 和 `base_url`
- 所有 provider 均失败时返回最后一个错误信息

### 4.8.3 工具签名

```python
@tool(name="image_generate", toolset="image")
def image_generate(
    prompt: str,
    size: str | None = None,      # 1024x1024 / 1024x1792 / 1792x1024
    quality: str | None = None,   # standard / hd
    n: int = 1,
) -> str
```

返回生成图片的 URL（多个 URL 以换行分隔）。

## 4.9 代码执行工具（code_execution）

### 4.9.1 execute_code 工具

`execute_code` 在隔离的子进程中执行 Python 代码，防止恶意代码危害主 Agent 进程。

**安全加固**：

| 加固层 | 措施 |
|--------|------|
| 进程隔离 | 在临时目录（`tempfile.TemporaryDirectory`）中执行，代码无法访问项目文件 |
| 环境变量清理 | 剥离所有 `API_KEY`/`TOKEN`/`SECRET` 等敏感前缀的环境变量 |
| 网络隔离 | 默认移除 `http_proxy`/`https_proxy` 环境变量，阻止网络请求 |
| 静态预检 | 阻止 `socket`/`subprocess`/`ctypes`/`multiprocessing`/`threading` 模块导入 |
| 进程资源限制 | Unix 下通过 `resource.setrlimit` 限制内存（默认 512MB）和 CPU 时间（默认 30s） |
| 输出截断 | 超过 10000 字符的输出被截断，防止 token 溢出 |

**工具签名**：

```python
@tool(name="execute_code", dangerous=True, toolset="code_execution")
def execute_code(
    code: str,
    timeout: int = 30,         # 最大执行秒数
    max_memory_mb: int = 512,   # 最大内存（Unix only）
    allow_network: bool = False,  # 是否允许网络访问
) -> str
```

**使用示例**：

```
Agent: 执行以下代码计算斐波那契数列前10项
Agent: code="def fib(n): return [fib:=lambda f: [0,1].__setitem__...

Agent: execute_code(code)
[1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
```

**配置**：`code_execution` 工具集默认在 `cli`/`tui`/`api` 平台启用。

## 4.10 任务管理工具（todo）

持久化 Todo 列表，存储在 `~/.Zeloo/todos.json`。

### 4.10.1 工具签名

| 工具 | 签名 | 说明 |
|------|------|------|
| `todo_add` | `(task: str, priority: str = "normal")` | 添加任务，支持 low/normal/high 优先级 |
| `todo_list` | `(show_done: bool = True)` | 列出任务，可过滤已完成 |
| `todo_complete` | `(todo_id: int)` | 标记任务完成 |
| `todo_remove` | `(todo_id: int)` | 删除任务 |

### 4.10.2 数据格式

```json
// ~/.Zeloo/todos.json
[
  {
    "id": 1,
    "task": "完成文档更新",
    "priority": "high",
    "done": false,
    "created_at": 1725700000.0
  }
]
```

## 4.11 定时任务工具（cron）

通过 `cron_add/cron_list/cron_remove` 工具管理定时任务，调度后端为 `cron/scheduler.py` 的 `CronScheduler`。

### 4.11.1 工具签名

| 工具 | 签名 | 说明 |
|------|------|------|
| `cron_add` | `(name: str, expression: str, command: str)` | 注册 cron 任务 |
| `cron_list` | `()` | 列出所有任务 |
| `cron_remove` | `(name: str)` | 删除任务 |

### 4.11.2 cron 表达式

使用标准 5 字段格式：`分 时 日 月 星期`

| 示例 | 含义 |
|------|------|
| `0 9 * * 1-5` | 每周一至周五 9:00 |
| `*/15 * * * *` | 每 15 分钟 |
| `0 0 1 * *` | 每月 1 日午夜 |

字段范围：分(0-59)、时(0-23)、日(1-31)、月(1-12)、星期(0-6)

支持特殊语法：`N-M`（范围）、`N,M`（列表）、`*/N`（步长）

### 4.11.3 CronScheduler 后端

`cron/scheduler.py` 的 `CronScheduler` 类在后台守护线程中运行：

```python
scheduler = CronScheduler(tick_interval=30)  # 每 30s 检查一次
scheduler.add_job("backup", "0 2 * * *", callback=lambda: shell("tar czf backup.tar.gz data/"))
scheduler.start()   # 启动守护线程
scheduler.stop()   # 优雅停止
```

防重复触发：同分钟内同一任务只执行一次（通过 `last_run` 时间戳对比）。

## 4.12 语音工具（voice）

文本转语音（TTS）和语音转文本（STT），后端由 `voice_backend` 配置指定。

### 4.12.1 工具签名

| 工具 | 签名 | 说明 |
|------|------|------|
| `voice_tts` | `(text: str, output_path: str)` | 将文本转为音频并保存 |
| `voice_stt` | `(audio_path: str)` | 将音频文件转录为文本 |

### 4.12.2 后端配置

```yaml
# config.yaml
voice:
  backend: console  # console（无操作）或 openai（TTS + Whisper）
```

`backend` 可选 `console`（默认，不产生实际效果）或 `openai`（调用 OpenAI TTS/Whisper API）。

## 4.13 浏览器自动化工具（browser）

通过 Playwright 控制浏览器，工具集默认在 `cli`/`tui` 平台启用（需安装 `pip install playwright && playwright install chromium`）。

### 4.13.1 工具列表

| 工具 | 签名 | 说明 |
|------|------|------|
| `browser_navigate` | `(url: str)` | 导航到 URL，返回页面标题 |
| `browser_click` | `(selector: str)` | 点击 CSS 选择器匹配的元素 |
| `browser_type` | `(selector: str, text: str)` | 向输入框填写文本 |
| `browser_get_text` | `()` | 获取页面可见文本（body.innerText） |
| `browser_get_html` | `()` | 获取页面完整 HTML |
| `browser_screenshot` | `(path: str = "screenshot.png")` | 截图保存 |
| `browser_evaluate` | `(script: str)` | 在页面上下文执行 JavaScript |
| `browser_back` | `()` | 后退一页 |
| `browser_forward` | `()` | 前进一页 |
| `browser_wait` | `(selector: str = "", timeout: int = 5000)` | 等待元素或超时 |
| `browser_close` | `()` | 关闭浏览器，释放资源 |

### 4.13.2 实现特性

- **单例浏览器上下文**：所有工具共享同一个 Playwright page 实例，保持状态连续性
- **线程安全**：通过 `_browser_lock` 保护浏览器状态
- **超时保护**：每个操作有默认超时（导航 30s）
- **静默失败**：所有浏览器异常被捕获并返回友好错误，不中断 Agent 循环

## 4.14 语音后端（gateway/voice.py）

Voice 后端在 `gateway/voice.py` 中定义，为 Agent 提供统一的 TTS/STT 抽象，不依赖具体实现。

### 4.14.1 后端类型

| 后端 | 说明 | 依赖 |
|------|------|------|
| `console`（默认） | 无操作，写空文件/返回空字符串 | 无 |
| `openai` | OpenAI TTS + Whisper STT | `openai` 包 |

### 4.14.2 VoiceBackend 接口

```python
class VoiceBackend:
    def tts(self, text: str, output_path: str) -> str:
        """将 text 转为语音，保存到 output_path，返回路径。"""
        raise NotImplementedError

    def stt(self, audio_path: str) -> str:
        """将 audio_path 音频文件转录为文本。"""
        raise NotImplementedError
```

### 4.14.3 工厂函数

```python
from gateway.voice import get_voice_backend

backend = get_voice_backend(name="openai", api_key="sk-...")
backend = get_voice_backend(name="console")  # 默认
```

### 4.14.4 OpenAI 后端参数

```python
OpenAIVoice(
    api_key=None,        # 或从 OPENAI_API_KEY 环境变量读取
    base_url=None,       # 可选，用于 OpenAI 兼容 API
    tts_model="tts-1",   # TTS 模型
    tts_voice="alloy",   # 音色
    stt_model="whisper-1",  # STT 模型
)
```

## 4.15 MCP（Model Context Protocol）

### 4.15.1 协议概述

MCP 是一个开放协议，用于在 AI 应用和数据源之间建立双向通信。Zeloo 通过 `mcp_serve.py` 提供 MCP 服务端，支持 stdio 和 HTTP 两种传输方式。

### 4.15.2 传输类型

| 传输 | 说明 | 适用场景 |
|------|------|----------|
| `stdio` | 标准输入输出，进程间通信 | CLI 工具、本地集成 |
| `http` | HTTP 长连接，SSE 事件流 | 远程服务、Web 集成 |

### 4.15.3 启动 MCP 服务

```bash
# stdio 模式
python -m mcp_serve

# HTTP 模式（需要 MCP_SERVER_TRANSPORT=http）
python -m mcp_serve --transport http --port 8765
```

### 4.15.4 MCP 工具注册

通过 `@mcp_tool` 装饰器注册 MCP 工具，工具自动暴露给 MCP 客户端：

```python
from mcp_serve import mcp_tool

@mcp_tool(name="my_tool", description="Do something")
def my_tool(arg: str) -> str:
    return f"Result: {arg}"
```

## 4.16 子代理委托（delegate）

### 4.16.1 委托模型

Zeloo 支持子代理委托，将复杂任务分解给多个 Worker Agent 并行处理。

| 角色 | 权限 | 典型场景 |
|------|------|----------|
| `leaf`（默认） | 无 delegate/clarify/memory | 专注工作者 |
| `orchestrator` | 保留 delegate_task | 任务分解与协调 |

### 4.16.2 委托工具

```python
@tool(name="delegate_task", toolset="delegation")
def delegate_task(
    goal: str,           # 子代理目标
    context: str = "",  # 上下文信息
    role: str = "leaf", # leaf 或 orchestrator
) -> str
```

### 4.16.3 约束参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_workers` | 3 | 最大并发子代理数 |
| `max_depth` | 2 | 最大嵌套深度 |
| `timeout` | 300s | 子代理超时时间 |

### 4.16.4 零知识隔离

子代理仅接收 `goal` + `context`，不包含父代理的完整会话历史，防止信息泄漏。

## 4.17 插件系统（plugins）

### 4.17.1 架构概览

```
plugins/
├── __init__.py         # 包初始化
├── hooks.py           # HookRegistry + HookType 枚举
├── manager.py         # PluginManager（发现/加载/注册）
└── example_plugin.py  # 参考实现
```

### 4.17.2 插件结构

```python
# my_plugin/__init__.py 或 my_plugin.py
from tools.base import tool
from plugins.hooks import HookType

@tool(name="my_tool", description="...", toolset="plugins")
def my_tool(arg: str) -> str:
    return f"hello {arg}"

def register(registry, skills_manager, hooks):
    hooks.register(HookType.PRE_TOOL_CALL, my_callback, "my_plugin")
```

### 4.17.3 PluginManager API

```python
from plugins.manager import PluginManager, PluginInfo

pm = PluginManager(plugin_dirs=["~/.Zeloo/plugins", "./plugins"])

# 加载所有插件
loaded = pm.load_all()

# 按名称获取插件信息
info: PluginInfo = pm.get_plugin("my_plugin")

# 启用/禁用
pm.enable("my_plugin")
pm.disable("my_plugin")

# 列出所有插件
all_plugins = pm.list_plugins()
```

### 4.17.4 HookType 枚举（plugins/hooks.py）

```python
class HookType(StrEnum):
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    ON_SESSION_START = "on_session_start"
    ON_SESSION_END = "on_session_end"
    TRANSFORM_LLM_OUTPUT = "transform_llm_output"
```

### 4.17.5 HookRegistry API

```python
from plugins.hooks import get_hook_registry, HookType

registry = get_hook_registry()

# 注册回调
registry.register(HookType.PRE_TOOL_CALL, my_callback, plugin_name="my_plugin")

# 解除注册
registry.unregister(HookType.PRE_TOOL_CALL, plugin_name="my_plugin")

# 获取钩子总数
count = registry.hook_count
```

### 4.17.6 配置

```yaml
# config.yaml
plugins:
  enabled: true
  dirs:
    - "~/.Zeloo/plugins"
    - "./plugins"
```

