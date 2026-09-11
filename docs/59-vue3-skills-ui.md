# 59 · Vue 3 技能 UI（zeloo_web_ui）

> Zeloo 技能系统的现代 Web 管理界面，基于 Vue 3 + Vite + TypeScript + Naive UI 构建。

## 目录

1. [概述](#1-概述)
2. [技术栈](#2-技术栈)
3. [项目结构](#3-项目结构)
4. [核心功能](#4-核心功能)
5. [组件设计](#5-组件设计)
6. [状态管理](#6-状态管理)
7. [API 层](#7-api-层)
8. [验证结果](#8-验证结果)

---

## 1. 概述

`zeloo_web_ui/` 是 Zeloo 技能系统的专用 Web 管理界面（[docs/58](./58-hermes-inspired-frontends.md) §2 中规划的 Vue 3 迁移第一步）。

**定位**：独立 npm 项目，通过 REST API 与 `zeloo_web/` 后端通信。不直接依赖 Python 代码，可独立构建、部署。

**构建产物**：`zeloo_web_ui/dist/`，可由 FastAPI 通过 `StaticFiles` 挂载，或独立部署到 CDN。

```
┌─────────────────── Browser ───────────────────────┐
│  #/ (SkillsView)    #/skills/:id (SkillDetailView) │
└────────────────────┬───────────────────────────────┘
                     │ /api/skills  (REST)
                     ▼
┌────────────── FastAPI ─────────────────────────────┐
│  /api/skills  GET/POST/PATCH                       │
│  → agent.skill_utils / optional_skills.skill_loader │
└────────────────────────────────────────────────────┘
```

---

## 2. 技术栈

| 层级 | 技术选型 | 版本 | 说明 |
|------|---------|------|------|
| **框架** | Vue 3（Composition API + `<script setup>`） | ^3.5 | 渐进式、文档友好 |
| **构建** | Vite | ^6.0 | 毫秒级 HMR、ESM native |
| **类型** | TypeScript（strict 模式） | ^5.6 | 严格类型检查 |
| **UI 组件库** | Naive UI | ^2.40 | Vue 3 原生、主题深度定制 |
| **路由** | Vue Router（Hash 模式） | ^4.5 | 适合前后端一体部署 |
| **状态管理** | Pinia | ^2.3 | 响应式 store，devtools 支持 |
| **样式** | SCSS + CSS 变量 | — | 复用 Zeloo CSS token 体系 |

**CSS 设计 Token**：与 `zeloo_web/static/style.css` 的 CSS 变量体系保持一致，通过 SCSS 变量文件 `src/styles/variables.scss` 统一管理。

---

## 3. 项目结构

```
zeloo_web_ui/
├── index.html              # 入口 HTML（加载 Inter + JetBrains Mono 字体）
├── vite.config.ts          # Vite 配置（@ 别名 + SCSS 全局注入）
├── tsconfig.app.json       # TypeScript 严格模式配置
├── package.json
├── dist/                   # 生产构建产物（由 FastAPI 托管）
│
└── src/
    ├── main.ts             # 入口：Pinia + Router + Naive UI 注册
    ├── App.vue             # 主布局（AppHeader + AppSidebar + RouterView）
    │
    ├── types/
    │   └── skill.ts        # Skill / SkillFilter / ApiResponse 类型定义
    │
    ├── api/
    │   └── client.ts       # REST API 客户端（fetch 封装）
    │
    ├── stores/
    │   └── skills.ts       # Pinia store：技能列表 / 筛选 / 启用禁用
    │
    ├── router/
    │   └── index.ts        # Vue Router（hash 模式，懒加载视图）
    │
    ├── components/
    │   ├── AppHeader.vue   # 顶栏：品牌 + 搜索框 + 统计徽章
    │   ├── AppSidebar.vue  # 侧边栏：分类筛选 + 排序 + 仅启用开关
    │   └── SkillCard.vue   # 技能卡片：分类图标 + 开关 + 触发短语 + 标签
    │
    ├── views/
    │   ├── SkillsView.vue      # 技能画廊（分组/列表模式）
    │   └── SkillDetailView.vue # 技能详情（统计 + 触发短语 + 工具）
    │
    └── styles/
        ├── variables.scss  # CSS Design Token（品牌色/字体/间距/阴影）
        └── global.scss     # 全局样式（reset / scrollbar / focus）
```

---

## 4. 核心功能

### 4.1 技能画廊（SkillsView）

**两种视图模式**：

- **分类分组**（默认，`sortBy === 'category'`）：按 6 个技能分类分组展示，每个分类有独立标题、颜色指示点、技能数量统计
- **平面列表**（其他排序模式）：无分组，按名称/使用量/最近使用排序

**搜索**：`NInput` 绑定 `store.filter.query`，实时过滤 name / description / tags。

**分类筛选**：侧边栏按钮切换 `store.filter.category`，7 个选项（全部 + 6 个分类），激活态有高亮。

**排序切换**：4 种排序维度即时生效。

**仅启用筛选**：侧边栏 toggle 切换 `store.filter.enabledOnly`。

### 4.2 技能详情（SkillDetailView）

路由 `#/skills/:id`，展示完整技能信息：

- **Hero 区域**：分类图标 + 名称 + 描述 + 启用/禁用大开关
- **统计行**：使用次数 / 触发短语数量 / 关联工具数量 / 标签数量
- **触发短语列表**：monospace 代码块 + 描述
- **工具网格**：工具名徽章
- **标签行**：NTag 组件

### 4.3 技能卡片（SkillCard）

每张卡片展示：

- 分类颜色顶边条（3px）
- 分类图标（emoji + 颜色背景）
- 技能名称 + 描述（2 行截断）
- 触发短语标签（最多 3 个 + 溢出计数）
- 使用次数 + 标签
- 启用/禁用 NSwitch（阻止冒泡）

**悬浮态**：上浮 2px + 阴影 + 分类色光晕（仅启用态）。

**禁用态**：整体透明度降低。

---

## 5. 组件设计

### 5.1 AppHeader

- 品牌区：⚡ Zeloo / Skills
- 中央搜索框（全局过滤）
- 右上角：启用数量统计 + 更多操作下拉

### 5.2 AppSidebar

- 分类导航：7 个分类项，含颜色圆点、名称、计数徽章
- 排序导航：4 个选项
- 仅启用开关：自定义 CSS toggle switch（不依赖 Naive UI NSwitch）

### 5.3 SkillCard

- **分类颜色体系**：6 个分类各有一个主色
  - 软件开发：#3b82f6（蓝）
  - 安全：#ef4444（红）
  - 研究：#8b5cf6（紫）
  - DevOps：#f59e0b（琥珀）
  - MLOps：#10b981（绿）
  - 数据科学：#06b6d4（青）
- **分类图标**：emoji 作为分类视觉标识
- **enabled glow**：启用卡片有微弱的分类色光晕（CSS blur overlay）

---

## 6. 状态管理

**useSkillsStore（Pinia）**：

```typescript
// State
skills: Skill[]           // 全部技能
loading: boolean
error: string | null
selectedId: string | null
selectedSkill: Skill | null
filter: SkillFilter       // query / category / enabledOnly / sortBy

// Getters
filteredSkills            // 过滤后技能
groupedByCategory         // 按分类 Map（用于分组视图）
enabledCount              // 已启用数量

// Actions
fetchSkills()             // GET /api/skills
fetchSkill(id)            // GET /api/skills/:id
toggleSkill(id)           // POST enable/disable
selectSkill(id)           // 选中并加载详情
```

**过滤计算**：
- `query`：name + description + tags 模糊匹配
- `category`：精确匹配分类
- `enabledOnly`：过滤 enabled 字段
- `sortBy`：按 name / usage / recent / category 排序

---

## 7. API 层

**基础 URL**：`/api`（通过 FastAPI 代理）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills` | 列表所有技能 |
| GET | `/api/skills/:id` | 获取单个技能详情 |
| POST | `/api/skills/:id/enable` | 启用技能 |
| POST | `/api/skills/:id/disable` | 禁用技能 |

**API 响应统一格式**：

```typescript
interface ApiResponse<T> {
  ok: boolean
  data?: T
  error?: string
}
```

> **后端实现**：在 `zeloo_web/app.py` 中新增 `/api/skills/*` 路由，调用 `optional_skills.skill_loader` 读取技能元数据。启用/禁用状态暂存于内存（生产环境应持久化到配置文件）。

---

## 8. 验证结果

### 8.1 构建检查

```bash
cd zeloo_web_ui
npm run build
# ✓ vue-tsc -b   (TypeScript 严格模式，0 错误)
# ✓ vite build   (3.28s, 8 个 chunk)
```

**构建产物**：

| 文件 | 大小 | gzip |
|------|------|------|
| `index.html` | 0.83 kB | 0.44 kB |
| `index.css` | 5.33 kB | 1.54 kB |
| `index.js`（含 Naive UI） | 1,309 kB | 348 kB |
| `vue-router.js` | 170 kB | 62 kB |
| `SkillsView.js` | 4.56 kB | 2.00 kB |
| `SkillDetailView.js` | 4.47 kB | 1.95 kB |

> Naive UI 整体较大（~1.3MB），是构建产物的主要部分。可通过 Tree Shaking 优化或按需引入减少体积。

### 8.2 TypeScript 严格模式

- `strict: true` — 所有类型严格推断
- `noUnusedLocals: true` — 无未使用变量
- `noUnusedParameters: true` — 无未使用参数
- `noFallthroughCasesInSwitch: true` — switch 必须穷举

### 8.3 待完成项

- **后端 API 端点**：`/api/skills` 系列路由尚未在 `zeloo_web/app.py` 中实现
- **持久化**：技能启用状态应持久化到 `$ZELOO_HOME/skills/enabled.json`
- **Naive UI 按需引入**：减少 bundle size
- **Playwright E2E 测试**：验证完整的启用/禁用/搜索流程

---

## 相关文档

- [docs/58-hermes-inspired-frontends.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/58-hermes-inspired-frontends.md) — Web 前端技术栈规划
- [docs/10-roadmap.md](file:///c:/Users/38324/OneDrive/Desktop/primus/docs/10-roadmap.md) — §10.29 同步
- [AGENTS.md](file:///c:/Users/38324/OneDrive/Desktop/primus/AGENTS.md) — 工作区规范
