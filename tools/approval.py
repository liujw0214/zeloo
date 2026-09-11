"""危险命令审批系统

提供命令审批的核心功能，包括：
- 危险命令检测
- 审批状态管理（会话级别 / 永久白名单）
- YOLO 模式控制
- Gateway 审批集成
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from tools.approval_context import get_approval_mode, is_gateway_session, is_interactive_session
from tools.approval_detection import detect_dangerous_command, get_command_risk_level
from tools.approval_floors import is_blocked, is_permanent_allowlisted
from tools.approval_gateway_wait import await_gateway_decision, submit_approval_request

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}
_session_approved: dict[str, set[str]] = {}
_session_yolo: set[str] = set()
_permanent_approved: set[str] = set()

ApprovalResult = tuple[bool, str]


@dataclass
class ApprovalRequest:
    """审批请求对象"""

    session_key: str
    command: str
    reason: str
    risk_level: str
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


def _generate_command_hash(command: str) -> str:
    """生成命令的唯一哈希值用于审批记录"""
    import hashlib

    normalized = re.sub(r"\s+", " ", command.strip())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def detect_dangerous_command(command: str) -> tuple[bool, str]:
    """检测危险命令，返回 (是否危险, 原因)

    Args:
        command: 待检测的命令字符串

    Returns:
        (是否危险, 原因描述)
    """
    from tools.approval_detection import detect_dangerous_command as detect

    return detect(command)


def is_approved(session_key: str, command: str) -> bool:
    """检查命令是否已审批

    检查顺序：
    1. 永久白名单
    2. 会话级别已审批
    3. YOLO 模式

    Args:
        session_key: 会话标识符
        command: 待检查的命令

    Returns:
        True 如果命令已批准执行
    """
    with _lock:
        cmd_hash = _generate_command_hash(command)
        if cmd_hash in _permanent_approved:
            logger.debug("Command approved by permanent whitelist: %s", command[:50])
            return True

        if session_key in _session_yolo:
            return True

        approved_set = _session_approved.get(session_key, set())
        if cmd_hash in approved_set:
            logger.debug("Command approved in session: %s", command[:50])
            return True

        return False


def approve_command(session_key: str, command: str) -> None:
    """审批一个命令，将其添加到会话审批集合

    Args:
        session_key: 会话标识符
        command: 要审批的命令
    """
    cmd_hash = _generate_command_hash(command)
    with _lock:
        if session_key not in _session_approved:
            _session_approved[session_key] = set()
        _session_approved[session_key].add(cmd_hash)
        logger.info("Command approved for session %s: %s", session_key[:8], command[:50])


def approve_permanent(command: str) -> None:
    """永久审批一个命令，将其添加到永久白名单

    Args:
        command: 要永久审批的命令
    """
    cmd_hash = _generate_command_hash(command)
    with _lock:
        _permanent_approved.add(cmd_hash)
        logger.info("Command permanently approved: %s", command[:50])


def revoke_approval(session_key: str, command: str) -> bool:
    """撤销会话中的命令审批

    Args:
        session_key: 会话标识符
        command: 要撤销审批的命令

    Returns:
        True 如果命令被成功撤销
    """
    cmd_hash = _generate_command_hash(command)
    with _lock:
        approved_set = _session_approved.get(session_key, set())
        if cmd_hash in approved_set:
            approved_set.discard(cmd_hash)
            logger.info("Approval revoked for session %s: %s", session_key[:8], command[:50])
            return True
        return False


def is_yolo_enabled(session_key: str) -> bool:
    """检查 YOLO 模式是否启用

    Args:
        session_key: 会话标识符

    Returns:
        True 如果 YOLO 模式已启用
    """
    with _lock:
        return session_key in _session_yolo


def enable_yolo(session_key: str) -> None:
    """启用 YOLO 模式（跳过所有审批检查）

    Args:
        session_key: 会话标识符
    """
    with _lock:
        _session_yolo.add(session_key)
        logger.warning("YOLO mode enabled for session: %s", session_key[:8])


def disable_yolo(session_key: str) -> None:
    """禁用 YOLO 模式

    Args:
        session_key: 会话标识符
    """
    with _lock:
        _session_yolo.discard(session_key)
        logger.info("YOLO mode disabled for session: %s", session_key[:8])


def toggle_yolo(session_key: str) -> bool:
    """切换 YOLO 模式状态

    Args:
        session_key: 会话标识符

    Returns:
        切换后的 YOLO 状态
    """
    with _lock:
        if session_key in _session_yolo:
            _session_yolo.discard(session_key)
            logger.info("YOLO mode disabled for session: %s", session_key[:8])
            return False
        else:
            _session_yolo.add(session_key)
            logger.warning("YOLO mode enabled for session: %s", session_key[:8])
            return True


def clear_session(session_key: str) -> None:
    """清除会话的审批状态

    Args:
        session_key: 会话标识符
    """
    with _lock:
        _session_approved.pop(session_key, None)
        _session_yolo.discard(session_key)
        logger.info("Session approval state cleared: %s", session_key[:8])


def get_session_approved_count(session_key: str) -> int:
    """获取会话已审批命令数量

    Args:
        session_key: 会话标识符

    Returns:
        已审批命令数量
    """
    with _lock:
        return len(_session_approved.get(session_key, set()))


def get_permanent_approved_count() -> int:
    """获取永久白名单命令数量

    Returns:
        永久白名单命令数量
    """
    with _lock:
        return len(_permanent_approved)


async def request_approval(
    session_key: str,
    command: str,
    context: dict[str, Any] | None = None,
) -> ApprovalResult:
    """请求命令审批

    审批流程：
    1. 检测危险命令
    2. 检查永久白名单
    3. 检查黑名单
    4. 检查会话已审批
    5. 根据会话类型请求审批

    Args:
        session_key: 会话标识符
        command: 待审批的命令
        context: 额外的上下文信息

    Returns:
        (是否批准, 原因)
    """
    if context is None:
        context = {}

    if is_approved(session_key, command):
        return True, "already_approved"

    if is_permanent_allowlisted(command):
        approve_permanent(command)
        return True, "permanent_allowlist"

    if is_blocked(command):
        return False, "blocked_command"

    dangerous, reason = detect_dangerous_command(command)
    risk_level = get_command_risk_level(command)

    if risk_level == "safe":
        return True, "safe_command"

    approval_mode = get_approval_mode()

    if approval_mode == "off":
        return True, "approval_disabled"

    if approval_mode == "auto":
        if risk_level in ("low", "medium"):
            approve_command(session_key, command)
            return True, f"auto_approved_{risk_level}"
        return False, f"requires_manual_approval_{risk_level}"

    request_id = f"{session_key}_{_generate_command_hash(command)}"

    _pending[request_id] = {
        "session_key": session_key,
        "command": command,
        "reason": reason,
        "risk_level": risk_level,
        "context": context,
    }

    try:
        if is_gateway_session():
            decision, reason = await_gateway_decision(session_key, request_id)
            if decision == "approve":
                approve_command(session_key, command)
                return True, "gateway_approved"
            return False, f"gateway_denied: {reason}"

        if is_interactive_session():
            from tools.approval_prompt import prompt_dangerous_approval

            approved = prompt_dangerous_approval(command, reason)
            if approved:
                approve_command(session_key, command)
                return True, "user_approved"
            return False, "user_denied"

        return False, "no_approval_channel"

    finally:
        _pending.pop(request_id, None)


def submit_for_review(
    session_key: str,
    command: str,
    context: dict[str, Any] | None = None,
) -> str:
    """提交命令以供审批（Gateway 模式）

    Args:
        session_key: 会话标识符
        command: 待审批的命令
        context: 额外的上下文信息

    Returns:
        审批请求 ID
    """
    request_id = f"{session_key}_{_generate_command_hash(command)}"

    submit_approval_request(
        session_key=session_key,
        request_id=request_id,
        command=command,
        context=context or {},
    )

    return request_id


def check_approval_status(request_id: str) -> tuple[str, str]:
    """检查审批请求状态

    Args:
        request_id: 审批请求 ID

    Returns:
        (状态, 原因)
        状态: pending | approved | denied | not_found
    """
    if request_id in _pending:
        return "pending", "awaiting_decision"

    return "not_found", "request_not_found"


def get_pending_approvals(session_key: str | None = None) -> list[dict[str, Any]]:
    """获取待审批请求列表

    Args:
        session_key: 可选的会话过滤

    Returns:
        待审批请求列表
    """
    with _lock:
        pending_list = []
        for req_id, req in _pending.items():
            if session_key is None or req.get("session_key") == session_key:
                pending_list.append(
                    {
                        "request_id": req_id,
                        "session_key": req.get("session_key"),
                        "command": req.get("command", "")[:100],
                        "reason": req.get("reason", ""),
                        "risk_level": req.get("risk_level", ""),
                    }
                )
        return pending_list


def approve_by_request_id(request_id: str) -> bool:
    """通过请求 ID 审批命令

    Args:
        request_id: 审批请求 ID

    Returns:
        True 如果审批成功
    """
    with _lock:
        if request_id not in _pending:
            return False

        req = _pending[request_id]
        session_key = req.get("session_key", "")
        command = req.get("command", "")

        if session_key and command:
            approve_command(session_key, command)
            return True

        return False


def deny_by_request_id(request_id: str) -> bool:
    """通过请求 ID 拒绝命令

    Args:
        request_id: 审批请求 ID

    Returns:
        True 如果拒绝成功
    """
    with _lock:
        if request_id not in _pending:
            return False

        _pending.pop(request_id, None)
        return True


def _load_permanent_approvals_from_config() -> None:
    """从配置文件加载永久审批列表"""
    try:
        import os

        zeloo_home = os.environ.get("ZELOO_HOME", os.path.expanduser("~/.Zeloo"))
        config_path = os.path.join(zeloo_home, "config.yaml")

        if not os.path.exists(config_path):
            return

        import yaml

        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        approvals = config.get("approvals", {})
        if not isinstance(approvals, dict):
            return

        permanent_list = approvals.get("permanent_approved", [])
        if isinstance(permanent_list, list):
            for cmd in permanent_list:
                if isinstance(cmd, str):
                    _permanent_approved.add(_generate_command_hash(cmd))

        logger.debug("Loaded %d permanent approvals from config", len(permanent_list))

    except Exception as e:
        logger.warning("Failed to load permanent approvals from config: %s", e)


_load_permanent_approvals_from_config()
