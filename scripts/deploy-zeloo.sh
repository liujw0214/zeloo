#!/bin/bash
# Zeloo WSL/Kali Linux 部署脚本
set -e

WHEEL_PATH="${1:-./dist/zeloo-0.1.0-py3-none-any.whl}"
TARGET_HOST="${2:-kali}"
TARGET_USER="${3:-root}"
TARGET_PREFIX="${4:-/opt/zeloo}"

echo "=============================================="
echo "Zeloo WSL/Kali 部署脚本"
echo "=============================================="
echo "Wheel: $WHEEL_PATH"
echo "目标主机: $TARGET_HOST"
echo "目标用户: $TARGET_USER"
echo "安装前缀: $TARGET_PREFIX"
echo "=============================================="

# 检查 wheel 文件是否存在
if [ ! -f "$WHEEL_PATH" ]; then
    echo "错误: 找不到 wheel 文件: $WHEEL_PATH"
    echo "请先运行: python -m build"
    exit 1
fi

# 上传 wheel 到 WSL
echo "[1/6] 上传 wheel 到 WSL..."
scp "$WHEEL_PATH" "$TARGET_USER@$TARGET_HOST:/tmp/zeloo.whl"

# SSH 执行部署
ssh "$TARGET_USER@$TARGET_HOST" << 'EOF'
set -e
WHEEL_PATH="/tmp/zeloo.whl"
PREFIX="${TARGET_PREFIX:-/opt/zeloo}"
PYTHON_BIN="${PREFIX}/venv/bin/python"

echo "[2/6] 创建虚拟环境..."
python3 -m venv "${PREFIX}/venv"
source "${PREFIX}/venv/bin/activate"

echo "[3/6] 升级 pip..."
pip install --upgrade pip

echo "[4/6] 安装 Zeloo..."
pip install "$WHEEL_PATH"

echo "[5/6] 配置环境变量..."
mkdir -p "${PREFIX}/config"
cat > "${PREFIX}/.env" << 'ENVEOF'
# Zeloo 环境配置
# LLM Provider API Keys
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-xxx

# 环境配置
ZELOO_ENV=production
ZELOO_HOME=${PREFIX}/data
ZELOO_LOG_LEVEL=WARNING
ZELOO_DISABLE_UPDATE_CHECK=1
ENVEOF

cat > "${PREFIX}/config.yaml" << 'YAMLEOF'
# Zeloo 生产配置
zeloo:
  log_level: WARNING
  verbose: false
  telemetry_dry_run: false

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
    enabled: true
    host: 0.0.0.0
    port: 9113
    rate_limit_capacity: 60
    rate_limit_rate: 1.0
YAMLEOF

echo "[6/6] 创建数据目录..."
mkdir -p "${PREFIX}/data/memory"
mkdir -p "${PREFIX}/data/sessions"
mkdir -p "${PREFIX}/logs"

echo ""
echo "=============================================="
echo "部署完成!"
echo "=============================================="
echo "安装路径: $PREFIX"
echo "Gateway 端口: 9113"
echo "配置文件: ${PREFIX}/config.yaml"
echo "环境变量: ${PREFIX}/.env"
echo ""
echo "启动命令:"
echo "  source ${PREFIX}/venv/bin/activate"
echo "  zeloo gateway"
echo ""
echo "或快捷命令:"
echo "  ${PYTHON_BIN} -m gateway.run"
echo ""
echo "验证安装:"
echo "  curl http://localhost:9113/health"
echo "=============================================="
EOF

echo "部署成功!"
