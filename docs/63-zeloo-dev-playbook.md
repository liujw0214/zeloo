# 63 · Zeloo 二次开发实操指南

> 配套 [docs/62-zeloo-framework-guide.md](./62-zeloo-framework-guide.md)，本文档聚焦**实战工作流**：常见修改场景的最小可行步骤、代码模板、调试技巧。

---

## 0. 开发环境搭建（5 分钟）

### 0.1 一次性环境

```bash
# 1. Node.js（项目要求 v20+）
node --version    # >= v20.0.0

# 2. Python（Zeloo CLI 子进程依赖）
python --version  # >= 3.10

# 3. 安装依赖（含 native rebuild）
cd zeloo
npm install           # 沙箱外运行：会自动 rebuild better-sqlite3

# 4. 验证
npm run typecheck     # TS 检查
npm run test          # 单元测试
```

### 0.2 开发模式

```bash
npm run dev          # 启动 Electron + Vite，5173 端口 Renderer，HMR 可用
```

> 沙箱环境：`npm install --ignore-scripts` + `npx electron-rebuild`

### 0.3 调试快捷键

| 快捷键 | 作用 |
|--------|------|
| `F12` | 打开 Renderer DevTools |
| `Ctrl+Shift+I` | 同上 |
| `Ctrl+R` | 重载 Renderer |
| `Ctrl+Shift+R` | 强制重载（清缓存） |
| `Ctrl+Q` | 退出应用 |

---

## 1. 场景矩阵（10 类常见修改）

| # | 场景 | 涉及文件 | 难度 |
|---|------|---------|------|
| 1 | 添加新 IPC 方法 | `shared/*` + `preload/index.ts` + `main/ipc/register.ts` | ⭐ |
| 2 | 添加新屏幕 | `renderer/src/screens/MyScreen/` + `Layout.tsx` + 12 套 i18n | ⭐⭐ |
| 3 | 添加新 LLM Provider | `main/provider-registry.ts` + `model-discovery.ts` | ⭐⭐ |
| 4 | 添加新 MCP 服务器 | `main/mcp-servers.ts` + 配套 UI | ⭐⭐ |
| 5 | 修改持久化表 | `main/db.ts` + 表 schema 迁移 | ⭐⭐⭐ |
| 6 | 添加流式事件 | `preload/index.ts` + `main/ipc/register.ts` + `renderer` 监听 | ⭐⭐ |
| 7 | 自定义 Chat 工具栏 | `renderer/src/screens/Chat/` | ⭐⭐ |
| 8 | 添加键盘快捷键 | `renderer/src/components/...` | ⭐ |
| 9 | 添加暗/亮主题变体 | `renderer/src/assets/main.css` | ⭐ |
| 10 | 修改打包配置 | `electron-builder.yml` | ⭐⭐ |

---

## 2. 场景 1：添加新 IPC 方法（最常见）

**目标**：新增 `getSystemInfo` 接口，返回 CPU/内存/磁盘信息。

### Step 1：定义共享类型

```typescript
// src/shared/system-info.ts  ← 新建
export interface SystemInfo {
  platform: NodeJS.Platform;
  arch: string;
  cpus: number;
  totalMemory: number;  // bytes
  freeMemory: number;   // bytes
  uptime: number;       // seconds
}

export const SYSTEM_INFO_CHANNEL = "get-system-info";
```

### Step 2：main 注册 handler

```typescript
// src/main/ipc/register.ts  ← 添加
import os from "node:os";
import { SYSTEM_INFO_CHANNEL, type SystemInfo } from "../../shared/system-info";

// 在 registerIpcHandlers 函数内：
ipcMain.handle(SYSTEM_INFO_CHANNEL, (): SystemInfo => ({
  platform: process.platform,
  arch: process.arch,
  cpus: os.cpus().length,
  totalMemory: os.totalmem(),
  freeMemory: os.freemem(),
  uptime: os.uptime(),
}));
```

### Step 3：preload 暴露 API

```typescript
// src/preload/index.ts  ← 在 hermesAPI 对象内添加
import type { SystemInfo } from "../shared/system-info";

// 在 hermesAPI 内：
getSystemInfo: (): Promise<SystemInfo> => ipcRenderer.invoke("get-system-info"),
```

