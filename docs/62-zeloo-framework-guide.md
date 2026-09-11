# 62 · Zeloo 框架深度解析

> 路径：`c:\Users\38324\OneDrive\Desktop\primus\zeloo`
> 名称：`zeloo`（基于 hermes-desktop 0.7.7 二次定制）
> 架构：Electron 44 + React 19 + TypeScript 5 + Tailwind CSS 4 + Three.js

---

## 1. 项目元数据

### 1.1 package.json 关键字段

| 项 | 值 |
|----|----|
| `name` | `zeloo` |
| `version` | `0.1.0` |
| `description` | "Zeloo — 自托管、自进化的常驻型 AI Agent 运行时" |
| `author` | Zeloo Project |
| `main` | `./out/main/index.js`（Electron 主进程入口） |
| `homepage` | https://github.com/zeloo/zeloo |

### 1.2 关键依赖（生产）

| 包 | 版本 | 用途 |
|-----|------|------|
| `electron` | ^44.1.1 | 桌面运行时 |
| `react` | ^19.2.1 | UI 框架 |
| `react-dom` | ^19.2.1 | DOM 渲染 |
| `react-router` | (路由) | 屏幕级路由 |
| `@radix-ui/react-dialog` | ^1.1.17 | 无障碍对话框 |
| `@react-three/fiber` + `@react-three/drei` | ^9.5.0 / ^10.7.7 | 3D 场景（Office） |
| `react-markdown` | ^10.1.0 | Markdown 渲染 |
| `react-syntax-highlighter` | ^16.1.1 | 代码高亮 |
| `remark-gfm` | ^4.0.1 | GitHub 风格 Markdown |
| `react-i18next` + `i18next` | ^15.7.3 / ^25.6.0 | 国际化（12 语言） |
| `better-sqlite3` | ^13.0.3 | 本地 SQLite（session、credential、profile） |
| `ws` | ^8.20.0 | WebSocket 客户端（gateway 桥接） |
| `ethers` | ^6.17.0 | 钱包/链上交互 |
| `motion` | ^12.40.0 | 动效 |
| `lucide-react` | ^1.7.0 | 图标 |
| `date-fns` | ^4.4.0 | 日期处理 |
| `border-beam` | ^1.3.0 | 装饰效果 |
| `electron-updater` | ^6.8.9 | 自动更新 |

### 1.3 devDependencies

| 包 | 用途 |
|-----|------|
| `electron-vite` ^5.0.0 | 三进程构建工具 |
| `vite` ^7.2.6 | 渲染层构建 |
| `typescript` ^5.9.3 | 类型检查 |
| `tailwindcss` ^4.2.2 | 样式 |
| `vitest` ^4.1.4 | 测试 |
| `playwright` ^1.60.0 | E2E |
| `eslint` ^9.39.1 + `prettier` ^3.7.4 | 代码规范 |

---

## 2. 项目结构

