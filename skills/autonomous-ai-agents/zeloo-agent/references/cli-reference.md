# Zeloo CLI Reference

Live sources when anything looks stale: `Zeloo --help`, `Zeloo <command> --help`,
https://Zeloo-agent.nousresearch.com/docs/reference/cli-commands

### Global Flags

```
Zeloo [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
Zeloo chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
Zeloo setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
Zeloo model                Interactive model/provider picker
Zeloo fallback [add|remove|list]  Fallback provider chain
Zeloo config [show|edit|get|set|unset|path|env-path|check|migrate]
Zeloo login / logout       OAuth sign-in / clear stored auth
Zeloo doctor [--fix]       Check dependencies and config
Zeloo status [--all]       Component status
```

### Tools & Skills

```
Zeloo tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

Zeloo skills list|browse|search QUERY|inspect ID
Zeloo skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
Zeloo skills config        Enable/disable skills per platform
Zeloo skills check|update|uninstall|publish PATH
Zeloo skills tap add REPO  Add a GitHub repo as a skill source
Zeloo bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
Zeloo mcp add NAME (--url or --command) | remove | list | test NAME
Zeloo mcp catalog | install NAME     Curated catalog install
Zeloo mcp configure NAME             Toggle tool selection
Zeloo mcp serve                      Run Zeloo as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
Zeloo gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `Zeloo photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://Zeloo-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
Zeloo sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
Zeloo cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
Zeloo webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
Zeloo profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
Zeloo profile rename A B | alias NAME | export NAME | import FILE
```

### Credentials & Pools

```
Zeloo auth                 Interactive credential manager
Zeloo auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
Zeloo auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
Zeloo desktop / gui        Native desktop app
Zeloo dashboard            Web admin panel + embedded chat (--stop / --status)
Zeloo proxy                OpenAI-compatible local proxy backed by an OAuth provider
Zeloo portal               Quick setup / sign in via Nous Portal
Zeloo kanban <verb>        Multi-agent work-queue board
Zeloo project              Named multi-folder workspaces
Zeloo skin list|use|set    Switch/tweak skins (see references/themes.md)
Zeloo pets <verb>          Pet mascots (see references/petdex.md)
Zeloo memory setup|status|off|reset   Memory provider
Zeloo secrets bitwarden|onepassword   External secret stores
Zeloo moa                  Mixture-of-Agents slots
Zeloo hooks / security / backup / import / checkpoints / console
Zeloo logs [-f] [errors]   View agent/error logs
Zeloo send                 One-off message through a gateway platform
Zeloo pairing / plugins / insights / journey / computer-use
Zeloo acp                  ACP server (IDE integration)
Zeloo completion bash|zsh|fish
Zeloo update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `Zeloo photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `Zeloo config edit` · [Configuration docs](https://Zeloo-agent.nousresearch.com/docs/user-guide/configuration) |
| Tools / toolsets | `Zeloo tools list` · [Tools reference](https://Zeloo-agent.nousresearch.com/docs/reference/tools-reference) |
| Skills catalog | `Zeloo skills browse` · [Skills catalog](https://Zeloo-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `Zeloo model` · [Providers guide](https://Zeloo-agent.nousresearch.com/docs/integrations/providers) |
| Env variables | `Zeloo config env-path` · [Env vars reference](https://Zeloo-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway logs | `~/.Zeloo/logs/gateway.log` (or `Zeloo logs`) |
| Sessions | `Zeloo sessions browse` (reads state.db) |
