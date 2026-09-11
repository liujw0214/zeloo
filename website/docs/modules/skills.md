---
id: modules-skills
title: Skills
sidebar_label: Skills
---

# Skills

Skills are reusable agent capabilities defined as Markdown files with YAML frontmatter.

## Skill file format

```markdown
---
name: docker_build
description: Build a Docker image from a Dockerfile
version: 1.0.0
---

# Docker Build

Step-by-step build procedure...

## Triggers

- "build docker image"
- "docker build"
```

## Lifecycle

```
┌──────────┐  use  ┌────────┐  idle   ┌──────────┐
│  active  │──────►│  used  │───────►│  stale   │
└──────────┘       └────────┘        └──────────┘
                                          │
                                          ▼ 30d
                                    ┌──────────┐
                                    │ archived │
                                    └──────────┘
```

Managed by `agent/curator.py`. See [docs/45-optional-skills-api.md](https://github.com/Zeloo/Zeloo/blob/main/docs/45-optional-skills-api.md).