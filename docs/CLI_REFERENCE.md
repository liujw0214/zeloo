# Zeloo CLI Reference

> Complete command index for the `Zeloo` binary (entry point: `cli.py`).
> All subcommands support `--help` for the canonical options list.

## Table of Contents

- [Core Conversation](#core-conversation)
- [Administration](#administration)
- [Status & Diagnostics](#status--diagnostics)
- [Tools & Skills](#tools--skills)
- [Memory](#memory)
- [Providers](#providers)
- [Workspace](#workspace)
- [Operations](#operations)
- [Helpers](#helpers)

---

## Core Conversation

### `Zeloo chat`

Start an interactive REPL with the agent.

```bash
Zeloo chat [--model MODEL] [--provider PROVIDER] [--profile PROFILE]
           [--no-tools] [--no-memory] [--cwd DIR] [--resume SESSION_ID]
           [--max-iterations N] [--temperature T] [--system-prompt SP]
```

| Option | Description |
|--------|-------------|
| `--model` | Override the default model |
| `--provider` | Override the default provider |
| `--profile` | Use a named gateway profile |
| `--no-tools` | Disable all tool calls (pure chat) |
| `--no-memory` | Do not read/write persistent memory |
| `--resume` | Continue an existing session |

Examples:

```bash
Zeloo chat
Zeloo chat --model claude-3-5-sonnet --provider anthropic
Zeloo chat --profile code_reviewer --resume sess_abc123
```

### `Zeloo tui`

Launch the full-screen Textual TUI.

```bash
Zeloo tui [--model MODEL] [--provider PROVIDER] [--theme THEME]
          [--keymap emacs|vim] [--no-mouse]
```

| Option | Description |
|--------|-------------|
| `--theme` | `dark`, `light`, or `high-contrast` |
| `--keymap` | Keybinding preset |
| `--no-mouse` | Disable mouse capture (useful over SSH) |

### `Zeloo serve`

Run the OpenAI-compatible HTTP API server.

```bash
Zeloo serve [--host 0.0.0.0] [--port 8080] [--workers N] [--reload]
            [--api-key KEY] [--cors-origins ORIGIN]
```

### `Zeloo z`

One-shot non-interactive question (no REPL, prints answer and exits).

```bash
Zeloo z "Explain this stack trace" [--model MODEL] [--max-iterations N]
```

---

## Administration

### `Zeloo setup`

First-run wizard. Creates `~/.Zeloo/`, writes `config.yaml`, and seeds the
default workspace.

```bash
Zeloo setup [--non-interactive] [--config PATH] [--workspace NAME]
```

### `Zeloo config`

Inspect / edit the active configuration.

```bash
Zeloo config show [--section llm|agent|memory|skills|browser|mcp|...]
Zeloo config get <key.path>
Zeloo config set <key.path> <value>
Zeloo config unset <key.path>
Zeloo config validate [--strict]
```

### `Zeloo auth`

Manage provider authentication credentials.

```bash
Zeloo auth list
Zeloo auth add <provider> [--token TOKEN | --oauth | --device]
Zeloo auth remove <provider>
Zeloo auth rotate <provider>
```

### `Zeloo login` / `Zeloo logout`

Convenience wrappers for `auth add` / `auth remove` with environment-variable
hints.

```bash
Zeloo login openai --token sk-...
Zeloo logout openai
```

### `Zeloo verify`

Re-run health checks for a specific provider or the whole stack.

```bash
Zeloo verify [--provider PROVIDER] [--include-tls] [--strict]
```

---

## Status & Diagnostics

### `Zeloo status`

Compact summary of runtime state (active profile, model, workspace, version).

```bash
Zeloo status [--json] [--quiet]
```

### `Zeloo doctor`

Deeper diagnostic — checks Python version, dependencies, credentials,
file permissions, network reachability.

```bash
Zeloo doctor [--fix] [--json]
```

### `Zeloo sync`

Re-sync the current workspace (memory, skills, plugins).

```bash
Zeloo sync [--memory] [--skills] [--plugins] [--force]
```

### `Zeloo sessions`

List / inspect / delete session history.

```bash
Zeloo sessions list [--limit N] [--since DATE]
Zeloo sessions show <session_id>
Zeloo sessions delete <session_id>
Zeloo sessions prune --keep-days N
```

### `Zeloo logs`

Tail or dump logs from the active workspace.

```bash
Zeloo logs [--tail] [--level DEBUG|INFO|WARN|ERROR] [--since 1h]
           [--output PATH]
```

### `Zeloo metrics`

Print Prometheus-style metrics (token usage, latency, error counts).

```bash
Zeloo metrics [--format text|json|prometheus] [--window 24h]
```

---

## Tools & Skills

### `Zeloo tools`

Browse, inspect, and toggle tools registered with the agent.

```bash
Zeloo tools list [--category browser|file|code|mcp|integration]
Zeloo tools show <tool_name>
Zeloo tools enable <tool_name>
Zeloo tools disable <tool_name>
```

### `Zeloo skills`

Manage skill packs (workflow documents).

```bash
Zeloo skills list [--installed] [--available]
Zeloo skills install <name>
Zeloo skills remove <name>
Zeloo skills show <name>
Zeloo skills validate <path>
```

### `Zeloo mcp`

Manage Model Context Protocol servers.

```bash
Zeloo mcp list
Zeloo mcp add --name N --transport stdio|http --url URL [--headers K=V]
Zeloo mcp remove <name>
Zeloo mcp restart <name>
Zeloo mcp login <name>            # device-code OAuth flow
Zeloo mcp discover [--auto]       # auto-discover local servers
```

### `Zeloo browser`

Configure / launch the headless browser subsystem.

```bash
Zeloo browser status
Zeloo browser install [--channel chromium|chrome|firefox]
Zeloo browser set backend <playwright|firecrawl|browserbase|camofox|...>
```

### `Zeloo plugins`

Discover and enable plugin extensions.

```bash
Zeloo plugins list
Zeloo plugins enable <plugin>
Zeloo plugins disable <plugin>
Zeloo plugins info <plugin>
```

### `Zeloo hooks`

Inspect pre/post hook chains attached to events.

```bash
Zeloo hooks list
Zeloo hooks add --event E --command C
Zeloo hooks remove <hook_id>
```

---

## Memory

### `Zeloo memory`

Inspect / edit the persistent memory store.

```bash
Zeloo memory show [--section USER|MEMORY|FACTS]
Zeloo memory add <text> [--tag TAG]
Zeloo memory search <query> [--limit N]
Zeloo memory forget <id>
Zeloo memory gc [--dry-run]
Zeloo memory compress [--use-llm]
Zeloo memory export <file>
Zeloo memory import <file>
```

### `Zeloo journey`

Track multi-step journeys / todos.

```bash
Zeloo journey list
Zeloo journey start "Migrate DB"
Zeloo journey step <id> --note "..."
Zeloo journey finish <id>
```

### `Zeloo goals`

Long-lived objectives.

```bash
Zeloo goals list
Zeloo goals add "Reduce p95 latency to <500ms"
Zeloo goals mark <id> --progress 0..1
```

---

## Providers

### `Zeloo model`

Switch, list, or inspect the active model.

```bash
Zeloo model list
Zeloo model current
Zeloo model set <model_id>
Zeloo model info <model_id>
Zeloo model bench <model_id> [--samples N]
```

### `Zeloo fallback`

Manage the provider fallback chain.

```bash
Zeloo fallback show
Zeloo fallback set --chain "primary,secondary,tertiary"
Zeloo fallback add <provider> --position N
Zeloo fallback remove <provider>
Zeloo fallback test
```

---

## Workspace

### `Zeloo workspace`

List, create, switch, archive, restore, tag, delete workspaces.

```bash
Zeloo workspace list [--tag TAG]
Zeloo workspace create <name> [--from <source>]
Zeloo workspace switch <name>
Zeloo workspace archive <name>
Zeloo workspace restore <archive> --as <name>
Zeloo workspace add-tag <name> <tag>
Zeloo workspace remove-tag <name> <tag>
Zeloo workspace delete <name> [--no-snapshot]
```

### `Zeloo profile`

Manage per-workspace agent profiles (model + toolset).

```bash
Zeloo profile list
Zeloo profile show <name>
Zeloo profile create <name> --model M --toolsets T1,T2
Zeloo profile delete <name>
```

### `Zeloo worktree`

git worktree helpers scoped to a workspace.

```bash
Zeloo worktree list
Zeloo worktree add <branch> [--base main]
Zeloo worktree remove <branch>
```

### `Zeloo init`

Bootstrap a new project inside the current workspace.

```bash
Zeloo init [--template python|node|rust|go] [--no-git]
```

### `Zeloo export` / `Zeloo import`

Serialize / restore a workspace bundle (memory + skills + config).

```bash
Zeloo export <workspace> --out bundle.tar.zst
Zeloo import <bundle.tar.zst> --as <workspace>
```

### `Zeloo reset`

Wipe the current workspace state (keeps the directory).

```bash
Zeloo reset [--memory] [--skills] [--sessions] [--all] [--confirm]
```

---

## Operations

### `Zeloo install`

Install Zeloo as a system service (systemd unit, launchd plist, or Windows
service).

```bash
Zeloo install [--user] [--start] [--enable]
```

### `Zeloo uninstall`

Remove the service installation.

```bash
Zeloo uninstall [--purge-config]
```

### `Zeloo update`

Self-update the `Zeloo` binary in place.

```bash
Zeloo update [--channel stable|beta|nightly] [--check-only]
```

### `Zeloo repair`

Re-install missing dependencies, regenerate caches, fix permissions.

```bash
Zeloo repair [--python] [--deps] [--caches] [--permissions] [--all]
```

### `Zeloo backup`

Snapshot a workspace to `~/.Zeloo/archive/`.

```bash
Zeloo backup <workspace> [--label milestone] [--exclude PATTERNS]
```

### `Zeloo dump`

Diagnostic bundle for bug reports.

```bash
Zeloo dump [--out PATH] [--redact-secrets]
```

### `Zeloo secrets`

Audit, rotate, or scrub secrets that may have leaked into config/logs.

```bash
Zeloo secrets scan [--path PATH]
Zeloo secrets rotate <provider>
Zeloo secrets scrub <file>
```

---

## Helpers

### `Zeloo version`

```bash
Zeloo version [--json] [--plugins] [--cron] [--fallback]
```

### `Zeloo dashboard`

Open the embedded web dashboard.

```bash
Zeloo dashboard [--host 127.0.0.1] [--port 7777] [--no-browser]
```

### `Zeloo usage`

Token / cost usage breakdown.

```bash
Zeloo usage [--by model|provider|day] [--since 7d] [--json]
```

### `Zeloo z`

Already documented under [Core Conversation](#core-conversation) — listed here
as the implicit default for scripting.

---

## Common Flags

Most subcommands accept these shared flags:

| Flag | Description |
|------|-------------|
| `--config PATH` | Override `~/.Zeloo/config.yaml` |
| `--workspace NAME` | Override the active workspace |
| `--json` | Emit machine-readable output |
| `--quiet` / `-q` | Suppress non-error output |
| `--verbose` / `-v` | Increase log verbosity (repeatable) |
| `--no-color` | Disable ANSI color output |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Generic error |
| `2` | Invalid usage / arguments |
| `3` | Configuration error |
| `4` | Authentication failure |
| `5` | Provider unreachable |
| `64` | Internal exception |
| `130` | User interrupted (Ctrl-C) |