### Step 4：renderer 调用

```vue
<!-- src/renderer/src/components/SystemInfoCard.vue -->
<script setup lang="ts">
import { ref, onMounted } from "vue"

const info = ref<{ cpus: number; totalMemory: number } | null>(null)

onMounted(async () => {
  info.value = await window.hermesAPI.getSystemInfo()
})
</script>

<template>
  <div v-if="info">
    CPUs: {{ info.cpus }} | Memory: {{ (info.totalMemory / 1024 ** 3).toFixed(1) }} GB
  </div>
</template>
```

### Step 5：测试

```typescript
// tests/unit/test_system_info.ts
import { describe, it, expect } from "vitest"
import { ipcRenderer } from "electron"

describe("getSystemInfo", () => {
  it("returns system information", async () => {
    const result = await ipcRenderer.invoke("get-system-info")
    expect(result.platform).toBe(process.platform)
    expect(result.cpus).toBeGreaterThan(0)
  })
})
```

---

## 3. 场景 2：添加新屏幕

**目标**：添加"MyFiles"屏幕，显示本地文件系统树。

### Step 1：创建屏幕组件

```vue
<!-- src/renderer/src/screens/MyFiles/MyFiles.tsx -->
<script setup lang="ts">
import { onMounted, ref } from "vue"

const files = ref<Array<{ name: string; isDir: boolean }>>([])

onMounted(async () => {
  const result = await window.hermesAPI.readDirectory("/tmp")
  files.value = result ?? []
})
</script>

<template>
  <div class="my-files">
    <h2>My Files</h2>
    <ul>
      <li v-for="f in files" :key="f.name" :class="{ dir: f.isDir }">
        {{ f.isDir ? "📁" : "📄" }} {{ f.name }}
      </li>
    </ul>
  </div>
</template>
```

### Step 2：注册到 Layout

```typescript
// src/renderer/src/screens/Layout/Layout.tsx  ← 添加 case
import MyFiles from "../MyFiles/MyFiles"

// 在 router 配置中添加：
{ key: "my-files", label: "My Files", icon: () => "📁", component: <MyFiles /> }
```

### Step 3：添加 i18n 翻译（12 语言 ×1 namespace）

```typescript
// src/shared/i18n/locales/zh-CN/navigation.ts
export const navigation = {
  chat: "聊天",
  agents: "代理",
  skills: "技能",
  // ... existing
  myFiles: "我的文件",  // ← 新增
} as const

// src/shared/i18n/locales/en/navigation.ts
export const navigation = {
  chat: "Chat",
  agents: "Agents",
  // ...
  myFiles: "My Files",  // ← 新增
} as const

// 其余 10 种语言同样添加
```

### Step 4：i18n 注册（autocomplete）

`src/shared/i18n/types.ts` 中的 `AppLocale` 与各 namespace 类型会自动推断。如果需要强制类型：

```typescript
import "i18next";
declare module "i18next" {
  interface CustomTypeOptions {
    resources: {
      navigation: typeof navigation;
    };
  }
}
```

---

## 4. 场景 3：添加新 LLM Provider

**目标**：注册 Cohere 作为 Provider（已支持列表见 `provider-registry.ts`）。

### Step 1：注册到路由

```typescript
// src/main/provider-registry.ts  ← 添加
export const OPENAI_COMPAT_PROVIDERS = [
  // ... existing
  {
    id: "cohere",
    label: "Cohere",
    envKey: "COHERE_API_KEY",
    defaultBaseUrl: "https://api.cohere.ai/v1",
    supportsBaseUrl: true,
    isAnthropic: false,
  },
] as const;
```

### Step 2：模型发现

```typescript
// src/main/model-discovery.ts  ← 添加
async function discoverCohereModels(apiKey: string): Promise<string[]> {
  const res = await fetch("https://api.cohere.ai/v1/models", {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  const data = await res.json();
  return data.models?.map((m: { name: string }) => m.name) ?? [];
}
```

### Step 3：UI 提供（自动出现）

`Providers.tsx` 通过 `listModels()` 获取，无需修改 UI。

---

## 5. 场景 4：添加 MCP 服务器

