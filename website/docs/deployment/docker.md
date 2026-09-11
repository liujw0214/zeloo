---
id: deployment-docker
title: Docker Deployment
sidebar_label: Docker
---

# Docker Deployment

## Quick start

```bash
docker build -t zeloo:latest .
docker run -e OPENAI_API_KEY=sk-... -p 8080:8080 zeloo:latest
```

## docker-compose profiles

`docker-compose.yml` ships three profiles:

```bash
# Gateway (API server)
docker compose --profile gateway up

# CLI (interactive shell)
docker compose --profile cli run --rm cli

# s6-overlay (multi-service)
docker compose --profile s6 up
```

## Multi-stage build

`Dockerfile` uses two stages:
1. **builder** — installs `uv`, syncs dependencies into `.venv`
2. **production** — copies `.venv`, runs as non-root `zeloo` user (UID 1000)

## Health check

```yaml
healthcheck:
  test: ["CMD-SHELL", "python -c \"import urllib.request; ..."]
  interval: 30s
```

## Persistent data

Mount `/var/lib/zeloo` to a named volume to persist memory and skills across container restarts.

## See also

- [Source: Dockerfile](https://github.com/Zeloo/Zeloo/blob/main/Dockerfile)
- [Source: docker-compose.yml](https://github.com/Zeloo/Zeloo/blob/main/docker-compose.yml)