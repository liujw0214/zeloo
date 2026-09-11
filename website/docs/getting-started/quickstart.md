---
id: quickstart
title: Quickstart
sidebar_label: Quickstart
---

# Quickstart

## Your first chat

```bash
Zeloo chat "Hello, agent!"
```

## Interactive mode

```bash
Zeloo chat
```

## Multi-turn with memory

```bash
Zeloo chat
> My name is Alice
> What's my name?
```

## Using a specific provider

```bash
Zeloo chat --provider anthropic --model claude-3.5-sonnet "Hello"
```

## Running as a server

```bash
Zeloo gateway --host 0.0.0.0 --port 8080
```

The OpenAI-compatible API is available at `http://localhost:8080/v1/chat/completions`.

## What's next?

- [Architecture](../architecture/overview)
- [CLI Reference](../deployment/cli)
- [Docker Deployment](../deployment/docker)