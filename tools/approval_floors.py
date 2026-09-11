"""审批底线规则和例外

定义安全命令白名单和高风险命令黑名单，用于快速判断命令是否需要审批。

白名单（永久允许）：
- 只读命令：ls, cat, grep 等
- 信息查询命令：pwd, whoami, date 等

黑名单（直接拒绝）：
- 不可恢复的破坏性操作
- 恶意代码模式
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

SAFE_COMMANDS: frozenset[str] = frozenset({
    "ls",
    "ll",
    "dir",
    "pwd",
    "echo",
    "printf",
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "find",
    "wc",
    "sort",
    "uniq",
    "cut",
    "tr",
    "stat",
    "file",
    "date",
    "time",
    "whoami",
    "id",
    "hostname",
    "uname",
    "env",
    "printenv",
    "ps",
    "pgrep",
    "which",
    "where",
    "command",
    "man",
    "help",
    "--help",
    "-h",
    "df",
    "du",
    "free",
    "top",
    "htop",
    "tree",
    "xdg-open",
    "open",
    "code",
    "nano",
    "vim",
    "vi",
    "emacs",
    "nano",
    "less",
    "more",
    "watch",
    "diff",
    "cmp",
    "md5sum",
    "sha256sum",
    "sha1sum",
    "base64",
    "xxd",
    "hexdump",
    "od",
    "strings",
    "jq",
    "yq",
    "python",
    "python3",
    "node",
    "ruby",
    "perl",
    "php",
    "lua",
    "lua5",
    "Rscript",
})

SAFE_PREFIXES: tuple[str, ...] = (
    "ls ",
    "ls -",
    "ll ",
    "ll -",
    "dir ",
    "pwd",
    "echo ",
    "printf ",
    "cat ",
    "head ",
    "tail ",
    "less ",
    "more ",
    "grep ",
    "egrep ",
    "fgrep ",
    "rg ",
    "find ",
    "wc ",
    "sort ",
    "uniq ",
    "cut ",
    "tr ",
    "stat ",
    "file ",
    "date",
    "time ",
    "whoami",
    "id",
    "hostname",
    "uname",
    "env",
    "printenv",
    "ps ",
    "pgrep ",
    "which ",
    "where ",
    "command ",
    "man ",
    "help",
    "--help",
    "-h",
    "df ",
    "du ",
    "free",
    "top",
    "htop",
    "tree ",
    "python ",
    "python3 ",
    "node ",
    "ruby ",
    "perl ",
    "php ",
    "jq ",
    "yq ",
)

BLOCKED_COMMANDS: tuple[str, ...] = (
    r"rm\s+-rf\s+/\s*$",
    r"rm\s+-rf\s+/\*\s*$",
    r"rm\s+-rf\s+\*\s*$",
    r":\(\)\{.*:\|.*:&\};:",
    r":\(\)\{.*:;.*:&\};:",
    r"fork\s*\(\s*\)\s*;.*fork",
    r"while\s+true\s+;do\s+fork",
)

BLOCKED_COMPILED = [re.compile(pattern, re.IGNORECASE) for pattern in BLOCKED_COMMANDS]

_lock = threading.Lock()
_user_deny_rules: list[str] = []
_user_allow_rules: list[str] = []
_user_allow_compiled: list[re.Pattern[str]] = []
_user_deny_compiled: list[re.Pattern[str]] = []


def is_permanent_allowlisted(command: str) -> bool:
    """检查命令是否在永久白名单中

    白名单检查基于命令的基础名称，不考虑参数。

    Args:
        command: 待检查的命令

    Returns:
        True 如果命令在白名单中
    """
    if not command or not command.strip():
        return False

    normalized = command.strip().split()[0] if command.strip() else ""

    normalized = normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized
    normalized = normalized.lstrip("-") if normalized.startswith("-") else normalized

    if normalized in SAFE_COMMANDS:
        return True

    for prefix in SAFE_PREFIXES:
        if command.startswith(prefix):
            return True

    return False


def is_blocked(command: str) -> bool:
    """检查命令是否在黑名单中

    黑名单使用正则表达式匹配，不可绕过的危险命令直接拒绝。

    Args:
        command: 待检查的命令

    Returns:
        True 如果命令在黑名单中
    """
    if not command or not command.strip():
        return False

    for pattern in BLOCKED_COMPILED:
        if pattern.search(command):
            logger.warning("Command blocked by blacklist: %s", command[:50])
            return True

    with _lock:
        for pattern in _user_deny_compiled:
            if pattern.search(command):
                logger.warning("Command blocked by user deny rule: %s", command[:50])
                return True

    return False


def matches_user_deny_rule(command: str, rules: list[str]) -> bool:
    """匹配用户定义的拒绝规则

    Args:
        command: 待检查的命令
        rules: 拒绝规则列表

    Returns:
        True 如果命令匹配任何拒绝规则
    """
    for rule in rules:
        try:
            if re.search(rule, command, re.IGNORECASE):
                logger.debug("Command matched deny rule: %s", rule)
                return True
        except re.error as e:
            logger.error("Invalid deny rule pattern: %s - %s", rule, e)
    return False


def matches_user_allow_rule(command: str, rules: list[str]) -> bool:
    """匹配用户定义的允许规则

    Args:
        command: 待检查的命令
        rules: 允许规则列表

    Returns:
        True 如果命令匹配任何允许规则
    """
    for rule in rules:
        try:
            if re.search(rule, command, re.IGNORECASE):
                logger.debug("Command matched allow rule: %s", rule)
                return True
        except re.error as e:
            logger.error("Invalid allow rule pattern: %s - %s", rule, e)
    return False


def add_user_deny_rule(rule: str) -> None:
    """添加用户拒绝规则

    Args:
        rule: 正则表达式规则
    """
    with _lock:
        try:
            compiled = re.compile(rule, re.IGNORECASE)
            _user_deny_rules.append(rule)
            _user_deny_compiled.append(compiled)
            logger.info("Added user deny rule: %s", rule)
        except re.error as e:
            logger.error("Invalid deny rule pattern: %s - %s", rule, e)


def add_user_allow_rule(rule: str) -> None:
    """添加用户允许规则

    Args:
        rule: 正则表达式规则
    """
    with _lock:
        try:
            compiled = re.compile(rule, re.IGNORECASE)
            _user_allow_rules.append(rule)
            _user_allow_compiled.append(compiled)
            logger.info("Added user allow rule: %s", rule)
        except re.error as e:
            logger.error("Invalid allow rule pattern: %s - %s", rule, e)


def clear_user_rules() -> None:
    """清除所有用户定义的规则"""
    with _lock:
        _user_deny_rules.clear()
        _user_deny_compiled.clear()
        _user_allow_rules.clear()
        _user_allow_compiled.clear()
        logger.info("Cleared all user-defined rules")


def get_user_rules() -> dict[str, list[str]]:
    """获取用户定义的规则

    Returns:
        包含 allow 和 deny 规则的字典
    """
    with _lock:
        return {
            "allow": list(_user_allow_rules),
            "deny": list(_user_deny_rules),
        }


def _load_rules_from_config() -> None:
    """从配置文件加载规则"""
    try:
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

        deny_rules = approvals.get("deny_rules", [])
        if isinstance(deny_rules, list):
            for rule in deny_rules:
                if isinstance(rule, str):
                    add_user_deny_rule(rule)

        allow_rules = approvals.get("allow_rules", [])
        if isinstance(allow_rules, list):
            for rule in allow_rules:
                if isinstance(rule, str):
                    add_user_allow_rule(rule)

        logger.debug("Loaded %d deny rules and %d allow rules from config",
                     len(deny_rules), len(allow_rules))

    except Exception as e:
        logger.warning("Failed to load rules from config: %s", e)


def is_command_safe(command: str, check_user_rules: bool = True) -> tuple[bool, str]:
    """综合判断命令是否安全

    综合检查白名单、黑名单和用户规则。

    Args:
        command: 待检查的命令
        check_user_rules: 是否检查用户规则

    Returns:
        (是否安全, 原因描述)
    """
    if not command or not command.strip():
        return False, "empty_command"

    if is_blocked(command):
        return False, "blocked_by_blacklist"

    if is_permanent_allowlisted(command):
        return True, "in_whitelist"

    if check_user_rules:
        with _lock:
            for pattern in _user_deny_compiled:
                if pattern.search(command):
                    return False, "matched_user_deny_rule"

            for pattern in _user_allow_compiled:
                if pattern.search(command):
                    return True, "matched_user_allow_rule"

    return False, "not_in_whitelist"


def get_safe_command_hint(command: str) -> str:
    """获取安全命令提示

    当命令不在白名单时，提供替代建议。

    Args:
        command: 原始命令

    Returns:
        建议或提示字符串
    """
    if is_permanent_allowlisted(command):
        return ""

    base_cmd = command.strip().split()[0] if command.strip() else ""

    if base_cmd in ("rm", "del", "delete"):
        return "考虑使用 safe_delete 或先备份文件"
    if base_cmd in ("chmod", "chown"):
        return "检查权限设置是否正确，避免 777 或 666"
    if base_cmd in ("sudo", "su"):
        return "确认命令的必要性和安全性"

    return "此命令不在白名单中，可能需要审批"


def get_blocked_reason(command: str) -> str:
    """获取命令被阻止的原因

    Args:
        command: 被阻止的命令

    Returns:
        阻止原因描述
    """
    if not command:
        return "empty_command"

    for pattern in BLOCKED_COMPILED:
        match = pattern.search(command)
        if match:
            return f"blocked_by_pattern: {pattern.pattern[:30]}..."

    with _lock:
        for pattern in _user_deny_compiled:
            match = pattern.search(command)
            if match:
                return f"matched_user_deny: {pattern.pattern[:30]}..."

    return "unknown_reason"


def reload_rules() -> None:
    """重新加载规则（清除并重新从配置读取）"""
    clear_user_rules()
    _load_rules_from_config()
    logger.info("Rules reloaded")


_load_rules_from_config()
