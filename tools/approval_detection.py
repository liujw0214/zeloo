"""危险命令模式检测

提供危险命令和高风险命令的检测功能，使用正则表达式匹配。

危险命令分类：
- 文件删除类：根目录删除、递归删除
- 网络安全类：远程代码执行、反向 shell
- 系统修改类：权限修改、Fork bomb
- 凭据泄露类：Token 操作、密钥写入
"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

RiskLevel = Literal["safe", "low", "medium", "high", "critical"]

DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+/\*?", "危险: 根目录递归删除"),
    (r"rm\s+-rf\s+\.\*", "危险: 递归删除所有文件"),
    (r"rm\s+-rf\s+/\*\s*$", "危险: 根目录递归删除"),
    (r"find\s+/.*-delete", "危险: find 删除"),
    (r"find\s+/\s+-name\s+.*-exec\s+rm", "危险: find + rm 组合"),
    (r"dd\s+if=.*of=/dev/", "危险: 直接写入设备"),
    (r"mkfs\s+", "危险: 格式化文件系统"),
    (r"fdisk\s+", "危险: 分区操作"),
    (r"parted\s+", "危险: 分区操作"),
    (r"curl\s+.*\|.*(sh|bash|python)", "危险: 远程代码执行"),
    (r"wget\s+.*\|.*(sh|bash|python)", "危险: 远程代码执行"),
    (r"curl\s+.*--upload-file", "危险: 数据上传"),
    (r"curl\s+.*-T\s+", "危险: 数据上传"),
    (r"wget\s+.*-O\s+/", "危险: 下载到根目录"),
    (r"nc\s+-e\s+", "危险: 反向 shell"),
    (r"ncat\s+.*-e\s+", "危险: 反向 shell"),
    (r"bash\s+-i\s+>\s*/dev/tcp/", "危险: 反向 shell"),
    (r"/dev/tcp/", "危险: TCP shell"),
    (r"perl\s+.*-e\s+.*system", "危险: Perl 代码执行"),
    (r"python.*-c\s+.*import\s+os", "危险: Python 代码执行"),
    (r"ruby\s+.*-e\s+.*exec", "危险: Ruby 代码执行"),
    (r"php\s+.*-r\s+.*system", "危险: PHP 代码执行"),
    (r"chmod\s+777\s+/\s", "危险: 777 权限根目录"),
    (r"chmod\s+-R\s+777\s+/\s", "危险: 递归 777 权限"),
    (r"chmod\s+777\s+.", "危险: 777 权限"),
    (r"chmod\s+-R\s+777", "危险: 递归 777 权限"),
    (r"chown\s+-R\s+.*:root\s+/\s", "危险: 递归修改所有者为 root"),
    (r"chgrp\s+-R\s+.*root\s+/\s", "危险: 递归修改组为 root"),
    (r":\(\)\{\s*:\|\s*:&\s*\};:", "危险: Fork bomb"),
    (r"fork\s*\(\s*\)\s*;.*fork", "危险: Fork bomb"),
    (r"gh\s+auth\s+token", "危险: GitHub token 操作"),
    (r"hermes\s+config\s+set.*api[_-]?key", "危险: 写入 API key"),
    (r"kubectl\s+delete\s+--all", "危险: 删除所有 Kubernetes 资源"),
    (r"docker\s+rm\s+-f\s+\$\(docker\s+ps\s+-aq\)", "危险: 删除所有容器"),
    (r"docker\s+rmi\s+\$\(docker\s+images\s+-q\)", "危险: 删除所有镜像"),
    (r"kill\s+-9\s+-1", "危险: 终止所有进程"),
    (r"init\s+0", "危险: 关机命令"),
    (r"shutdown\s+-h\s+now", "危险: 关机命令"),
    (r"reboot", "危险: 重启命令"),
    (r"halt", "危险: 停止命令"),
    (r"poweroff", "危险: 关机命令"),
    (r"echo\s+.*>\s*/etc/sudoers", "危险: 修改 sudoers 文件"),
    (r"echo\s+.*>\s*/etc/passwd", "危险: 修改 passwd 文件"),
    (r"cat\s+/etc/shadow", "危险: 读取 shadow 文件"),
    (r"ssh\s+.*-o\s+StrictHostKeyChecking=no", "危险: 跳过 SSH 主机验证"),
    (r"scp\s+.*:/etc/", "危险: 复制敏感文件"),
    (r"base64\s+-d\s+.*\|.*sh", "危险: Base64 编码的 shell 执行"),
    (r"openssl\s+req\s+-x509\s+-newkey", "危险: 生成自签名证书"),
]

RISKY_PATTERNS: list[tuple[str, str]] = [
    (r"sudo\s+", "高风险: sudo 命令"),
    (r"apt-get\s+install", "高风险: 安装软件包"),
    (r"apt\s+install", "高风险: 安装软件包"),
    (r"yum\s+install", "高风险: 安装软件包"),
    (r"dnf\s+install", "高风险: 安装软件包"),
    (r"pacman\s+-S\s+", "高风险: 安装软件包"),
    (r"pip\s+install", "高风险: 安装 Python 包"),
    (r"pip3\s+install", "高风险: 安装 Python 包"),
    (r"npm\s+install\s+-g", "高风险: 全局安装 npm 包"),
    (r"yarn\s+global\s+add", "高风险: 全局安装 yarn 包"),
    (r"gem\s+install", "高风险: 安装 Ruby gem"),
    (r"cargo\s+install", "高风险: 安装 Rust 包"),
    (r"go\s+install", "高风险: 安装 Go 包"),
    (r"composer\s+require", "高风险: 安装 PHP 包"),
    (r"docker\s+run", "高风险: 运行 Docker 容器"),
    (r"docker\s+exec", "高风险: 在容器中执行命令"),
    (r"kubectl\s+apply\s+-f", "高风险: 应用 Kubernetes 配置"),
    (r"kubectl\s+create\s+", "高风险: 创建 Kubernetes 资源"),
    (r"terraform\s+apply", "高风险: 应用 Terraform 配置"),
    (r"terraform\s+destroy", "高风险: 销毁 Terraform 资源"),
    (r"aws\s+.*\s+delete", "高风险: 删除 AWS 资源"),
    (r"gcloud\s+.*\s+delete", "高风险: 删除 GCP 资源"),
    (r"az\s+.*\s+delete", "高风险: 删除 Azure 资源"),
    (r"chmod\s+", "高风险: 修改文件权限"),
    (r"chown\s+", "高风险: 修改文件所有者"),
    (r"useradd\s+", "高风险: 创建用户"),
    (r"userdel\s+", "高风险: 删除用户"),
    (r"passwd\s+", "高风险: 修改密码"),
    (r"crontab\s+-r", "高风险: 删除 crontab"),
    (r"service\s+", "高风险: 服务管理"),
    (r"systemctl\s+stop", "高风险: 停止系统服务"),
    (r"systemctl\s+disable", "高风险: 禁用系统服务"),
    (r"iptables\s+-F", "高风险: 清空 iptables 规则"),
    (r"ufw\s+disable", "高风险: 禁用防火墙"),
    (r"mv\s+.*\s+/tmp", "高风险: 移动文件到临时目录"),
    (r">\s*/var/log/", "高风险: 清空日志文件"),
    (r":\s*>\s*/var/log/", "高风险: 清空日志文件"),
    (r">\s*.*\.log", "高风险: 清空日志文件"),
]

DANGEROUS_COMPILED = [(re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in DANGEROUS_PATTERNS]
RISKY_COMPILED = [(re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in RISKY_PATTERNS]


def detect_dangerous_command(command: str) -> tuple[bool, str]:
    """检测命令是否危险

    Args:
        command: 待检测的命令字符串

    Returns:
        (是否危险, 原因描述)
    """
    if not command or not command.strip():
        return False, ""

    for pattern, reason in DANGEROUS_COMPILED:
        if pattern.search(command):
            logger.warning("Dangerous command detected: %s", reason)
            return True, reason

    return False, ""


def detect_risky_command(command: str) -> tuple[bool, str]:
    """检测命令是否有风险

    Args:
        command: 待检测的命令字符串

    Returns:
        (是否有风险, 原因描述)
    """
    if not command or not command.strip():
        return False, ""

    for pattern, reason in RISKY_COMPILED:
        if pattern.search(command):
            logger.debug("Risky command detected: %s", reason)
            return True, reason

    return False, ""


def get_command_risk_level(command: str) -> RiskLevel:
    """获取命令风险等级

    Args:
        command: 待检测的命令字符串

    Returns:
        风险等级: safe | low | medium | high | critical
    """
    if not command or not command.strip():
        return "safe"

    dangerous, _ = detect_dangerous_command(command)
    if dangerous:
        return "critical"

    risky, _ = detect_risky_command(command)
    if risky:
        for pattern, _ in RISKY_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                if any(x in command for x in ["rm", "delete", "kill", "destroy"]):
                    return "high"
                if any(x in command for x in ["sudo", "chmod", "chown"]):
                    return "medium"
                return "low"

    return "safe"


def analyze_command(command: str) -> dict[str, any]:
    """分析命令并返回详细信息

    Args:
        command: 待分析的命令

    Returns:
        包含分析结果的字典
    """
    dangerous, danger_reason = detect_dangerous_command(command)
    risky, risk_reason = detect_risky_command(command)
    risk_level = get_command_risk_level(command)

    return {
        "command": command,
        "is_dangerous": dangerous,
        "danger_reason": danger_reason,
        "is_risky": risky,
        "risk_reason": risk_reason,
        "risk_level": risk_level,
        "requires_approval": risk_level in ("high", "critical"),
    }


def add_dangerous_pattern(pattern: str, reason: str) -> None:
    """添加自定义危险模式

    Args:
        pattern: 正则表达式模式
        reason: 原因描述
    """
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
        DANGEROUS_COMPILED.append((compiled, reason))
        DANGEROUS_PATTERNS.append((pattern, reason))
        logger.info("Added dangerous pattern: %s", reason)
    except re.error as e:
        logger.error("Invalid dangerous pattern: %s", e)


def add_risky_pattern(pattern: str, reason: str) -> None:
    """添加自定义风险模式

    Args:
        pattern: 正则表达式模式
        reason: 原因描述
    """
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
        RISKY_COMPILED.append((compiled, reason))
        RISKY_PATTERNS.append((pattern, reason))
        logger.info("Added risky pattern: %s", reason)
    except re.error as e:
        logger.error("Invalid risky pattern: %s", e)


def get_risk_description(risk_level: RiskLevel) -> str:
    """获取风险等级描述

    Args:
        risk_level: 风险等级

    Returns:
        风险等级描述
    """
    descriptions = {
        "safe": "安全 - 无需审批",
        "low": "低风险 - 可能需要审批",
        "medium": "中风险 - 建议审批",
        "high": "高风险 - 需要审批",
        "critical": "危险 - 强制审批",
    }
    return descriptions.get(risk_level, "未知")


def scan_command_list(commands: list[str]) -> dict[str, any]:
    """批量扫描命令列表

    Args:
        commands: 命令列表

    Returns:
        扫描结果统计
    """
    results = {
        "total": len(commands),
        "safe": 0,
        "low": 0,
        "medium": 0,
        "high": 0,
        "critical": 0,
        "details": [],
    }

    for cmd in commands:
        analysis = analyze_command(cmd)
        risk_level = analysis["risk_level"]
        results[risk_level] = results.get(risk_level, 0) + 1
        if risk_level in ("high", "critical"):
            results["details"].append(analysis)

    return results
