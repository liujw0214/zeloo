# Zeloo Linux 部署完整指南

> 本指南涵盖 Zeloo 在 Linux 生产环境的完整部署流程：打包、安装、配置、systemd 服务、Docker 等。

---

## 目录

1. [环境要求](#1-环境要求)
2. [方式一：pip 直接安装](#2-方式一pip-直接安装)
3. [方式二：构建 wheel 包](#3-方式二构建-wheel-包)
4. [方式三：Docker 部署](#4-方式三docker-部署)
5. [方式四：systemd 服务](#5-方式四systemd-服务)
6. [方式五：独立进程部署](#6-方式五独立进程部署)
7. [生产环境配置](#7-生产环境配置)
8. [验证与排查](#8-验证与排查)

---

## 1. 环境要求

### 1.1 系统要求

| 要求 | 规格 |
|---|---|
| **操作系统** | Ubuntu 20.04+ / Debian 11+ / CentOS 8+ / Fedora 36+ |
| **Python** | 3.10 / 3.11 / 3.12 |
| **内存** | 最低 1GB，推荐 2GB+ |
| **磁盘** | 最低 2GB |
| **网络** | 需要访问 LLM Provider API |

### 1.2 必需依赖

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    git curl build-essential

# CentOS/RHEL/Fedora
sudo dnf install -y \
    python3 python3-pip python3-devel git curl gcc
```

---

## 2. 方式一：pip 直接安装

### 2.1 安装稳定版

```bash
# 创建虚拟环境（推荐）
python3 -m venv /opt/zeloo/venv
source /opt/zeloo/venv/bin/activate

# 安装
pip install --upgrade pip
pip install zeloo

# 验证
zeloo --version
```

### 2.2 安装 beta 版

```bash
# 设置 beta 通道
export ZELOO_UPDATE_CHANNEL=beta
pip install zeloo --pre

# 或指定版本
pip install zeloo==0.17.0b1
```

### 2.3 安装指定版本

```bash
# 从 PyPI 安装指定版本
pip install zeloo==0.16.0

# 查看可用版本
pip index versions zeloo
```

### 2.4 从源码安装

```bash
# 克隆或拷贝源码后
git clone https://github.com/zeloo/zeloo.git /opt/zeloo-src
cd /opt/zeloo-src

# 使用 uv（推荐，比 pip 快 10x）
pip install uv
uv pip install -e ".[tui,server]"

# 或使用 pip
pip install -e ".[tui,server]"

# 验证
python -m cli --version
```

---

## 3. 方式二：构建 wheel 包

### 3.1 构建 wheel

```bash
# 安装构建工具
pip install build

# 构建 wheel 包
cd /path/to/zeloo-source
python -m build

# 查看输出
ls dist/
# wheelhouse/
#   zeloo-0.16.0-py3-none-any.whl
```

### 3.2 构建跨平台 wheel（使用 uv）

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 构建
uv pip install build
uv build
```

### 3.3 打包分发

```bash
# 创建分发目录
mkdir -p /opt/zeloo-dist
cp dist/*.whl /opt/zeloo-dist/

# 或打包 tar.gz
tar -czvf zeloo-0.16.0.tar.gz -C /opt/zeloo-src .

# 分发包内容
/opt/zeloo-dist/
├── zeloo-0.16.0-py3-none-any.whl
└── zeloo-0.16.0.tar.gz
```

### 3.4 离线安装

```bash
# 在目标机器上
pip install /opt/zeloo-dist/zeloo-0.16.0-py3-none-any.whl

# 或 tar.gz
tar -xzf zeloo-0.16.0.tar.gz -C /opt/
```

---

## 4. 方式三：Docker 部署

### 4.1 拉取镜像

```bash
# 稳定版
docker pull zeloo/zeloo:latest

# 指定版本
docker pull zeloo/zeloo:0.16.0
```

### 4.2 运行容器

```bash
# 基本运行
docker run -d \
  --name zeloo \
  -p 9113:9113 \
  -v zeloo-data:/data \
  -e ZELOO_ENV=production \
  -e OPENAI_API_KEY=sk-xxx \
  zeloo/zeloo:latest

# 查看日志
docker logs -f zeloo
```

### 4.3 Docker Compose 完整部署

创建 `docker-compose.yml`：

```yaml
version: "3.9"

services:
  zeloo:
    image: zeloo/zeloo:latest
    container_name: zeloo
    restart: unless-stopped
    ports:
      - "9113:9113"  # Gateway API
      - "3000:3000"  # Dashboard
    volumes:
      - zeloo-data:/data
      - ./config.yaml:/data/config.yaml:ro
    environment:
      - ZELOO_ENV=production
      - ZELOO_HOME=/data
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9113/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data

volumes:
  zeloo-data:
  redis-data:
```

启动：

```bash
# 创建 .env 文件
cat > .env << 'EOF'
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
EOF

# 启动
docker compose up -d

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f zeloo
```

### 4.4 构建自定义镜像

```dockerfile
# Dockerfile.zeloo
FROM python:3.12-slim

# 安装 uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 安装 Zeloo
COPY dist/*.whl /tmp/
RUN uv pip install --system /tmp/zeloo*.whl[tui,server]

# 配置
COPY config.yaml /etc/zeloo/config.yaml
COPY entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint

# 健康检查
HEALTHCHECK --interval=30s CMD curl -f http://localhost:9113/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["gateway", "foreground"]
```

```bash
# 构建镜像
docker build -f Dockerfile.zeloo -t my-zeloo:latest .

# 运行
docker run -d -p 9113:9113 my-zeloo:latest
```

### 4.5 生产镜像安全加固

```dockerfile
# 最小权限用户
RUN useradd -r -m -u 1000 zeloo
USER zeloo

# 只读根文件系统（可选）
# READONLY_ROOT
```

---

## 5. 方式四：systemd 服务

### 5.1 安装服务

```bash
# root 用户执行
sudo cp packaging/systemd/zeloo.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/zeloo.service

# 重新加载 systemd
sudo systemctl daemon-reload
sudo systemctl enable zeloo
```

### 5.2 创建用户（推荐）

```bash
# 创建专用用户
sudo useradd -r -m -d /var/lib/zeloo -s /usr/sbin/nologin zeloo

# 创建目录
sudo mkdir -p /var/lib/zeloo
sudo mkdir -p /var/log/zeloo
sudo chown -R zeloo:zeloo /var/lib/zeloo /var/log/zeloo
```

### 5.3 配置环境变量

```bash
# /etc/zeloo/zeloo.env
cat > /etc/zeloo/zeloo.env << 'EOF'
ZELOO_ENV=production
ZELOO_HOME=/var/lib/zeloo
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
ZELOO_LOG_LEVEL=WARNING
EOF

sudo chmod 600 /etc/zeloo/zeloo.env
sudo chown root:root /etc/zeloo/zeloo.env
```

### 5.4 配置文件

```bash
# 复制生产配置
sudo cp config_examples/production.yaml /var/lib/zeloo/config.yaml
sudo chown zeloo:zeloo /var/lib/zeloo/config.yaml
```

### 5.5 启动服务

```bash
# 启动
sudo systemctl start zeloo

# 检查状态
sudo systemctl status zeloo

# 查看日志
journalctl -u zeloo -f

# 停止
sudo systemctl stop zeloo

# 重启
sudo systemctl restart zeloo
```

### 5.6 日志管理

```bash
# 查看所有日志
journalctl -u zeloo --no-pager

# 查看最近日志
journalctl -u zeloo -n 50

# 查看错误日志
journalctl -u zeloo -p err
```

---

## 6. 方式五：独立进程部署

### 6.1 目录结构

```
/opt/zeloo/
├── venv/              # Python 虚拟环境
├── config/            # 配置文件
├── data/              # 数据目录
├── logs/              # 日志
└── bin/               # 启动脚本
    └── start.sh
```

### 6.2 安装脚本

```bash
#!/bin/bash
# install.sh

set -e

PREFIX="${PREFIX:-/opt/zeloo}"
VERSION="${VERSION:-0.16.0}"

echo "Installing Zeloo $VERSION to $PREFIX..."

mkdir -p "$PREFIX"/{venv,config,data,logs,bin}

# Python 虚拟环境
python3 -m venv "$PREFIX/venv"
source "$PREFIX/venv/bin/activate"

pip install --upgrade pip
pip install "zeloo==$VERSION"

# 配置
cp config_examples/production.yaml "$PREFIX/config/config.yaml"

# 启动脚本
cat > "$PREFIX/bin/start.sh" << 'SCRIPT'
#!/bin/bash
exec /opt/zeloo/venv/bin/python -m gateway.run
SCRIPT
chmod +x "$PREFIX/bin/start.sh"

echo "Installed to $PREFIX"
echo "Run: $PREFIX/bin/start.sh"
```

### 6.3 启动脚本

```bash
#!/bin/bash
# /opt/zeloo/bin/start.sh

export ZELOO_HOME=/opt/zeloo/data
export ZELOO_CONFIG=/opt/zeloo/config/config.yaml
export OPENAI_API_KEY=${OPENAI_API_KEY:-$(cat /run/secrets/openai_key 2>/dev/null || echo "")}

exec /opt/zeloo/venv/bin/python -m gateway.run
```

---

## 7. 生产环境配置

### 7.1 生产配置文件

创建 `/var/lib/zeloo/config.yaml` 或 `~/.Zeloo/config.yaml`：

```yaml
# 生产配置示例
zeloo:
  log_level: WARNING
  verbose: false

llm:
  default_provider: openai
  default_model: gpt-4o
  providers:
    openai:
      enabled: true
      api_key: ${OPENAI_API_KEY}

gateway:
  enabled: true
  api:
    host: 0.0.0.0
    port: 9113
    rate_limit_capacity: 60
    rate_limit_rate: 1.0

memory:
  backend: redis
  redis_url: ${REDIS_URL}

security:
  sanitize_input: true
  validate_output: true
  threat_scan: true
```

### 7.2 环境变量

| 变量 | 说明 |
|---|---|
| `ZELOO_ENV` | `production` / `development` |
| `ZELOO_HOME` | 数据目录 |
| `ZELOO_CONFIG` | 配置文件路径 |
| `ZELOO_LOG_LEVEL` | DEBUG / INFO / WARNING / ERROR |
| `ZELOO_LLM_TIMEOUT_SECONDS` | LLM 超时（秒）|
| `OPENAI_API_KEY` | OpenAI API Key |
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `ZELOO_DISABLE_UPDATE_CHECK` | 禁用版本检查（生产设为 1）|
| `REDIS_URL` | Redis 连接字符串 |

### 7.3 TLS/HTTPS 配置

```nginx
# /etc/nginx/sites-available/zeloo
server {
    listen 443 ssl http2;
    server_name api.zeloo.example.com;

    ssl_certificate /etc/ssl/certs/zeloo.crt;
    ssl_certificate_key /etc/ssl/private/zeloo.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:9113;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

### 7.4 反向代理配置

```yaml
# Caddyfile (Caddyfile)
api.zeloo.example.com {
    reverse_proxy localhost:9113
    tls internal
}
```

---

## 8. 验证与排查

### 8.1 健康检查

```bash
# HTTP 健康检查
curl http://localhost:9113/health

# systemd 服务状态
systemctl status zeloo --no-pager

# Docker 健康检查
docker inspect --format='{{.State.Health.Status}}' zeloo
```

### 8.2 日志位置

| 部署方式 | 日志位置 |
|---|---|
| systemd | `journalctl -u zeloo -f` |
| Docker | `docker logs zeloo -f` |
| 直接运行 | stdout / stderr |

### 8.3 常见问题

| 问题 | 解决方案 |
|---|---|
| 导入错误 | 重新 `pip install -e .` |
| 权限问题 | 检查目录归属 `chown -R zeloo:zeloo /var/lib/zeloo` |
| 端口占用 | `lsof -i :9113` / `netstat -tlnp | grep 9113` |
| API Key 无效 | 检查环境变量或配置文件 |
| 连接超时 | 检查网络和防火墙 |

### 8.4 防火墙配置

```bash
# Ubuntu/Debian (ufw)
sudo ufw allow 9113/tcp comment "Zeloo Gateway"
sudo ufw reload

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=9113/tcp
sudo firewall-cmd --reload
```

### 8.5 性能调优

```bash
# 增大文件描述符限制
# /etc/security/limits.conf
zeloo soft nofile 65536
zeloo hard nofile 65536

# systemd 资源限制
# /etc/systemd/system/zeloo.service.d/override.conf
[Service]
MemoryMax=2G
LimitNOFILE=65536
```
