"""审批上下文和环境检测

提供会话类型检测、审批模式判断等功能，支持：
- 交互式会话 vs Gateway 会话 vs Cron 会话
- 自动审批 vs 手动审批 vs 关闭审批
- Zeloo 配置兼容
"""

from __future__ import annotations

import logging
import os
import threading
from contextvars import ContextVar
from typing import Literal

logger = logging.getLogger(__name__)

_approval_mode: ContextVar[str] = ContextVar("approval_mode", default="interactive")
_session_key: ContextVar[str] = ContextVar("session_key", default="default")
_session_type: ContextVar[str] = ContextVar("session_type", default="interactive")

ApprovalMode = Literal["interactive", "auto", "off"]
SessionType = Literal["interactive", "gateway", "cron", "api", "unknown"]

_lock = threading.Lock()
_config_cache: dict[str, str] = {}
_cache_loaded = False


def _load_config() -> dict[str, str]:
    """从配置文件加载审批配置"""
    global _config_cache, _cache_loaded

    if _cache_loaded:
        return _config_cache

    with _lock:
        if _cache_loaded:
            return _config_cache

        try:
            zeloo_home = os.environ.get("ZELOO_HOME", os.path.expanduser("~/.Zeloo"))
            config_path = os.path.join(zeloo_home, "config.yaml")

            if os.path.exists(config_path):
                import yaml

                with open(config_path, encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}

                approvals = config.get("approvals", {})
                if isinstance(approvals, dict):
                    _config_cache["mode"] = approvals.get("mode", "interactive")
                    _config_cache["auto_approve_low_risk"] = str(
                        approvals.get("auto_approve_low_risk", True)
                    ).lower()
                    _config_cache["yolo_by_default"] = str(
                        approvals.get("yolo_by_default", False)
                    ).lower()

        except Exception as e:
            logger.warning("Failed to load approval config: %s", e)

        _cache_loaded = True
        return _config_cache


def _get_config_value(key: str, default: str = "") -> str:
    """获取配置值，支持环境变量覆盖"""
    env_key = f"ZELOO_APPROVAL_{key.upper()}"
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val

    config = _load_config()
    return config.get(key, default)


def invalidate_config_cache() -> None:
    """使配置缓存失效，强制重新加载"""
    global _cache_loaded, _config_cache
    with _lock:
        _cache_loaded = False
        _config_cache = {}


def get_current_session_key() -> str:
    """获取当前会话 key

    Returns:
        当前会话的标识符
    """
    return _session_key.get()


def set_session_key(session_key: str) -> None:
    """设置当前会话 key

    Args:
        session_key: 会话标识符
    """
    _session_key.set(session_key)


def get_session_type() -> str:
    """获取当前会话类型

    Returns:
        会话类型：interactive, gateway, cron, api, unknown
    """
    return _session_type.get()


def set_session_type(session_type: SessionType) -> None:
    """设置当前会话类型

    Args:
        session_type: 会话类型
    """
    _session_type.set(session_type)


def is_interactive_session() -> bool:
    """是否交互式会话

    交互式会话指用户在终端直接与 Agent 交互的场景。

    Returns:
        True 如果是交互式会话
    """
    session_type = get_session_type()
    if session_type != "unknown":
        return session_type == "interactive"

    if hasattr(os, "isatty"):
        try:
            if not os.isatty(0):
                return False
        except Exception:
            pass

    platform = os.environ.get("ZELOO_PLATFORM", "").lower()
    if platform in ("cli", "tui", "repl"):
        return True

    return False


def is_gateway_session() -> bool:
    """是否 Gateway 会话

    Gateway 会话指通过 Gateway API 进行的会话。

    Returns:
        True 如果是 Gateway 会话
    """
    session_type = get_session_type()
    if session_type != "unknown":
        return session_type == "gateway"

    gateway_mode = os.environ.get("ZELOO_GATEWAY_MODE", "").lower()
    if gateway_mode == "1" or gateway_mode == "true":
        return True

    platform = os.environ.get("ZELOO_PLATFORM", "").lower()
    if platform in ("gateway", "api", "web"):
        return True

    return False


def is_cron_session() -> bool:
    """是否 cron 会话

    Cron 会话指定时任务执行的场景。

    Returns:
        True 如果是 cron 会话
    """
    session_type = get_session_type()
    if session_type != "unknown":
        return session_type == "cron"

    cron_mode = os.environ.get("ZELOO_CRON", "").lower()
    if cron_mode == "1" or cron_mode == "true":
        return True

    return False


