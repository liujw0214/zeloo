# Zeloo

A self-hosted, self-evolving AI agent runtime framework.

> **Note**: This project was formerly known as **Zeloo** (2026-09-09 rename).

## Features

- Three-layer System Prompt (stable / context / volatile)
- Multi-provider LLM routing (41 providers: OpenAI, Anthropic, Grok, DeepSeek, Gemini, …)
- 90+ built-in tools (file, web, shell, code-exec, browser, image gen, advanced toolkit)
- 18+ messaging platform adapters (Telegram, Discord, Slack, WeChat, Lark, …)
- 39 web search providers (Tavily, Brave, Perplexity, Google, Bing, SerpAPI, …)
- 65 optional MCP servers (GitHub, Notion, Linear, Slack, Discord, AWS, GCP, Kubernetes, …)
- 8 image gen + 3 video gen providers (DeepInfra / FAL.ai / xAI Grok Video)
- Full state persistence (SQLite + FTS5 + connection pool)
- Self-evolving skills (curator lifecycle, background review)
- Prompt Optimizer V2 (safety/compression/templates/meta-prompting/reports)
- Enterprise core framework (16 modules: event bus, cache, scheduler, rate limiter, …)
- Native extensions (FTS5 CJK tokenizer)
- Multi-platform deployment (Nix, Docker, CI/CD)

## Quick start

```bash
pip install zeloo
zeloo install
zeloo doctor
zeloo chat "Hello, agent!"
```

## Install via system package manager

The official recipes under `packaging/` install Zeloo, create an isolated
`zeloo` system user, bootstrap the workspace tree at `/var/lib/zeloo` (or
`%USERPROFILE%\.zeloo` on Windows), and register a `zeloo.service` unit so
the agent comes back on reboot. Every recipe ships a smoke test the
packager can run (`zeloo --version`).

### Homebrew (macOS / Linux)

```bash
brew tap your-org/zeloo
brew install zeloo
zeloo doctor
```

### Windows (winget)

```powershell
winget install --id Zeloo.Zeloo -v 0.1.0
zeloo doctor
```

The manifests under `packaging/winget/manifests/y/zeloo/zeloo/0.1.0/`
(version, locale.en-US, installer) are ready to be submitted to
`winget-pkgs`.

### Debian / Ubuntu

```bash
sudo apt install ./zeloo_0.1.0_amd64.deb
sudo systemctl status zeloo.service
zeloo doctor
```

Build the package locally with `dpkg-buildpackage -us -uc -b`.

### Fedora / RHEL

```bash
sudo dnf install ./zeloo-0.1.0-1.fc*.rpm
sudo systemctl status zeloo.service
zeloo doctor
```

Build the package with `rpmbuild -ba packaging/rpm/zeloo.spec`.

### Snap

```bash
snap install zeloo --classic=false
zeloo doctor
```

### Arch Linux (AUR)

```bash
git clone https://aur.archlinux.org/zeloo.git
cd zeloo
makepkg -si
zeloo doctor
```

### Windows PowerShell (one-shot installer)

```powershell
pwsh -ExecutionPolicy Bypass -File packaging/install.ps1
zeloo doctor
```

For uninstall on Windows, use `packaging/uninstall.ps1` (it offers a
data-wipe prompt and removes the desktop shortcut + PATH entry).

## Generic hooks

`packaging/scripts/post_install.sh` and `packaging/scripts/pre_uninstall.sh`
are portable POSIX hooks shared by the recipes. The pre-uninstall hook
creates a `tar.zst` snapshot under `/var/backups/zeloo/` so an accidental
removal can be reverted.

## Documentation

See [docs/](docs/) for the full architecture and roadmap.

## License

Apache-2.0
