"""Optional MCP server catalog.

Pre-configured MCP server definitions (command, args, env vars) for the
6 P1 priority servers: GitHub, Notion, Linear, Slack, Vercel, Supabase.

Callers can use :func:`get_server` to retrieve a definition and add it
to the running agent's MCP configuration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = [
    "MCPServerDefinition",
    "get_server",
    "list_servers",
    "get_all_servers",
]


@dataclass
class MCPServerDefinition:
    """A pre-configured MCP server definition."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""
    category: str = "general"
    docs_url: str = ""
    required_env: list[str] = field(default_factory=list)


_P1_SERVERS: dict[str, MCPServerDefinition] = {
    "github": MCPServerDefinition(
        name="github",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        description="GitHub MCP server — manage repos, issues, PRs, and code.",
        category="development",
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/github",
        required_env=["GITHUB_PERSONAL_ACCESS_TOKEN"],
    ),
    "notion": MCPServerDefinition(
        name="notion",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-notion"],
        env={"NOTION_API_KEY": ""},
        description="Notion MCP server — search and edit pages, databases, blocks.",
        category="productivity",
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/notion",
        required_env=["NOTION_API_KEY"],
    ),
    "linear": MCPServerDefinition(
        name="linear",
        command="npx",
        args=["-y", "@linear/mcp"],
        env={"LINEAR_API_KEY": ""},
        description="Linear MCP server — create and manage issues, projects, cycles.",
        category="development",
        docs_url="https://developers.linear.app/docs/mcp",
        required_env=["LINEAR_API_KEY"],
    ),
    "slack": MCPServerDefinition(
        name="slack",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={
            "SLACK_BOT_TOKEN": "",
            "SLACK_TEAM_ID": "",
        },
        description="Slack MCP server — search channels, post messages, read threads.",
        category="communication",
        docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/slack",
        required_env=["SLACK_BOT_TOKEN"],
    ),
    "vercel": MCPServerDefinition(
        name="vercel",
        command="npx",
        args=["-y", "@vercel/mcp-server"],
        env={"VERCEL_TOKEN": ""},
        description="Vercel MCP server — manage deployments, projects, domains, logs.",
        category="devops",
        docs_url="https://vercel.com/docs/mcp",
        required_env=["VERCEL_TOKEN"],
    ),
    "supabase": MCPServerDefinition(
        name="supabase",
        command="npx",
        args=["-y", "supabase-mcp-server"],
        env={
            "SUPABASE_URL": "",
            "SUPABASE_SERVICE_ROLE_KEY": "",
        },
        description="Supabase MCP server — query tables, run SQL, manage storage.",
        category="database",
        docs_url="https://supabase.com/docs/guides/mcp",
        required_env=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"],
    ),
}


def get_server(name: str) -> MCPServerDefinition | None:
    """Return the server definition for *name*, or None if not found."""
    return _P1_SERVERS.get(name.lower())


def list_servers() -> list[str]:
    """Return the names of all available P1 servers."""
    return sorted(_P1_SERVERS.keys())


def get_all_servers() -> dict[str, MCPServerDefinition]:
    """Return all P1 server definitions keyed by name."""
    return dict(_P1_SERVERS)


def _register_server(definition: MCPServerDefinition) -> None:
    """Register a server definition (internal use)."""
    _P1_SERVERS[definition.name] = definition