### Step 1：注册到 catalog

```typescript
// src/main/mcp-servers.ts  ← 添加
export const MCP_CATALOG = [
  // ... existing
  {
    name: "my-custom-mcp",
    description: "My custom MCP server",
    source: "npm",
    transport: "stdio" as const,
    command: "npx",
    args: ["-y", "@my-org/mcp-server"],
    env: {},
  },
];
```

### Step 2：UI 自动出现

`src/renderer/src/components/.../MCPBrowserModal.tsx` 会渲染新的 catalog 条目。

---

## 6. 场景 5：修改持久化表

**目标**：给 sessions 表新增 `archived_at` 列。

### Step 1：schema 迁移

```typescript
// src/main/db.ts  ← 修改迁移逻辑
const MIGRATIONS: Array<(db: Database) => void> = [
  // ...existing migrations
  (db) => {
    // v2 → v3: add archived_at column
    if (!columnExists(db, "sessions", "archived_at")) {
      db.exec(`ALTER TABLE sessions ADD COLUMN archived_at INTEGER`)
    }
  },
];
```

### Step 2：类型更新

```typescript
// src/shared/sessions.ts  ← 添加字段
export interface SessionMeta {
  id: string;
  // ... existing
  archivedAt: number | null;
}
```

### Step 3：CRUD 实现

```typescript
// src/main/sessions.ts  ← 新增 archive 函数
export function archiveSession(sessionId: string): void {
  db.prepare(`UPDATE sessions SET archived_at = ? WHERE id = ?`)
    .run(Date.now(), sessionId);
}
```

### Step 4：preload + IPC + UI

按场景 1 的流程，添加 `archiveSession` → `hermesAPI.archiveSession` → UI 按钮。

---

## 7. 场景 6：添加流式事件

**目标**：新增 `onTaskProgress` 推送长时间任务的进度。

### Step 1：main 端推送

```typescript
// src/main/notifications.ts  ← 新建
import { BrowserWindow } from "electron"

export function notifyTaskProgress(taskId: string, progress: number, message: string) {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send("task-progress", { taskId, progress, message })
  }
}
```

### Step 2：触发点

```typescript
// src/main/long-task.ts  ← 业务逻辑
import { notifyTaskProgress } from "./notifications"

async function runLongTask(taskId: string) {
  for (let i = 0; i <= 100; i += 10) {
    notifyTaskProgress(taskId, i, `Processing ${i}%`)
    await sleep(1000)
  }
}
```

### Step 3：preload 监听接口

```typescript
// src/preload/index.ts  ← 在 hermesAPI 添加
onTaskProgress: (
  callback: (data: { taskId: string; progress: number; message: string }) => void,
): (() => void) => {
  const handler = (_event: Electron.IpcRendererEvent, data: unknown) =>
    callback(data as { taskId: string; progress: number; message: string })
  ipcRenderer.on("task-progress", handler)
  return () => ipcRenderer.removeListener("task-progress", handler)
},
```

### Step 4：renderer 监听

```vue
<!-- 任何 Vue 组件 -->
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue"

const progress = ref(0)
let cleanup: (() => void) | null = null

onMounted(() => {
  cleanup = window.hermesAPI.onTaskProgress((data) => {
    progress.value = data.progress
  })
})

onUnmounted(() => cleanup?.())
</script>
```

---

## 8. 场景 7：自定义 Chat 工具栏

**目标**：在 ChatInput 上方添加"语音转文字"按钮。

### Step 1：preload 已有 `transcribeAudio`

```typescript
// 已存在
transcribeAudio: (audio: Uint8Array, mimeType: string, profile?: string) => Promise<string>
```

### Step 2：UI 组件

