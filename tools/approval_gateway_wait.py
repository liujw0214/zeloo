"""Gateway 审批等待循环

提供 Gateway 审批请求的等待和处理功能，支持：
- 异步等待审批决策
- 审批请求提交
- 超时处理
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

_decisions: dict[str, dict[str, str]] = {}
_decisions_lock = threading.Lock()
_pending_requests: dict[str, dict[str, Any]] = {}
_pending_lock = threading.Lock()
_callbacks: dict[str, list] = {}
_callbacks_lock = threading.Lock()


@dataclass
class GatewayDecision:
    """Gateway 审批决策"""

    request_id: str
    decision: str
    reason: str
    timestamp: float = field(default_factory=time.time)


def _get_decision(request_id: str) -> Optional[GatewayDecision]:
    """获取审批决策

    Args:
        request_id: 请求 ID

    Returns:
        审批决策或 None
    """
    with _decisions_lock:
        data = _decisions.get(request_id)
        if data:
            return GatewayDecision(
                request_id=request_id,
                decision=data.get("decision", "timeout"),
                reason=data.get("reason", ""),
                timestamp=data.get("timestamp", time.time()),
            )
        return None


def _store_decision(request_id: str, decision: str, reason: str = "") -> None:
    """存储审批决策

    Args:
        request_id: 请求 ID
        decision: 决策结果
        reason: 决策原因
    """
    with _decisions_lock:
        _decisions[request_id] = {
            "decision": decision,
            "reason": reason,
            "timestamp": time.time(),
        }
        logger.info("Gateway decision stored: %s = %s", request_id, decision)

    with _callbacks_lock:
        callbacks = _callbacks.pop(request_id, [])
        for callback in callbacks:
            try:
                callback(decision, reason)
            except Exception as e:
                logger.error("Callback error: %s", e)


def await_gateway_decision(
    session_key: str,
    request_id: str,
    timeout: float = 300.0,
) -> tuple[str, str]:
    """等待 Gateway 审批决策

    Args:
        session_key: 会话标识符
        request_id: 请求 ID
        timeout: 超时时间（秒）

    Returns:
        (decision, reason)
        decision: approve | deny | timeout
    """
    start_time = time.time()
    poll_interval = 0.5
    max_poll_interval = 2.0

    while time.time() - start_time < timeout:
        decision = _get_decision(request_id)
        if decision:
            return decision.decision, decision.reason

        time.sleep(poll_interval)

        poll_interval = min(poll_interval * 1.2, max_poll_interval)

        remaining = timeout - (time.time() - start_time)
        if remaining < poll_interval:
            poll_interval = remaining / 2

        if poll_interval <= 0:
            break

    logger.warning("Gateway approval timeout for request: %s", request_id)
    return "timeout", "approval_timeout"


def submit_approval_request(
    session_key: str,
    request_id: str,
    command: str,
    context: dict[str, Any],
) -> None:
    """提交审批请求到 Gateway

    Args:
        session_key: 会话标识符
        request_id: 请求 ID
        command: 待审批的命令
        context: 上下文信息
    """
    from tools.approval_detection import get_command_risk_level
    from tools.approval_detection import detect_dangerous_command

    dangerous, reason = detect_dangerous_command(command)
    risk_level = get_command_risk_level(command)

    request_data = {
        "session_key": session_key,
        "request_id": request_id,
        "command": command,
        "reason": reason,
        "risk_level": risk_level,
        "context": context,
        "timestamp": time.time(),
        "requires_approval": dangerous or risk_level in ("high", "critical"),
    }

    with _pending_lock:
        _pending_requests[request_id] = request_data

    try:
        _submit_to_gateway_api(session_key, request_data)
    except Exception as e:
        logger.warning("Failed to submit to Gateway API: %s", e)


def _submit_to_gateway_api(session_key: str, request_data: dict[str, Any]) -> None:
    """提交请求到 Gateway API

    Args:
        session_key: 会话标识符
        request_data: 请求数据
    """
    try:
        import os

        gateway_url = os.environ.get("ZELOO_GATEWAY_URL", "")
        if not gateway_url:
            return

        import json

        data = {
            "session_key": session_key,
            "request_id": request_data["request_id"],
            "command": request_data["command"],
            "reason": request_data["reason"],
            "risk_level": request_data["risk_level"],
            "timestamp": request_data["timestamp"],
        }

        try:
            import urllib.request

            req = urllib.request.Request(
                f"{gateway_url}/api/approval/request",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
                logger.debug("Approval request submitted to Gateway")
        except Exception as e:
            logger.debug("Gateway API not available: %s", e)

    except Exception as e:
        logger.warning("Failed to submit approval request: %s", e)


def handle_gateway_callback(
    request_id: str,
    decision: str,
    reason: str = "",
) -> None:
    """处理来自 Gateway 的回调

    Args:
        request_id: 请求 ID
        decision: 决策结果
        reason: 决策原因
    """
    if decision not in ("approve", "deny", "timeout"):
        logger.warning("Invalid gateway decision: %s", decision)
        decision = "deny"

    _store_decision(request_id, decision, reason)

    logger.info(
        "Gateway callback processed: request=%s decision=%s reason=%s",
        request_id,
        decision,
        reason,
    )


def register_approval_callback(
    request_id: str,
    callback: Any,
) -> None:
    """注册审批回调

    Args:
        request_id: 请求 ID
        callback: 回调函数
    """
    with _callbacks_lock:
        if request_id not in _callbacks:
            _callbacks[request_id] = []
        _callbacks[request_id].append(callback)


def get_pending_requests(session_key: Optional[str] = None) -> list[dict[str, Any]]:
    """获取待审批请求列表

    Args:
        session_key: 可选的会话过滤

    Returns:
        待审批请求列表
    """
    with _pending_lock:
        requests = []
        for req_id, req in _pending_requests.items():
            if session_key is None or req.get("session_key") == session_key:
                requests.append(
                    {
                        "request_id": req_id,
                        "session_key": req.get("session_key"),
                        "command": req.get("command", "")[:100],
                        "reason": req.get("reason", ""),
                        "risk_level": req.get("risk_level", ""),
                        "timestamp": req.get("timestamp", 0),
                        "age_seconds": time.time() - req.get("timestamp", time.time()),
                    }
                )
        return requests


def cancel_pending_request(request_id: str) -> bool:
    """取消待审批请求

    Args:
        request_id: 请求 ID

    Returns:
        True 如果成功取消
    """
    with _pending_lock:
        if request_id in _pending_requests:
            del _pending_requests[request_id]
            logger.info("Pending request cancelled: %s", request_id)
            return True
        return False


def clear_session_requests(session_key: str) -> int:
    """清除会话的所有待审批请求

    Args:
        session_key: 会话标识符

    Returns:
        清除的请求数量
    """
    count = 0
    with _pending_lock:
        to_remove = [
            req_id
            for req_id, req in _pending_requests.items()
            if req.get("session_key") == session_key
        ]
        for req_id in to_remove:
            del _pending_requests[req_id]
            count += 1

    logger.info("Cleared %d pending requests for session: %s", count, session_key)
    return count


def get_request_status(request_id: str) -> dict[str, Any]:
    """获取请求状态

    Args:
        request_id: 请求 ID

    Returns:
        状态信息字典
    """
    with _decisions_lock:
        decision = _decisions.get(request_id)

    with _pending_lock:
        pending = _pending_requests.get(request_id)

    if decision:
        return {
            "request_id": request_id,
            "status": decision["decision"],
            "reason": decision.get("reason", ""),
            "timestamp": decision.get("timestamp", 0),
        }

    if pending:
        age = time.time() - pending.get("timestamp", time.time())
        return {
            "request_id": request_id,
            "status": "pending",
            "command": pending.get("command", "")[:100],
            "risk_level": pending.get("risk_level", ""),
            "age_seconds": age,
        }

    return {
        "request_id": request_id,
        "status": "not_found",
    }


def set_decision_for_testing(request_id: str, decision: str, reason: str = "") -> None:
    """设置测试用决策（仅用于测试）

    Args:
        request_id: 请求 ID
        decision: 决策结果
        reason: 决策原因
    """
    _store_decision(request_id, decision, reason)


def clear_all_decisions() -> None:
    """清除所有决策（测试用）"""
    with _decisions_lock:
        _decisions.clear()
    with _pending_lock:
        _pending_requests.clear()
    with _callbacks_lock:
        _callbacks.clear()


def clear_decisions_older_than(max_age_seconds: float) -> int:
    """清除超过指定时间的决策

    Args:
        max_age_seconds: 最大存活时间（秒）

    Returns:
        清除的决策数量
    """
    cutoff = time.time() - max_age_seconds
    count = 0

    with _decisions_lock:
        to_remove = [
            req_id
            for req_id, data in _decisions.items()
            if data.get("timestamp", 0) < cutoff
        ]
        for req_id in to_remove:
            del _decisions[req_id]
            count += 1

    with _pending_lock:
        to_remove = [
            req_id
            for req_id, data in _pending_requests.items()
            if data.get("timestamp", 0) < cutoff
        ]
        for req_id in to_remove:
            del _pending_requests[req_id]
            count += 1

    if count > 0:
        logger.info("Cleared %d expired decisions/requests", count)

    return count


def get_gateway_approval_stats() -> dict[str, Any]:
    """获取 Gateway 审批统计信息

    Returns:
        统计信息字典
    """
    with _decisions_lock:
        total_decisions = len(_decisions)
        approve_count = sum(1 for d in _decisions.values() if d.get("decision") == "approve")
        deny_count = sum(1 for d in _decisions.values() if d.get("decision") == "deny")
        timeout_count = sum(1 for d in _decisions.values() if d.get("decision") == "timeout")

    with _pending_lock:
        pending_count = len(_pending_requests)

    return {
        "total_decisions": total_decisions,
        "approved": approve_count,
        "denied": deny_count,
        "timeout": timeout_count,
        "pending": pending_count,
    }
