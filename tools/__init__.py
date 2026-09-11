"""Zeloo Agent tools."""

from tools.mcp_tool import (
    MCPClient,
    MCPServerTask,
)
from tools.mcp_tool_discovery import (
    discover_mcp_servers,
    get_server_capabilities,
    filter_discovered_servers,
    get_server_by_name,
)
from tools.mcp_tool_handlers import (
    handle_mcp_tool_call,
    handle_mcp_tool_list,
    handle_mcp_server_status,
    handle_mcp_batch_call,
)
from tools.mcp_tool_lifecycle import (
    ServerLifecycleManager,
    start_mcp_servers,
    stop_mcp_servers,
    restart_server,
    shutdown_mcp_servers,
)
from tools.mcp_tool_config import (
    parse_mcp_servers_config,
    resolve_command,
    get_mcp_env,
    validate_server_config,
)
from tools.mcp_tool_common import (
    mcp_field,
    format_mcp_error,
    format_mcp_content,
)
from tools.browser_tool_cloud import (
    CloudBrowserAdapter,
    CloudSession,
    CloudBrowserError,
)
from tools.browser_tool_origin import (
    OriginTracker,
    OriginEntry,
)
from tools.browser_tool_vision import (
    BrowserVision,
    VisionTransport,
)
from tools.browser_tool_snapshot import (
    BrowserSnapshot,
    SnapshotManager,
)
from tools.browser_tool_real_profile import (
    RealProfileBrowser,
    LaunchPlan,
)
from tools.browser_camofox import (
    CamofoxAdapter,
    CamofoxSession,
    CamofoxElement,
    CamofoxError,
)
from tools.browser_lightpanda import (
    LightPandaAdapter,
    LightPandaSession,
    LightPandaElement,
    LightPandaError,
)
from tools.approval_human_wait import (
    HumanApprovalWaiter,
)
from tools.approval_smart import (
    SmartApprovalEngine,
)
from tools.integrations.spotify_integration import (
    SpotifyIntegration,
    SpotifyPlayer,
    SpotifySearch,
    SpotifyAPIError,
)
from tools.integrations.whatsapp_integration import (
    WhatsAppIntegration,
)
from tools.integrations.homeassistant_integration import (
    HomeAssistantIntegration,
)
from tools.integrations.github_integration import (
    GitHubIntegration,
)
from tools.approval import (
    ApprovalRequest,
    detect_dangerous_command,
    is_approved,
    approve_command,
    approve_permanent,
    revoke_approval,
    enable_yolo,
    disable_yolo,
    toggle_yolo,
    is_yolo_enabled,
    clear_session,
    get_session_approved_count,
    get_permanent_approved_count,
    request_approval,
    submit_for_review,
    check_approval_status,
    get_pending_approvals,
    approve_by_request_id,
    deny_by_request_id,
)
from tools.approval_context import (
    get_current_session_key,
    get_session_type,
    is_interactive_session,
    is_gateway_session,
    is_cron_session,
    should_auto_approve,
    get_approval_mode,
    is_yolo_mode,
    ApprovalContext,
    get_approval_timeout,
)
from tools.approval_detection import (
    DANGEROUS_PATTERNS,
    RISKY_PATTERNS,
    detect_dangerous_command as detect_cmd,
    detect_risky_command,
    get_command_risk_level,
    analyze_command,
    add_dangerous_pattern,
    add_risky_pattern,
)
from tools.approval_floors import (
    SAFE_COMMANDS,
    BLOCKED_COMMANDS,
    is_permanent_allowlisted,
    is_blocked,
    is_command_safe,
    add_user_allow_rule,
    add_user_deny_rule,
)
from tools.approval_prompt import (
    prompt_dangerous_approval,
    print_approval_banner,
    print_safe_command,
    print_dangerous_command,
    prompt_confirmation,
)
from tools.approval_gateway_wait import (
    await_gateway_decision,
    submit_approval_request,
    handle_gateway_callback,
)
from tools.browser_tool import (
    browser_click,
    browser_close,
    browser_execute_js,
    browser_get_cookies,
    browser_get_html,
    browser_get_tabs,
    browser_get_text,
    browser_get_url,
    browser_go_back,
    browser_go_forward,
    browser_hover,
    browser_info,
    browser_navigate,
    browser_new_tab,
    browser_press,
    browser_reload,
    browser_scroll,
    browser_scroll_to_element,
    browser_screenshot,
    browser_select_option,
    browser_set_cookies,
    browser_clear_cookies,
    browser_switch_tab,
    browser_close_tab,
    browser_check,
    browser_uncheck,
    browser_type,
    browser_wait,
    get_current_page,
)
from tools.browser_tool_install import (
    check_browsers_installed,
    check_chrome_installed,
    check_firefox_installed,
    check_playwright_installed,
    get_installation_instructions,
    get_playwright_version,
    install_browsers,
    install_playwright,
    verify_installation,
)
from tools.browser_tool_lifecycle import (
    BrowserLifecycle,
    cleanup_all_sessions,
    get_lifecycle,
    register_emergency_cleanup,
    reset_session_manager,
    setup_lifecycle_hooks,
)
from tools.browser_tool_session import (
    BrowserSession,
    BrowserSessionManager,
    get_session_manager,
)
from tools.browser_cdp_tool import (
    CDPClient,
    CDPServer,
    CDPCommand,
    CDPMessage,
    create_cdp_client_from_url,
    get_available_tabs,
    get_cdp_debugging_url,
    parse_cdp_ws_url,
)
from tools.browser_supervisor import (
    BrowserSupervisor,
    SupervisorConfig,
    HealthStatus,
    get_supervisor,
    reset_supervisor,
)
from tools.profile_distribution import (
    ProfileDistribution,
    ProfileRevision,
    ProfileDiff,
    ProfileSource,
    ProfileMerge,
    ProfileMergeStrategy,
    clone_profile_repo,
    fetch_profile,
    sync_profiles,
    import_profile_from_git,
    export_profile_to_git,
    profile_add_source,
    profile_remove_source,
    profile_list_sources,
    profile_pull,
    profile_diff,
)
from tools.journey_tracker import (
    JourneyTracker,
    Goal,
    Journey,
    Checkpoint,
    GoalStatus,
    Priority,
    GoalsView,
    create_goal,
    list_goals,
    complete_goal,
    pause_goal,
    add_checkpoint,
    get_journey_progress,
    goals_summary,
    render_goals_board,
    create_journey,
    list_journeys,
)
from tools.mcp_oauth import (
    MCPOAuthClient,
    OAuthConfig,
)
from tools.mcp_oauth_device import (
    DeviceCodeClient,
)
from tools.mcp_oauth_manager import (
    MCPOAuthManager,
)
from tools.database_tool import (
    DatabaseTool,
    DatabaseDriver,
    DatabaseConnection,
    DatabaseQueryResult,
    parse_connection_string,
    db_query,
    db_execute,
    db_list_tables,
    db_describe_table,
    db_list_databases,
    db_backup,
    db_explain,
)
from tools.ssh_tool import (
    SSHTool,
    SSHConfig,
    SSHResult,
    SSHConfigParser,
    ssh_execute,
    ssh_upload,
    ssh_download,
    ssh_test,
)
from tools.clipboard_tool import (
    ClipboardTool,
    ClipboardEntry,
    clipboard_read,
    clipboard_write,
    clipboard_clear,
    clipboard_history,
    clipboard_add,
)
from tools.file_operations import (
    FileOperations,
)
from tools.file_operations_common import (
    normalize_path,
    safe_read,
    safe_write,
    compute_hash,
    get_file_info,
    is_binary,
    guess_mime_type,
)
from tools.file_operations_search import (
    FileSearch,
)
from tools.file_operations_lint import (
    FileLint,
)
from tools.file_state import (
    FileStateTracker,
)
from tools.file_operations_batch import (
    BatchFileOperations,
)
from tools.delegate_tool_child_run import (
    ChildTaskRunner,
    TaskResult,
)
from tools.delegate_tool_config import (
    DelegateConfig,
    DelegateConfigManager,
)
from tools.delegate_tool_dispatch import (
    TaskDispatcher,
)
from tools.delegate_tool_progress import (
    TaskProgressTracker,
)
from tools.delegate_tool_registry import (
    TaskRegistry,
)
from tools.delegate_tool_tasks import (
    DelegatedTaskManager,
)
from tools.code_execution_env import (
    VirtualEnvEnvironment,
    DockerEnvironment,
    RemoteEnvironment,
)
from tools.code_execution_rpc import (
    CodeExecutionRPC,
)
from tools.code_kernel import (
    CodeKernel,
    KernelManager,
)
from tools.mcp_discovery_auto import (
    MCPAutoDiscovery,
    MCPServerCandidate,
    mcp_scan_all,
    mcp_scan_npm,
    mcp_scan_pip,
    mcp_auto_register,
)

