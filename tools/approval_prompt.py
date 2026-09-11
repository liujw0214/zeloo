"""交互式审批提示

提供命令行审批交互界面，包括：
- 危险命令审批提示
- 审批横幅和格式化输出
- 用户输入处理
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)

RISK_COLORS = {
    "safe": "\033[92m",
    "low": "\033[93m",
    "medium": "\033[93m",
    "high": "\033[91m",
    "critical": "\033[91m",
    "reset": "\033[0m",
}

RISK_EMOJI = {
    "safe": "✅",
    "low": "⚠️",
    "medium": "⚠️",
    "high": "🚨",
    "critical": "🚨",
}


def _is_color_supported() -> bool:
    """检查终端是否支持彩色输出"""
    if not hasattr(sys.stdout, "isatty"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _get_risk_color(risk_level: str) -> tuple[str, str]:
    """获取风险等级对应的颜色代码"""
    color = RISK_COLORS.get(risk_level, RISK_COLORS["reset"])
    reset = RISK_COLORS["reset"]
    return color, reset


def _get_risk_emoji(risk_level: str) -> str:
    """获取风险等级对应的 emoji"""
    return RISK_EMOJI.get(risk_level, "❓")


def print_approval_banner(command: str, risk_level: str, reason: str = "") -> None:
    """打印审批横幅

    Args:
        command: 待审批的命令
        risk_level: 风险等级
        reason: 风险原因
    """
    if not _is_color_supported():
        risk_level = "unknown"

    color, reset = _get_risk_color(risk_level)
    emoji = _get_risk_emoji(risk_level)

    width = min(80, max(60, len(command) + 20))
    separator = "=" * width

    print()
    print(f"{color}{separator}{reset}")
    print(f"{color}  {emoji}  命令审批请求  {emoji}{reset}")
    print(f"{color}{separator}{reset}")
    print()

    print(f"  风险等级: {color}{risk_level.upper()}{reset}")
    if reason:
        print(f"  风险原因: {color}{reason}{reset}")
    print()

    print(f"  命令:")
    print(f"  {color}{command}{reset}")
    print()

    print(f"{color}{separator}{reset}")
    print()


def print_safe_command(command: str) -> None:
    """打印安全命令提示

    Args:
        command: 安全命令
    """
    if _is_color_supported():
        green = "\033[92m"
        reset = "\033[0m"
        print(f"{green}✅ 安全命令已执行: {reset}{command}")
    else:
        print(f"[SAFE] {command}")


def print_dangerous_command(command: str, reason: str) -> None:
    """打印危险命令警告

    Args:
        command: 危险命令
        reason: 危险原因
    """
    if _is_color_supported():
        red = "\033[91m"
        reset = "\033[0m"
        print(f"{red}🚨 危险命令: {reset}{command}")
        print(f"{red}   原因: {reset}{reason}")
    else:
        print(f"[DANGEROUS] {command}")
        print(f"  Reason: {reason}")


def print_approval_status(
    approved: bool,
    command: str,
    reason: str = "",
) -> None:
    """打印审批状态

    Args:
        approved: 是否已批准
        command: 相关命令
        reason: 原因
    """
    if approved:
        if _is_color_supported():
            green = "\033[92m"
            reset = "\033[0m"
            print(f"{green}✅ 已批准: {reset}{command}")
        else:
            print(f"[APPROVED] {command}")
    else:
        if _is_color_supported():
            red = "\033[91m"
            reset = "\033[0m"
            print(f"{red}❌ 已拒绝: {reset}{command}")
        else:
            print(f"[DENIED] {command}")

    if reason:
        if _is_color_supported():
            yellow = "\033[93m"
            reset = "\033[0m"
            print(f"{yellow}   原因: {reset}{reason}")
        else:
            print(f"  Reason: {reason}")


def prompt_dangerous_approval(
    command: str,
    reason: str,
    risk_level: str = "high",
) -> bool:
    """显示危险命令审批提示并等待用户响应

    Args:
        command: 待审批的危险命令
        reason: 危险原因
        risk_level: 风险等级

    Returns:
        True 如果用户批准，False 如果拒绝
    """
    print_approval_banner(command, risk_level, reason)

    if risk_level == "critical":
        prompt_text = "确认执行此危险命令? [y/N]"
    elif risk_level == "high":
        prompt_text = "确认执行此高风险命令? [y/N]"
    else:
        prompt_text = "确认执行此命令? [Y/n]"

    try:
        response = input(f"\n  {prompt_text} ").strip().lower()

        if not response:
            return risk_level != "critical"

        if response in ("y", "yes", "是", "确认", "1"):
            logger.info("Command approved by user: %s", command[:50])
            return True

        if response in ("n", "no", "否", "拒绝", "0"):
            logger.info("Command denied by user: %s", command[:50])
            return False

        if response == "a" or response == "always":
            from tools.approval import approve_permanent

            approve_permanent(command)
            print("  已将此命令添加到永久白名单")
            return True

        if response == "s" or response == "session":
            from tools.approval_context import get_current_session_key
            from tools.approval import approve_command

            session_key = get_current_session_key()
            approve_command(session_key, command)
            print("  已批准此命令在当前会话中执行")
            return True

        if response == "v" or response == "view":
            print("\n  命令详情:")
            print(f"    {command}")
            print(f"\n  风险原因:")
            print(f"    {reason}")
            return prompt_dangerous_approval(command, reason, risk_level)

        if response in ("h", "help", "?"):
            print("\n  可用选项:")
            print("    y/yes/是    - 批准并执行命令")
            print("    n/no/否     - 拒绝执行命令")
            print("    a/always   - 批准并添加到永久白名单")
            print("    s/session  - 仅批准在当前会话执行")
            print("    v/view     - 查看命令详情")
            print("    h/help     - 显示此帮助")
            print("    q/quit     - 退出审批")
            return prompt_dangerous_approval(command, reason, risk_level)

        if response in ("q", "quit", "exit"):
            print("  已取消审批流程")
            return False

        print("  无效输入，请重新输入")
        return prompt_dangerous_approval(command, reason, risk_level)

    except EOFError:
        print("\n  输入已关闭，默认拒绝执行")
        return False
    except KeyboardInterrupt:
        print("\n  已取消审批流程")
        return False


def prompt_confirmation(
    message: str,
    default: Optional[bool] = None,
) -> bool:
    """通用确认提示

    Args:
        message: 提示消息
        default: 默认选项，True=默认是，False=默认否，None=无默认

    Returns:
        用户选择
    """
    if default is True:
        prompt_text = f"{message} [Y/n]"
    elif default is False:
        prompt_text = f"{message} [y/N]"
    else:
        prompt_text = f"{message} [y/n]"

    try:
        response = input(f"\n  {prompt_text} ").strip().lower()

        if not response:
            if default is not None:
                return default
            return False

        if response in ("y", "yes", "是", "1"):
            return True
        if response in ("n", "no", "否", "0"):
            return False

        print("  请输入 y 或 n")
        return prompt_confirmation(message, default)

    except EOFError:
        return False
    except KeyboardInterrupt:
        return False


def print_command_preview(
    command: str,
    index: int = 0,
    total: int = 1,
) -> None:
    """打印命令预览

    Args:
        command: 命令
        index: 当前索引
        total: 总数
    """
    if _is_color_supported():
        blue = "\033[94m"
        reset = "\033[0m"
        if total > 1:
            print(f"{blue}[{index + 1}/{total}]{reset} {command}")
        else:
            print(f"{blue}>{reset} {command}")
    else:
        if total > 1:
            print(f"[{index + 1}/{total}] {command}")
        else:
            print(f"> {command}")


def print_batch_approval_summary(
    approved: int,
    denied: int,
    skipped: int,
) -> None:
    """打印批量审批摘要

    Args:
        approved: 批准数量
        denied: 拒绝数量
        skipped: 跳过数量
    """
    if _is_color_supported():
        green = "\033[92m"
        red = "\033[91m"
        yellow = "\033[93m"
        reset = "\033[0m"
        print()
        print(f"{green}✅ 已批准: {approved}{reset}")
        print(f"{red}❌ 已拒绝: {denied}{reset}")
        print(f"{yellow}⏭️  已跳过: {skipped}{reset}")
        print()
    else:
        print()
        print(f"Approved: {approved}")
        print(f"Denied: {denied}")
        print(f"Skipped: {skipped}")
        print()


def format_command_for_display(command: str, max_width: int = 60) -> str:
    """格式化命令以便于显示

    Args:
        command: 原始命令
        max_width: 最大宽度

    Returns:
        格式化后的命令
    """
    if len(command) <= max_width:
        return command

    half = (max_width - 3) // 2
    return f"{command[:half]}...{command[-half:]}"


def print_approval_timeout_warning(timeout: float) -> None:
    """打印审批超时警告

    Args:
        timeout: 超时时间（秒）
    """
    if _is_color_supported():
        yellow = "\033[93m"
        reset = "\033[0m"
        print(f"{yellow}⚠️  审批超时时间: {timeout} 秒{reset}")
    else:
        print(f"Approval timeout: {timeout} seconds")
