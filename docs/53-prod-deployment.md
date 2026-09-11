# 53. Production Docker Deployment

## 53.1 Overview

`docker-compose.prod.yml` is the **hardened** counterpart to the dev
`docker-compose.yml`. It differs in:

* Non-root user (`1000:1000`) for all services
* Read-only root filesystem + tmpfs for `/tmp` / `/run`
* `no-new-privileges` + `cap_drop: [ALL]` security options
* Resource limits (`cpus`, `memory`)
* Persistent volumes for state DB, secrets, master key, off-host copy
* Optional off-host backup container (LocalPusher / S3Pusher / OSSPusher)
* Optional Caddy reverse proxy with auto-TLS
* Optional Prometheus metrics scraping
* `start_period` on healthchecks (slow cold starts are tolerated)
* Tier-isolated networks (`zeloo-frontend`, `zeloo-backend`)

## 53.2 File layout

```
docker-compose.prod.yml       # production compose (this round)
docker/
├── Caddyfile                 # reverse proxy config
└── prometheus.yml            # metrics scrape config

.env.prod.example             # production env overrides (commit-safe)
.env                          # real secrets (NEVER commit)
```

## 53.3 Quick start

```bash
# 1. Copy env template and fill in real values
cp .env.prod.example .env
$EDITOR .env

# 2. Generate API token
echo "zeloo_API_TOKEN=$(openssl rand -hex 32)" >> .env

# 3. Start gateway (and caddy reverse proxy)
docker compose -f docker-compose.prod.yml --profile gateway up -d

# 4. Start cron service (PITR archive)
docker compose -f docker-compose.prod.yml --profile cron up -d

# 5. Start nightly off-host backup
docker compose -f docker-compose.prod.yml --profile backup up -d

# 6. Optionally enable Prometheus
docker compose -f docker-compose.prod.yml --profile metrics up -d
```

## 53.4 Profile matrix

| Profile | Services started | When |
|---------|------------------|------|
| `gateway` | gateway + caddy | Production runtime |
| `cli` | cli (interactive) | Manual ops |
| `cron` | cron (PITR archive scheduler) | Continuous |
| `backup` | backup (off-host push) | Continuous |
| `caddy` | caddy reverse proxy | With gateway |
| `metrics` | prometheus | Optional |

## 53.5 Volumes

| Volume | Mount point | What it stores |
|--------|-------------|----------------|
| `zeloo_state_prod` | `/var/lib/Zeloo` | `state.db`, `credentials.enc`, `.master_key`, `memories/`, `skills/`, `backups/`, `wal-archive/` |
| `zeloo_offhost_prod` | `/var/lib/Zeloo-offhost` | LocalPusher destination (separate disk / mount) |
| `caddy-data` | `/data` | Caddy cert cache |
| `caddy-config` | `/config` | Caddy runtime config |
| `prometheus-data` | `/prometheus` | 15d TSDB retention |

To back up state: `docker run --rm -v zeloo_state_prod:/data -v $(pwd):/backup alpine tar czf /backup/zeloo-state-$(date +%F).tgz /data`.

## 53.6 Healthcheck

| Endpoint | Returns |
|----------|---------|
| `GET /health` | `200 OK` when gateway is ready |
| `GET /metrics` | Prometheus exposition format (port 9090) |

Docker healthchecks use 30s interval, 10s timeout, 3 retries, 30s `start_period`.

## 53.7 Networks

```
zeloo_frontend (bridge)      zeloo_backend (bridge)
─────────────────────       ─────────────────────
caddy → gateway              gateway ↔ cron
                             gateway ↔ backup
                             prometheus → gateway
```

`caddy` and `prometheus` are the only services reachable from the host
(`127.0.0.1` ports). Gateway binds to localhost-only port 8080 — must
go through Caddy (or your own) for public access.

## 53.8 Backup strategy