__all__ = [
    # MCP tools
    "MCPClient", "MCPServerTask",
    "discover_mcp_servers", "get_server_capabilities",
    "filter_discovered_servers", "get_server_by_name",
    "handle_mcp_tool_call", "handle_mcp_tool_list",
    "handle_mcp_server_status", "handle_mcp_batch_call",
    "ServerLifecycleManager", "start_mcp_servers", "stop_mcp_servers",
    "restart_server", "shutdown_mcp_servers",
    "parse_mcp_servers_config", "resolve_command",
    "get_mcp_env", "validate_server_config",
    "mcp_field", "format_mcp_error", "format_mcp_content",
    "MCPOAuthClient", "OAuthConfig", "DeviceCodeClient", "MCPOAuthManager",
    # Approval tools
    "ApprovalRequest",
    "detect_dangerous_command", "is_approved", "approve_command",
    "approve_permanent", "revoke_approval",
    "enable_yolo", "disable_yolo", "toggle_yolo", "is_yolo_enabled",
    "clear_session", "request_approval",
    "get_session_approved_count", "get_permanent_approved_count",
    "get_pending_approvals", "submit_for_review",
    "check_approval_status", "approve_by_request_id", "deny_by_request_id",
    "get_current_session_key", "get_session_type",
    "is_interactive_session", "is_gateway_session", "is_cron_session",
    "should_auto_approve", "get_approval_mode", "is_yolo_mode",
    "ApprovalContext", "get_approval_timeout",
    "DANGEROUS_PATTERNS", "RISKY_PATTERNS", "detect_cmd",
    "detect_risky_command", "get_command_risk_level", "analyze_command",
    "add_dangerous_pattern", "add_risky_pattern",
    "SAFE_COMMANDS", "BLOCKED_COMMANDS",
    "is_permanent_allowlisted", "is_blocked", "is_command_safe",
    "add_user_allow_rule", "add_user_deny_rule",
    "prompt_dangerous_approval", "print_approval_banner",
    "print_safe_command", "print_dangerous_command", "prompt_confirmation",
    "await_gateway_decision", "submit_approval_request", "handle_gateway_callback",
    # Browser tools
    "browser_click",
    "browser_close",
    "browser_execute_js",
    "browser_get_cookies",
    "browser_get_html",
    "browser_get_tabs",
    "browser_get_text",
    "browser_get_url",
    "browser_go_back",
    "browser_go_forward",
    "browser_hover",
    "browser_info",
    "browser_navigate",
    "browser_new_tab",
    "browser_press",
    "browser_reload",
    "browser_scroll",
    "browser_scroll_to_element",
    "browser_screenshot",
    "browser_select_option",
    "browser_set_cookies",
    "browser_clear_cookies",
    "browser_switch_tab",
    "browser_close_tab",
    "browser_check",
    "browser_uncheck",
    "browser_type",
    "browser_wait",
    "get_current_page",
    "check_playwright_installed",
    "get_playwright_version",
    "check_chrome_installed",
    "check_firefox_installed",
    "check_browsers_installed",
    "install_playwright",
    "install_browsers",
    "verify_installation",
    "get_installation_instructions",
    "BrowserLifecycle",
    "get_lifecycle",
    "cleanup_all_sessions",
    "setup_lifecycle_hooks",
    "register_emergency_cleanup",
    "reset_session_manager",
    "BrowserSession",
    "BrowserSessionManager",
    "get_session_manager",
    "CDPClient",
    "CDPServer",
    "CDPCommand",
    "CDPMessage",
    "get_cdp_debugging_url",
    "parse_cdp_ws_url",
    "create_cdp_client_from_url",
    "get_available_tabs",
    "BrowserSupervisor",
    "SupervisorConfig",
    "HealthStatus",
    "get_supervisor",
    "reset_supervisor",
    # Profile distribution tools
    "ProfileDistribution",
    "ProfileRevision",
    "ProfileDiff",
    "ProfileSource",
    "ProfileMerge",
    "ProfileMergeStrategy",
    "clone_profile_repo",
    "fetch_profile",
    "sync_profiles",
    "import_profile_from_git",
    "export_profile_to_git",
    "profile_add_source",
    "profile_remove_source",
    "profile_list_sources",
    "profile_pull",
    "profile_diff",
    # Round 71-77 advanced tools
    "CloudBrowserAdapter", "CloudSession", "CloudBrowserError",
    "OriginTracker", "OriginEntry",
    "BrowserVision", "VisionTransport",
    "BrowserSnapshot", "SnapshotManager",
    "RealProfileBrowser", "LaunchPlan",
    "CamofoxAdapter", "CamofoxSession", "CamofoxElement", "CamofoxError",
    "LightPandaAdapter", "LightPandaSession", "LightPandaElement", "LightPandaError",
    "HumanApprovalWaiter",
    "SmartApprovalEngine",
    "SpotifyIntegration", "SpotifyPlayer", "SpotifySearch", "SpotifyAPIError",
    "WhatsAppIntegration", "HomeAssistantIntegration", "GitHubIntegration",
]
