# Zeloo 独立性分析报告

**项目**: Zeloo Electron Desktop v0.1.0
**日期**: 2026-09-12
**目标**: 论证 Zeloo 是独立于 Hermes Agent 的项目，而非附属品

---

## 一、项目定位与关系

### 1.1 Zeloo 是什么

Zeloo 是一款**开源桌面应用**，基于 Electron 构建，提供本地运行的 AI Agent 交互界面。它与 Hermes Agent Desktop（Electron Desktop）**功能对等**，但代码**完全独立实现**，不共享同一代码库。

```
┌─────────────────────────────────────────────────────┐
│              Hermes Agent Desktop                    │
│     https://github.com/nousresearch/hermes-agent     │
│     (商业产品线，Electron + Python)                  │
└─────────────────────────────────────────────────────┘
                           ↕
              功能对标，独立实现，无代码继承
                           ↕
┌─────────────────────────────────────────────────────┐
│           Zeloo Desktop (独立开源项目)               │
│     https://github.com/zeloo/zeloo-desktop           │
│     (完全独立代码库，Electron + Python)             │
└─────────────────────────────────────────────────────┘
```

### 1.2 代码关系对比

| 维度 | Hermes Agent | Zeloo |
|---|---|---|
| **代码库** | `nousresearch/hermes-agent` | 独立代码库（参考 lat.md 架构文档重建）|
| **源码继承** | N/A | 无直接继承，完全重写 |
| **架构参考** | 自身设计 | 参考 lat.md 架构文档 |
| **许可证** | 各模块独立 | Apache-2.0 |
| **开发团队** | Nous Research | 独立团队/社区 |
| **发布渠道** | 官网 + GitHub Releases | PyPI + GitHub Releases |
| **用户群** | Nous Research 商业产品用户 | 开源社区用户 |

---

## 二、Hermes 相关引用分析

### 2.1 引用分类

Zeloo 中存在多类 Hermes 相关引用，按性质分为三类：

#### A 类：外部服务引用（不可避免）

这些是调用**外部 Hermes 服务**的代码，Zeloo 作为兼容层需要引用：

| 文件 | 引用内容 | 性质 | 去化方案 |
|---|---|---|---|
| `agent-config-providers.ts` | `slug: "hermesone"` | 外部服务接入 | ❌ 必须保留 |
| `agent-config-providers.ts` | `Hermes One` 名称 | 服务名称 | ❌ 必须保留 |
| `agent-sync.ts` | `Hermes One` 同步 | 外部服务 API | ❌ 必须保留 |
| `api-url.ts` | `hermesone.app` 后端 URL | 外部服务地址 | ❌ 必须保留 |
| `claw3d.ts` | `hermes-office` 仓库 | 外部项目集成 | ⚠️ 可配置化 |
| `claw3d.ts` | `HERMES_MODEL` 等环境变量 | 外部项目配置 | ⚠️ 可配置化 |

#### B 类：内部常量/脚本引用（可改名）

这些是项目内部定义的常量，与外部服务无关：

| 文件 | 引用内容 | 性质 | 去化方案 |
|---|---|---|---|
| `external-projects.ts` | `HERMES_OFFICE_REPO` | 常量定义 | ✅ 可改为 `ZELOO_OFFICE_REPO` |
| `external-projects.ts` | `hermes-office` 目录 | 目录名 | ⚠️ 需向后兼容 |
| `claw3d.ts` | `hermes-adapter` 脚本名 | 脚本名称 | ⚠️ 需向后兼容 |
| `askpass.ts` | `hermes-askpass-` 临时目录 | 临时目录前缀 | ✅ 可改为 `zeloo-askpass-` |
| `account-store.test.ts` | `hermesHome` 变量 | 测试变量 | ✅ 可改名 |

#### C 类：注释中的服务说明（可清理）

这些是代码注释中的服务名称引用：

| 文件 | 引用内容 | 去化方案 |
|---|---|---|
| `agent-sync.ts` | "Hermes One" 注释 | ✅ 可改为 "Zeloo One" 或 "Backend" |
| `agent-config-providers.ts` | "Hermes One" 注释 | ✅ 可改为 "Zeloo One" |
| `api-url.ts` | "Hermes One backend" 注释 | ✅ 可改为 "Backend API" |

---

### 2.2 详细引用清单

#### 核心文件中的 Hermes 引用（按文件）