```
zeloo/
├── src/
│   ├── main/              # Electron 主进程（Node.js + Electron API）
│   │   ├── index.ts        # 入口
│   │   ├── app/
│   │   │   ├── start.ts    # 主进程启动 / BrowserWindow 创建
│   │   │   ├── menu.ts     # 原生菜单栏
│   │   │   ├── context-menu.ts  # 右键菜单
│   │   │   └── updater.ts  # electron-updater 自动更新
│   │   ├── ipc/
│   │   │   └── register.ts # 注册所有 IPC handler（200+）
│   │   ├── config.ts       # 连接配置（local/remote/ssh）
│   │   ├── secrets/        # 凭据管理（命令提供器/环境提供器）
│   │   ├── hermes.ts       # Zeloo CLI 包装（chat、doctor、update）
│   │   ├── dashboard.ts    # 内置 Dashboard 进程
│   │   ├── session-cache.ts / session-location-store.ts / ...
│   │   ├── ssh-tunnel.ts / ssh-remote.ts / ssh-docker.ts
│   │   ├── profiles.ts / providers.ts / model-discovery.ts
│   │   ├── kanban.ts / cronjobs.ts / media.ts / soul.ts / ...
│   │   └── gpu-fallback.ts # GPU 崩溃保护
│   │
│   ├── preload/            # 预加载脚本（contextBridge 安全网关）
│   │   ├── index.ts         # 主预加载（导出 hermesAPI / electron）
│   │   └── askpass.ts       # SSH 密码输入辅助
│   │
│   ├── renderer/          # 渲染进程（React UI）
│   │   └── src/
│   │       ├── App.tsx           # 顶层路由（splash → welcome/install/setup/main）
│   │       ├── main.tsx          # ReactDOM.createRoot
│   │       ├── components/       # 通用组件（I18nProvider、Modal、Settings）
│   │       ├── hooks/            # useChatScroll、useVoiceInput 等
│   │       ├── screens/          # 顶级屏幕
│   │       │   ├── Welcome/Install/Setup/Chat/Agents/Skills/Sessions/...
│   │       │   ├── Gateway/  # 远程 gateway 状态
│   │       │   ├── Kanban/   # 看板
│   │       │   ├── Memory/   # 记忆管理
│   │       │   ├── Office/   # 3D 办公室
│   │       │   │   └── office3d/   # Three.js 场景 + agent AI
│   │       │   ├── Providers/Schedules/Tools/Soul/Discover/SplashScreen/
│   │       ├── shared/         # 但实际位于 src/shared/
│   │       └── utils/
│   │
│   └── shared/            # 主/渲染进程共享 TypeScript 类型
│       ├── i18n/            # i18next 配置 + 12 套 locale 文件
│       │   └── locales/{en,zh-CN,zh-TW,ja,es,ar,he,id,pl,pt-BR,pt-PT,tr}/
│       ├── chat-stream.ts   # 流式聊天事件类型
│       ├── account.ts / agent-capabilities.ts / agent-sync.ts
│       ├── attachments.ts / model-override.ts / ...
│       ├── registry.ts       # 跨进程注册表
│       └── wallets.ts / tokens.ts / ...
│
├── build/                 # electron-builder 资源（icon、entitlements、Linux 安装脚本）
├── resources/              # 应用资源（icon.png、icon.ico、icon.icns）
├── lat.md/                # 知识图谱（lat.md 格式）
├── scripts/                # 探针、E2E 脚本、SSH 远程实验室、Docker Compose
├── .agents / .claude / .codex  # 代理技能定义
├── docs/                   # SSH 隧道、聊天对账、远程访问实验文档
│
├── electron.vite.config.ts  # 三进程 Vite 配置
├── electron-builder.yml     # 打包配置
├── tsconfig.node.json / tsconfig.web.json
├── eslint.config.mjs / .prettierrc / .gitignore
└── package.json
```

---

## 3. 三进程架构（Electron 模型）