| Layer | Where | When |
|-------|-------|------|
| Snapshot | `zeloo-state/backups/` | Hourly (via `zeloo-cron`) |
| WAL segment | `zeloo-state/wal-archive/` | Every 5 min (via `zeloo-cron`) |
| Off-host (local) | `zeloo-offhost/` | After each snapshot + segment (via `zeloo-cron` pushing through `LocalPusher`) |
| Off-host (S3/OSS) | bucket | Nightly at 03:00 UTC (via `zeloo-backup`) |
| Encrypted | Fernet envelope | All segments since Round 50 |

Retention: 30 days default (`ZELOO_BACKUP_KEEP_DAYS`).

## 53.9 Logs use the `json-file` driver with rotation:

```
driver: json-file
options:
  max-size: 10m
  max-file: 5
```

Each service emits at most 50 MB of logs (5 × 10 MB) before old logs
are rotated out. Use `docker compose logs --follow` or wire a log
shipper (Fluentd / Promtail) to scrape from `/var/lib/docker/containers/`.

## 53.10 Resource budget

| Service | CPU limit | Memory limit |
|---------|-----------|--------------|
| gateway | 2.0 | 2 GB |
| cli | (none) | (none) |
| cron | (none) | 512 MB suggested |
| backup | (none) | 512 MB suggested |
| caddy | (none) | 128 MB |
| prometheus | (none) | 1 GB |

Tune via `deploy.resources.limits` / `deploy.resources.reservations`.

## 53.11 Upgrade procedure

```bash
# 1. Pull new image
docker compose -f docker-compose.prod.yml pull

# 2. Run database migrations if any (currently: schema is auto-applied)
docker compose -f docker-compose.prod.yml run --rm gateway python -m zeloo_state.schema --check

# 3. Rolling restart — bring up the new image with zero downtime
docker compose -f docker-compose.prod.yml up -d --no-deps gateway
docker compose -f docker-compose.prod.yml up -d --no-deps cron
docker compose -f docker-compose.prod.yml up -d --no-deps backup

# 4. Verify health
docker compose -f docker-compose.prod.yml ps
curl http://localhost:8080/health
```

## 53.12 Disaster recovery

```bash
# Restore from off-host S3 snapshot
docker compose -f docker-compose.prod.yml run --rm \
  -e OFFHOST_BACKEND=s3 \
  -e OFFHOST_S3_BUCKET=zeloo-backup-prod \
  backup \
  python -m zeloo_state.pitr restore --target-ts $(date +%s)
```

The `zeloo-backup` container has the master key + WAL archive + S3
credentials, so it can run a restore in isolation without bringing the
gateway up first.

## 53.13 Common pitfalls

| 问题 | 排查 |
|------|------|
| 端口冲突 | 检查 `8080` / `443` 是否被占用 |
| 健康检查一直失败 | 增加 `start_period` 或检查 `/health` 是否被中间件拦截 |
| 容器启动后立刻重启 | `docker logs zeloo-gateway` 查看 stderr；通常是缺 env var |
| Master key 跨容器不一致 | 容器销毁前务必 `docker volume ls`；state 卷是 named volume |
| 跨主机迁移 | 先 `docker run --rm -v zeloo_state_prod:/d alpine tar czf /backup.tgz /d`，再在新主机 `docker volume create zeloo_state_prod && docker run --rm -v zeloo_state_prod:/d -v $(pwd):/b alpine tar xzf /b/backup.tgz -C /d` |

## 53.14 Migration from dev compose

```bash
# Dev compose uses profiles=cli/gateway/s6; prod compose uses the
# hardened equivalents. To migrate:
docker compose down                          # stop dev stack
docker compose -f docker-compose.prod.yml \
  --profile gateway --profile cron --profile backup \
  up -d
docker volume ls                             # confirm zeloo_state_prod exists
```

State persists across the migration because both compose files mount
the same path inside the container (`/var/lib/Zeloo`). If you change
the volume name in `prod`, you must copy data over explicitly.