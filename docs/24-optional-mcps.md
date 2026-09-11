# 24. optional-mcps 可选 MCP 服务器

> 可选 MCP 服务器设计目标 **65 个**，目前已实现 **18 个**（详见 24.6 已实现清单）。每个 MCP 服务器遵循统一结构。

> **官方 Catalog**：所有 MCP 服务器经人工 review 后进入官方 Catalog，确保质量与安全。

## 24.1 服务器总览（目标 65 个）

| 类别 | 服务器 | 优先级 | 实现状态 |
|------|--------|--------|----------|
| 数据 | Notion, Airtable, Supabase, PostgreSQL, PlanetScale, Google Sheets | P1 | Notion ✅ / Supabase ✅ / Airtable ✅ |
| 通信 | Slack, Discord, Gmail, Twilio, Intercom, Feishu | P1 | Slack ✅ / Gmail ✅ |
| 开发 | GitHub, GitLab, Jira, Linear, Figma, CircleCI, Sentry, Bitbucket | P1 | GitHub ✅ / GitLab ✅ / Jira ✅ / Linear ✅ / Figma ✅ / CircleCI ✅ / Sentry ✅ |
| 云平台 | AWS Knowledge, Vercel, Netlify, Railway, NeatSQL, Fly.io | P1 | Vercel ✅ / Railway ✅ |
| 监控 | Datadog, Grafana, New Relic, Cloudflare | P2 | Datadog ✅ |
| 商业工具 | Stripe, PayPal, Plaid, Square, Shopify | P2 | Stripe ✅ |
| 设计 | Figma, Canva, Gamma, Loom | P2 | Figma ✅ |
| 自动化 | n8n, Zapier, Make, PagerDuty | P2 | ❌ |
| 搜索 | Deepwiki, Brave, Exa | P3 | ❌ |
| 其他 | Wolfram, WordPress, Unreal Engine, RAG | P3 | ❌ |

---

## 24.2 服务器目录结构

每个 MCP 服务器遵循统一结构：

```
optional-mcps/<name>/
├── __init__.py            # 包初始化
├── server.py              # MCP 服务器实现
├── tools.py               # 工具定义
├── auth.py                # 认证逻辑
├── README.md              # 服务器说明
├── pyproject.toml         # 依赖锁定
└── tests/
    └── test_server.py
```

---

## 24.3 MCP 服务器模板

```python
# optional-mcps/<name>/server.py

from mcp.server import MCPServer
from mcp.types import Tool

class MyServiceServer(MCPServer):
    name = "mcp-<name>"
    version = "1.0.0"

    def __init__(self, api_key: str, **kwargs):
        super().__init__()
        self.api_key = api_key
        self._register_tools()

    def _register_tools(self):
        self.add_tool(Tool(
            name="my_action",
            description="执行某操作",
            inputSchema={
                "type": "object",
                "properties": {
                    "param": {"type": "string"}
                }
            },
            handler=self._my_action,
        ))

    async def _my_action(self, arguments: dict) -> dict:
        # 调用第三方 API
        result = await self._call_api(arguments["param"])
        return {"result": result}


if __name__ == "__main__":
    import os
    server = MyServiceServer(api_key=os.environ["MY_SERVICE_API_KEY"])
    server.run()
```

---

## 24.4 高优先级 MCP 服务器

### 24.4.1 GitHub MCP

```markdown
# optional-mcps/github/README.md
## 工具
- `github_list_repos`: 列出仓库
- `github_get_issue`: 获取 Issue
- `github_create_issue`: 创建 Issue
- `github_create_pr`: 创建 Pull Request
- `github_review_pr`: 审查 PR
- `github_list_workflows`: 列出 Actions 工作流
- `github_trigger_workflow`: 触发工作流
- `github_get_file`: 获取文件内容
- `github_update_file`: 更新文件
```

### 24.4.2 Notion MCP

```markdown
## 工具
- `notion_search_pages`: 搜索页面
- `notion_get_page`: 获取页面内容
- `notion_create_page`: 创建页面
- `notion_append_block`: 添加块
- `notion_query_database`: 查询数据库
- `notion_create_database_item`: 创建数据库条目
```

