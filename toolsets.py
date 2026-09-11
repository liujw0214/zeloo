"""Tool set definitions — logical grouping of tools."""

from __future__ import annotations

# Core tool sets: toolset_name -> list of tool names
zeloo_CORE_TOOLS: dict[str, list[str]] = {
    "web": ["web_search", "web_fetch"],
    "terminal": ["shell", "shell_unsafe"],
    "file": [
        "file_read", "file_write", "file_edit", "file_list", "file_find",
        "file_delete", "file_move", "file_copy",
    ],
    "browser": [
        "browser_navigate", "browser_click", "browser_type", "browser_screenshot",
        "browser_get_text", "browser_get_html", "browser_evaluate",
        "browser_back", "browser_forward", "browser_wait", "browser_close",
    ],
    "code_execution": ["execute_code"],
    "delegation": ["delegate_task"],
    "skills": ["skill_view", "skills_list", "skill_manage"],
    "memory": ["memory", "session_search"],
    "todo": ["todo_add", "todo_list", "todo_complete", "todo_remove"],
    "cron": ["cron_add", "cron_list", "cron_remove"],
    "kanban": ["kanban_create", "kanban_list", "kanban_show", "kanban_complete", "kanban_assign"],
    "voice": ["voice_tts", "voice_stt"],
    "image": ["image_generate"],
    "mcp": [],  # populated dynamically by MCPServerManager
    "optional_skill:software_development": [
        "code_review", "refactor_code", "generate_tests",
    ],
    "optional_skill:devops": [
        "cicd_analysis", "docker_diagnostics", "k8s_health",
    ],
    "optional_skill:data_science": [
        "eda", "feature_analysis", "data_quality_report",
    ],
    "optional_skill:mlops": [
        "model_drift_check", "training_diagnostics", "model_registry_info",
    ],
    "optional_skill:research": [
        "summarize_paper", "extract_citations", "literature_review",
    ],
    "optional_skill:security": [
        "dependency_audit", "secret_detection", "threat_analysis",
    ],
}

# Platform -> enabled toolsets
PLATFORM_TOOLSETS: dict[str, list[str]] = {
    "cli": [
        "web", "terminal", "file", "browser", "code_execution",
        "delegation", "skills", "memory", "todo", "mcp", "cron", "voice", "image",
        "kanban", "workspace",
        "optional_skill:software_development",
        "optional_skill:devops",
        "optional_skill:data_science",
        "optional_skill:mlops",
        "optional_skill:research",
        "optional_skill:security",
    ],
    "tui": [
        "web", "terminal", "file", "browser", "code_execution",
        "delegation", "skills", "memory", "todo", "mcp", "cron", "voice", "image",
        "optional_skill:software_development",
        "optional_skill:devops",
        "optional_skill:data_science",
        "optional_skill:mlops",
        "optional_skill:research",
        "optional_skill:security",
    ],
    "telegram": [
        "web", "file", "delegation", "skills", "memory", "mcp", "cron", "voice", "image",
        "optional_skill:software_development",
        "optional_skill:security",
    ],
    "discord": [
        "web", "file", "delegation", "skills", "memory", "mcp", "cron", "voice", "image",
        "optional_skill:software_development",
        "optional_skill:security",
    ],
    "api": [
        "web", "file", "code_execution", "delegation", "skills",
        "memory", "mcp", "cron", "voice", "image",
        "optional_skill:software_development",
        "optional_skill:devops",
        "optional_skill:data_science",
        "optional_skill:security",
    ],
    "delegated": [
        "web", "terminal", "file", "code_execution", "skills",
        "memory", "todo", "mcp", "cron", "voice", "workspace",
        "optional_skill:software_development",
        "optional_skill:devops",
        "optional_skill:data_science",
        "optional_skill:mlops",
        "optional_skill:research",
        "optional_skill:security",
    ],
}


def get_toolset_for_tool(tool_name: str) -> str | None:
    """Return the toolset name for a given tool, or None."""
    for toolset, tools in zeloo_CORE_TOOLS.items():
        if tool_name in tools:
            return toolset
    return None


def get_toolsets_for_platform(platform: str) -> list[str]:
    """Return the list of toolset names enabled for a platform."""
    return PLATFORM_TOOLSETS.get(platform, PLATFORM_TOOLSETS["cli"])