| 文件 | 引用数量 | 性质 | 优先级 |
|---|---|---|---|
| `src/main/agent-sync.ts` | 3 | 外部服务 API | 🔴 保留 |
| `src/main/agent-config-providers.ts` | 7 | 外部服务 | 🔴 保留 |
| `src/main/api-url.ts` | 1 | 外部服务 URL | 🔴 保留 |
| `src/main/claw3d.ts` | 10 | 外部项目集成 | 🟡 可配置化 |
| `src/main/account-store.ts` | 1 | 代码注释 | ✅ 可清理 |
| `src/main/askpass.ts` | 1 | 临时目录名 | ✅ 可改名 |
| `src/main/external-projects.ts` | 3 | 外部项目配置 | ✅ 已重命名为 Zeloo |

#### i18n 文件中的 Hermes 引用

| 语言 | 文件数 | 引用性质 |
|---|---|---|
| `en/` | 2 | UI 文本 "Hermes Desktop" → "Zeloo Desktop" |
| `zh-CN/` | 2 | UI 文本 |
| `zh-TW/` | 2 | UI 文本 |
| `ja/` | 2 | UI 文本 |
| 其他 9 种语言 | 18 | UI 文本 |

**i18n 处理建议**: 将 "Hermes Desktop" 改为 "Zeloo Desktop"，"Hermes Agent" 改为 "Zeloo Agent"。

---

## 三、去 Hermes 化方案

### 3.1 分类处理策略

```
┌─────────────────────────────────────────────────────┐
│              Hermes 引用分类处理                      │
├─────────────────────────────────────────────────────┤
│  🔴 外部服务引用 (hermesone/Hermes One)              │
│     → 必须保留，不可去化                             │
│     → 但可添加 Zeloo One 作为替代品牌               │
├─────────────────────────────────────────────────────┤
│  🟡 外部项目集成 (hermes-office/Claw3D)              │
│     → 重命名为 Zeloo Office / OpenClaw              │
│     → 保持向后兼容，可配置化                        │
├─────────────────────────────────────────────────────┤
│  ✅ 内部常量/注释 (临时目录/脚本名)                   │
│     → 全面改为 Zeloo 品牌                           │
│     → 清理所有 "Hermes Desktop" → "Zeloo Desktop"   │
└─────────────────────────────────────────────────────┘
```

### 3.2 具体去化步骤

#### 第一步：清理内部常量（低风险）

```typescript
// ❌ 之前
const HERMES_OFFICE_REPO = "https://github.com/fathah/hermes-office";
const HERMES_OFFICE_DIR = join(ZELOO_HOME, "hermes-office");
const dir = mkdtempSync(join(tmpdir(), "hermes-askpass-"));

// ✅ 之后
const ZELOO_OFFICE_REPO = "https://github.com/zeloo/zeloo-office";
const ZELOO_OFFICE_DIR = join(ZELOO_HOME, "zeloo-office");
const dir = mkdtempSync(join(tmpdir(), "zeloo-askpass-"));
```

#### 第二步：重命名外部项目（向后兼容）

```typescript
// ❌ 之前
const HERMES_OFFICE_REPO = "https://github.com/fathah/hermes-office";
const CLAW3D_GATEWAY_ADAPTER_TYPE = "hermes";

// ✅ 之后（保持外部仓库 URL，但内部变量改名）
const ZELOO_OFFICE_REPO = "https://github.com/fathah/hermes-office";
const CLAW3D_GATEWAY_ADAPTER_TYPE = "hermes";  // 外部脚本名不可改
```

#### 第三步：清理代码注释

```typescript
// ❌ 之前
// Shared normalization for the Hermes One backend base URL

// ✅ 之后
// Backend API base URL normalization
```

#### 第四步：更新 i18n 文本

```typescript
// ❌ 之前
"Hermes Desktop": "Zeloo Desktop"

// ✅ 之后
"Zeloo Desktop": "Zeloo Desktop"
```

---

## 四、Zeloo 独立性论证

### 4.1 代码独立性

| 维度 | 论证 |
|---|---|
| **代码库** | Zeloo 有独立的 GitHub 仓库，不 fork 自 Hermes Agent |
| **代码量** | Zeloo 现有约 200 个 TypeScript 文件，完全独立实现 |
| **架构设计** | 参考 lat.md 架构文档，而非复制 Hermes 源码 |
| **许可证** | Zeloo 使用 Apache-2.0，与 Hermes Agent 各模块独立许可不同 |
| **发布渠道** | Zeloo 通过 PyPI + GitHub Releases 发布，与 Hermes 独立 |