def is_api_session() -> bool:
    """是否 API 会话

    API 会话指通过 REST API 进行的会话。

    Returns:
        True 如果是 API 会话
    """
    session_type = get_session_type()
    if session_type != "unknown":
        return session_type == "api"

    platform = os.environ.get("ZELOO_PLATFORM", "").lower()
    if platform in ("api", "http", "rest"):
        return True

    return False


def should_auto_approve() -> bool:
    """是否应该自动审批

    自动审批条件：
    - 审批模式为 auto
    - Cron 会话且配置允许
    - 安全命令

    Returns:
        True 如果应该自动审批
    """
    mode = get_approval_mode()
    if mode == "auto":
        return True

    if mode == "off":
        return True

    if is_cron_session():
        auto_approve = _get_config_value("auto_approve_low_risk", "true")
        if auto_approve == "true":
            return True

    return False


def get_approval_mode() -> str:
    """获取审批模式

    审批模式：
    - interactive: 交互式审批，需要用户确认
    - auto: 自动审批，低风险命令自动通过
    - off: 关闭审批，所有命令直接执行

    Returns:
        当前审批模式
    """
    mode = _approval_mode.get()

    env_mode = os.environ.get("ZELOO_APPROVAL_MODE", "").lower()
    if env_mode in ("interactive", "auto", "off"):
        return env_mode

    config_mode = _get_config_value("mode", "interactive").lower()
    if config_mode in ("interactive", "auto", "off"):
        return config_mode

    return mode


def set_approval_mode(mode: ApprovalMode) -> None:
    """设置审批模式

    Args:
        mode: 审批模式
    """
    if mode not in ("interactive", "auto", "off"):
        raise ValueError(f"Invalid approval mode: {mode}")
    _approval_mode.set(mode)
    logger.info("Approval mode set to: %s", mode)


def is_yolo_mode() -> bool:
    """是否 YOLO 模式

    YOLO 模式下跳过所有审批检查。

    Returns:
        True 如果是 YOLO 模式
    """
    env_yolo = os.environ.get("ZELOO_YOLO", "").lower()
    if env_yolo in ("1", "true", "yes"):
        return True

    config_yolo = _get_config_value("yolo_by_default", "false")
    if config_yolo == "true":
        return True

    return False


def get_session_info() -> dict[str, str]:
    """获取会话信息摘要

    Returns:
        包含会话类型、审批模式等信息的字典
    """
    return {
        "session_key": get_current_session_key(),
        "session_type": get_session_type(),
        "approval_mode": get_approval_mode(),
        "is_interactive": str(is_interactive_session()),
        "is_gateway": str(is_gateway_session()),
        "is_cron": str(is_cron_session()),
        "is_yolo": str(is_yolo_mode()),
    }


class ApprovalContext:
    """审批上下文管理器

    用于在特定代码块中临时修改审批上下文。

    Example:
        ctx = ApprovalContext(session_key="my-session", approval_mode="auto")
        with ctx:
            # 在这个上下文中使用新的设置
            pass
    """

    def __init__(
        self,
        session_key: str | None = None,
        session_type: SessionType | None = None,
        approval_mode: ApprovalMode | None = None,
    ) -> None:
        self.new_session_key = session_key
        self.new_session_type = session_type
        self.new_approval_mode = approval_mode
        self._tokens: list[object] = []

    def __enter__(self) -> "ApprovalContext":
        if self.new_session_key is not None:
            self._tokens.append(_session_key.set(self.new_session_key))
        if self.new_session_type is not None:
            self._tokens.append(_session_type.set(self.new_session_type))
        if self.new_approval_mode is not None:
            self._tokens.append(_approval_mode.set(self.new_approval_mode))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        for token in reversed(self._tokens):
            if token is not None:
                try:
                    if isinstance(token, tuple) and len(token) == 2:
                        _session_key.reset(token[0])
                        _session_type.reset(token[1])
                    elif hasattr(_session_key, "reset"):
                        _session_key.reset(token)
                except Exception:
                    pass


def get_approval_timeout() -> float:
    """获取审批超时时间（秒）

    Returns:
        超时时间（秒），默认 300 秒
    """
    env_timeout = os.environ.get("ZELOO_APPROVAL_TIMEOUT")
    if env_timeout:
        try:
            return float(env_timeout)
        except ValueError:
            pass

    config_timeout = _get_config_value("timeout", "300")
    try:
        return float(config_timeout)
    except ValueError:
        return 300.0