```vue
<!-- src/renderer/src/screens/Chat/ChatInput.tsx  ← 修改 -->
<script setup lang="ts">
import { ref } from "vue"

const isRecording = ref(false)
const mediaRecorder = ref<MediaRecorder | null>(null)

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  mediaRecorder.value = new MediaRecorder(stream)
  const chunks: Blob[] = []
  mediaRecorder.value.ondataavailable = (e) => chunks.push(e.data)
  mediaRecorder.value.onstop = async () => {
    const blob = new Blob(chunks, { type: "audio/webm" })
    const buffer = await blob.arrayBuffer()
    const text = await window.hermesAPI.transcribeAudio(
      new Uint8Array(buffer),
      "audio/webm",
    )
    input.value = text
    stream.getTracks().forEach((t) => t.stop())
  }
  mediaRecorder.value.start()
  isRecording.value = true
}

function stopRecording() {
  mediaRecorder.value?.stop()
  isRecording.value = false
}
</script>

<template>
  <div class="chat-input-toolbar">
    <button @click="isRecording ? stopRecording() : startRecording()">
      {{ isRecording ? "⏹ 停止" : "🎤 语音" }}
    </button>
    <!-- 其他工具按钮 -->
  </div>
  <!-- textarea / input -->
</template>
```

---

## 9. 场景 8：添加全局键盘快捷键

### 在 Renderer 中

```typescript
// src/renderer/src/composables/useGlobalShortcuts.ts
import { onMounted, onUnmounted } from "vue"

export function useGlobalShortcuts() {
  function handleKey(e: KeyboardEvent) {
    // Ctrl+K → 搜索会话
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault()
      window.dispatchEvent(new CustomEvent("zeloo:search-sessions"))
    }
    // Ctrl+N → 新建聊天
    if ((e.ctrlKey || e.metaKey) && e.key === "n") {
      e.preventDefault()
      window.dispatchEvent(new CustomEvent("zeloo:new-chat"))
    }
  }

  onMounted(() => window.addEventListener("keydown", handleKey))
  onUnmounted(() => window.removeEventListener("keydown", handleKey))
}
```

### 在 main 中（全局系统级）

```typescript
// src/main/app/menu.ts  ← 添加
{
  label: "New Chat",
  accelerator: "CmdOrCtrl+N",
  click: () => sendToFocusedWindow("menu-new-chat"),
},
{
  label: "Search Sessions",
  accelerator: "CmdOrCtrl+K",
  click: () => sendToFocusedWindow("menu-search-sessions"),
},
```

---

## 10. 场景 9：自定义主题色

```scss
/* src/renderer/src/assets/main.css  ← 在 :root 添加自定义变量 */
:root {
  --zeloo-primary: #6366f1;          /* 当前：Indigo */
  /* --zeloo-primary: #10b981;        /* 自定义：Emerald */ */
  --zeloo-bg-base: #0f1117;
  --zeloo-bg-surface: #161b27;
  --zeloo-accent: #10b981;
}

/* Tailwind 主题映射在 tailwind.config.js */
```

---

## 11. 场景 10：自定义打包

### 11.1 改产物名 + 安装路径

```yaml
# electron-builder.yml
productName: Zeloo Pro              # 改安装包显示名
nsis:
  artifactName: ${name}-${version}-pro-setup.${ext}
mac:
  artifactName: ${name}-${version}-${arch}-mac.dmg
```

### 11.2 添加代码签名

```bash
# 设置环境变量
export CSC_LINK=/path/to/cert.p12
export CSC_KEY_PASSWORD=*****
export CSC_IDENTITY_AUTO_DISCOVERY=false   # Windows 必需

# 打包
npm run build:win
```

### 11.3 启用自动更新

```yaml
# electron-builder.yml
publish:
  provider: github
  owner: zeloo
  repo: zeloo
```

需配合 GitHub Personal Access Token 环境变量：
```bash
export GH_TOKEN=ghp_***
npm run build:win
```

---

## 12. 调试技巧

### 12.1 主进程调试

```bash
# 启用 DevTools
HERMES_OPEN_DEVTOOLS=1 npm run dev

# 或 CDP 远程调试
ENABLE_CDP=1 npm run dev
# 然后访问 chrome://inspect 并配置 target
```

### 12.2 Renderer 调试

```bash
# DevTools 里:
# - Application > Local Storage > 检查 zeloo-locale
# - Console: window.hermesAPI.getSystemInfo().then(console.log)
# - Network: 检查 WS / REST 请求
```

### 12.3 子进程调试

```bash
# 查看 Zeloo CLI 子进程 stdout
# Renderer DevTools > Sources > search "spawn"

# 直接运行 CLI 验证：
~/.Zeloo/profile/bin/zeloo chat "test"
```

