"""Browser session management for isolated browser instances.

This module provides session management capabilities for creating, tracking,
and cleaning up isolated browser instances. Each session maintains its own
independent browser context.

Example::

    from tools.browser_tool_session import BrowserSessionManager, BrowserSession

    manager = BrowserSessionManager()
    session = manager.create_session()
    session.page.goto("https://example.com")
    manager.close_session(session.id)
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BrowserSession:
    """Represents an isolated browser session.

    Each session maintains its own browser instance with independent
    cookies, local storage, and browsing state.

    Attributes:
        id: Unique session identifier.
        created_at: Session creation timestamp.
        browser_type: Type of browser (chromium, firefox, webkit).
        headless: Whether browser runs in headless mode.
        page: Playwright Page instance for this session.
        context: Playwright BrowserContext for this session.
        browser: Playwright Browser instance for this session.
        playwright: Playwright instance for this session.
        metadata: Additional session metadata.
    """

    id: str
    created_at: datetime
    browser_type: str = "chromium"
    headless: bool = True
    page: Any = None
    context: Any = None
    browser: Any = None
    playwright: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def is_active(self) -> bool:
        """Check if the session is still active."""
        with self._lock:
            return (
                self.browser is not None
                and self.context is not None
                and self.page is not None
            )

    def get_info(self) -> dict[str, Any]:
        """Get session information as dictionary."""
        with self._lock:
            return {
                "id": self.id,
                "created_at": self.created_at.isoformat(),
                "browser_type": self.browser_type,
                "headless": self.headless,
                "is_active": self.is_active(),
                "metadata": self.metadata,
            }


class BrowserSessionManager:
    """Manager for isolated browser sessions.

    This class handles creating, tracking, and cleaning up browser sessions.
    Each session runs in its own isolated browser context for session
    isolation and security.

    Example::

        manager = BrowserSessionManager()

        # Create a new session
        session = manager.create_session(browser_type="chromium", headless=True)

        # Use the session
        session.page.goto("https://example.com")
        title = session.page.title()

        # Close when done
        manager.close_session(session.id)

        # Get all active sessions
        sessions = manager.get_all_sessions()
    """

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = threading.Lock()
        self._playwright_available = self._check_playwright()

    def _check_playwright(self) -> bool:
        """Check if Playwright is available."""
        try:
            import playwright

            return playwright is not None
        except ImportError:
            return False

    def _ensure_playwright_import(self) -> None:
        """Ensure Playwright is imported, raise if not available."""
        if not self._playwright_available:
            raise RuntimeError(
                "Playwright is not installed. "
                "Install with: pip install playwright && playwright install chromium"
            )

    def create_session(
        self,
        browser_type: str = "chromium",
        headless: bool = True,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        user_agent: str | None = None,
        cookies: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BrowserSession:
        """Create a new isolated browser session.

        Args:
            browser_type: Browser type ('chromium', 'firefox', 'webkit').
            headless: Whether to run browser in headless mode.
            viewport_width: Browser viewport width in pixels.
            viewport_height: Browser viewport height in pixels.
            user_agent: Custom user agent string.
            cookies: Initial cookies to set for the session.
            metadata: Additional metadata for the session.

        Returns:
            BrowserSession object for the created session.

        Raises:
            RuntimeError: If Playwright is not installed.
        """
        self._ensure_playwright_import()

        session_id = str(uuid.uuid4())
        session = BrowserSession(
            id=session_id,
            created_at=datetime.now(),
            browser_type=browser_type,
            headless=headless,
            metadata=metadata or {},
        )

        try:
            from playwright.sync_api import sync_playwright

            session.playwright = sync_playwright().start()
            browser_launcher = getattr(session.playwright, browser_type)
            session.browser = browser_launcher.launch(headless=headless)

            context_options: dict[str, Any] = {
                "viewport": {"width": viewport_width, "height": viewport_height},
            }
            if user_agent:
                context_options["user_agent"] = user_agent

            session.context = session.browser.new_context(**context_options)

            if cookies:
                for cookie in cookies:
                    try:
                        session.context.add_cookies([cookie])
                    except Exception as e:
                        logger.warning("Failed to add cookie: %s", e)

            session.page = session.context.new_page()
            session.page.set_default_timeout(30000)

            with self._lock:
                self._sessions[session_id] = session

            logger.info("Created browser session: %s (type=%s)", session_id, browser_type)
            return session

        except Exception as e:
            logger.error("Failed to create browser session: %s", e)
            self._cleanup_session(session)
            raise

    def get_session(self, session_id: str) -> BrowserSession | None:
        """Get a session by ID.

        Args:
            session_id: The session identifier.

        Returns:
            BrowserSession if found, None otherwise.
        """
        with self._lock:
            return self._sessions.get(session_id)

    def get_session_page(self, session_id: str) -> Any | None:
        """Get the page object for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Playwright Page object if session is active, None otherwise.
        """
        session = self.get_session(session_id)
        if session and session.is_active():
            return session.page
        return None

    def close_session(self, session_id: str) -> bool:
        """Close and remove a browser session.

        Args:
            session_id: The session identifier.

        Returns:
            True if session was closed, False if session not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

        self._cleanup_session(session)

        with self._lock:
            self._sessions.pop(session_id, None)

        logger.info("Closed browser session: %s", session_id)
        return True

    def _cleanup_session(self, session: BrowserSession) -> None:
        """Clean up resources for a session."""
        try:
            if session.page:
                try:
                    session.page.close()
                except Exception:
                    pass
                session.page = None
        except Exception as e:
            logger.debug("Error closing page: %s", e)

        try:
            if session.context:
                try:
                    session.context.close()
                except Exception:
                    pass
                session.context = None
        except Exception as e:
            logger.debug("Error closing context: %s", e)

        try:
            if session.browser:
                try:
                    session.browser.close()
                except Exception:
                    pass
                session.browser = None
        except Exception as e:
            logger.debug("Error closing browser: %s", e)

        try:
            if session.playwright:
                try:
                    session.playwright.stop()
                except Exception:
                    pass
                session.playwright = None
        except Exception as e:
            logger.debug("Error stopping playwright: %s", e)

    def close_all_sessions(self) -> int:
        """Close all active browser sessions.

        Returns:
            Number of sessions closed.
        """
        with self._lock:
            session_ids = list(self._sessions.keys())

        closed_count = 0
        for session_id in session_ids:
            if self.close_session(session_id):
                closed_count += 1

        logger.info("Closed %d browser sessions", closed_count)
        return closed_count

    def get_all_sessions(self) -> list[BrowserSession]:
        """Get all browser sessions.

        Returns:
            List of all BrowserSession objects.
        """
        with self._lock:
            return list(self._sessions.values())

    def get_active_sessions(self) -> list[BrowserSession]:
        """Get all active (running) browser sessions.

        Returns:
            List of active BrowserSession objects.
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active()]

    def get_session_count(self) -> dict[str, int]:
        """Get count of sessions by status.

        Returns:
            Dictionary with 'total', 'active', and 'inactive' counts.
        """
        with self._lock:
            total = len(self._sessions)
            active = sum(1 for s in self._sessions.values() if s.is_active())
            return {
                "total": total,
                "active": active,
                "inactive": total - active,
            }

    def cleanup_inactive_sessions(self) -> int:
        """Remove inactive sessions from the registry.

        Returns:
            Number of inactive sessions removed.
        """
        removed = 0
        with self._lock:
            inactive_ids = [
                sid for sid, s in self._sessions.items() if not s.is_active()
            ]
            for sid in inactive_ids:
                self._sessions.pop(sid, None)
                removed += 1

        if removed > 0:
            logger.info("Removed %d inactive sessions", removed)

        return removed

    def set_session_cookies(
        self,
        session_id: str,
        cookies: list[dict[str, Any]],
    ) -> bool:
        """Set cookies for a session.

        Args:
            session_id: The session identifier.
            cookies: List of cookie dictionaries.

        Returns:
            True if cookies were set successfully.
        """
        session = self.get_session(session_id)
        if not session or not session.context:
            return False

        try:
            session.context.add_cookies(cookies)
            return True
        except Exception as e:
            logger.error("Failed to set cookies for session %s: %s", session_id, e)
            return False

    def get_session_cookies(self, session_id: str) -> list[dict[str, Any]]:
        """Get cookies for a session.

        Args:
            session_id: The session identifier.

        Returns:
            List of cookie dictionaries.
        """
        session = self.get_session(session_id)
        if not session or not session.context:
            return []

        try:
            return session.context.cookies()
        except Exception as e:
            logger.error("Failed to get cookies for session %s: %s", session_id, e)
            return []


_global_session_manager: BrowserSessionManager | None = None
_global_manager_lock = threading.Lock()


def get_session_manager() -> BrowserSessionManager:
    """Get the global session manager instance.

    Returns:
        The global BrowserSessionManager singleton.
    """
    global _global_session_manager
    with _global_manager_lock:
        if _global_session_manager is None:
            _global_session_manager = BrowserSessionManager()
        return _global_session_manager


def reset_session_manager() -> None:
    """Reset the global session manager."""
    global _global_session_manager
    with _global_manager_lock:
        if _global_session_manager is not None:
            _global_session_manager.close_all_sessions()
            _global_session_manager = None
