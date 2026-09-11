# Zeloo Agent — 开发者文档

> **Zeloo** — 与你共同成长的智能体。
> 一个自托管、自进化的常驻型 AI Agent 运行时框架。

## 核心特性

- **自进化**：从每个会话中学习，持续改进
- **多平台**：连接 Telegram、Discord、Slack、企业微信、钉钉、飞书等
- **持久记忆**：跨会话存储上下文
- **渐进技能**：自动开发和精炼技能
- **可扩展架构**：插件、MCP、自定义工具

## 快速开始

```bash
# 克隆仓库
git clone <Zeloo-repo-url>
cd Zeloo

# 使用 uv 安装
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 启动 CLI
Zeloo

# 常用命令
Zeloo config show     # 查看配置
Zeloo doctor          # 诊断检查
Zeloo sessions        # 列出会话
Zeloo skills          # 列出技能
```

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      用户交互层                              │
│        CLI / TUI / 网关 (Telegram/Discord 等)              │
├─────────────────────────────────────────────────────────────┤
│                      Agent 核心层                            │
│   System Prompt (三层) │ 对话循环 │ 工具系统               │
├─────────────────────────────────────────────────────────────┤
│                      能力扩展层                              │
│    Skills │ 记忆 │ Cron │ 子代理 │ MCP │ i18n           │
├─────────────────────────────────────────────────────────────┤
│                      基础设施层                              │
│   SQLite(WAL+FTS5) │ 7种终端后端 │ 多Provider路由         │
└─────────────────────────────────────────────────────────────┘
```

## 三层 System Prompt 设计

| 层级 | 名称 | 内容 | 缓存策略 |
|------|------|------|---------|
| Stable | 稳定层 | 身份、工具指导、技能提示 | 永久前缀缓存命中 |
| Context | 上下文层 | 项目文件、平台提示 | 按项目切换失效 |
| Volatile | 易变层 | 技能索引、记忆快照 | 每轮重算 |

## 技术栈

| 类别 | 技术 |
|------|------|
| 主语言 | Python 3.11+ |
| 包管理 | uv |
| 数据库 | SQLite (WAL + FTS5) |
| 前端 | Node.js 22+ / pnpm |
| LLM | OpenAI 兼容，支持 30+ Provider |

## 开发指南

```bash
# 运行测试
python -m pytest tests/ -v

# 代码检查
uv run ruff check .

# 添加新工具
# 编辑 tools/registry.py 并创建 tools/my_tool.py
```

## 贡献指南

参见 [CONTRIBUTING.md](./CONTRIBUTING.md) 了解开发规范。

## 许可证

MIT — 参见 [LICENSE](./LICENSE)
