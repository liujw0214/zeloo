# 故障排查与常见问题 (FAQ)

本文档涵盖 Zeloo 框架运行中常见的安装、配置、运行时问题及解决方案。

---

## 目录

1. [安装与启动](#1-安装与启动)
2. [Provider 配置](#2-provider-配置)
3. [Agent 核心](#3-agent-核心)
4. [Memory 与存储](#4-memory-与存储)
5. [MCP Server](#5-mcp-server)
6. [性能与资源](#6-性能与资源)
7. [安全与权限](#7-安全与权限)
8. [CLI 命令](#8-cli-命令)
9. [部署与运维](#9-部署与运维)

---

## 1. 安装与启动

### Q1: `uv sync` 报错 `TOMLDecodeError`

**症状**：
```
tomllib.TOMLDecodeError: Invalid statement (at line 1, column 1)
```

**原因**：`pyproject.toml` 文件包含 UTF-8 BOM（`EF BB BF`），Windows 编辑器写入。

**修复**：
```bash
# 用 Python 去除 BOM
python -c "
with open('pyproject.toml', 'rb') as f:
    data = f.read()
if data.startswith(b'\xef\xbb\xbf'):
    with open('pyproject.toml', 'wb') as f:
        f.write(data[3:])
print('BOM removed')
"
uv sync
```

### Q2: `uv sync --reinstall` 卸载了 pytest / ruff 等 dev 依赖

**症状**：dev 依赖被卸载而非保留。

**原因**：`pyproject.toml` 中 dev 依赖版本约束与其他包冲突，uv 自动解决时可能降级。

**修复**：单独补充 dev 依赖：
```bash
uv add --dev "pytest>=8.0" "pytest-cov>=4.1" "ruff>=0.4" "mypy>=1.0"
uv sync
```

### Q3: `python -m zeloo` 或 `zeloo` 命令找不到

**修复**：
```bash
# 确认虚拟环境激活
source .venv/bin/activate  # Linux/macOS
.\.venv\Scripts\activate   # Windows PowerShell

# 或直接使用
.venv\Scripts\python -m zeloo --help
.venv\Scripts\zeloo --help
```

### Q4: Ruff / mypy 报错大量预存错误

**说明**：框架代码中存在部分代码风格问题（`UP035/UP042` 等），建议逐步清理：
```bash
# 查看当前 ruff 错误
ruff check . --output-format=concise | head -50

# 自动修复安全类问题
ruff check . --fix --unsafe-fixes

# 不修复，保持现状（不影响运行）
ruff check . --ignore UP035,UP042,UP041,E501
```

---

## 2. Provider 配置

### Q5: LLM Provider 返回 401 Unauthorized

**检查步骤**：
1. 确认 API Key 正确且未过期
2. 确认环境变量已正确设置（不要有多余空格）
3. 确认 Provider 名称匹配（如 `openai` 而非 `OpenAI`）

```bash
# 正确格式
export OPENAI_API_KEY=sk-xxxx

# 错误格式（多余空格）
export OPENAI_API_KEY= sk-xxxx   # ❌
export OPENAI_API_KEY="sk-xxxx"  # ❌
```

### Q6: `CostTracker` 环境变量不生效（Windows）

**症状**：设置 `zeloo_COST_WARN_THRESHOLD=5.0` 但追踪器仍使用默认值。

**原因**：Windows `os.environ` 大小写不敏感但保留写入格式，`startswith('zeloo_')` 在某些情况下匹配失败。

**状态**：已在 `environments/__init__.py` 中修复，使用大小写不敏感匹配。

### Q7: Web Provider `openstreetmap` 导入失败

**症状**：
```
ModuleNotFoundError: No module named 'web_providers.openstreetmap'
```

**原因**：模块实际文件名为 `osm_search.py`，不是 `openstreetmap.py`。

**状态**：已在 `web_providers/__init__.py` 中修复。

---

## 3. Agent 核心

### Q8: Agent 不输出任何内容（无响应）

**排查步骤**：
1. 检查 LLM Provider 配置：`echo $zeloo_MODEL`
2. 检查 API Key：`echo $OPENAI_API_KEY`（确认不为空）
3. 开启 DEBUG 日志：
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Q9: `prompt_optimizer_v2` 与 `prompt_optimizer` 区别

- **v1 (`PromptOptimizer`)**：基础版本，包含 CoT、Example Selection、A/B Test
- **v2 (`PromptOptimizerV2`)**：增强版，增加 Safety Validator、Prompt Compressor、Template Library、Meta Prompt Engine

**推荐**：新项目直接使用 v2。v1 保留用于向后兼容。

### Q10: `task_planner` 依赖图循环检测

**说明**：`TaskPlanner.execute_plan()` 对循环依赖图会返回空执行（`completed=0`），不会死循环。设计 DAG 时确保无循环。

---

## 4. Memory 与存储

### Q11: 记忆内容丢失或重复

**原因**：可能是 `MemoryConsolidator` 配置过于激进。

**建议**：
```python
# 保守配置
consolidator = MemoryConsolidator(
    similarity_threshold=0.95,  # 提高阈值，减少误合并
    max_entries=5000,            # 增大容量
    importance_decay_days=90.0,  # 延长衰减周期
)
```

### Q12: SQLite 数据库锁定

**症状**：`sqlite3.OperationalError: database is locked`

**解决**：
```python
# SessionDB 使用 WAL 模式，默认支持并发
# 如遇锁定，检查是否有多进程同时写入
# 推荐使用单进程 + 异步队列写入
```

---

## 5. MCP Server

### Q13: MCP Server 连接失败

**排查**：
```bash
# 确认 MCP server 命令存在
npx -y @modelcontextprotocol/server-filesystem --help

# 确认 JSON-RPC 通信正常
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  npx -y @modelcontextprotocol/server-sequential-thinking
```

### Q14: MCP 工具未注册

**检查**：
```python
from zeloo.mcp import MCPServerRegistry

registry = MCPServerRegistry()
print(registry.list_servers())  # 确认已注册
```

---

## 6. 性能与资源

### Q15: 内存占用过高

**排查**：
```python
import tracemalloc
tracemalloc.start()

# 执行操作...

current, peak = tracemalloc.get_traced_memory()
print(f"Current: {current / 1024 / 1024:.1f} MB, Peak: {peak / 1024 / 1024:.1f} MB")
```

**常见原因**：
- 大量未释放的 LLM 响应缓存
- SessionDB 积累过多历史消息（使用 `limit` 参数）
- MemoryConsolidator 未定期执行

### Q16: API 调用延迟高

**优化建议**：
1. 使用支持流式输出的 Provider
2. 启用 Response Caching（`agent/cache/`）
3. 配置适当的 `max_tokens` 上限
4. 考虑使用本地模型（Ollama / LM Studio）降低网络延迟

---

## 7. 安全与权限

### Q17: `execution_sandbox` STRICT 策略未能拦截危险操作

**状态**：已知问题。STRICT 策略当前实现不完整（仅拦截 `os.system`/`os.popen`/`subprocess`）。生产环境建议同时配合进程级沙箱（Docker / gVisor）。

### Q18: API Key 安全建议

- **不提交到 Git**：确保 `.env` 在 `.gitignore` 中
- **使用密钥管理服务**：生产环境使用 Vault / AWS Secrets Manager
- **环境变量而非硬编码**：使用 `os.environ` 而非代码中写死

```python
# ✅ 推荐
api_key = os.environ.get("OPENAI_API_KEY")

# ❌ 不推荐
api_key = "sk-xxxx"  # 硬编码
```

---

## 8. CLI 命令

### Q19: `zeloo new` 报错 `PermissionError`

**症状**：
```
PermissionError: [Errno 13] Permission denied: '~/.Zeloo'
```

**修复**：
```bash
# 检查目录权限
ls -la ~/

# 修复权限
chmod 700 ~/.Zeloo  # Linux/macOS
```

### Q20: `zeloo run` 卡住不动

**排查**：
```bash
# 使用 verbose 模式
zeloo run --verbose

# 检查网络连通性
curl -I https://api.openai.com
```

---

## 9. 部署与运维

### Q21: Docker 容器启动失败

**排查**：
```bash
# 查看容器日志
docker logs <container_id>

# 常见问题：
# 1. 端口冲突
docker run -p 8080:8080 zeloo  # 8080 被占用 → 换端口

# 2. 环境变量缺失
docker run -e OPENAI_API_KEY=sk-xxx zeloo

# 3. 内存不足
docker run --memory=512m zeloo  # 增加内存限制
```

### Q22: CI 测试在 GitHub Actions 失败但本地通过

**常见原因**：
1. 环境变量差异（本地有 API Key，CI 没有）
2. 网络限制（CI 无法访问外部 API）
3. Python 版本差异

**解决方案**：
```bash
# 使用 .env.test 隔离测试环境
pytest --env-file=.env.test

# 本地模拟 API 响应
pytest tests/unit/ --mock-http
```

### Q23: 如何升级 Zeloo？

```bash
# 更新代码
git pull origin main

# 同步依赖
uv sync

# 运行迁移（如有）
uv run python -m zeloo migrate

# 重启服务
systemctl restart zeloo  # 或重启容器
```

---

## 获取帮助

- **Issues**: https://github.com/zeloo-project/zeloo/issues
- **文档**: https://docs.zeloo.ai
- **Discussions**: https://github.com/zeloo-project/zeloo/discussions