### 24.4.3 Linear MCP

```markdown
## 工具
- `linear_list_issues`: 列出 Issue
- `linear_create_issue`: 创建 Issue
- `linear_update_issue`: 更新 Issue
- `linear_get_issue`: 获取 Issue 详情
- `linear_create_comment`: 创建评论
```

### 24.4.4 Stripe MCP

```markdown
## 工具
- `stripe_get_balance`: 获取余额
- `stripe_list_customers`: 列出客户
- `stripe_create_customer`: 创建客户
- `stripe_create_payment_intent`: 创建支付意图
- `stripe_refund`: 退款
- `stripe_get_subscription`: 获取订阅
```

---

## 24.5 配置格式

```yaml
# config.yaml
mcp:
  servers:
    - name: github
      type: optional-mcp
      path: optional-mcps/github
      env:
        GITHUB_TOKEN: ${GITHUB_TOKEN}
    - name: notion
      type: optional-mcp
      path: optional-mcps/notion
      env:
        NOTION_API_KEY: ${NOTION_API_KEY}
    - name: linear
      type: optional-mcp
      path: optional-mcps/linear
      env:
        LINEAR_API_KEY: ${LINEAR_API_KEY}
```

---

## 24.6 已实现清单（18 个）

当前实际实现的 18 个 MCP 服务器（含基础设施 2 个）：

| 服务器 | 文件 | 主要工具 |
|--------|------|----------|
| **GitHub** | `github.py` | `github_list_issues` / `github_create_pr` / `github_search_code` |
| **GitLab** | `gitlab.py` | `gitlab_list_projects` / `gitlab_list_issues` / `gitlab_list_merge_requests` |
| **Gmail** | `gmail.py` | `gmail_list_messages` / `gmail_send_message` / `gmail_search` |
| **Notion** | `notion.py` | `notion_search` / `notion_create_page` / `notion_query_database` |
| **Slack** | `slack.py` | `slack_list_channels` / `slack_post_message` / `slack_history` |
| **Jira** | `jira.py` | `jira_list_issues` / `jira_create_issue` / `jira_transition` |
| **Linear** | `linear.py` | `linear_list_issues` / `linear_create_issue` / `linear_update_issue` |
| **Figma** | `figma.py` | `figma_get_file` / `figma_list_comments` / `figma_post_comment` |
| **Vercel** | `vercel.py` | `vercel_list_deployments` / `vercel_create_deployment` |
| **Supabase** | `supabase.py` | `supabase_list_tables` / `supabase_select` / `supabase_insert` / `supabase_update` / `supabase_delete` 等 10 个工具 |
| **Sentry** | `sentry.py` | `sentry_list_issues` / `sentry_get_event` |
| **Stripe** | `stripe.py` | `stripe_get_balance` / `stripe_create_payment_intent` / `stripe_refund` |
| **Datadog** | `datadog.py` | `datadog_query_metrics` / `datadog_list_dashboards` |
| **CircleCI** | `circleci.py` | `circleci_list_pipelines` / `circleci_trigger_workflow` |
| **Railway** | `railway.py` | `railway_list_services` / `railway_deploy` |
| **Airtable** | `airtable.py` | `airtable_list_bases` / `airtable_list_tables` / `airtable_list_records` 等 8 个工具 |
| **server_registry** | `server_registry.py` | 服务器注册表（register_server / list_servers / get_server） |
| **base** | `base.py` | `MCPServer` ABC 基类 |

所有服务器均位于 `optional_mcps/` 目录，每个为单一 .py 文件（非子目录结构）。

---

## 24.7 开发优先级

| 优先级 | 服务器 |
|--------|--------|
| P1 | GitHub ✅, GitLab ✅, Notion ✅, Linear ✅, Slack ✅, Vercel ✅, Supabase ✅, Sentry ✅, Airtable ✅ |
| P2 | Stripe ✅, Figma ✅, Datadog ✅, CircleCI ✅, Jira ✅, Gmail ✅, Railway ✅ |
| P3 | 其他 47+ 服务器（Discord / Twilio / Intercom / Grafana / PayPal 等） |