### 12.4 数据库调试

```bash
# 使用 sqlite3 命令行
sqlite3 ~/.Zeloo/<profile>/state.db

sqlite> .tables
sqlite> .schema sessions
sqlite> SELECT * FROM sessions LIMIT 5;
```

### 12.5 性能分析

```typescript
// src/renderer/src/utils/perf.ts
import { mark, measure } from "perf_hooks"

mark("chat-start")
// ... 代码
measure("chat", "chat-start")
```

---

## 13. 测试最佳实践

### 13.1 单元测试

```typescript
// tests/unit/test_my_utility.ts
import { describe, it, expect } from "vitest"
import { parseFrontmatter } from "@/agent/skill_utils"

describe("parseFrontmatter", () => {
  it("parses YAML frontmatter", () => {
    const content = `---
name: foo
description: test
---
body content`
    const result = parseFrontmatter(content)
    expect(result.name).toBe("foo")
    expect(result.body).toContain("body content")
  })
})
```

### 13.2 E2E 测试（Playwright）

```typescript
// tests/e2e/test_app_launch.ts
import { test, expect, _electron as electron } from "@playwright/test"

test("app launches and shows welcome screen", async () => {
  const app = await electron.launch({ args: ["path/to/electron"] })
  const window = await app.firstWindow()
  await expect(window).toHaveTitle(/Zeloo/)
  await window.screenshot({ path: "screenshots/welcome.png" })
  await app.close()
})
```

### 13.3 IPC Mock

```typescript
// tests/unit/preload_mock.ts
export const mockHermesAPI = {
  getSystemInfo: vi.fn().mockResolvedValue({
    platform: "win32",
    cpus: 8,
    totalMemory: 16 * 1024 ** 3,
  }),
  // ... 其他 mock
} as unknown as Window["hermesAPI"]
```

---

## 14. 性能优化清单

| 优化点 | 工具/方法 | 影响 |
|--------|-----------|------|
| Renderer bundle 拆分 |  | 1.3MB → 600KB（Naive UI tree-shake） |
| better-sqlite3 → sql.js |  | 减少 native 模块依赖 |
| Vite manualChunks | `vite.config.ts` | 减小主 bundle |
| 图片懒加载 | `<img loading="lazy">` | 首屏提速 |
| i18n 按需加载 | `i18next-http-backend` | 减小初始下载 |
| Three.js 资产压缩 | `gltf-transform` | Office 资源减小 |
| WS 流式 backpressure |  | 防止内存爆炸 |

---

## 15. 常见错误速查

| 错误 | 原因 | 解决 |
|------|------|------|
| `better-sqlite3` rebuild 失败 | sandbox 限制 | `npm install --ignore-scripts` + `electron-rebuild` |
| `contextBridge` 报错 | preload 错误使用 | 检查 `process.contextIsolated` |
| CSP 阻止 inline script | Tailwind 内联样式 | 添加 `'unsafe-inline'` 到 `style-src` |
| `proxy.ghproxy.com` 网络超时 | git mirror 失效 | `npm config delete url.https://ghproxy.com` |
| IPC 返回 `undefined` | 缺 `return` | main handler 必须 return |
| Renderer 显示旧代码 | Vite HMR 失败 | `Ctrl+Shift+R` 强制重载 |
| 窗口无法启动 | GPU 崩溃 | 已实现 GPU fallback（`installGpuCrashGuard`） |

---

## 16. 提交规范（参考 AGENTS.md）

```
feat(skills): add new MCP catalog entry for postgres
fix(chat): handle abort during streaming
docs(guide): update IPC channel list
chore(deps): bump electron to 44.1.1
test(ipc): add integration test for sendMessage
```

---

## 相关文档

- [docs/62-zeloo-framework-guide.md](./62-zeloo-framework-guide.md) — 框架总览
- [docs/60-deployment-scan-report.md](./60-deployment-scan-report.md) — 部署扫描
- [docs/61-env-sync-guide.md](./61-env-sync-guide.md) — .env 同步
- [zeloo/AGENTS.md](../zeloo/AGENTS.md) — 项目级工作规范