```
┌──────────────────────── BrowserWindow ────────────────────────┐
│ Renderer Process (React 19 + TypeScript)                       │
│  ├─ App.tsx → 路由（splash / welcome / install / setup / main）│
│  ├─ screens/* → 顶级屏幕（Chat / Agents / Skills / Sessions…） │
│  ├─ components/* → 通用组件（I18nProvider、ThemeProvider）     │
│  └─ 共享：src/shared/i18n/locales/*（12 套语言包）               │
│                                                                │
│      ┌─── contextBridge (安全网关) ───┐                         │
│      │   window.hermesAPI              │                        │
│      │   window.electron               │                        │
│      └─────────────────────────────────┘                        │
└─────────────────────────────────┬──────────────────────────────┘
                                  │ ipcRenderer.invoke()
                                  │ ipcRenderer.on()
                                  ▼
┌──────────────────────── Preload Script ────────────────────────┐
│ src/preload/index.ts                                          │
│  ├─ 定义 hermesAPI（200+ RPC 方法）                            │
│  └─ contextBridge.exposeInMainWorld("hermesAPI", hermesAPI)   │
└─────────────────────────────────┬──────────────────────────────┘
                                  │ ipcMain.handle()
                                  ▼
┌──────────────────────── Main Process ──────────────────────────┐
│ src/main/index.ts → startMainProcess()                        │
│  ├─ app/start.ts 创建 BrowserWindow + 加载 preload             │
│  ├─ ipc/register.ts 注册 200+ IPC handler                       │
│  ├─ hermes.ts 调用 `zeloo` CLI 子进程（chat / doctor / update）│
│  ├─ dashboard.ts 启动内置 dashboard (FastAPI/Uvicorn 子进程)   │
│  ├─ ssh-tunnel.ts / ssh-remote.ts SSH 远程连接                  │
│  ├─ secrets/* 凭据管理（Keychain / Windows Credential Manager）│
│  ├─ profiles.ts / providers.ts / model-discovery.ts            │
│  └─ config.ts 连接模式（local / remote / ssh）                  │
│                                                                │
│      ┌──────────── 子进程管理 ──────────┐                       │
│      │  1. zeloo CLI（chat/doctor）      │                       │
│      │  2. 内置 dashboard HTTP server    │                       │
│      │  3. WebSocket /ws/dashboard       │                       │
│      │  4. Claw3D dev server（可选）     │                       │
│      └────────────────────────────────────┘                       │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. IPC 桥接层（200+ RPC）

### 4.1 preload/index.ts 注册的 `hermesAPI` 方法

| 分类 | 方法数 | 代表方法 |
|------|--------|---------|
| 安装 / 升级 | 10 | `checkInstall` / `verifyInstall` / `startInstall` / `inspectInstallTarget` |
| 引擎 / 能力 | 6 | `getHermesVersion` / `refreshHermesVersion` / `getAgentCapabilities` |
| OAuth 登录 | 8 | `oauthLogin` / `cancelOAuthLogin` / `getOAuthProviderStatuses` |
| Hermes 账户 | 6 | `accountLogin` / `getAccount` / `ensureHermesOneKey` / `getHermesOneCredits` |
| 聊天流式 | 8 | `sendMessage` / `abortChat` / `onChatChunk` / `onChatDone` / `onChatUsage` / `onClarifyRequest` |
| Gateway 控制 | 6 | `startGateway` / `stopGateway` / `restartGateway` / `gatewayStatus` / `startDashboard` / `stopDashboard` |
| Platform Toggles | 4 | `getPlatformEnabled` / `setPlatformEnabled` / `getMessagingPlatforms` / `testMessagingPlatform` |
| Sessions | 8 | `listSessions` / `getSessionMessages` / `searchSessions` / `updateSessionTitle` / `deleteSessions` |
| Profiles | 10 | `listProfiles` / `createProfile` / `setActiveProfile` / `setProfileColor` / `setProfileName` / `setProfileAvatar` |
| Memory / Soul | 5 | `readMemory` / `addMemoryEntry` / `writeSoul` / `resetSoul` |
| Wallets | 8 | `listWallets` / `syncWallets` / `getWalletPortfolio` / `createWallet` / `getTokenBalances` |
| Models | 8 | `listModels` / `addModel` / `removeModel` / `discoverProviderModels` |
| Skills | 5 | `listInstalledSkills` / `installSkill` / `uninstallSkill` |
| MCP | 10 | `listMcpServers` / `addMcpServer` / `testMcpServer` / `listMcpCatalog` |
| Kanban | 12 | `kanbanListBoards` / `kanbanCreateTask` / `kanbanAssignTask` / `kanbanCompleteTask` |
| Cron Jobs | 5 | `listCronJobs` / `createCronJob` / `pauseCronJob` / `triggerCronJob` |
| Updates | 5 | `checkForUpdates` / `downloadUpdate` / `installUpdate` / `setAutoUpgradeEnabled` |
| Connection | 15 | `setConnectionConfig` / `testRemoteConnection` / `startSshTunnel` / `provisionSshDockerTarget` |
| Media | 4 | `readMediaFile` / `saveMediaFile` / `getPathForFile` / `stageAttachment` |
| 注册表 / 市场 | 5 | `fetchRegistry` / `fetchModelRegistry` / `installRegistryItem` |
| Claw3D | 8 | `claw3dStatus` / `claw3dSetup` / `claw3dStartAll` / `claw3dStartDev` |
| 杂项 | 10 | `getLogs` / `runHermesBackup` / `runHermesImport` / `kanbanDispatchOnce` / `copyToClipboard` |

### 4.2 消息通道（ipcRenderer.on）

| 事件 | 触发场景 |
|------|---------|
| `chat-chunk` / `chat-reasoning-chunk` / `chat-done` / `chat-error` | 流式聊天 |
| `chat-tool-progress` / `chat-tool-event` / `chat-usage` | 工具调用进度 + 用量 |
| `chat-clarify-request` | Agent 询问澄清（inline card） |
| `install-progress` / `claw3d-setup-progress` / `oauth-login-progress` | 安装进度流 |
| `agent-sync-updated` / `model-library-changed` / `custom-providers-changed` | 数据同步通知 |
| `update-available` / `update-download-progress` / `update-downloaded` | 自动更新 |
| `connection-config-changed` | 远程连接变更 |
| `context-menu-copy-chat` / `context-menu-select-bubble` | 右键菜单 |
| `menu-new-chat` / `menu-search-sessions` | 原生菜单事件 |

---

## 5. 配置清单

### 5.1 electron-builder.yml

```yaml
appId: com.zeloo.agent
productName: Zeloo
directories:
  buildResources: build
