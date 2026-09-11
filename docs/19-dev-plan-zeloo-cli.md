# 19. zeloo_cli 脚手架开发计划

> Zeloo CLI 模块的完整子命令系统、配置加载、安装修复、observability 等能力。本文档记录缺失或需扩展的子模块。

## 19.1 模块总览

| 子模块 | 职责 | 状态 |
|--------|------|------|
| `subcommands/` | CLI 子命令（install/config/doctor 等） | ✅ P1 已实现 |
| `config.py` | 配置加载（load_config()） | ✅ P1 已实现 |
| `_parser.py` | 参数解析器（已集成到 subcommands/__init__.py） | ✅ P1 已实现 |
| `_install_repair.py` | 安装修复脚本 | ✅ P1 已实现（doctor.py） |
| `dashboard_auth/` | 仪表盘认证（basic/drain/nous/self_hosted） | P2 待实现 |
| `web_routers/` | Web 路由（用户管理/会话/设置） | P2 待实现 |
| `observability/` | 可观测性（用量/日志/监控） | P2 部分实现 |
| `_startup_fast.py` | 快速启动优化 | P2 待实现 |

---

## 19.2 subcommands/ 子命令（P1）✅

### 19.2.1 规划子命令

```bash
# 安装命令
Zeloo install          # 初始化配置和环境
Zeloo install --repair # 修复损坏的安装
# 配置命令
Zeloo config show     # 显示当前配置
Zeloo config edit     # 编辑配置
Zeloo config validate # 校验配置语法
# 诊断命令
Zeloo doctor          # 运行诊断检查
Zeloo doctor --fix    # 自动修复可修复的问题
# 会话命令
Zeloo session list     # 列出所有会话
Zeloo session export   # 导出会话记录
Zeloo session delete   # 删除会话
# 模型命令
Zeloo model list       # 列出可用模型
Zeloo model test       # 测试模型连接
# 更新命令
Zeloo update           # 检查并安装更新
Zeloo update --check   # 仅检查不更新
```

### 19.2.2 实现结构

```python
# zeloo_cli/subcommands/__init__.py

class Subcommand(ABC):
    name: str
    help: str

    @abstractmethod
    def run(self, args: argparse.Namespace) -> int:
        """返回退出码。"""
        ...

# 注册
def register_subcommands(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="command")
    for cmd_class in Subcommand.__subclasses__():
        cmd = cmd_class()
        subparsers.add_parser(cmd.name, help=cmd.help)
```

---

## 19.3 config.py 配置加载（P1）✅

### 19.3.1 职责

集中管理配置加载，支持多层级合并：环境变量 > 用户配置 > 项目配置 > 默认值。

### 19.3.2 实现

```python
# zeloo_cli/config.py

@dataclass
class CLIConfig:
    model: str = "gpt-4o"
    provider: str = "openai"
    toolsets: list[str] = field(default_factory=list)
    profile: str = "default"

def load_config(
    config_paths: list[Path] | None = None,
    env_prefix: str = "zeloo_",
) -> CLIConfig:
    """从多层级加载配置。"""
    ...

def merge_configs(*configs: dict) -> dict:
    """深度合并多个配置字典。"""

def resolve_env_vars(
    config: dict, prefix: str = "zeloo_"
) -> dict:
    """将 ${VAR_NAME} 环境变量替换为实际值。"""

def validate_config(config: dict) -> list[str]:
    """校验配置，返回错误列表。"""
```

---

## 19.4 _parser.py 参数解析（P1）✅

> 已集成到 `zeloo_cli/subcommands/__init__.py`，通过 `@subcommand` 装饰器和 `register_subcommands()` 函数实现。

```python
# zeloo_cli/subcommands/__init__.py

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Zeloo",
        description="Zeloo Agent Runtime",
    )
    # 全局参数
    parser.add_argument("--config", type=Path, help="Config file path")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument("--profile", default="default")

    # 子命令
    register_subcommands(parser)
    return parser
```

---

## 19.5 _install_repair.py 安装修复（P1）✅

> 已实现为 `zeloo_cli/subcommands/doctor.py`，包含 5 项检查 + 自动修复能力。

```python
# zeloo_cli/subcommands/doctor.py

class InstallerRepair:
    CHECKS = [
        ("python_version", "检查 Python 版本"),
        ("dependencies", "检查依赖完整性"),
        ("config_file", "检查配置文件"),
        ("skills_dir", "检查 skills 目录"),
        ("db_path", "检查数据库路径"),
        ("log_path", "检查日志路径"),
    ]

    def run_checks(self, fix: bool = False) -> dict[str, CheckResult]:
        """运行所有检查，返回结果字典。"""

    def repair(self, check_name: str) -> bool:
        """尝试修复指定检查项。"""

    def fix_all(self) -> dict[str, bool]:
        """自动修复所有可修复问题。"""
```

---

## 19.6 dashboard_auth/ 仪表盘认证（P2）

### 19.6.1 认证方式

| 方式 | 描述 | 适用场景 |
|------|------|----------|
| `basic` | 用户名 + 密码 | 快速部署 |
| `nous` | Nous 官方账号 | 云端管理 |
| `self_hosted` | 自建 OAuth2 | 企业内网 |
| `drain` | 代理认证 | 开发调试 |

### 19.6.2 实现结构

```python
# zeloo_cli/dashboard_auth/base.py

class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, credentials: dict) -> AuthResult: ...

    @abstractmethod
    def validate_token(self, token: str) -> bool: ...

# zeloo_cli/dashboard_auth/nous.py
class NousAuthProvider(AuthProvider):
    """Nous 官方账号认证。"""

# zeloo_cli/dashboard_auth/self_hosted.py
class SelfHostedAuthProvider(AuthProvider):
    """自建 OAuth2 认证。"""
```

---

## 19.7 observability/ 可观测性（P2）

### 19.7.1 能力

- **用量统计**：Token 消费、API 调用次数、成本估算
- **日志聚合**：结构化日志输出，支持 JSON 格式
- **健康检查**：定时自检各组件状态

### 19.7.2 实现结构

```python
# zeloo_cli/observability/usage.py

class UsageTracker:
    def record_token_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        ...

    def get_summary(
        self, period: str = "day"
    ) -> UsageSummary:
        ...

# zeloo_cli/observability/health.py

class HealthChecker:
    def check_all(self) -> dict[str, HealthStatus]:
        """检查所有组件健康状态。"""
```

---

## 19.8 web_routers/ Web 路由（P2）

### 19.8.1 目标

提供 Web 界面路由（用户管理/会话/设置），作为 CLI 的 GUI 补充。

### 19.8.2 路由设计

```
/auth/login         # 登录
/auth/logout        # 登出
/sessions           # 会话列表
/sessions/:id       # 会话详情
/settings           # 用户设置
/health             # 健康检查
```

---

## 19.9 _startup_fast.py 快速启动（P2）

### 19.9.1 目标

优化启动速度，通过延迟加载和缓存减少冷启动时间。

### 19.9.2 策略

- 延迟导入非核心模块（按需加载）
- 预热常用 Provider 连接
- 缓存技能索引（启动时扫描一次）
