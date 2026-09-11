# 58 · Hermes Agent 前端技术借鉴 + Web 前端最佳技术栈

> 本模块深度借鉴 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 的前端设计，在 Zeloo 项目中实现五项核心功能。
> 原始实现来源：[PR #13379](https://github.com/NousResearch/hermes-agent/pull/13379)，[docs/developer-guide](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)。

## 目录

1. [背景与架构分析](#1-背景与架构分析)
2. [Web 前端技术栈（最佳实践）](#2-web-前端技术栈最佳实践)
3. [Setup Wizard](#3-setup-wizard)
4. [Skin Engine](#4-skin-engine)
5. [TUI 输入历史与 Slash 命令补全](#5-tui-输入历史与-slash-命令补全)
6. [Web Chat Markdown 渲染](#6-web-chat-markdown-渲染)
7. [Web Chat Session 持久化](#7-web-chat-session-持久化)
8. [验证结果](#8-验证结果)

---

## 1. 背景与架构分析

### 1.1 Hermes Agent 项目定位

Hermes Agent（NousResearch）是基于 Nous Research 生态的自托管 AI Agent 运行时，采用**模块化前后端分离**架构：

- **Agent Core**：Python 后端，处理 LLM 调用、工具调度、记忆管理
- **TUI Gateway**：JSON-RPC over stdio / WebSocket，连接 Agent Core 与各前端
- **多前端共存**：CLI（argparse + rich）、TUI（Ink/React）、Web Chat（Vanilla JS + xterm.js + PTY bridge）

### 1.2 Zeloo 与 Hermes Agent 的架构对比

| 维度 | Zeloo | Hermes Agent |
|------|-------|-------------|
| Agent Core | Python async agent | Python async agent |
| Agent Bridge | WebRouterBridge (REST/WebSocket) | tui_gateway (JSON-RPC) |
| CLI | argparse + rich + interactive mode | argparse + skin engine + setup wizard |
| TUI | Textual | Ink/React + xterm.js |
| Web Chat | Vanilla JS + FastAPI | xterm.js + PTY bridge (real TUI in browser) |
| Persistence | SQLite WAL | SQLite WAL |

> **关键发现**：Hermes Agent 的 Web Chat 通过 PTY bridge 将真实 TUI 嵌入浏览器（`ptyprocess.PtyProcess` + `xterm.js`），而 Zeloo 的 Web Chat 采用独立的 WebSocket 流式前端。两者的设计取舍不同——Hermes Agent 追求 TUI 与 Web 共享渲染，Zeloo 追求独立功能丰富的 Web 界面。

### 1.3 借鉴决策

从 Hermes Agent 借鉴了以下**通用最佳实践**（非专利实现），已针对 Zeloo 架构重新实现：

1. **Setup Wizard**：交互式配置引导，TTY 自适应，CI 友好
2. **Skin Engine**：可插拔 CLI 视觉主题，支持用户自定义
3. **TUI Input History**：↑/↓ 历史导航 + 草稿保留
4. **TUI Slash Completion**：前缀过滤的斜杠命令下拉面板
5. **Web Markdown 渲染**：流式文本 + `done` 事件批量渲染
6. **Web Session Persistence**：SQLite WAL 持久化 + probe 检查 + in-memory 回退

---

## 2. Web 前端技术栈（最佳实践）

### 2.1 Zeloo Web 前端现状

Zeloo 目前有 5 个前端入口，各自技术栈如下：

| 前端 | 技术栈 | 状态 | 备注 |
|------|--------|------|------|
| **Landing 页** | 纯 HTML + CSS | ✅ 完整 | 静态营销页，无需框架 |
| **Web Chat** | Vanilla JS + Jinja2（无构建） | ⚠️ 基础可用 | `zeloo_web/static/chat.js`（340 行）|
| **Web Dashboard** | Vanilla JS + Jinja2 SPA（无构建） | ⚠️ 基础可用 | `zeloo_dashboard/`（单页 5 tab）|
| **TUI** | Python Textual | ✅ 完整 | `zeloo_tui/`（Round 55） |
| **CLI** | Python argparse + rich | ✅ 完整 | `cli.py` |

**当前痛点**：Vanilla JS 无构建方案在 Web Chat / Dashboard 达到产品级复杂度后会遇到：

- **无类型安全**：TS 能捕获 API 响应字段错误，Vanilla JS 只有运行时才发现
- **无组件复用**：重复 DOM 操作代码，修改成本高
- **无构建优化**：无法 tree-shaking、code splitting、按需加载
- **无开发体验**：热更新、类型提示、ESLint/Prettier 集成

### 2.2 推荐的 Web 前端技术栈

基于以下原则选型：**成熟稳定、生态丰富、团队熟悉、长期维护**：

#### 2.2.1 推荐方案：Vue 3 + Vite + TypeScript

| 层级 | 技术选型 | 版本 | 说明 |
|------|---------|------|------|
| **框架** | Vue 3（Composition API） | ^3.5 | 渐进式、文档友好、上手快 |
| **构建** | Vite | ^6.0 | 毫秒级 HMR、ESM native、按需编译 |
| **类型** | TypeScript | ^5.6 | 严格类型检查，IDE 全支持 |
| **UI 组件库** | Naive UI | ^2.40 | Vue 3 原生、主题深度定制、组件丰富 |
| **路由** | Vue Router | ^4.5 | SPA 路由，hash 模式适合前后端一体部署 |
| **状态管理** | Pinia | ^2.3 | Vue 3 官方推荐，比 Vuex 轻量 |
| **Markdown 渲染** | marked + highlight.js | — | 流式渲染 + 代码高亮 |
| **HTTP 客户端** | ky | ^1.0 | 轻量、Promise-based、超时/重试内置 |
| **样式** | SCSS + CSS 变量 | — | 复用现有 CSS 变量体系，与 CSS 变量兼容 |
| **测试** | Vitest + Playwright | — | Vite 原生集成、组件级测试 |

> **为什么不选 React？**
>
> Vue 3 的 Composition API 与 Zeloo 现有 Python 代码的"模块化 + dataclass"思维高度一致，团队学习曲线更平缓。Naive UI 比 Ant Design Vue 更轻量、主题配置更灵活，适合需要深度品牌定制的产品。
>
> **为什么不选 Next.js / Nuxt？**
>
> Zeloo 的 Web 前端是**后端渲染 + API 消费**模式（FastAPI 提供 REST + WebSocket），不是 SSR 首屏优先场景。纯 SPA + Vite 更轻量，避免 SSR 复杂度。

#### 2.2.2 备选方案：保持 Vanilla JS（轻量化场景）

对于以下场景，可保持 Vanilla JS 无构建方案：

- **内网 / 工具型页面**：功能固定、不需要复杂交互
- **快速原型验证**：先跑通功能，再决定是否重构
- **极简部署约束**：无 Node.js 环境的受限环境

Vanilla JS 项目的质量底线：
- 使用 ES Modules（`type="module"`）避免全局污染
- 至少使用 JSDoc 类型注解（VS Code 原生支持）
- 外部依赖走 CDN（不要手动下载复制）

#### 2.2.3 迁移策略（渐进式）

不推荐一次性重写，应分阶段迁移：

**Phase 1（立即可做）**：为现有 `chat.js` 添加 TypeScript 类型注解（JS 类型渐进迁移）

```typescript
// chat-types.ts — 先建立类型文件，不改变构建流程
export interface ChatMessage {
  type: "user" | "assistant" | "tool_call" | "tool_result" | "done";
  content?: string;
  toolName?: string;
  model?: string;
  duration?: number;
  tokensIn?: number;
  tokensOut?: number;
}

export interface WebSocketOptions {
  url: string;
  onMessage: (msg: ChatMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
}
```

**Phase 2（3-6 个月）**：新建 `zeloo_web_vue/` 子项目，与旧版并行运行，逐步迁移功能页面

**Phase 3（稳定后）**：废弃 Vanilla JS 版本，旧代码归档

### 2.3 推荐的 Web 前端目录结构（Vue 3 项目）

```
zeloo_web/
├── __init__.py              # FastAPI app factory（保持不变）
├── app.py                   # REST 端点（保持不变）
├── chat_socket.py           # WebSocket 处理器（保持不变）
├── persistence.py           # SQLite 持久化（保持不变）
├── sessions.py              # Session Store（保持不变）
├── cli.py                   # zeloo web 入口（保持不变）
├── static/                  # 后端静态资源（保持不变）
│   ├── chat.js
│   └── style.css
└── templates/               # 后端 Jinja2 模板（保持不变）
    └── chat.html

# ── 新的 Vue 3 前端项目（未来迁移目标）────────────────────────
zeloo_web_ui/                # 独立 npm 项目
├── public/
│   └── favicon.ico
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── router/
│   │   └── index.ts         # Vue Router（chat / dashboard）
│   ├── stores/
│   │   ├── chat.ts          # Pinia：会话状态
│   │   └── auth.ts          # Pinia：认证状态
│   ├── views/
│   │   ├── ChatView.vue     # Web Chat 主页面
│   │   ├── DashboardView.vue # Dashboard 主页面
│   │   └── LoginView.vue    # 登录页
│   ├── composables/
│   │   ├── useWebSocket.ts  # WS 连接复用
│   │   └── useMarkdown.ts   # Markdown 渲染逻辑
│   ├── components/
│   │   ├── ChatMessage.vue  # 消息气泡
│   │   ├── ToolCallCard.vue # 工具调用卡片
│   │   ├── SessionSidebar.vue
│   │   └── CompletionDropdown.vue
│   ├── api/
│   │   └── client.ts        # ky HTTP 客户端
│   └── styles/
│       ├── variables.scss   # CSS 变量定义
│       └── markdown.scss    # Markdown 排版样式
├── index.html
├── vite.config.ts
├── tsconfig.json
└── package.json
```

### 2.4 技术选型决策矩阵

| 维度 | Vanilla JS（现状） | Vue 3 + Vite + TS（推荐） | React + Next.js（备选） |
|------|------------------|--------------------------|------------------------|
| **上手成本** | ⭐⭐⭐⭐⭐ 最低 | ⭐⭐⭐⭐ 中等 | ⭐⭐ 中等偏高 |
| **类型安全** | ⭐ 无 | ⭐⭐⭐⭐⭐ 完整 | ⭐⭐⭐⭐⭐ 完整 |
| **组件复用** | ⭐ 无 | ⭐⭐⭐⭐⭐ 高 | ⭐⭐⭐⭐⭐ 高 |
| **构建产物** | ⭐⭐⭐⭐⭐ 最优（无构建） | ⭐⭐⭐⭐ 良好 | ⭐⭐⭐ 中等 |
| **生态丰富度** | ⭐⭐⭐ 依赖 CDN | ⭐⭐⭐⭐⭐ 丰富 | ⭐⭐⭐⭐⭐ 丰富 |
| **学习曲线** | ⭐⭐⭐⭐⭐ 最平缓 | ⭐⭐⭐⭐ 平缓 | ⭐⭐⭐ 较陡 |
| **维护成本** | ⭐⭐ 随复杂度增加 | ⭐⭐⭐⭐⭐ 长期低 | ⭐⭐⭐⭐ 长期中 |
| **适合场景** | 工具页/原型 | **产品级 Web UI** | SSR 优先场景 |

**结论**：Web Chat 和 Web Dashboard 应迁移至 **Vue 3 + Vite + TypeScript**。TUI、CLI、Landing 页保持现有方案。

### 2.5 开发规范（Web 前端）

所有 Web 前端代码必须遵循：

- **TypeScript 严格模式**：`strict: true`，禁止 `any` 类型
- **ESLint + Prettier**：提交前检查，CI 强制执行
- **组件规范**：SFC（单文件组件），`<script setup lang="ts">` 语法
- **样式规范**：CSS 变量定义在 `:root`，禁止行内样式（`style=` 属性），优先使用 BEM 命名
- **无障碍（a11y）**：所有交互元素有 `aria-label`，键盘可访问，对比度符合 WCAG AA
- **性能指标**：LCP < 2.5s，FID < 100ms，CLS < 0.1（Google Core Web Vitals）

---

## 3. Setup Wizard

### 3.1 需求来源

Hermes Agent 的 `setup.py` 提供交互式初始化流程，Zeloo 需要类似的**首次启动引导**，覆盖 Provider 选择、API Key 配置、功能开关。

### 3.2 设计实现

**文件**：[zeloo_cli/setup_wizard.py](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo_cli/setup_wizard.py)

**核心组件**：

- `PROVIDER_CATALOG`：6 家 Provider 的元数据（default_model, env_var, models, label）
- `WizardAnswers`：配置答案 dataclass
- `run_setup_wizard(home, ask, isatty)`：TTY 自适应入口
- `apply_wizard_answers(answers, home, overwrite)`：写入 config.yaml + .env
- `run_setup()`：CLI 入口点

**TTY 自适应策略**（Hermes Agent 模式）：

```python
# 非 TTY 模式：CI / Docker / 程序化调用 → 返回默认值
if not isatty:
    return WizardAnswers(
        provider="openai", model=None, api_key=None, base_url=None,
        max_iterations=100, temperature=0.7,
        enable_memory=True, enable_skills=True, enable_mcp=False,
    )

# TTY 模式：交互式 prompts（使用 rich 或 fallback 到 input()）
```

**Provider 目录**：

| Provider | 模型列表 | 环境变量 |
|----------|---------|---------|
| openai | gpt-4o, gpt-4o-mini, gpt-4-turbo | `OPENAI_API_KEY` |
| anthropic | claude-sonnet-4-20250514, claude-3-5-sonnet-latest | `ANTHROPIC_API_KEY` |
| xai | xai-grok-2-1212, xai-grok-2-vision-1212 | `XAI_API_KEY` |
| openrouter | openrouter/auto + 100+ 模型 | `OPENROUTER_API_KEY` |
| deepseek | deepseek-chat, deepseek-reasoner | `DEEPSEEK_API_KEY` |
| google | gemini-2.0-flash-exp, gemini-1.5-flash | `GOOGLE_API_KEY` |

**配置写入逻辑**（加性合并）：

- `config.yaml`：覆盖 agent.provider / agent.model / agent.max_iterations / agent.temperature
- `.env`：追加 `ANTHROPIC_API_KEY=xxx` 等 Provider API Key
- `--overwrite` 标志：允许完全覆盖已有配置（默认拒绝保护已有配置）

### 3.3 CLI 集成

**文件**：[cli.py](file:///c:/Users/38324/OneDrive/Desktop/primus/cli.py)

```bash
zeloo setup [--overwrite] [--json] [--home PATH]
zeloo skin list | skin show [--name SKIN] | skin set KEY VALUE
```

---

## 4. Skin Engine

### 4.1 需求来源

Hermes Agent 的 `skin_engine.py` 提供可插拔 CLI 视觉主题，Zeloo 需要类似能力让用户自定义 CLI 提示符颜色、Banner 图形、状态图标。

### 4.2 设计实现

**文件**：[zeloo_cli/skin_engine.py](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo_cli/skin_engine.py)

**Skin 数据结构**：

```python
@dataclass
class Colors:
    banner_fg: str = "cyan"
    banner_bg: str = ""
    prompt: str = "green"
    user: str = "blue"
    assistant: str = "yellow"
    tool: str = "magenta"
    error: str = "red"
    success: str = "green"
    warning: str = "yellow"

@dataclass
class Banner:
    line1: str = "⚡ Zeloo"
    line2: str = "  Agent"

@dataclass
class Prompt:
    symbol: str = "❯"
    continuation: str = "  "

@dataclass
class TuiAccent:
    info: str = "blue"
    event: str = "cyan"
    tool: str = "magenta"
    billing: str = "yellow"
    error: str = "red"

@dataclass
class Skin:
    name: str
    colors: Colors
    banner: Banner
    prompt: Prompt
    tui_accent: TuiAccent
```

**内置主题（4 个）**：

| 皮肤 | 提示符 | 主色调 | 适用场景 |
|------|--------|--------|---------|
| `default` | ❯ | 绿色 | 默认生产使用 |
| `plain` | >>> | 无色 | 日志/CI/无色彩终端 |
| `starlight` | ⭐ | 紫色 | 暗色终端 |
| `solarized` | ☀ | 暖黄 | 护眼长时间使用 |

**用户主题覆盖**：用户文件 `$ZELOO_HOME/skins/{name}.yaml` 覆盖内置主题。

**渲染函数**：

- `render_banner(skin)`：输出 ANSI 彩色 Banner（可禁用色彩用于日志）
- `render_prompt(skin)`：返回提示符字符串（`❯ ` 或 `>>> ` 等）
- `render_status(level, msg, skin)`：INFO / WARN / ERROR / DEBUG 状态行
- `set_skin_value(key, value, skin_name)`：点路径写入（`colors.prompt = "magenta"`）

**缓存策略**：加载后缓存于模块级 `LoadedSkin`，调用 `reset_skin_cache()` 清除。

### 4.3 CLI 集成

在 `interactive_mode()` 中调用 `render_banner()` 和 `render_prompt()`，fallback 到硬编码字符串（如果皮肤加载失败）。

---

## 5. TUI 输入历史与 Slash 命令补全

### 5.1 需求来源

Hermes Agent 的 TUI 使用 `useInputHistory` hook（↑/↓ 历史导航 + 草稿保留）和 `useCompletion` hook（`/` 触发斜杠命令下拉）。Zeloo 的 Textual TUI 需要同等体验。

### 5.2 设计实现

**文件**：[zeloo_tui/history.py](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo_tui/history.py)

**InputHistory 算法**（Hermes Agent 的 cursor semantics 模式）：

```python
@dataclass
class InputHistory:
    entries: list[str] = field(default_factory=list)  # 历史条目（最新在末尾）
    cursor: int = -1                                   # -1=编辑草稿, 0..N=历史索引
    draft: str = ""                                    # 退出历史时的草稿文本
    max_size: int = 500

    def up(self, current_text: str) -> str | None:
        if not self.entries:
            return None
        if self.cursor == -1:
            self.draft = current_text          # 首次按 ↑ → 保存草稿
        if self.cursor < len(self.entries) - 1:
            self.cursor += 1
        return self.entries[-(self.cursor + 1)]

    def down(self, current_text: str) -> str | None:
        if self.cursor > -1:
            self.cursor -= 1
            if self.cursor == -1:
                return self.draft              # 返回草稿
            return self.entries[-(self.cursor + 1)]
        return None
```

**去重与过滤**：
- `push(line)`：跳过纯空白行，连续相同内容去重，上限 500 条
- `reset()`：清空历史

**Slash 命令目录**：

```python
SLASH_COMMANDS: list[SlashCommand] = [
    SlashCommand(name="/help",     description="显示帮助信息"),
    SlashCommand(name="/model",    description="切换模型"),
    SlashCommand(name="/session",  description="查看当前会话信息"),
    SlashCommand(name="/review",   description="触发代码审查"),
    SlashCommand(name="/plugins",  description="查看已加载插件"),
    SlashCommand(name="/stats",    description="显示运行统计"),
    SlashCommand(name="/clear",    description="清屏"),
    SlashCommand(name="/skin",     description="切换皮肤主题"),
]
```

**前缀过滤**：`filter_slash_commands(query)` — 大小写不敏感前缀匹配。

**Textual 绑定集成**：`make_history_handlers(widget, history)` 返回 `(on_up, on_down)` 函数，注入到 Textual 的 `BINDINGS`：

```python
KEYBOARD_BINDINGS = [
    Binding("up",   "history_up",    "History up",   show=False),
    Binding("down", "history_down",  "History down", show=False),
    Binding("escape", "dismiss_completion", "", show=False),
]
```

### 5.3 TUI 补全面板

**文件**：[zeloo_tui/app.py](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo_tui/app.py)

- `#completion` 覆盖层：绝对定位的下拉面板，最多显示 4 条匹配命令
- `on_input_changed()`：每次击键过滤 SLASH_COMMANDS，刷新补全面板
- `on_input_submitted()`：推送内容到历史 + 镜像到 EventLog
- `action_dismiss_completion()`：ESC 关闭补全面板

---

## 6. Web Chat Markdown 渲染

### 6.1 需求来源

Hermes Agent 的 Web Chat 在流式输出时将文本以纯文本方式实时推送，在 `done` 事件时批量渲染 Markdown（感知延迟更小）。Zeloo 需要类似的 Markdown 渲染能力。

### 6.2 设计实现

**Markdown 渲染库**：marked.js（[CDN v13.0.3](https://cdn.jsdelivr.net/npm/marked@13.0.3/marked.min.js)）

**文件**：[zeloo_web/templates/chat.html](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo_web/templates/chat.html)

```html
<script src="https://cdn.jsdelivr.net/npm/marked@13.0.3/marked.min.js" defer></script>
```

**JS 工具函数**：[zeloo_web/static/chat.js](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo_web/static/chat.js)

```javascript
// 转义 HTML 特殊字符
function escapeHtml(s) { ... }

// 渲染 Markdown（调用 marked.parse，失败时回退到 escapeHtml）
function renderMarkdown(text) {
    if (typeof marked !== 'undefined') {
        return marked.parse(text);
    }
    return escapeHtml(text);
}

// DOM TreeWalker 白名单净化（防止 XSS）
function sanitizeHtml(html) {
    const allowed = new Set(['P','BR','B','I','EM','STRONG','A','CODE','PRE',
                             'H1','H2','H3','H4','UL','OL','LI','BLOCKQUOTE',
                             'HR','TABLE','THEAD','TBODY','TR','TH','TD','DIV','SPAN']);
    const allowedAttrs = new Set(['href','title','target','rel']);
    // 拒绝 javascript: URL
    ...
}
```

**Markdown CSS**：[zeloo_web/static/style.css](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo_web/static/style.css)

```css
.message .body { font-size: 14px; line-height: 1.7; }
.message .body h1 { font-size: 1.4em; margin: 1em 0 0.4em; }
.message .body h2 { font-size: 1.2em; }
.message .body code { background: var(--code-bg); padding: 2px 6px; border-radius: 4px; }
.message .body pre  { white-space: pre; overflow-x: auto; background: var(--code-bg); padding: 12px; border-radius: 6px; }
.message .body blockquote { border-left: 3px solid var(--border); padding-left: 12px; color: var(--muted); }
```

**渲染策略**（Hermes Agent 模式）：

1. **流式阶段**：内容以纯文本追加到 `activeStreamBuffer`（感知延迟最小）
2. **`done` 事件**：调用 `renderMarkdown()` 一次性渲染完整 Markdown 响应
3. **`tool_call` 事件**：保持工具调用原始格式（`innerText`）

---

## 7. Web Chat Session 持久化

### 7.1 需求来源

Hermes Agent 使用 SQLite WAL 持久化对话历史。Zeloo 需要在服务器重启后保留对话记录。

### 7.2 设计实现

**文件**：[zeloo_web/persistence.py](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo_web/persistence.py)

**存储位置**：`$ZELOO_HOME/web_chat.db`（SQLite WAL 模式）

**数据库 schema**：

```sql
CREATE TABLE chat_sessions (
    id        TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE chat_messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,      -- 'user' | 'assistant' | 'tool_call' | 'tool_result'
    content    TEXT NOT NULL,
    model      TEXT,
    duration   REAL,
    tokens_in  INTEGER,
    tokens_out INTEGER,
    timestamp  REAL NOT NULL
);
```

**Probe 检查模式**（Hermes Agent 风格）：

```python
def _default_session_store():
    # 1. 环境变量绕过
    if os.environ.get("zeloo_WEB_CHAT_INMEMORY") == "1":
        return ChatSessionStore()

    # 2. Probe 检查 SQLite 可写性
    try:
        test_path = os.path.join(get_zeloo_home(), "web_chat.db")
        conn = _connect(test_path)
        conn.execute("CREATE TABLE IF NOT EXISTS _probe (id INTEGER)")
        conn.execute("DROP TABLE _probe")
        conn.close()
    except Exception:
        return ChatSessionStore()   # 不可写 → 回退到 in-memory

    # 3. 使用 PersistentChatSessionStore
    return PersistentChatSessionStore(test_path)
```

**双写策略**：内存存储 + SQLite WAL 同步写入，重启后可从磁盘恢复。

**消息类型支持**：
- `user`：用户消息
- `assistant`：助手回复（支持 Markdown 内容）
- `tool_call`：工具调用（包含 tool_name / arguments）
- `tool_result`：工具结果（包含 result 摘要）

---

## 8. 验证结果

### 8.1 Lint 检查

```bash
ruff check zeloo_cli/setup_wizard.py zeloo_cli/skin_engine.py \
           zeloo_tui/history.py zeloo_tui/app.py \
           zeloo_tui/widgets/event_log.py zeloo_web/persistence.py \
           zeloo_web/app.py zeloo_web/__init__.py cli.py \
           tests/unit/test_hermes_inspired.py
# All checks passed!
```

### 8.2 单元测试

| 测试集 | 用例数 | 结果 |
|--------|--------|------|
| `test_hermes_inspired.py` — WizardAnswers | 3 | ✅ |
| `test_hermes_inspired.py` — SetupWizardNonInteractive | 4 | ✅ |
| `test_hermes_inspired.py` — SkinEngine | 7 | ✅ |
| `test_hermes_inspired.py` — InputHistory | 7 | ✅ |
| `test_hermes_inspired.py` — Completion | 5 | ✅ |
| `test_hermes_inspired.py` — PersistentChatSessionStore | 5 | ✅ |
| `test_web_chat.py`（回归） | 16 | ✅ |
| `test_dashboard.py`（回归） | 32 | ✅ |
| **总计** | **80** | **80/80 ✅** |

### 8.3 关键设计决策回顾

| 决策 | Hermes Agent 原始方案 | Zeloo 落地方案 | 选型理由 |
|------|----------------------|--------------|---------|
| TTY 模式检测 | `sys.stdin.isatty()` | 显式传入 `isatty` 参数 | 便于测试覆盖 |
| 非 TTY 默认值 | 部分必需交互 | 全套默认值 + 最小化交互 | CI/CD 友好 |
| Skin 持久化 | 写入 `~/.config/hermes/` | 写入 `$ZELOO_HOME/skins/` | 复用 Zeloo 目录规范 |
| TUI History 大小 | 未披露 | max_size=500，ring buffer | 防止内存泄漏 |
| Markdown 渲染 | 流式逐字渲染 | 流式纯文本 + done 批量渲染 | 感知延迟优化 |
| SQLite 路径 | 未披露 | `$ZELOO_HOME/web_chat.db` | 统一数据目录 |
| Persistence probe | 未披露 | create+delete 探针检查 | 避免服务器启动失败 |

---

## 相关文档

- [docs/10-roadmap.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/10-roadmap.md) — §10.28 同步
- [docs/56-web-chat-ui.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/56-web-chat-ui.md) — Web Chat UI 实现
- [docs/57-web-dashboard.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/57-web-dashboard.md) — Web Dashboard 实现
- [docs/54-frontend-audit.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/54-frontend-audit.md) — 前端完成度审计
- [AGENTS.md](file:///c:/Users/38324/OneDrive/Desktop/primus/AGENTS.md) — 工作区规范
