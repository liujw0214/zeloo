---
id: installation
title: Installation
sidebar_label: Installation
---

# Installation

## Prerequisites

- Python 3.10 or later
- pip or `uv`
- An OpenAI-compatible API key (or alternative provider)

## Install

```bash
pip install Zeloo
```

Or install from source:

```bash
git clone https://github.com/Zeloo/Zeloo.git
cd Zeloo
uv pip install -e .
```

## Initialize

```bash
Zeloo install
```

This creates `~/.Zeloo/` with the directory structure:

```
~/.Zeloo/
├── profile/         # config.yaml, .env
├── memory/          # MEMORY.md, USER.md (per workspace)
├── skills/          # Local skills
└── archive/         # Workspace snapshots
```

Edit `~/.Zeloo/.env` and add your API key:

```bash
OPENAI_API_KEY=sk-...
zeloo_MODEL=gpt-4o
zeloo_PROVIDER=openai
```

## Verify

```bash
Zeloo doctor
```

Expected output:

```
Zeloo Doctor — system diagnostic
====================================================
  [OK  ] python_version       Python 3.12.x (>= 3.10)
  [OK  ] zeloo_home          /home/user/.Zeloo
  [OK  ] python_deps          All core dependencies installed
  [OK  ] env_file             .env with API key
====================================================
```