def _register_builtins() -> None:
    """Register all built-in MCP server definitions."""

    _register_server(
        MCPServerDefinition(
            name="airtable",
            command="uvx",
            args=[
                "--from",
                "git+https://github.com/ModelContextProtocol/servers.git",
                "mcp-airtable",
            ],
            env={
                "AIRTABLE_API_KEY": "",
                "AIRTABLE_BASE_ID": "",
            },
            description="Airtable MCP server — list bases, tables, records, and CRUD operations.",
            category="database",
            docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/airtable",
            required_env=["AIRTABLE_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="gitlab",
            command="uvx",
            args=[
                "--from",
                "git+https://github.com/ModelContextProtocol/servers.git",
                "mcp-gitlab",
            ],
            env={
                "GITLAB_TOKEN": "",
                "GITLAB_URL": "https://gitlab.com",
            },
            description="GitLab MCP server — projects, issues, MRs, pipelines, file operations.",
            category="development",
            docs_url="https://github.com/modelcontextprotocol/servers/tree/main/src/gitlab",
            required_env=["GITLAB_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="feishu",
            command="python",
            args=["-m", "optional_mcps.feishu_mcp"],
            env={
                "FEISHU_APP_ACCESS_TOKEN": "",
            },
            description="飞书 MCP server — 消息、日历、联系人、文档搜索。",
            category="communication",
            docs_url="https://open.feishu.cn/document/",
            required_env=["FEISHU_APP_ACCESS_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="twilio",
            command="python",
            args=["-m", "optional_mcps.twilio"],
            env={
                "TWILIO_ACCOUNT_SID": "",
                "TWILIO_AUTH_TOKEN": "",
            },
            description="Twilio MCP server — SMS, WhatsApp, Voice calls via Twilio API.",
            category="communication",
            docs_url="https://www.twilio.com/docs/",
            required_env=["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="discord",
            command="python",
            args=["-m", "optional_mcps.discord"],
            env={
                "DISCORD_BOT_TOKEN": "",
            },
            description="Discord MCP server — channels, messages, threads, guild management.",
            category="communication",
            docs_url="https://discord.com/developers/docs",
            required_env=["DISCORD_BOT_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="postgresql",
            command="python",
            args=["-m", "optional_mcps.postgresql"],
            env={
                "POSTGRES_HOST": "localhost",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DB": "postgres",
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": "",
            },
            description="PostgreSQL MCP server — read-only SQL queries, schema inspection.",
            category="database",
            docs_url="https://www.postgresql.org/docs/",
            required_env=["POSTGRES_PASSWORD"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="grafana",
            command="python",
            args=["-m", "optional_mcps.grafana"],
            env={
                "GRAFANA_TOKEN": "",
                "GRAFANA_URL": "http://localhost:3000",
            },
            description="Grafana MCP server — dashboards, alerts, Prometheus queries.",
            category="monitoring",
            docs_url="https://grafana.com/docs/grafana/latest/",
            required_env=["GRAFANA_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="elasticsearch",
            command="python",
            args=["-m", "optional_mcps.elasticsearch"],
            env={
                "ELASTICSEARCH_URL": "http://localhost:9200",
                "ELASTICSEARCH_USER": "",
                "ELASTICSEARCH_PASSWORD": "",
            },
            description="Elasticsearch MCP — search, index, aggregations, cluster health.",
            category="database",
            docs_url="https://www.elastic.co/guide/en/elasticsearch/reference/current/",
            required_env=["ELASTICSEARCH_URL"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="digitalocean",
            command="uvx",
            args=[
                "--from",
                "git+https://github.com/ModelContextProtocol/servers.git",
                "mcp-digitalocean",
            ],
            env={
                "DIGITALOCEAN_TOKEN": "",
            },
            description="DigitalOcean MCP — droplets, domains, floating IPs, volumes.",
            category="infrastructure",
            docs_url="https://docs.digitalocean.com/reference/api/",
            required_env=["DIGITALOCEAN_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="upstash",
            command="python",
            args=["-m", "optional_mcps.upstash"],
            env={
                "UPSTASH_REDIS_REST_URL": "",
                "UPSTASH_REDIS_REST_TOKEN": "",
            },
            description="Upstash Redis MCP — key-value, hash, list operations.",
            category="database",
            docs_url="https://upstash.com/docs/redis",
            required_env=["UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="resend",
            command="python",
            args=["-m", "optional_mcps.resend"],
            env={
                "RESEND_API_KEY": "",
            },
            description="Resend MCP — send transactional emails, manage domains.",
            category="communication",
            docs_url="https://resend.com/docs",
            required_env=["RESEND_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="kubernetes",
            command="python",
            args=["-m", "optional_mcps.kubernetes"],
            env={
                "KUBECONFIG": "",
                "KUBECTL_CONTEXT": "",
            },
            description="Kubernetes MCP — pods, services, deployments, logs, scaling.",
            category="infrastructure",
            docs_url="https://kubernetes.io/docs/reference/kubectl/",
            required_env=[],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="shopify",
            command="python",
            args=["-m", "optional_mcps.shopify"],
            env={
                "SHOPIFY_SHOP": "",
                "SHOPIFY_ACCESS_TOKEN": "",
            },
            description="Shopify MCP — products, orders, fulfillment management.",
            category="ecommerce",
            docs_url="https://shopify.dev/docs/api/admin-rest",
            required_env=["SHOPIFY_SHOP", "SHOPIFY_ACCESS_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="hubspot",
            command="python",
            args=["-m", "optional_mcps.hubspot"],
            env={
                "HUBSPOT_ACCESS_TOKEN": "",
            },
            description="HubSpot MCP — contacts, deals, tickets, search.",
            category="crm",
            docs_url="https://developers.hubspot.com/docs/api/overview",
            required_env=["HUBSPOT_ACCESS_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="intercom",
            command="python",
            args=["-m", "optional_mcps.intercom"],
            env={
                "INTERCOM_ACCESS_TOKEN": "",
            },
            description="Intercom MCP — conversations, contacts, messages.",
            category="communication",
            docs_url="https://developers.intercom.com/intercom-api-reference",
            required_env=["INTERCOM_ACCESS_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="asana",
            command="python",
            args=["-m", "optional_mcps.asana"],
            env={
                "ASANA_ACCESS_TOKEN": "",
                "ASANA_WORKSPACE_GID": "",
            },
            description="Asana MCP — projects, tasks, create/update/list.",
            category="project",
            docs_url="https://developers.asana.com/docs",
            required_env=["ASANA_ACCESS_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="aws",
            command="python",
            args=["-m", "optional_mcps.aws"],
            env={
                "AWS_REGION": "us-east-1",
                "AWS_ACCESS_KEY_ID": "",
                "AWS_SECRET_ACCESS_KEY": "",
            },
            description="AWS MCP — EC2, S3, Lambda, IAM via boto3.",
            category="infrastructure",
            docs_url="https://boto3.amazonaws.com/v1/documentation/api/latest/index.html",
            required_env=["AWS_ACCESS_KEY_ID"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="gcp",
            command="python",
            args=["-m", "optional_mcps.gcp"],
            env={
                "GCP_PROJECT": "",
                "GCP_REGION": "us-central1",
            },
            description="GCP MCP — Compute Engine, Cloud Storage, Cloud Functions, BigQuery.",
            category="infrastructure",
            docs_url="https://cloud.google.com/python/docs/reference",
            required_env=["GCP_PROJECT"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="pagerduty",
            command="python",
            args=["-m", "optional_mcps.pagerrduty"],
            env={
                "PAGERDUTY_TOKEN": "",
            },
            description="PagerDuty MCP — incidents, on-call, alerts.",
            category="monitoring",
            docs_url="https://developer.pagerduty.com/docs/rest-api-v2/rest-api",
            required_env=["PAGERDUTY_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="todoist",
            command="python",
            args=["-m", "optional_mcps.todoist"],
            env={
                "TODOIST_API_TOKEN": "",
            },
            description="Todoist MCP — tasks, projects, priorities.",
            category="project",
            docs_url="https://developer.todoist.com/rest/v2",
            required_env=["TODOIST_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="trello",
            command="python",
            args=["-m", "optional_mcps.trello"],
            env={
                "TRELLO_API_KEY": "",
                "TRELLO_TOKEN": "",
            },
            description="Trello MCP — boards, lists, cards, archives.",
            category="project",
            docs_url="https://developer.atlassian.com/cloud/trello/",
            required_env=["TRELLO_API_KEY", "TRELLO_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="clickup",
            command="python",
            args=["-m", "optional_mcps.clickup"],
            env={
                "CLICKUP_API_KEY": "",
            },
            description="ClickUp MCP — tasks, spaces, priorities.",
            category="project",
            docs_url="https://clickup.com/api",
            required_env=["CLICKUP_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="zendesk",
            command="python",
            args=["-m", "optional_mcps.zendesk"],
            env={
                "ZENDESK_SUBDOMAIN": "",
                "ZENDESK_EMAIL": "",
                "ZENDESK_API_TOKEN": "",
            },
            description="Zendesk MCP — tickets, users, support.",
            category="customer-support",
            docs_url="https://developer.zendesk.com/api-reference",
            required_env=["ZENDESK_SUBDOMAIN", "ZENDESK_EMAIL", "ZENDESK_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="github-native",
            command="python",
            args=["-m", "optional_mcps.github_native"],
            env={
                "GITHUB_TOKEN": "",
            },
            description="GitHub MCP native — repos, issues, PRs, Actions.",
            category="development",
            docs_url="https://docs.github.com/rest",
            required_env=["GITHUB_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="notion-native",
            command="python",
            args=["-m", "optional_mcps.notion_native"],
            env={
                "NOTION_API_KEY": "",
            },
            description="Notion native MCP — pages, databases, blocks, search.",
            category="knowledge",
            docs_url="https://developers.notion.com/",
            required_env=["NOTION_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="slack-native",
            command="python",
            args=["-m", "optional_mcps.slack_native"],
            env={
                "SLACK_BOT_TOKEN": "",
            },
            description="Slack native MCP — channels, messages, threads, search.",
            category="communication",
            docs_url="https://api.slack.com/web",
            required_env=["SLACK_BOT_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="freshdesk",
            command="python",
            args=["-m", "optional_mcps.freshdesk"],
            env={
                "FRESHDESK_DOMAIN": "",
                "FRESHDESK_API_KEY": "",
            },
            description="Freshdesk MCP — tickets, agents, groups.",
            category="customer-support",
            docs_url="https://developers.freshdesk.com/api-reference",
            required_env=["FRESHDESK_DOMAIN", "FRESHDESK_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="monday",
            command="python",
            args=["-m", "optional_mcps.monday"],
            env={
                "MONDAY_API_KEY": "",
            },
            description="Monday.com MCP — boards, items, groups, search.",
            category="project",
            docs_url="https://api.monday.com/api-docs",
            required_env=["MONDAY_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="pipedrive",
            command="python",
            args=["-m", "optional_mcps.pipedrive"],
            env={
                "PIPEDRIVE_API_TOKEN": "",
                "PIPEDRIVE_DOMAIN": "api.pipedrive.com/v1",
            },
            description="Pipedrive MCP — deals, contacts, pipelines.",
            category="crm",
            docs_url="https://developers.pipedrive.com/docs",
            required_env=["PIPEDRIVE_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="strava",
            command="python",
            args=["-m", "optional_mcps.strava"],
            env={
                "STRAVA_CLIENT_ID": "",
                "STRAVA_CLIENT_SECRET": "",
                "STRAVA_REFRESH_TOKEN": "",
            },
            description="Strava MCP — activities, segments, clubs.",
            category="fitness",
            docs_url="https://developers.strava.com/docs",
            required_env=["STRAVA_CLIENT_ID"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="jumpcloud",
            command="python",
            args=["-m", "optional_mcps.jumpsend"],
            env={
                "JUMPCLOUD_API_KEY": "",
            },
            description="JumpCloud MCP — users, groups, devices, policies.",
            category="security",
            docs_url="https://developers.jumpcloud.com/docs",
            required_env=["JUMPCLOUD_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="linear-extra",
            command="python",
            args=["-m", "optional_mcps.linear_extra"],
            env={
                "LINEAR_API_KEY": "",
            },
            description="Linear extra MCP — workflows, cycles, projects, labels.",
            category="project",
            docs_url="https://developers.linear.app/docs/api/graphql/overview",
            required_env=["LINEAR_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="freshbooks",
            command="python",
            args=["-m", "optional_mcps.freshbooks"],
            env={
                "FRESHBOOKS_CLIENT_ID": "",
                "FRESHBOOKS_CLIENT_SECRET": "",
                "FRESHBOOKS_REFRESH_TOKEN": "",
                "FRESHBOOKS_ACCOUNT_ID": "",
            },
            description="FreshBooks MCP — clients, invoices, payments, expenses.",
            category="finance",
            docs_url="https://www.freshbooks.com/api",
            required_env=["FRESHBOOKS_CLIENT_ID"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="quickbooks",
            command="python",
            args=["-m", "optional_mcps.quickbooks"],
            env={
                "QUICKBOOKS_CLIENT_ID": "",
                "QUICKBOOKS_CLIENT_SECRET": "",
                "QUICKBOOKS_REFRESH_TOKEN": "",
                "QUICKBOOKS_REALM_ID": "",
            },
            description="QuickBooks MCP — customers, invoices, accounts, P&L reports.",
            category="finance",
            docs_url="https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/account",
            required_env=["QUICKBOOKS_CLIENT_ID"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="plaid",
            command="python",
            args=["-m", "optional_mcps.plaid"],
            env={
                "PLAID_CLIENT_ID": "",
                "PLAID_SECRET": "",
                "PLAID_ENV": "sandbox",
            },
            description="Plaid MCP — banking accounts, transactions, transfers.",
            category="finance",
            docs_url="https://plaid.com/docs/api/",
            required_env=["PLAID_CLIENT_ID"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="brex",
            command="python",
            args=["-m", "optional_mcps.brex"],
            env={
                "BREX_API_TOKEN": "",
            },
            description="Brex MCP — corporate cards, expenses, reimbursements.",
            category="finance",
            docs_url="https://developer.brex.com",
            required_env=["BREX_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="ramp",
            command="python",
            args=["-m", "optional_mcps.ramp"],
            env={
                "RAMP_API_KEY": "",
            },
            description="Ramp MCP — corporate cards, transactions, bills, departments.",
            category="finance",
            docs_url="https://docs.ramp.com/reference",
            required_env=["RAMP_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="mercury",
            command="python",
            args=["-m", "optional_mcps.mercury"],
            env={
                "MERCURY_API_TOKEN": "",
            },
            description="Mercury MCP — startup banking, accounts, transactions.",
            category="finance",
            docs_url="https://mercury.com/api",
            required_env=["MERCURY_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="n8n",
            command="python",
            args=["-m", "optional_mcps.n8n"],
            env={
                "N8N_BASE_URL": "http://localhost:5678",
                "N8N_API_KEY": "",
            },
            description="n8n MCP — workflows, executions, activation.",
            category="automation",
            docs_url="https://docs.n8n.io/api/",
            required_env=["N8N_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="make",
            command="python",
            args=["-m", "optional_mcps.make"],
            env={
                "MAKE_API_KEY": "",
                "MAKE_ZONE": "us1",
            },
            description="Make.com MCP — scenarios, apps, runs.",
            category="automation",
            docs_url="https://www.make.com/en/api-documentation",
            required_env=["MAKE_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="zapier",
            command="python",
            args=["-m", "optional_mcps.zapier"],
            env={
                "ZAPIER_API_KEY": "",
            },
            description="Zapier MCP — zaps, actions, history.",
            category="automation",
            docs_url="https://platform.zapier.com/cli",
            required_env=["ZAPIER_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="shortcut",
            command="python",
            args=["-m", "optional_mcps.shortcut"],
            env={
                "SHORTCUT_API_TOKEN": "",
            },
            description="Shortcut MCP — stories, workflows, members.",
            category="project",
            docs_url="https://developer.shortcut.com",
            required_env=["SHORTCUT_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="aha",
            command="python",
            args=["-m", "optional_mcps.aha"],
            env={
                "AHA_API_TOKEN": "",
                "AHA_DOMAIN": "",
            },
            description="Aha! MCP — products, features, releases, ideas.",
            category="product",
            docs_url="https://www.aha.io/api",
            required_env=["AHA_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="productboard",
            command="python",
            args=["-m", "optional_mcps.productboard"],
            env={
                "PRODUCTBOARD_API_TOKEN": "",
            },
            description="Productboard MCP — products, features, objectives, initiatives.",
            category="product",
            docs_url="https://developer.productboard.com",
            required_env=["PRODUCTBOARD_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="confluence",
            command="python",
            args=["-m", "optional_mcps.confluence"],
            env={
                "CONFLUENCE_DOMAIN": "",
                "CONFLUENCE_EMAIL": "",
                "CONFLUENCE_API_TOKEN": "",
            },
            description="Confluence MCP — spaces, pages, search.",
            category="knowledge",
            docs_url="https://developer.atlassian.com/cloud/confluence/rest/v2/intro/",
            required_env=["CONFLUENCE_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="coda",
            command="python",
            args=["-m", "optional_mcps.coda"],
            env={
                "CODA_API_TOKEN": "",
            },
            description="Coda MCP — docs, tables, rows, search.",
            category="knowledge",
            docs_url="https://coda.io/developers/apis/v1",
            required_env=["CODA_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="contentful",
            command="python",
            args=["-m", "optional_mcps.contentful"],
            env={
                "CONTENTFUL_SPACE_ID": "",
                "CONTENTFUL_ACCESS_TOKEN": "",
                "CONTENTFUL_ENVIRONMENT": "master",
            },
            description="Contentful MCP — content types, entries, assets.",
            category="knowledge",
            docs_url="https://www.contentful.com/developers/docs/references/content-management-api/",
            required_env=["CONTENTFUL_SPACE_ID", "CONTENTFUL_ACCESS_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="sanity",
            command="python",
            args=["-m", "optional_mcps.sanity"],
            env={
                "SANITY_PROJECT_ID": "",
                "SANITY_DATASET": "production",
                "SANITY_API_TOKEN": "",
            },
            description="Sanity MCP — GROQ queries, documents, schemas.",
            category="knowledge",
            docs_url="https://www.sanity.io/docs/api-versioning",
            required_env=["SANITY_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="mixpanel",
            command="python",
            args=["-m", "optional_mcps.mixpanel"],
            env={
                "MIXPANEL_API_TOKEN": "",
                "MIXPANEL_PROJECT_ID": "",
            },
            description="Mixpanel MCP — events, segmentation, funnel, retention.",
            category="analytics",
            docs_url="https://developer.mixpanel.com/reference/overview",
            required_env=["MIXPANEL_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="amplitude",
            command="python",
            args=["-m", "optional_mcps.amplitude"],
            env={
                "AMPLITUDE_API_KEY": "",
                "AMPLITUDE_SECRET_KEY": "",
            },
            description="Amplitude MCP — events, funnels, user activity.",
            category="analytics",
            docs_url="https://developers.amplitude.com/",
            required_env=["AMPLITUDE_API_KEY", "AMPLITUDE_SECRET_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="segment",
            command="python",
            args=["-m", "optional_mcps.segment_mcp"],
            env={
                "SEGMENT_WRITE_KEY": "",
            },
            description="Segment MCP — track, identify, group, batch events.",
            category="analytics",
            docs_url="https://segment.com/docs/connections/sources/catalog/libraries/server/http-api/",
            required_env=["SEGMENT_WRITE_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="posthog",
            command="python",
            args=["-m", "optional_mcps.posthog"],
            env={
                "POSTHOG_API_KEY": "",
                "POSTHOG_PROJECT_ID": "",
                "POSTHOG_HOST": "https://app.posthog.com",
            },
            description="PostHog MCP — events, feature flags, HogQL queries.",
            category="analytics",
            docs_url="https://posthog.com/docs/api",
            required_env=["POSTHOG_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="wrike",
            command="python",
            args=["-m", "optional_mcps.wrike"],
            env={
                "WRIKE_API_TOKEN": "",
            },
            description="Wrike MCP — folders, tasks, comments.",
            category="project",
            docs_url="https://developers.wrike.com/",
            required_env=["WRIKE_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="bitbucket",
            command="python",
            args=["-m", "optional_mcps.bitbucket"],
            env={
                "BITBUCKET_USERNAME": "",
                "BITBUCKET_APP_PASSWORD": "",
                "BITBUCKET_WORKSPACE": "",
            },
            description="Bitbucket MCP — repos, PRs, issues, pipelines.",
            category="development",
            docs_url="https://developer.atlassian.com/cloud/bitbucket/rest/v2/intro/",
            required_env=["BITBUCKET_USERNAME", "BITBUCKET_APP_PASSWORD"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="jenkins",
            command="python",
            args=["-m", "optional_mcps.jenkins"],
            env={
                "JENKINS_URL": "http://localhost:8080",
                "JENKINS_USER": "",
                "JENKINS_API_TOKEN": "",
            },
            description="Jenkins MCP — jobs, builds, nodes.",
            category="ci-cd",
            docs_url="https://www.jenkins.io/doc/book/using/remote-access-api/",
            required_env=["JENKINS_USER", "JENKINS_API_TOKEN"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="octopus",
            command="python",
            args=["-m", "optional_mcps.octopus"],
            env={
                "OCTOPUS_URL": "",
                "OCTOPUS_API_KEY": "",
                "OCTOPUS_SPACE_NAME": "",
            },
            description="Octopus Deploy MCP — projects, releases, deployments.",
            category="ci-cd",
            docs_url="https://octopus.com/docs/octopus-rest-api",
            required_env=["OCTOPUS_URL", "OCTOPUS_API_KEY"],
        )
    )
    _register_server(
        MCPServerDefinition(
            name="bamboo",
            command="python",
            args=["-m", "optional_mcps.bamboo"],
            env={
                "BAMBOO_URL": "",
                "BAMBOO_USER": "",
                "BAMBOO_API_TOKEN": "",
            },
            description="Atlassian Bamboo MCP — plans, branches, builds.",
            category="ci-cd",
            docs_url="https://docs.atlassian.com/bamboo/REST/latest/",
            required_env=["BAMBOO_URL", "BAMBOO_USER", "BAMBOO_API_TOKEN"],
        )
    )


_register_builtins()
