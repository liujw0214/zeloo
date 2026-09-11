# 35. 终端后端（terminal）

## 35.1 模块总览

`terminal/` 提供 **7 种**执行后端，从本地开发到 HPC 环境全覆盖：

```
terminal/
├── base.py              # CommandResult + TerminalBackend Protocol
├── __init__.py          # create_backend() 工厂函数 + 全部导出
├── local.py             # LocalTerminalBackend（subprocess）
├── ssh.py               # SSHTerminalBackend（paramiko）
├── docker.py            # DockerTerminalBackend（docker exec）
├── modal.py             # ModalTerminalBackend（Modal cloud）
├── daytona.py           # DaytonaTerminalBackend（Daytona sandbox）
├── vercel_sandbox.py    # VercelSandboxTerminalBackend（Vercel Functions）
└── singularity.py       # SingularityTerminalBackend（HPC 容器）
```

## 35.2 后端总览

| 后端 | 场景 | 依赖 | 隔离级别 |
|------|------|------|----------|
| `local` | 本地开发调试，零配置 | 无 | 无 |
| `ssh` | 远程服务器执行 | paramiko | 无 |
| `docker` | 隔离环境，CI/CD | Docker daemon | 容器级 |
| `modal` | 云端 serverless，GPU | modal | 函数级 |
| `daytona` | 云端沙箱，持久化 | daytona | 沙箱级 |
| `vercel_sandbox` | Vercel 无服务器执行 | Vercel account | 函数级 |
| `singularity` | HPC 学术科研，GPU/TPU | singularity/apptainer | 容器级 |

## 35.3 通用 API

所有后端均实现 `TerminalBackend` Protocol：

```python
from terminal import create_backend, CommandResult

backend = create_backend("local", cwd="/path/to/project")
result: CommandResult = backend.execute("ls -la", timeout=30)

print(result.stdout)       # 标准输出
print(result.stderr)        # 错误输出
print(result.returncode)    # 退出码
print(result.success)       # returncode == 0
print(result.timed_out)     # 是否超时
```

## 35.4 LocalTerminalBackend

适用于本地开发、测试、CI/CD 流水线：

```python
from terminal import create_backend

backend = create_backend("local", cwd="/project/root")
result = backend.execute("python -m pytest tests/")
```

特性：
- 零依赖，仅 stdlib
- `threading.Lock` 保证线程安全
- 超时控制（默认 30s，returncode=124）

## 35.5 SSHTerminalBackend

远程服务器执行，支持密码和私钥认证：

```python
from terminal import create_backend

backend = create_backend("ssh", host="server.example.com", user="ubuntu",
                        key_path="/path/to/id_rsa")
result = backend.execute("python train.py --epochs 100")
```

**SSHConfig 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `host` | str | 服务器地址 |
| `port` | int | 端口，默认 22 |
| `user` | str | 用户名 |
| `password` | str | 密码认证 |
| `key_path` | Path | 私钥文件路径（优先于密码） |

## 35.6 DockerTerminalBackend

容器内执行，环境隔离、可复现：

```python
from terminal import create_backend

backend = create_backend(
    "docker",
    image="python:3.11-slim",
    container_name="Zeloo-runtime",
    workdir="/workspace",
)
result = backend.execute("python train.py --epochs 100")
```

**容器管理**：
- 容器启动时以 `sleep infinity` 保持运行
- `put_file(content, dest)` / `get_file(path)` 文件传输
- `close()` 清理容器

## 35.7 ModalTerminalBackend

Modal 云端 serverless 执行，支持 GPU：

```python
from terminal import create_backend

backend = create_backend(
    "modal",
    app_name="Zeloo-runtime",
    image_tag="python:3.11",
    gpu="T4",  # T4/L/A100/H100
)
result = backend.execute("python train.py --epochs 100", timeout=600)
```

## 35.8 DaytonaTerminalBackend

Daytona 云端沙箱，持久化工作区：

```python
from terminal import create_backend
import os

backend = create_backend(
    "daytona",
    api_key=os.environ["DAYTONA_API_KEY"],
    workspace_id="ws-abc123",
    region="us-east-1",
)
result = backend.execute("python train.py")
```

## 35.9 VercelSandboxTerminalBackend

Vercel Functions 运行时执行：

```python
from terminal import create_backend
import os

backend = create_backend(
    "vercel_sandbox",
    deployment_url=os.environ["VERCEL_DEPLOYMENT_URL"],
    access_token=os.environ["VERCEL_TOKEN"],
)
result = backend.execute("node script.js")
```

> 注意：需要先部署一个 `/api/exec` 端点接收 `{command}` JSON 并返回 `{stdout, stderr, exitCode}`。

## 35.10 SingularityTerminalBackend

HPC 环境（学术/科研）执行，支持 GPU：

```python
from terminal import create_backend

backend = create_backend(
    "singularity",
    image="/projects/gpu-image.sif",
    bind_paths=["/project", "/scratch"],
    env_vars={"CUDA_VISIBLE_DEVICES": "0"},
)
result = backend.execute("python train.py --epochs 200", timeout=600)
```

特性：
- 自动检测 `singularity` 或 `apptainer` CLI
- `.sif` 镜像自动启用 `--nv` GPU 支持
- 多目录绑定（`--bind`）

## 35.11 工厂函数

```python
from terminal import create_backend

# 按名称创建（推荐）
backend = create_backend("docker", image="python:3.11-slim")

# 获取所有可用后端名称
from terminal import _backend_names  # 不推荐直接使用
```

## 35.12 配置示例

```yaml
# config.yaml
terminal:
  backend: "docker"
  docker:
    image: "python:3.11-slim"
    container_name: "Zeloo-runtime"
    workdir: "/workspace"
```

## 35.13 测试覆盖

| 测试文件 | 覆盖内容 | 用例数 |
|----------|----------|--------|
| `test_terminal_backends.py` | 7 后端创建 + Local 执行/失败/超时 | 10 |
