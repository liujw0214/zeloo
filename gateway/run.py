"""Gateway runtime — multi-platform message routing.

Integrates:
* :class:`gateway.session.SessionManager` for per-user session isolation.
* Platform adapters (Telegram, Discord, ...).
* Optional OpenAI-compatible API server.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from gateway.api_server import DEFAULT_PORT as _API_PORT
from gateway.session import SessionManager

logger = logging.getLogger(__name__)


def _t(key: str, **kwargs: object) -> str:
    """Translate a message key using the active i18n locale."""
    try:
        from agent.i18n import gettext

        return gettext(key, **kwargs)
    except Exception:
        # Fallback to the key itself if i18n is unavailable
        return key


class Gateway:
    """Multi-platform message gateway."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.platforms: dict[str, Any] = {}
        self._api_server: Any | None = None

        # Apply i18n language from config (default: en)
        language = config.get("language", "en")
        try:
            from agent.i18n import set_language

            set_language(language)
        except Exception:
            logger.debug("i18n not available, using default language")

        # Session DB + manager
        from zeloo_state import SessionDB

        self._session_db = SessionDB()

        allowed = self._build_allowed_users(config)
        idle_timeout = config.get("session_idle_timeout", 3600)
        self._session_manager = SessionManager(
            self._session_db,
            idle_timeout=idle_timeout,
            allowed_users=allowed,
        )

        # Idle-eviction background thread
        self._stop_eviction = threading.Event()
        self._eviction_thread: threading.Thread | None = None

    # ── Public API ──────────────────────────────────────────────────

    def register_platform(self, name: str, adapter: Any) -> None:
        """Register a platform adapter."""
        self.platforms[name] = adapter
        logger.info("Registered platform: %s", name)

    def handle_message(self, platform: str, user_id: str, message: str) -> str:
        """Handle an incoming message from a platform."""
        agent = self._session_manager.get_or_create_agent(
            user_id=user_id,
            platform=platform,
            agent_factory=self._make_agent,
        )
        if agent is None:
            return _t("not_authorized")
        return agent.run_conversation(message)

    def run(self) -> None:
        """Start the gateway (platform adapters + optional API server)."""
        logger.info("Gateway starting with %d platform(s)", len(self.platforms))

        # Start idle eviction loop
        self._eviction_thread = threading.Thread(
            target=self._eviction_loop, daemon=True, name="gateway-eviction"
        )
        self._eviction_thread.start()

        # Start API server if configured
        api_config = self.config.get("api", {})
        if api_config.get("enabled"):
            self._start_api_server(api_config)

        # Start platform adapters (blocking)
        for name, adapter in self.platforms.items():
            try:
                adapter.start(self.handle_message)
            except Exception:
                logger.exception("Platform %s failed to start", name)

    def shutdown(self) -> None:
        """Stop all platforms and the API server."""
        logger.info("Gateway shutting down")
        self._stop_eviction.set()
        if self._api_server is not None:
            self._api_server.stop()
        for name, adapter in self.platforms.items():
            try:
                adapter.stop()
            except Exception:
                logger.exception("Platform %s failed to stop", name)
        self._session_db.close()

    # ── Internal helpers ────────────────────────────────────────────

    def _make_agent(self, session_id: str, platform: str, user_id: str = "") -> Any:
        """Factory for AIAgent instances.

        Selects model/provider/toolsets from the user's profile (if mapped
        in ``gateway.user_profiles``), otherwise falls back to the default
        profile or top-level config.
        """
        from run_agent import AIAgent

        profile = self._get_profile_for_user(user_id)

        default_model = self.config.get("model", os.environ.get("zeloo_MODEL", "gpt-4o"))
        default_provider = self.config.get(
            "provider", os.environ.get("zeloo_PROVIDER", "openai")
        )
        model = profile.get("model", default_model)
        provider = profile.get("provider", default_provider)
        base_url = profile.get("base_url", self.config.get("base_url"))
        api_key = profile.get("api_key", self.config.get("api_key"))

        agent = AIAgent(
            model=model,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            platform=platform,
            restore_session_id=session_id,
        )
        return agent

    def _get_profile_for_user(self, user_id: str) -> dict[str, Any]:
        """Return the profile config for a user, or the default profile.

        Looks up ``gateway.user_profiles[user_id]`` then
        ``gateway.profiles[<name>]``. Falls back to ``gateway.profiles.default``
        or an empty dict (meaning "use top-level config").
        """
        gw_cfg = self.config.get("gateway", {})
        if not isinstance(gw_cfg, dict):
            return {}

        profiles = gw_cfg.get("profiles", {})
        if not isinstance(profiles, dict):
            return {}

        user_profiles = gw_cfg.get("user_profiles", {})
        if not isinstance(user_profiles, dict):
            user_profiles = {}

        profile_name = user_profiles.get(user_id)
        if profile_name and profile_name in profiles:
            return profiles[profile_name]

        return profiles.get("default", {})

    @staticmethod
    def _build_allowed_users(config: dict[str, Any]) -> dict[str, list[str] | None]:
        """Extract per-platform allowed_users from config."""
        allowed: dict[str, list[str] | None] = {}
        platforms_cfg = config.get("platforms", {})
        for name, pcfg in platforms_cfg.items():
            users = pcfg.get("allowed_users")
            allowed[name] = list(users) if users else None
        return allowed

    def _start_api_server(self, api_config: dict[str, Any]) -> None:
        """Start the OpenAI-compatible API server."""
        from gateway.api_server import APIServer

        # Bearer token auth: api_server.auth.tokens (list) or env zeloo_API_TOKEN
        auth_cfg = api_config.get("auth", {}) if isinstance(api_config, dict) else {}
        tokens: list[str] = list(auth_cfg.get("tokens", []))
        import os

        env_token = os.environ.get("zeloo_API_TOKEN", "").strip()
        if env_token:
            tokens.append(env_token)

        def _mcp_reload() -> int:
            """Reload MCP servers on all active agents and return total tools."""
            from zeloo_cli.config import load_config

            try:
                cfg = load_config()
            except Exception:
                cfg = None

            total = 0
            for _uid, _plat, agent in self._session_manager.iter_active_agents():
                mgr = getattr(agent, "_mcp_manager", None)
                if mgr is not None:
                    total += mgr.reload(cfg)
            return total

        self._api_server = APIServer(
            agent_factory=lambda **kw: self._make_agent(
                session_id=self._session_manager._create_session("api", "api"),
                platform="api",
            ),
            host=api_config.get("host", "0.0.0.0"),
            port=api_config.get("port", _API_PORT),
            model_name=self.config.get("model", "Zeloo"),
            auth_tokens=tokens or None,
            mcp_reload_callback=_mcp_reload,
        )
        self._api_server.start()

    def _eviction_loop(self) -> None:
        """Periodically evict idle agent instances."""
        interval = self.config.get("eviction_interval", 300)
        while not self._stop_eviction.wait(interval):
            try:
                self._session_manager.evict_idle()
            except Exception:
                logger.exception("Idle eviction failed")