files:
  - "!src/*"
  - "!{.env,.env.*,.npmrc}"
  - "!{tsconfig.json,tsconfig.node.json,tsconfig.web.json}"
asarUnpack:
  - resources/**
  - node_modules/better-sqlite3/prebuilds/*.node
win:
  executableName: hermes-agent
  target:
    - nsis         # NSIS 安装包（一键安装）
    - portable     # 便携版
portable:
  artifactName: ${name}-${version}-portable.${ext}
nsis:
  artifactName: ${name}-${version}-setup.${ext}
  shortcutName: ${productName}
  createDesktopShortcut: always
  oneClick: true
  perMachine: false
npmRebuild: false
# publish 已删除（避免 schema 校验 + 避免网络调用）
```

### 5.2 electron.vite.config.ts

- **main**：`build.rollupOptions.external = ["better-sqlite3"]`（native 模块不打包）
- **preload**：`rollupOptions.input` = `index` + `askpass`（两个入口）
- **renderer**：`port = HERMES_DESKTOP_RENDERER_PORT || 0`，plugins = `[react(), tailwindcss()]`
- **resolve.dedupe**：`["three"]`（避免 Three.js 多实例冲突）

### 5.3 tsconfig 矩阵

| 文件 | 编译目标 | 包含 |
|------|---------|------|
| `tsconfig.json` | Project References | `app.json` + `node.json` |
| `tsconfig.web.json` | ESNext / DOM / Vite client | `src/renderer/src/**` |
| `tsconfig.node.json` | ES2023 / Node 22 | `src/main/**` `src/preload/**` `src/shared/**` `electron.vite.config.ts` |

### 5.4 环境变量（运行时）

| 变量 | 用途 |
|------|------|
| `HERMES_DESKTOP_APP_NAME` | 应用名（覆盖默认值 "Hermes One"） |
| `HERMES_OPEN_DEVTOOLS=1` | 启动时打开 DevTools |
| `HERMES_DESKTOP_OPEN_DEVTOOLS=1` | 同上 |
| `ENABLE_CDP=1` | 启用 Chrome DevTools Protocol 远程调试 |
| `CDP_PORT` | CDP 端口（默认 9222） |
| `HERMES_DESKTOP_RENDERER_PORT` | Renderer 端口（dev 用） |
| `HERMES_HOME` | Zeloo 数据目录（被 main 进程读取） |

---

## 6. 屏幕级 UI 架构

### 6.1 顶层路由（App.tsx）

```
splash (3000ms 启动动画)
  └─ welcome   (未安装 / 未配置时)
       └─ installing  (一键安装)
            └─ setup    (Provider / 模型配置)
                 └─ main  (主界面 = Layout)
                      ├─ Chat
                      ├─ Agents
                      ├─ Skills
                      ├─ Sessions
                      ├─ Memory
                      ├─ Office (3D)
                      ├─ Gateway
                      ├─ Kanban
                      ├─ Tools
                      ├─ Providers
                      ├─ Schedules
                      ├─ Soul
                      ├─ Settings (modal)
                      └─ ...
```

### 6.2 主界面 Layout

```
┌─ Sidebar ─┬─ Topbar ──────────────────────────────────────┐
│  ⚡ Logo   │  🔍 Search sessions   👤 Profile   ⚙ Settings │
│  Chat     ├──────────────────────────────────────────────────┤
│  Agents   │                                                  │
│  Skills   │            Screen Content                       │
│  Sessions │            (Chat / Agents / Skills …)            │
│  Memory   │                                                  │
│  Office   │                                                  │
│  Kanban   │                                                  │
│  ...      │                                                  │
└──────────┴──────────────────────────────────────────────────┘
```

### 6.3 关键屏幕组件

| 屏幕 | 路径 | 核心组件 | 关键能力 |
|------|------|---------|---------|
| Chat | `screens/Chat/` | `Chat.tsx`、`ChatInput.tsx`、`MessageRow.tsx` | 流式 token + reasoning 双通道 |
| Agents | `screens/Agents/` | `Agents.tsx` | Agent 列表 + 同步到云端 |
| Skills | `screens/Skills/` | `Skills.tsx` | 已安装 + 待安装 + 详情 |
| Sessions | `screens/Sessions/` | `Sessions.tsx` | 会话列表 + 搜索 + 缓存 |
| Memory | `screens/Memory/` | `Memory.tsx`、`MemoryEntries.tsx` | 长/短期记忆 CRUD |
| Office | `screens/Office/` | `Office3D.tsx` | Three.js 场景 + AI agent |
| Gateway | `screens/Gateway/` | `Gateway.tsx` | 远程 gateway 状态 |
| Kanban | `screens/Kanban/` | `Kanban.tsx` | 看板任务管理 |
| Setup | `screens/Setup/` | `Setup.tsx` | 首次配置向导 |

---

## 7. 子进程拓扑

### 7.1 main 进程直接管理

- **Zeloo CLI 子进程**：`src/main/hermes.ts` 通过 `child_process.spawn` 启动 `zeloo chat` / `zeloo doctor`
  - **流式 stdout** 解析：正则提取 token / reasoning / tool_event 事件
  - **生命周期**：每次 `sendMessage` 启动，结束自动 kill

- **Dashboard 子进程**：`src/main/dashboard.ts`
  - 内置 FastAPI/Uvicorn server
  - 通过 `localhost:<port>` + WebSocket `/ws/dashboard` 桥接到 Renderer
  - 启动 / 停止 / 重启由 IPC 控制

- **SSH tunnel 子进程**：`src/main/ssh-tunnel.ts`
  - 通过 `ssh -L localPort:remoteHost:remotePort` 建立本地端口转发
  - 用户通过 `testSshConnection` / `startSshTunnel` IPC 控制

- **Claw3D dev server**：`src/main/claw3d.ts`
  - 可选：Three.js + 3D 办公室场景
  - 通过 WS URL + HTTP API 与 Adapter 通信

### 7.2 凭据提供器（分层架构）

```
┌─────────────────────────── secrets/ ──────────────────────────┐
│ index.ts (统一入口)                                            │
│  ├─ Provider[] = [                                            │
│  │   ├─ commandProvider.ts (从 shell `env` 命令读取)          │
│  │   ├─ envProvider.ts (从 process.env 直接读取)              │
│  │   └─ (未来扩展) Windows Credential Manager / Keychain     │
│  └─ getSecretsProvider() 懒加载选择优先级                       │
│     - command 优先 → env fallback → 返回 undefined            │
└───────────────────────────────────────────────────────────────┘
```

---

## 8. 持久化层（better-sqlite3）

### 8.1 数据库

`src/main/db.ts` 维护 `~/.Zeloo/<profile>/state.db`，表结构包括：

| 表 | 用途 |
|----|------|
| `sessions` | 会话元数据 |
| `messages` | 消息历史（含 token / cost / model） |
| `profiles` | 多 profile 配置（color / avatar / path） |
| `credentials` | API Key 池（多源 + 优先级轮转） |
| `models` | 模型库（id / provider / contextLength / capabilities） |
| `providers` | Provider 配置（OpenAI / Anthropic / 自定义） |
| `platforms` | Telegram / Discord / Slack 等 bot 平台配置 |
| `session_cache` | 会话缓存（生成标题 + 预览） |
| `attachments` | 附件 staging |

### 8.2 备份与恢复

- `runHermesBackup()` → 创建 zip 快照到 `~/Documents/Zeloo-Backups/`
- `runHermesImport(path)` → 解压并恢复

---

## 9. i18n 与本地化（12 语言）

### 9.1 默认语言切换

`src/shared/i18n/config.ts`:

```typescript
export const DEFAULT_ACTIVE_LOCALE: AppLocale = "zh-CN";  // ← 已改为中文
export const APP_LOCALES: AppLocale[] = [
  "en", "ar", "es", "he", "id", "ja", "pl", "pt-BR", "pt-PT", "tr", "zh-CN", "zh-TW",
];
```

### 9.2 翻译目录结构

```
src/shared/i18n/locales/zh-CN/  (20 个文件)
├── agents.ts        ├── navigation.ts
├── chat.ts          ├── office.ts
├── common.ts        ├── providers.ts
├── constants.ts     ├── schedules.ts
├── diagnose.ts      ├── sessions.ts
├── discover.ts      ├── settings.ts
├── errors.ts        ├── setup.ts
├── gateway.ts       ├── skills.ts
├── install.ts       ├── soul.ts
├── kanban.ts        ├── tools.ts
├── memory.ts        └── welcome.ts
├── models.ts
```

每个文件导出 `export const <namespace> = { ... } as const`：

```typescript
// locales/zh-CN/chat.ts
export const chat = {
  send: "发送",
  stop: "停止",
  typing: "正在输入…",
  // ...
} as const;
```

### 9.3 运行时切换

1. 用户在 Settings → Appearance → Language 选择
2. `I18nProvider.tsx: setLocaleState` 更新 React state
3. `localStorage.setItem("zeloo-locale", locale)`
4. `applyDocumentLocale(locale)` 设置 `<html lang="zh-CN" dir="ltr">`
5. `window.hermesAPI.setLocale(locale)` 持久化到 SQLite

---

## 10. 安全模型

### 10.1 三层安全

| 层 | 机制 |
|----|------|
| **进程隔离** | `contextIsolation: true` + `nodeIntegration: false` |
| **API 网关** | `contextBridge.exposeInMainWorld("hermesAPI", …)` 暴露受限方法 |
| **IPC 校验** | `ipcMain.handle(channel, handler)` 每个 handler 自行校验参数类型 |
| **CSP** | `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'…` |
| **WebContents 加固** | `hardenAttachedWebContents()` 禁止 webview 导航到非白名单 |
| **Secret 管理** | `secrets/` 提供器链（command → env → Keychain），API Key 不入 SQLite 明文 |

### 10.2 危险操作策略

`zeloo_DANGEROUS_POLICY`（从环境变量传入 main 进程）：
- `allow`（默认）：直接执行
- `deny`：拒绝 + 返回错误
- `confirm`：首次调用返回确认提示，传入 `__confirm: true` 二次确认

---

## 11. 如何二次开发

### 11.1 开发环境搭建

```bash
cd zeloo
npm install --ignore-scripts          # 跳过 native rebuild（沙箱限制）
npx electron-rebuild                   # 重建 better-sqlite3 native 模块
npm run dev                            # 启动 dev server（Vite + Electron）
```

### 11.2 添加新 IPC 方法（标准流程）

**示例**：新增 `getMyData` 接口

1. **shared 类型**（`src/shared/my-data.ts`）：
   ```typescript
   export interface MyData {
     id: string;
     name: string;
   }
   ```

2. **preload 暴露**（`src/preload/index.ts`）：
   ```typescript
   import type { MyData } from "../shared/my-data";
   const hermesAPI = {
     // ...existing
     getMyData: (): Promise<MyData[]> => ipcRenderer.invoke("get-my-data"),
   };
   ```

3. **main 处理**（`src/main/ipc/register.ts`）：
   ```typescript
   ipcMain.handle("get-my-data", async () => {
     // ... 业务逻辑
     return await db.getAllMyData();
   });
   ```

4. **renderer 调用**：
   ```typescript
   const data = await window.hermesAPI.getMyData();
   ```

### 11.3 添加新屏幕

1. 创建 `src/renderer/src/screens/MyScreen/MyScreen.tsx`
2. 在 `src/renderer/src/screens/Layout/Layout.tsx` 中添加菜单项 + 路由 case
3. 添加 i18n 翻译到 12 个 locale 文件的对应 namespace

### 11.4 添加 i18n 翻译

1. 修改 `src/shared/i18n/locales/zh-CN/<namespace>.ts`
2. 在相同 namespace 文件夹下修改 en/ja/es 等
3. 重新运行 `npm run build:win` 触发 vite 重新打包

### 11.5 添加新皮肤 / 主题

`src/renderer/src/components/ThemeProvider.tsx` + `src/renderer/src/assets/main.css`

### 11.6 添加新 Provider

1. `src/main/provider-registry.ts` 注册 Provider 路由
2. `src/main/model-discovery.ts` 添加探测逻辑
3. UI 在 `src/renderer/src/screens/Providers/Providers.tsx` 增补

### 11.7 添加新 MCP 服务器

1. `src/main/mcp-servers.ts` 注册（name / transport / endpoint）
2. UI 在 `src/renderer/src/screens/Connectors/` 增补配置表单

### 11.8 调试技巧

```bash
# DevTools 自动打开
HERMES_OPEN_DEVTOOLS=1 npm run dev

# CDP 远程调试
ENABLE_CDP=1 npm run dev  # 访问 chrome://inspect

# 调试日志
tail -f ~/.Zeloo/<profile>/logs/*.log

# debug dump
npm run start -- --dump  # 触发 main 进程的 runHermesDump
```

### 11.9 测试

```bash
npm run test                 # Vitest 单元测试
npm run test:coverage        # 覆盖率
npm run test:sandbox         # 沙箱测试（PowerShell）
npm run typecheck            # TypeScript 全量检查
npm run typecheck:node       # 仅 main + preload
npm run typecheck:web        # 仅 renderer
npm run lint                 # ESLint
```

### 11.10 打包

```bash
npm run build:win            # NSIS + portable
npm run build:mac            # macOS DMG
npm run build:linux          # AppImage / deb / rpm
```

---

## 12. 已实现的特性（与原 Zeloo Agent 兼容性）

| Zeloo Agent 功能 | hermes-desktop 实现位置 | IPC 方法 |
|------------------|--------------------------|---------|
| Profile 多账户 | `profiles.ts` | `listProfiles` / `createProfile` |
| Memory 长/短期 | `Memory.tsx` | `readMemory` / `addMemoryEntry` |
| Skills 安装/卸载 | `Skills.tsx` | `listInstalledSkills` / `installSkill` |
| MCP 服务器 | `mcp-servers.ts` | `listMcpServers` / `addMcpServer` |
| Kanban | `kanban.ts` | `kanbanListBoards` / `kanbanCreateTask` |
| Cron Jobs | `cronjobs.ts` | `listCronJobs` / `createCronJob` |
| Provider 模型自动发现 | `model-discovery.ts` | `discoverProviderModels` |
| 多模态聊天 | `Chat.tsx` | `sendMessage` (附件支持) |
| 流式响应 | `hermes.ts` (stdout parse) | `onChatChunk` |
| Reasoning 推理 | `hermes.ts` | `onChatReasoningChunk` |
| Tool calls | `hermes.ts` | `onChatToolProgress` / `onChatToolEvent` |
| Usage 统计 | `hermes.ts` | `onChatUsage` |
| 远程 gateway | `Gateway.tsx` + `dashboard.ts` | `startDashboard` / `dashboardStatus` |
| SSH 远程 | `ssh-tunnel.ts` + `ssh-remote.ts` | `startSshTunnel` |
| Wallet（区块链） | `wallets.ts` | `listWallets` / `getTokenBalances` |
| 3D Office | `Office3D.tsx` + Three.js | `claw3dSetup` / `claw3dStartAll` |
| 自动更新 | `updater.ts` | `checkForUpdates` / `installUpdate` |
| 注册表 / 市场 | `registry.ts` | `fetchRegistry` / `installRegistryItem` |
| 配置健康检查 | `config-health.ts` | `getConfigHealth` / `autofixConfigIssue` |

---

## 13. 待办与扩展点

| 方向 | 描述 |
|------|------|
| 打包优化 | 当前 NSIS 155MB，可考虑 better-sqlite3 → sql.js（去掉 native 模块） |
| 自动更新 | 配置 `latest.yml` + GitHub Releases 启用自动更新 |
| 签名 | 配置 `CSC_LINK` + `CSC_KEY_PASSWORD` 给 Windows 代码签名证书 |
| AppImage | 添加 `linux.beforePack` hook 修复 chrome-sandbox setuid（已写在配置注释） |
| 安全 | 启用 `ELECTRON_ENABLE_LOGGING=1` 收集日志到中心化存储 |
| 性能 | Renderer 大型 bundle（7.7MB）可拆分为 manualChunks（Vite 已支持） |
| i18n | 添加 `zh-HK`、`ko-KR`、`fr-FR` 等更多 locale |
| 测试 | 添加 Playwright E2E（已配置 `test:sandbox`）|

---

## 相关文档

- [docs/60-deployment-scan-report.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/60-deployment-scan-report.md) — 部署环境扫描
- [docs/61-env-sync-guide.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/61-env-sync-guide.md) — .env 双端同步
- [docs/55-tui-rendering.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/55-tui-rendering.md) — TUI 实现
- [AGENTS.md](file:///c:/Users/38324/OneDrive/Desktop/primus/zeloo/AGENTS.md) — hermes-desktop 工作规范