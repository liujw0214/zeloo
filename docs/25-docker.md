# 25. Docker 容器配置开发计划

> Zeloo 提供完整的 Docker 运行时支持。本文档记录需要补全的 Docker 相关配置。

## 25.1 目录结构

```
docker/
├── cont-init.d/           # 容器初始化脚本（s6 第一阶段）
├── s6-rc.d/             # s6 服务管理脚本
├── SOUL.md              # 容器身份设定
├── entrypoint.sh        # 主入口脚本
├── entrypoint-dispatch.sh # 入口分发（CLI/Gateway/Web）
├── main-wrapper.sh      # 主进程包装
├── stage2-hook.sh       # 二阶段钩子
└── tini-shim.sh         # tini 垫片
```

---

## 25.2 entrypoint-dispatch.sh 入口分发

根据环境变量 `zeloo_MODE` 启动不同组件：

```bash
# docker/entrypoint-dispatch.sh

zeloo_MODE="${zeloo_MODE:-cli}"

case "$zeloo_MODE" in
    cli)
        exec Zeloo run
        ;;
    gateway)
        exec Zeloo gateway
        ;;
    web)
        exec Zeloo web
        ;;
    tui)
        exec Zeloo tui
        ;;
    *)
        echo "Unknown zeloo_MODE: $zeloo_MODE"
        exit 1
        ;;
esac
```

---

## 25.3 s6-overlay 服务管理

s6-overlay 提供进程Supervisor，支持多服务管理：

```bash
# docker/s6-rc.d/
# ├── run                   # 主服务运行脚本
# └── user/                 # 用户服务
#     └── Zeloo/
#         └── run           # Zeloo 进程
```

```bash
# docker/s6-rc.d/user/Zeloo/run
#!/command/executable/with -x
# run Zeloo in the foreground
exec /usr/local/bin/Zeloo run
```

### 25.3.1 服务列表

| 服务 | 描述 | 重启策略 |
|------|------|----------|
| Zeloo | 主 Agent 进程 | on-failure |
| Zeloo-gateway | 网关服务 | on-failure |
| Zeloo-web | Web 界面 | on-failure |
| cron | 定时任务服务 | on-failure |

---

## 25.4 cont-init.d 第一阶段初始化

```bash
# docker/cont-init.d/01-setup.sh

#!/command/executable/with -x

# 创建必要目录
mkdir -p /var/lib/Zeloo/.Zeloo
mkdir -p /var/lib/Zeloo/skills
mkdir -p /var/lib/Zeloo/logs

# 设置权限
chown -R Zeloo:Zeloo /var/lib/Zeloo

# 初始化配置文件（如果不存在）
if [ ! -f /var/lib/Zeloo/.Zeloo/config.yaml ]; then
    cp /app/config.docker.yaml /var/lib/Zeloo/.Zeloo/config.yaml
fi
```

---

## 25.5 main-wrapper.sh 主进程包装

```bash
# docker/main-wrapper.sh

#!/command/executable/with -x

# 加载环境变量
set -a
source /etc/profile.d/Zeloo-env.sh
set +a

# 健康检查
curl -f http://localhost:8080/health || true

# 启动主进程
exec /usr/local/bin/Zeloo "$@"
```

---

## 25.6 stage2-hook.sh 二阶段钩子

```bash
# docker/stage2-hook.sh

#!/command/executable/with -x

# 在容器启动后执行一次性的初始化
# 例如：安装额外依赖、运行数据库迁移

if [ ! -f /var/lib/Zeloo/.initialized ]; then
    # 运行数据库初始化
    python -m Zeloo.db init

    # 标记已初始化
    touch /var/lib/Zeloo/.initialized
fi
```

---

## 25.7 SOUL.md 容器身份设定

```markdown
# docker/SOUL.md

你是一个在 Docker 容器中运行的 Zeloo Agent。

## 环境信息

- 运行在容器内
- 配置文件：/var/lib/Zeloo/.Zeloo/config.yaml
- 工作目录：/workspace
- 持久化数据：/var/lib/Zeloo

## 行为约束

- 不要在容器内执行危险操作（如格式化磁盘）
- 遇到问题时优先使用日志诊断
- 持久化数据在重启后保持
```

---

## 25.8 docker-compose.yml 配置

```yaml
# docker-compose.yml

services:
  Zeloo:
    build: .
    container_name: Zeloo-agent
    environment:
      - zeloo_MODE=gateway
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./data:/var/lib/Zeloo
      - ./skills:/app/skills
    ports:
      - "8080:8080"  # Gateway API
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

  Zeloo-cli:
    build: .
    container_name: Zeloo-cli
    environment:
      - zeloo_MODE=cli
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./data:/var/lib/Zeloo
      - .:/workspace
    stdin_open: true
    tty: true
    restart: on-failure
```

---

## 25.9 Dockerfile 示例

```dockerfile
# Dockerfile

FROM python:3.12-slim

# 安装运行时依赖
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# 安装 s6-overlay
COPY --from=ghcr.io/just-containers/s6-overlay:latest / /

# 安装 Zeloo
COPY dist/Zeloo-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/Zeloo-*.whl \
    && rm /tmp/Zeloo-*.whl

# 复制脚本
COPY docker/entrypoint.sh /usr/local/bin/
COPY docker/entrypoint-dispatch.sh /usr/local/bin/
COPY docker/main-wrapper.sh /usr/local/bin/
COPY docker/s6-rc.d/ /etc/s6-overlay/s6-rc.d/
COPY docker/cont-init.d/ /etc/cont-init.d/

# 复制配置文件
COPY config.docker.yaml /app/

# 创建用户
RUN useradd -m -u 1000 Zeloo \
    && chown -R Zeloo:Zeloo /app

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["run"]
```

---

## 25.10 tini-shim.sh

```bash
# docker/tini-shim.sh

#!/command/executable/with -x

# tini 是容器 PID 1 的最小化 init 系统
# 此脚本垫片用于在不支持 tini 的环境中优雅降级

if command -v tini > /dev/null; then
    exec tini -- "$@"
else
    exec "$@"
fi
```