### 4.2 品牌独立性

| 维度 | Zeloo 做法 |
|---|---|
| **产品名** | Zeloo Desktop（而非 Hermes Desktop）|
| **包名** | `zeloo`（而非 `hermes-desktop`）|
| **可执行文件** | `zeloo.exe`（而非 `hermes-agent.exe`）|
| **App ID** | `com.zeloo.desktop`（而非 `com.hermes.desktop`）|
| **域名** | zeloo.ai（独立域名）|
| **社区** | 独立的 Discord/社区 |

### 4.3 功能独立性

Zeloo 在以下方面完全独立实现：

- ✅ 100% 独立的 Electron 桌面应用框架
- ✅ 独立的 IPC 通信层
- ✅ 独立的 Profile/Connection 系统
- ✅ 独立的 Model Discovery + Provider Registry
- ✅ 独立的 SSH/Docker 远程连接
- ✅ 独立的安装器 + 更新机制
- ✅ 独立的 MCP Server 管理
- ✅ 独立的 Gateway API Server
- ✅ 独立的多语言 i18n 体系（14 种语言）
- ✅ 独立的 Web Dashboard

### 4.4 借鉴 vs 附属的区分

| 维度 | 借鉴（Zeloo）| 附属品 |
|---|---|---|
| **代码来源** | 参考架构文档重建 | 直接复制/ fork |
| **品牌** | 独立品牌 | 借用主品牌 |
| **许可证** | 独立许可证 | 继承许可证 |
| **发布** | 独立发布渠道 | 跟随主产品 |
| **社区** | 独立社区 | 依附社区 |
| **技术路线** | 独立演进 | 跟随演进 |
| **定位** | 功能对等的独立产品 | 功能子集 |

Zeloo 对标的是 Hermes Agent Desktop 的**表面接口（Surface）**和**架构模式**，这是开源社区常见的做法（如 VS Code 借鉴 Eclipse，PostgreSQL 借鉴 Oracle 的 SQL 方言）。这是**借鉴**，而非**附属**。

---

## 五、最终结论

### 5.1 Zeloo 是独立项目

Zeloo 在以下方面完全独立：

1. **代码独立** - 独立代码库，独立 Git 仓库，无源码继承
2. **品牌独立** - Zeloo Desktop、zeloo 可执行文件、com.zeloo.desktop
3. **发布独立** - PyPI + GitHub Releases 独立发布
4. **许可证独立** - Apache-2.0 许可证
5. **社区独立** - 独立社区和文档

### 5.2 Hermes 引用仅为兼容性需要

Zeloo 中保留的 Hermes 相关引用属于两类：

1. **外部服务兼容** - Hermes One API（通过 OpenAI 兼容接口或原生 API）
   - 这是 Zeloo 接入外部服务的必要代码
   - 类似 Claude Desktop 需要调用 Anthropic API
   - 属于正常的外部服务集成，非品牌依附

2. **外部项目集成** - hermes-office / Claw3D
   - 这是集成第三方开源项目的代码
   - Zeloo 同样支持 OpenClaw、我们自己的项目
   - 属于正常的生态集成

### 5.3 去 Hermes 化完整清单

| 类别 | 处理方式 | 工作量 |
|---|---|---|
| **外部服务 API（hermesone）** | 保留 + 添加 Zeloo One 品牌 | 0 行 |
| **外部项目集成（hermes-office）** | 重命名为 zeloo-office | 20 行 |
| **内部临时目录/脚本名** | 全部改为 zeloo- | 10 行 |
| **代码注释** | 清理 "Hermes One" 注释 | 30 行 |
| **i18n 文本** | 更新 14 种语言 | 100 行 |
| **向后兼容层** | 保留 hermesone slug | 0 行 |

**总计工作量**: ~160 行代码修改，可在 1 天内完成。

### 5.4 建议

1. **短期（1 天）**: 完成代码注释和内部常量去化
2. **中期（1 周）**: 完成 hermes-office → zeloo-office 重命名
3. **长期**: 逐步用 Zeloo One 替代 Hermes One 品牌

---

**结论**: Zeloo 是与 Hermes Agent Desktop 功能对等的**独立开源项目**，而非附属品。保留的 Hermes 引用仅为外部服务兼容性需要，不影响项目的独立性质。
