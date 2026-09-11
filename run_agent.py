"""Zeloo Agent — AIAgent core class.

Integrates system prompt caching, conversation loop, tool registry,
memory store, and LLM provider calls.
"""

from __future__ import annotations

import contextvars
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from agent.conversation_loop import ConversationLoop
from agent.memory_manager import MemoryStore
from agent.provider_router import ProviderConfig, ProviderRouter
from agent.system_prompt import build_system_prompt, invalidate_system_prompt
from agent.turn_finalizer import TurnFinalizer, TurnResult
from agent.zeloo_constants import DEFAULT_MAX_ITERATIONS
from model_tools import discover_and_filter_tools, execute_tool
from plugins.hooks import HookType, get_hook_registry
from zeloo_state import SessionDB

logger = logging.getLogger(__name__)

# Context variable to expose the current agent to tools
_current_agent: contextvars.ContextVar[AIAgent | None] = contextvars.ContextVar(
    "_current_agent", default=None
)


class AIAgent:
    """The main agent class that orchestrates conversation, tools, and memory."""

    def __init__(
        self,
        model: str = "gpt-4o",
        provider: str = "openai",
        base_url: str | None = None,
        api_key: str | None = None,
        platform: str = "cli",
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        load_soul_identity: bool = True,
        skip_context_files: bool = False,
        memory_enabled: bool = True,
        user_profile_enabled: bool = True,
        providers: list[dict[str, Any]] | None = None,
        restore_session_id: str | None = None,
    ) -> None:
        self.model = model
        self.provider = provider
        self.base_url = base_url
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.platform = platform
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.load_soul_identity = load_soul_identity
        self.skip_context_files = skip_context_files
        self._memory_enabled = memory_enabled
        self._user_profile_enabled = user_profile_enabled

        # Provider router (multi-provider with failover)
        self._provider_router = self._build_provider_router(
            providers, model, provider, base_url, api_key
        )

        # Smart model routing (route simple requests to a cheap model)
        from agent.provider_router import SmartModelRouter

        self._smart_router = SmartModelRouter.from_config(self._load_user_config())

        # Auxiliary client (side tasks on a cheaper model)
        from agent.auxiliary_client import AuxiliaryClient

        self.auxiliary = AuxiliaryClient.from_config(self._load_user_config())

        # Session
        self.session_id = restore_session_id or self._generate_session_id()
        self.session_start = datetime.now()

        # State
        self._cached_system_prompt: str | None = None
        self._cached_system_prompt_static: str | None = None

        # Cache statistics (for prefix cache hit-rate monitoring)
        self._cache_hits: int = 0
        self._cache_misses: int = 0

        # Self-evolution state
        self._turn_count = 0
        self._memory_nudge = False
        self._skill_nudge = False
        self._background_review_enabled = self._resolve_bg_review()
        self._finalizer = TurnFinalizer(
            background_review_enabled=self._background_review_enabled
        )

        # Memory store
        self._memory_store = (
            MemoryStore(max_chars=self._resolve_memory_max_chars())
            if (memory_enabled or user_profile_enabled)
            else None
        )

        # Prompt caching stats (provider-level cached tokens tracking)
        self._prompt_caching_enabled = bool(
            self._load_user_config().get("prompt_caching", {}).get("enabled", False)
        )
        self._cached_tokens: int = 0
        self._total_prompt_tokens: int = 0

        # Cost tracking
        from agent.cost_tracker import CostTracker

        cost_cfg: dict[str, Any] = self._load_user_config().get("cost_tracker", {})
        _warn_env = os.environ.get("zeloo_COST_WARN_THRESHOLD", "")
        _abort_env = os.environ.get("zeloo_COST_ABORT_THRESHOLD", "")
        warn_threshold = float(_warn_env) if _warn_env else float(cost_cfg.get("warn_threshold_usd", 10.0))
        abort_threshold = float(_abort_env) if _abort_env else float(cost_cfg.get("abort_threshold_usd", 100.0))
        self._cost_tracker = CostTracker(
            model=self.model,
            warn_threshold_usd=warn_threshold,
            abort_threshold_usd=abort_threshold,
        )

        context_cfg: dict[str, Any] = self._load_user_config().get("context", {})

        # Context engine (optional — token budget + compression orchestration)
        self._context_engine: Any | None = None
        if context_cfg.get("context_engine_enabled", False):
            try:
                from agent.context_engine import ContextConfig, ContextEngine
                ccfg = ContextConfig(
                    model=model,
                    max_context_tokens=context_cfg.get("max_context_tokens", 128000),
                    compression_mode=context_cfg.get("compression_mode", "auto"),
                    preserve_recent_turns=context_cfg.get("preserve_recent_turns", 3),
                )
                self._context_engine = ContextEngine(config=ccfg)
                logger.info("ContextEngine enabled (mode=%s)", ccfg.compression_mode)
            except Exception:
                logger.exception("Failed to initialize ContextEngine")

        # Agent coordinator (optional — multi-agent orchestration)
        self._coordinator: Any | None = None
        if self._load_user_config().get("coordinator", {}).get("enabled", False):
            try:
                from agent.agents_workflow import AgentCoordinator
                self._coordinator = AgentCoordinator(agents={})
                self._coordinator.add_agent("main", self)
                logger.info("AgentCoordinator enabled")
            except Exception:
                logger.exception("Failed to initialize AgentCoordinator")

        # Session database
        self._session_db: SessionDB | None = None
        try:
            self._session_db = SessionDB()
            self._session_db.create_session(self.session_id, platform=platform)
        except Exception:
            logger.exception("Failed to initialize session DB")

        # Tools
        # MCP servers must be started BEFORE discover_and_filter_tools so
        # their tools are registered and available to the platform filter.
        self._mcp_manager = self._init_mcp_servers()
        tool_info = discover_and_filter_tools(platform)
        self.valid_tool_names: set[str] = tool_info["valid_tool_names"]
        self.available_toolsets: set[str] = tool_info["available_toolsets"]
        self._tool_schemas: list[dict[str, Any]] = tool_info["tool_schemas"]

        # Conversation history (multi-turn context). Persisted to SessionDB
        # and reloaded on restore. Truncated to keep within token budget.
        self._messages: list[dict[str, Any]] = []
        self._max_history_messages = 40  # ~20 turns of user+assistant

        # Restore conversation history if resuming an existing session
        if restore_session_id and self._session_db is not None:
            self._load_history_from_db()

        # Conversation loop
        self._loop = ConversationLoop(
            self,
            max_iterations=max_iterations,
            max_context_tokens=context_cfg.get(
                "max_context_tokens", 12000
            ),
            use_llm_summary=context_cfg.get("use_llm_summary", False),
        )

        # LLM client (lazy)
        self._client: Any | None = None

        # Terminal backend (local / docker / ssh) — used by shell & file tools
        self.terminal_backend = self._build_terminal_backend()

        # Cron scheduler (background timed tasks) — started lazily on first use
        self.cron_scheduler = self._init_cron_scheduler()

        # Voice backend (TTS/STT) — used by voice tools
        self.voice_backend = self._build_voice_backend()

        # Fire ON_SESSION_START hook (all other hooks are fired per-call)
        try:
            hooks = get_hook_registry()
            hooks.fire(HookType.ON_SESSION_START, self.session_id, platform=self.platform)
        except Exception:
            logger.exception("ON_SESSION_START hook failed")

    @classmethod
    def from_agent_init(cls, init_result: dict[str, Any]) -> AIAgent:
        """Create an AIAgent from an AgentInit.create_agent() result dict.

        This bridges the declarative AgentInit bootstrap pipeline with the
        fully-wired AIAgent class. The init_result dict contains the resolved
        config, provider router, memory manager, tools, etc.

        Args:
            init_result: Dict returned by AgentInit.create_agent().

        Returns:
            A new AIAgent instance wired with all the initialized components.
        """
        config: Any = init_result["config"]
        provider_router: Any = init_result["provider_router"]
        memory_manager: Any = init_result["memory_manager"]
        tools: list[Any] = init_result["tools"]
        model_config: Any = init_result.get("model_config")

        from agent.memory_manager import MemoryStore

        store: MemoryStore | None = None
        if memory_manager is not None:
            store = MemoryStore(max_chars=8000)

        agent = cls(
            model=config.model,
            provider=config.provider,
            base_url=config.base_url,
            max_iterations=config.max_iterations,
            temperature=config.temperature,
            memory_enabled=(config.memory_backend != "disabled"),
            user_profile_enabled=True,
        )

        agent._provider_router = provider_router
        if store is not None:
            agent._memory_store = store
        if tools:
            agent._tool_schemas = [
                {
                    "type": "function",
                    "function": {
                        "name": getattr(t, "name", "unknown"),
                        "description": getattr(t, "description", ""),
                        "parameters": getattr(t, "input_schema", {"type": "object"}),
                    },
                }
                for t in tools
            ]
            agent.valid_tool_names = {getattr(t, "name", "unknown") for t in tools}
        if model_config is not None:
            agent.model = getattr(model_config, "model", agent.model)
            agent.provider = getattr(model_config, "provider", agent.provider)

        logger.info(
            "AIAgent created from AgentInit: provider=%s model=%s tools=%d",
            agent.provider,
            agent.model,
            len(tools),
        )
        return agent

    def _generate_session_id(self) -> str:
        """Generate a session ID with embedded timestamp."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{ts}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _resolve_bg_review() -> bool:
        """Resolve background review flag: env var > config.yaml > False."""
        env_val = os.environ.get("zeloo_BG_REVIEW", "").lower()
        if env_val in ("1", "true", "yes"):
            return True
        if env_val in ("0", "false", "no"):
            return False
        # Fall back to config.yaml
        try:
            from zeloo_cli.config import load_config

            cfg = load_config()
            se_cfg = cfg.get("self_evolution", {}) if isinstance(cfg, dict) else {}
            bg_cfg = se_cfg.get("background_review", {}) if isinstance(se_cfg, dict) else {}
            return bool(bg_cfg.get("enabled", False))
        except Exception:
            return False

    @staticmethod
    def _resolve_memory_max_chars() -> int:
        """Resolve memory max-chars: env var > config.yaml > default 8000."""
        env_val = os.environ.get("zeloo_MEMORY_MAX_CHARS")
        if env_val:
            try:
                return max(1000, int(env_val))
            except ValueError:
                pass
        try:
            from zeloo_cli.config import load_config

            cfg = load_config()
            if isinstance(cfg, dict):
                mem_cfg = cfg.get("memory", {})
                if isinstance(mem_cfg, dict):
                    val = mem_cfg.get("max_chars")
                    if isinstance(val, int) and val > 0:
                        return val
        except Exception:
            pass
        return 8000

    def _record_prompt_cache_stats(self, response: Any) -> None:
        """Extract provider-level prompt cache stats from an LLM response.

        OpenAI-compatible providers expose cached token counts under
        ``response.usage.prompt_tokens_details.cached_tokens``. Other
        providers may expose ``response.usage.cache_read_input_tokens``
        (Anthropic). We read whichever is present.
        """
        if not self._prompt_caching_enabled:
            return
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                return
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            cached = 0
            # OpenAI format
            details = getattr(usage, "prompt_tokens_details", None)
            if details is not None:
                cached = int(getattr(details, "cached_tokens", 0) or 0)
            # Anthropic format (via OpenAI-compatible shim)
            if cached == 0:
                cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            if prompt_tokens > 0:
                self._total_prompt_tokens += prompt_tokens
                self._cached_tokens += cached
        except Exception:
            pass  # never let stats break the call

    @property
    def prompt_cache_hit_ratio(self) -> float:
        """Return the fraction of prompt tokens served from cache (0.0–1.0)."""
        if self._total_prompt_tokens == 0:
            return 0.0
        return self._cached_tokens / self._total_prompt_tokens

    @property
    def cost(self) -> dict[str, Any]:
        """Return a cost summary dict for this agent's lifetime."""
        ct = self._cost_tracker
        return {
            "model": ct.model,
            "total_tokens": ct.total_tokens,
            "input_tokens": ct.total_input_tokens,
            "output_tokens": ct.total_output_tokens,
            "cached_tokens": ct.total_cached_tokens,
            "total_cost_usd": round(ct.total_cost, 6),
            "input_cost_usd": round(ct.input_cost, 6),
            "output_cost_usd": round(ct.output_cost, 6),
        }

    @staticmethod
    def _load_user_config() -> dict[str, Any]:
        """Load and return the user's config.yaml dict (empty dict on failure)."""
        try:
            from zeloo_cli.config import load_config

            cfg = load_config()
            return cfg if isinstance(cfg, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _build_terminal_backend() -> Any:
        """Build the terminal backend from the resolved user configuration."""
        from terminal import create_backend

        config: dict[str, Any] = {}
        try:
            from zeloo_cli.config import load_config

            loaded = load_config()
            config = loaded if isinstance(loaded, dict) else {}
        except Exception:
            pass

        term_cfg = config.get("terminal", {})
        term_cfg = term_cfg if isinstance(term_cfg, dict) else {}
        backend_name = (
            os.environ.get("TERMINAL_BACKEND")
            or os.environ.get("zeloo_TERMINAL__BACKEND", "")
            or str(term_cfg.get("backend", "local")).lower()
        ).lower()

        kwargs: dict[str, Any] = {}
        if backend_name == "docker":
            kwargs = {
                "image": os.environ.get("DOCKER_IMAGE", str(term_cfg.get("image", "python:3.12-slim"))),
                "container_name": os.environ.get("DOCKER_CONTAINER_NAME", str(term_cfg.get("container_name", ""))),
                "workdir": str(term_cfg.get("workdir", "/workspace")),
                "network": str(term_cfg.get("network", "bridge")),
            }
        elif backend_name == "ssh":
            kwargs = {
                "host": os.environ.get("SSH_HOST", str(term_cfg.get("host", ""))),
                "username": os.environ.get("SSH_USER", str(term_cfg.get("user", ""))),
                "password": os.environ.get("SSH_PASSWORD", ""),
                "key_path": os.environ.get("SSH_KEY_FILE", str(term_cfg.get("key_path", ""))) or None,
                "port": int(os.environ.get("SSH_PORT", str(term_cfg.get("port", 22)))),
            }
        elif backend_name == "modal":
            kwargs = {
                "app_name": os.environ.get("MODAL_APP_NAME", str(term_cfg.get("app_name", "Zeloo-runtime"))),
                "image_tag": os.environ.get("MODAL_IMAGE", str(term_cfg.get("image", "python:3.12-slim"))),
                "gpu": str(term_cfg.get("gpu", "")),
            }
        elif backend_name == "daytona":
            kwargs = {
                "api_key": os.environ.get("DAYTONA_API_KEY", ""),
                "workspace_id": str(term_cfg.get("workspace_id", "")),
                "region": str(term_cfg.get("region", "us-east-1")),
            }
        elif backend_name == "vercel_sandbox":
            kwargs = {
                "deployment_url": os.environ.get("VERCEL_DEPLOYMENT_URL", ""),
                "access_token": os.environ.get("VERCEL_TOKEN", ""),
                "timeout": int(term_cfg.get("timeout", 30)),
            }
        elif backend_name == "singularity":
            kwargs = {
                "image": os.environ.get("SINGULARITY_IMAGE", str(term_cfg.get("image", ""))),
                "bind_paths": list(term_cfg.get("bind_paths", [])),
                "env_vars": dict(term_cfg.get("env_vars", {})),
                "home_dir": str(term_cfg.get("home_dir", "/home/user")),
            }
        elif backend_name == "local":
            kwargs = {"cwd": term_cfg.get("cwd")}

        try:
            return create_backend(backend_name, **kwargs)
        except Exception:
            from terminal.local import LocalTerminalBackend

            logger.exception("Terminal backend unavailable, falling back to local")
            return LocalTerminalBackend()

    def _init_mcp_servers(self) -> Any:
        """Start configured MCP servers and register their tools.

        Returns the MCPServerManager instance (call ``.shutdown()`` on exit).
        If no MCP servers are configured, returns a no-op manager.
        """
        from mcp.manager import MCPServerManager

        manager = MCPServerManager()
        try:
            from zeloo_cli.config import load_config

            config = load_config()
        except Exception:
            config = None
        count = manager.load_and_register(config)
        if count:
            logger.info("MCP: registered %d external tool(s)", count)
        return manager

    @staticmethod
    def _init_cron_scheduler() -> Any:
        """Create and start the background cron scheduler.

        Returns the CronScheduler instance. It starts immediately so jobs
        registered via the cron_add tool begin firing on schedule.
        """
        from cron.scheduler import CronScheduler

        scheduler = CronScheduler(tick_interval=30)
        scheduler.start()
        return scheduler

    @staticmethod
    def _build_voice_backend() -> Any:
        """Build the configured TTS/STT backend from user settings."""
        from gateway.voice import get_voice_backend

        voice_cfg: dict[str, Any] = {}
        try:
            from zeloo_cli.config import load_config

            loaded = load_config()
            voice_cfg = loaded.get("voice", {}) if isinstance(loaded, dict) else {}
            voice_cfg = voice_cfg if isinstance(voice_cfg, dict) else {}
        except Exception:
            pass

        name = os.environ.get("zeloo_VOICE_BACKEND", "").lower() or str(
            voice_cfg.get("backend", "console")
        ).lower()
        kwargs: dict[str, Any] = {}
        if name == "openai":
            kwargs = {
                "api_key": voice_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY"),
                "base_url": voice_cfg.get("base_url"),
                "tts_model": voice_cfg.get("model", "tts-1"),
                "tts_voice": voice_cfg.get("voice", "alloy"),
                "stt_model": voice_cfg.get("stt_model", "whisper-1"),
            }
        elif name == "elevenlabs":
            kwargs = {
                "api_key": voice_cfg.get("api_key") or os.environ.get("ELEVENLABS_API_KEY"),
                "voice_id": voice_cfg.get("voice_id", ""),
                "model_id": voice_cfg.get("model_id", "eleven_multilingual_v2"),
                "stt_model": voice_cfg.get("stt_model", "scribe_v1"),
            }
        return get_voice_backend(name, **kwargs)

    def shutdown(self) -> None:
        """Gracefully stop background services (cron, MCP, session DB)."""
        # Fire ON_SESSION_END hook before cleanup
        try:
            hooks = get_hook_registry()
            hooks.fire(
                HookType.ON_SESSION_END,
                self.session_id,
                duration=(datetime.now() - self.session_start).total_seconds(),
            )
        except Exception:
            logger.exception("ON_SESSION_END hook failed")

        if hasattr(self, "cron_scheduler") and self.cron_scheduler is not None:
            try:
                self.cron_scheduler.stop()
            except Exception:
                logger.exception("Failed to stop cron scheduler")
        if hasattr(self, "_mcp_manager") and self._mcp_manager is not None:
            try:
                self._mcp_manager.shutdown()
            except Exception:
                logger.exception("Failed to shut down MCP manager")
        if self._session_db is not None:
            try:
                self._session_db.close()
            except Exception:
                logger.exception("Failed to close session DB")

    def get_cached_system_prompt(self) -> str:
        """Return the cached system prompt, building it if necessary."""
        if self._cached_system_prompt is None:
            self._cache_misses += 1
            self._cached_system_prompt = build_system_prompt(self)
        else:
            self._cache_hits += 1
        return self._cached_system_prompt

    def cache_stats(self) -> dict[str, object]:
        """Return cache hit/miss statistics and the hit rate."""
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total) if total > 0 else 1.0
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "total": total,
            "hit_rate": round(hit_rate, 4),
        }

    def context_stats(self) -> dict[str, object]:
        """Return ContextEngine stats if enabled, otherwise empty dict."""
        if self._context_engine is None:
            return {}
        return self._context_engine.get_stats()

    def coordinator_stats(self) -> dict[str, object]:
        """Return AgentCoordinator summary if enabled, otherwise empty dict."""
        if self._coordinator is None:
            return {}
        return self._coordinator.summarize()

    def spawn_agent(self, name: str, **kwargs: Any) -> Any:
        """Spawn a new AIAgent as a sub-agent and register it with the coordinator.

        Args:
            name: Unique name for the sub-agent.
            **kwargs: Forwarded to AIAgent constructor (model, provider, etc.).

        Returns:
            The new AIAgent instance, or None if the coordinator is not enabled.
        """
        if self._coordinator is None:
            logger.warning("Coordinator not enabled — call spawn_agent() has no effect")
            return None
        try:
            from run_agent import AIAgent
            sub_agent = AIAgent(**kwargs)
            self._coordinator.add_agent(name, sub_agent)
            return sub_agent
        except Exception:
            logger.exception("Failed to spawn sub-agent %s", name)
            return None

    def invalidate_system_prompt(self) -> None:
        """Force a rebuild of the system prompt."""
        invalidate_system_prompt(self)

    def call_llm(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Call the LLM provider with automatic failover and return the response."""
        hooks = get_hook_registry()
        # Pre-LLM hook: plugins can modify messages/tools
        modified = hooks.fire(HookType.PRE_LLM_CALL, messages, self._tool_schemas or [])
        if modified is not None and isinstance(modified, tuple) and len(modified) == 2:
            messages, _ = modified
        try:
            response = self._provider_router.call_with_fallback(
                messages=messages,
                tools=self._tool_schemas if self._tool_schemas else None,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,
            )
            # Post-LLM hook
            hooks.fire(HookType.POST_LLM_CALL, response)
            self._record_prompt_cache_stats(response)
            self._cost_tracker.record_usage(getattr(response, "usage", None))
            # Push the latest cumulative snapshot to Langfuse (no-op when
            # the tracer is disabled or env vars are missing).
            try:
                self._cost_tracker.push_to_tracer()
            except Exception:  # noqa: BLE001
                # push_to_tracer already swallows internal errors; this
                # is a belt-and-braces guard around any unexpected failure
                # so the main loop is never broken.
                pass
            message = response.choices[0].message
            result: dict[str, Any] = {"content": message.content or ""}
            if message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]
            return result
        except RuntimeError as exc:
            # No providers configured (e.g. placeholder API key). Fall back
            # to a local echo so the agent skeleton stays usable for smoke
            # tests / development without a real LLM key.
            if "No configured providers" in str(exc) or "no providers" in str(exc).lower():
                logger.warning("No LLM providers available — returning echo fallback")
                user_msg = ""
                for m in reversed(messages):
                    if m.get("role") == "user":
                        user_msg = m.get("content") or ""
                        if isinstance(user_msg, list):
                            user_msg = " ".join(
                                part.get("text", "") for part in user_msg if isinstance(part, dict)
                            )
                        break
                echo = (
                    "[echo-mode] No LLM provider is configured. "
                    "Set a real OPENAI_API_KEY (or another provider) in ~/.Zeloo/.env "
                    "to enable real responses.\n\n"
                    f"You said: {user_msg}"
                )
                return {"content": echo}
            logger.exception("LLM call failed (all providers exhausted)")
            raise
        except Exception:
            logger.exception("LLM call failed (all providers exhausted)")
            raise

    def call_llm_stream(
        self,
        messages: list[dict[str, Any]],
        on_token: Any | None = None,
    ) -> dict[str, Any]:
        """Call the LLM with streaming, invoking on_token for each delta.

        Returns the same dict shape as :meth:`call_llm` (content + tool_calls).
        Tool calls cannot be streamed incrementally in a useful way, so when
        the model emits tool calls this falls back to non-streaming.
        """
        try:
            stream = self._provider_router.call_with_fallback(
                messages=messages,
                tools=self._tool_schemas if self._tool_schemas else None,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )
        except Exception:
            logger.exception("LLM stream failed")
            raise

        content_parts: list[str] = []
        tool_calls_accum: dict[int, dict[str, Any]] = {}
        last_usage = None

        try:
            for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    last_usage = chunk.usage
                delta = chunk.choices[0].delta
                if delta.content:
                    content_parts.append(delta.content)
                    if on_token:
                        on_token(delta.content)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_accum:
                            tool_calls_accum[idx] = {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.id:
                            tool_calls_accum[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_calls_accum[idx]["function"]["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_calls_accum[idx]["function"]["arguments"] += tc.function.arguments
        except Exception:
            logger.exception("Error during stream consumption")
            raise

        result: dict[str, Any] = {"content": "".join(content_parts)}
        if tool_calls_accum:
            result["tool_calls"] = [tool_calls_accum[i] for i in sorted(tool_calls_accum)]
        if last_usage is not None:
            self._cost_tracker.record_usage(last_usage)
            try:
                self._cost_tracker.push_to_tracer()
            except Exception:  # noqa: BLE001
                pass
        return result

    def _build_provider_router(
        self,
        providers: list[dict[str, Any]] | None,
        model: str,
        provider: str,
        base_url: str | None,
        api_key: str | None,
    ) -> ProviderRouter:
        """Build the provider router from explicit config or env vars."""
        if providers:
            configs = [
                ProviderConfig(
                    name=p.get("name", provider),
                    model=p.get("model", model),
                    base_url=p.get("base_url"),
                    api_key=p.get("api_key"),
                    priority=p.get("priority", i),
                )
                for i, p in enumerate(providers)
            ]
            return ProviderRouter(configs)

        # Backward-compatible single-provider mode
        config = ProviderConfig(
            name=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            priority=0,
        )
        router = ProviderRouter([config])
        # If no providers were configured (no API key), fall back to auto-config
        if not router.providers:
            router = ProviderRouter()
        return router

    def _get_client(self) -> Any:
        """Get or create the OpenAI client for the primary provider."""
        if self._client is None:
            primary = self._provider_router.primary
            if primary is None:
                raise RuntimeError("No configured providers available")
            self._client = self._provider_router.get_client(primary.name)
        return self._client

    def execute_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Execute a tool by name."""
        import time

        from agent.insights import insights_engine

        hooks = get_hook_registry()
        # Pre-tool hook: plugins can modify args or block
        modified = hooks.fire(HookType.PRE_TOOL_CALL, name, args)
        if modified is not None and isinstance(modified, dict):
            args = modified

        # Set current agent context for tools that need it
        token = _current_agent.set(self)
        start = time.time()
        try:
            result = execute_tool(name, args)
        except Exception:
            duration = time.time() - start
            try:
                insights_engine.record_tool_call(name, duration, error=True)
                insights_engine.record_error("tool_error")
            except Exception:
                pass
            _current_agent.reset(token)
            raise
        duration = time.time() - start
        _current_agent.reset(token)
        # Record successful tool call metrics
        try:
            insights_engine.record_tool_call(name, duration, error=False)
        except Exception:
            pass
        # Post-tool hook: plugins can transform the result
        transformed = hooks.fire_chain(HookType.POST_TOOL_CALL, result, name, args)
        return transformed

    def run_conversation(
        self,
        user_message: str,
        system_message: str | None = None,
        on_token: Any | None = None,
    ) -> str:
        """Run a full conversation turn and return the assistant's response.

        Args:
            user_message: The user's input.
            system_message: Optional override for the system prompt.
            on_token: Optional streaming callback (str) -> None.
        """
        # Set context for tools
        token = _current_agent.set(self)
        try:
            # Smart model routing: use a cheaper model for simple inputs
            original_model, original_provider = self.model, self.provider
            routed_provider, routed_model = self._smart_router.select(
                user_message, self.provider, self.model
            )
            if routed_model != self.model or routed_provider != self.provider:
                logger.info(
                    "Smart routing: %s/%s -> %s/%s (simple input)",
                    self.provider, self.model, routed_provider, routed_model,
                )
                self.provider, self.model = routed_provider, routed_model

            # Feed messages to ContextEngine if enabled (for token budget tracking)
            if self._context_engine is not None:
                self._context_engine.add_message({"role": "user", "content": user_message})

            # Append user message to conversation history (multi-turn context)
            self._messages.append({"role": "user", "content": user_message})

            # Truncate history if it exceeds the budget (keep most recent)
            self._truncate_history()

            # Build system prompt (reuse cache)
            if system_message is not None:
                # If system_message provided, rebuild with it
                self._cached_system_prompt = build_system_prompt(self, system_message)
            else:
                self.get_cached_system_prompt()

            # Persist user message
            if self._session_db:
                self._session_db.save_message(self.session_id, "user", user_message)

            # Run the conversation loop (appends assistant + tool messages to self._messages)
            response = self._loop.run(self._messages, on_token=on_token)

            # Persist assistant response
            if self._session_db:
                self._session_db.save_message(self.session_id, "assistant", response)

            # Self-evolution: finalize the turn (trajectory + nudges + review)
            self._turn_count += 1
            self._finalize_turn(user_message, response, self._messages)

            # Log provider-level prompt cache hit ratio when enabled
            if self._prompt_caching_enabled and self._total_prompt_tokens > 0:
                logger.info(
                    "Prompt cache hit ratio: %.1f%% (%d/%d cached tokens)",
                    self.prompt_cache_hit_ratio * 100,
                    self._cached_tokens,
                    self._total_prompt_tokens,
                )

            # Log cost summary
            if self._cost_tracker.total_tokens > 0:
                logger.info("Cost summary: %s", self._cost_tracker.summary())

            return response
        finally:
            # Restore original model/provider if smart routing changed them
            self.model, self.provider = original_model, original_provider
            _current_agent.reset(token)

    def _truncate_history(self) -> None:
        """Keep conversation history within the message budget.

        Drops the oldest non-system messages when the limit is exceeded.
        Tool-call/result pairs are dropped together to avoid mismatches.
        """
        if len(self._messages) <= self._max_history_messages:
            return
        overflow = len(self._messages) - self._max_history_messages
        # Round up to an even number to keep user/assistant pairs intact
        if overflow % 2 != 0:
            overflow += 1
        del self._messages[:overflow]

    def _load_history_from_db(self) -> None:
        """Load prior conversation messages from SessionDB into self._messages.

        Only user/assistant text messages are restored (tool-call turns are
        not persisted in a replayable form). This gives the agent context
        continuity across process restarts.
        """
        if self._session_db is None:
            return
        try:
            rows = self._session_db.get_messages(
                self.session_id, limit=self._max_history_messages
            )
            for row in rows:
                role = row["role"]
                content = row["content"]
                if role in ("user", "assistant") and content:
                    self._messages.append({"role": role, "content": content})
            logger.info(
                "Restored %d message(s) for session %s",
                len(self._messages),
                self.session_id,
            )
        except Exception:
            logger.exception("Failed to load history for session %s", self.session_id)
            self._messages = []

    def _finalize_turn(
        self, user_message: str, response: str, messages: list[dict[str, Any]]
    ) -> None:
        """Build a TurnResult and run the finalizer (never raises)."""
        try:
            tool_calls: list[dict[str, Any]] = []
            tool_results: list[dict[str, Any]] = []
            for msg in messages:
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    tool_calls.extend(msg["tool_calls"])
                elif msg.get("role") == "tool":
                    tool_results.append(msg)

            turn_result = TurnResult(
                session_id=self.session_id,
                turn_id=self._turn_count,
                user_message=user_message,
                assistant_response=response,
                tool_calls=tool_calls,
                tool_results=tool_results,
                success=not response.startswith("Error:"),
            )
            self._finalizer.finalize(self, turn_result)

            # Rebuild system prompt if a nudge was armed so the next
            # turn sees it. Nudges live in the volatile tier.
            if self._memory_nudge or self._skill_nudge:
                self.invalidate_system_prompt()
        except Exception:
            logger.exception("Turn finalization failed")

    def close(self) -> None:
        """Clean up resources."""
        if self._session_db:
            self._session_db.close()