def build_gateway_from_config(config: dict[str, Any]) -> Gateway:
    """Build a Gateway and register configured platform adapters.

    Platforms are only registered when their SDK is importable; missing
    dependencies are logged and skipped.
    """
    gateway = Gateway(config)

    platforms_cfg = config.get("platforms", {})

    for name, pcfg in platforms_cfg.items():
        if not pcfg.get("enabled", False):
            continue

        try:
            adapter = _build_adapter(name, pcfg)
            gateway.register_platform(name, adapter)
        except ImportError as e:
            logger.warning("Skipping platform %s: %s", name, e)
        except Exception:
            logger.exception("Failed to build adapter for platform %s", name)

    return gateway


def _build_adapter(name: str, config: dict[str, Any]) -> Any:
    """Build a platform adapter from its config block."""
    if name == "telegram":
        from gateway.platforms.telegram import TelegramAdapter

        token = config.get("token") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError("telegram token is required")
        return TelegramAdapter(
            token=token,
            allowed_users=config.get("allowed_users"),
        )
    elif name == "discord":
        from gateway.platforms.discord import DiscordAdapter

        token = config.get("token") or os.environ.get("DISCORD_BOT_TOKEN", "")
        if not token:
            raise ValueError("discord token is required")
        return DiscordAdapter(
            token=token,
            allowed_users=config.get("allowed_users"),
            guild_id=config.get("guild_id"),
            allowed_guilds=config.get("allowed_guilds"),
            allowed_roles=config.get("allowed_roles"),
        )
    elif name == "slack":
        from gateway.platforms.slack import SlackAdapter

        token = config.get("bot_token") or os.environ.get("SLACK_BOT_TOKEN", "")
        if not token:
            raise ValueError("slack bot_token is required")
        return SlackAdapter(
            bot_token=token,
            signing_secret=config.get("signing_secret"),
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "whatsapp":
        from gateway.platforms.whatsapp import WhatsAppAdapter

        token = config.get("access_token") or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        phone_id = config.get("phone_number_id") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        if not token or not phone_id:
            raise ValueError("whatsapp access_token and phone_number_id are required")
        return WhatsAppAdapter(
            access_token=token,
            phone_number_id=phone_id,
            verify_token=config.get("verify_token"),
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "signal":
        from gateway.platforms.signal import SignalAdapter

        account = config.get("account") or os.environ.get("SIGNAL_ACCOUNT", "")
        if not account:
            raise ValueError("signal account is required")
        return SignalAdapter(
            account=account,
            signal_cli_path=config.get("signal_cli_path", "signal-cli"),
            api_url=config.get("api_url"),
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "email":
        from gateway.platforms.email_adapter import EmailAdapter

        return EmailAdapter(
            smtp_host=config["smtp_host"],
            smtp_port=int(config.get("smtp_port", 465)),
            imap_host=config["imap_host"],
            imap_port=int(config.get("imap_port", 993)),
            username=config["username"],
            password=config["password"],
            use_tls=bool(config.get("use_tls", True)),
            poll_interval=int(config.get("poll_interval", 30)),
        )
    elif name == "feishu":
        from gateway.platforms.feishu import FeishuAdapter

        app_id = config.get("app_id") or os.environ.get("FEISHU_APP_ID", "")
        app_secret = config.get("app_secret") or os.environ.get("FEISHU_APP_SECRET", "")
        if not app_id or not app_secret:
            raise ValueError("feishu app_id and app_secret are required")
        return FeishuAdapter(
            app_id=app_id,
            app_secret=app_secret,
            encrypt_key=config.get("encrypt_key"),
            verification_token=config.get("verification_token"),
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "dingtalk":
        from gateway.platforms.dingtalk import DingTalkAdapter

        app_key = config.get("app_key") or os.environ.get("DINGTALK_APP_KEY", "")
        app_secret = config.get("app_secret") or os.environ.get("DINGTALK_APP_SECRET", "")
        if not app_key or not app_secret:
            raise ValueError("dingtalk app_key and app_secret are required")
        return DingTalkAdapter(
            app_key=app_key,
            app_secret=app_secret,
            verify_token=config.get("verify_token"),
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "wecom":
        from gateway.platforms.wecom import WeComAdapter

        corp_id = config.get("corp_id") or os.environ.get("WECOM_CORP_ID", "")
        corp_secret = config.get("corp_secret") or os.environ.get("WECOM_CORP_SECRET", "")
        agent_id = int(config.get("agent_id") or os.environ.get("WECOM_AGENT_ID", 0))
        if not corp_id or not corp_secret or not agent_id:
            raise ValueError("wecom corp_id, corp_secret and agent_id are required")
        return WeComAdapter(
            corp_id=corp_id,
            corp_secret=corp_secret,
            agent_id=agent_id,
            token=config.get("token"),
            encoding_aes_key=config.get("encoding_aes_key"),
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "teams":
        from gateway.platforms.teams import TeamsAdapter

        bot_id = config.get("bot_id") or os.environ.get("TEAMS_BOT_ID", "")
        bot_password = config.get("bot_password") or os.environ.get(
            "TEAMS_BOT_PASSWORD", ""
        )
        if not bot_id or not bot_password:
            raise ValueError("teams bot_id and bot_password are required")
        return TeamsAdapter(
            bot_id=bot_id,
            bot_password=bot_password,
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "matrix":
        from gateway.platforms.matrix import MatrixAdapter

        homeserver = config.get("homeserver") or os.environ.get("MATRIX_HOMESERVER", "")
        access_token = config.get("access_token") or os.environ.get(
            "MATRIX_ACCESS_TOKEN", ""
        )
        user_id = config.get("user_id") or os.environ.get("MATRIX_USER_ID", "")
        if not homeserver or not access_token or not user_id:
            raise ValueError("matrix homeserver, access_token and user_id are required")
        return MatrixAdapter(
            homeserver=homeserver,
            access_token=access_token,
            user_id=user_id,
        )
    elif name == "google_chat":
        from gateway.platforms.google_chat import GoogleChatAdapter

        return GoogleChatAdapter(
            service_account_json=config.get("service_account_json"),
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "sms":
        from gateway.platforms.sms import SMSAdapter

        sid = config.get("account_sid") or os.environ.get("TWILIO_ACCOUNT_SID", "")
        token = config.get("auth_token") or os.environ.get("TWILIO_AUTH_TOKEN", "")
        from_num = config.get("from_number") or os.environ.get("TWILIO_FROM_NUMBER", "")
        if not sid or not token or not from_num:
            raise ValueError("sms account_sid, auth_token and from_number are required")
        return SMSAdapter(
            account_sid=sid,
            auth_token=token,
            from_number=from_num,
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "qqbot":
        from gateway.platforms.qqbot import QQBotAdapter

        app_id = config.get("app_id") or os.environ.get("QQBOT_APP_ID", "")
        app_secret = config.get("app_secret") or os.environ.get("QQBOT_APP_SECRET", "")
        if not app_id or not app_secret:
            raise ValueError("qqbot app_id and app_secret are required")
        return QQBotAdapter(
            app_id=app_id,
            app_secret=app_secret,
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "irc":
        from gateway.platforms.irc import IRCAdapter

        server = config.get("server") or os.environ.get("IRC_SERVER", "")
        nickname = config.get("nickname") or os.environ.get("IRC_NICKNAME", "")
        channel = config.get("channel") or os.environ.get("IRC_CHANNEL", "")
        if not server or not nickname or not channel:
            raise ValueError("irc server, nickname and channel are required")
        return IRCAdapter(
            server=server,
            nickname=nickname,
            channel=channel,
            port=int(config.get("port", 6667)),
            password=config.get("password"),
        )
    elif name == "line":
        from gateway.platforms.line import LINEAdapter

        access_token = config.get("channel_access_token") or os.environ.get(
            "LINE_CHANNEL_ACCESS_TOKEN", ""
        )
        channel_secret = config.get("channel_secret") or os.environ.get(
            "LINE_CHANNEL_SECRET", ""
        )
        if not access_token:
            raise ValueError("line channel_access_token is required")
        return LINEAdapter(
            channel_access_token=access_token,
            channel_secret=channel_secret,
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "mattermost":
        from gateway.platforms.mattermost import MattermostAdapter

        base_url = config.get("base_url") or os.environ.get("MATTERMOST_URL", "")
        bot_token = config.get("bot_token") or os.environ.get("MATTERMOST_TOKEN", "")
        if not base_url or not bot_token:
            raise ValueError("mattermost base_url and bot_token are required")
        return MattermostAdapter(
            base_url=base_url,
            bot_token=bot_token,
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    elif name == "home_assistant":
        from gateway.platforms.home_assistant import HomeAssistantAdapter

        ha_url = config.get("ha_url") or os.environ.get("HA_URL", "")
        ha_token = config.get("ha_token") or os.environ.get("HA_TOKEN", "")
        if not ha_url or not ha_token:
            raise ValueError("home_assistant ha_url and ha_token are required")
        return HomeAssistantAdapter(
            ha_url=ha_url,
            ha_token=ha_token,
            webhook_port=int(config.get("webhook_port", _API_PORT)),
        )
    else:
        raise ValueError(f"Unknown platform: {name}")


def main(
    port: int | None = None,
    home: str | None = None,
) -> int:
    """Entry point: load config.yaml and start the gateway runtime.

    Integrates startup watchdog for liveness detection during boot.
    Returns exit code.
    """
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="gateway.run")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--home", type=str, default=None)
    args = parser.parse_args([])

    if port is None and args.port is not None:
        port = args.port
    if home is None and args.home is not None:
        home = args.home

    if home:
        os.environ["ZELOO_HOME"] = str(Path(home).resolve())

    from zeloo_cli.config import load_config
    from hermes_startup_watchdog import (
        arm_startup_watchdog,
        disarm_startup_watchdog,
        report_startup_progress,
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    report_startup_progress("config_load", 10.0)

    config = load_config()
    if not config:
        logger.error(
            "No config.yaml found. Copy config.yaml.example "
            "to config.yaml and configure it."
        )
        return 1

    if port:
        config.setdefault("gateway", {}).setdefault("api", {})["port"] = port

    watchdog = arm_startup_watchdog()

    gateway = build_gateway_from_config(config)
    gateway_pid = os.getpid()

    from gateway.status import (
        GatewayState,
        GatewayStatus,
        _get_zeloo_home,
        write_gateway_state,
    )
    from gateway.api_server import DEFAULT_PORT as _API_PORT

    effective_port = (
        port
        or config.get("gateway", {}).get("api", {}).get("port", _API_PORT)
    )
    report_startup_progress("build_gateway", 30.0)

    write_gateway_state(
        GatewayState(
            kind="zeloo-gateway",
            status=GatewayStatus.RUNNING.value,
            pid=gateway_pid,
            port=effective_port,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            profile="default",
            version="0.16.0",
        )
    )

    try:
        gateway.run()
        return 0
    except KeyboardInterrupt:
        logger.info("Shutting down gateway...")
        return 0
    except Exception as exc:
        logger.exception("Gateway crashed")
        return 1
    finally:
        if watchdog:
            disarm_startup_watchdog()
        gateway.shutdown()



if __name__ == "__main__":
    main()
