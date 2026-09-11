"""Provider registry for :mod:`zeloo_cli.auth`.

Concrete :class:`BaseAuth` sub-classes register themselves via
:func:`register_auth` either as a class decorator or a direct call.
Once registered, callers can look them up by name with
:func:`get_auth`.

Built-in providers (OpenAI, Anthropic, Google, GitHub, Discord) are
auto-registered when :mod:`zeloo_cli.auth` is imported.
"""

from __future__ import annotations

import logging
from typing import Any

from zeloo_cli.auth.base import BaseAuth

logger = logging.getLogger(__name__)


AUTH_REGISTRY: dict[str, type[BaseAuth]] = {}
"""Mapping of provider name → :class:`BaseAuth` sub-class."""


def register_auth(name: str, cls: type[BaseAuth] | None = None) -> Any:
    """Register a provider class under *name*.

    Two usage styles are supported::

        @register_auth("openai")
        class OpenAIAuth(BaseAuth): ...

        class OpenAIAuth(BaseAuth): ...
        register_auth("openai", OpenAIAuth)

    Args:
        name: Lowercase provider name (e.g. ``"openai"``).
        cls: The class to register.  When used as a bare decorator
            the argument is omitted and the class is taken from
            the wrapped callable.

    Returns:
        When used as a decorator, returns the class unchanged.
        When used as a function call, returns ``None``.
    """
    if cls is None:
        # Decorator form: ``@register_auth("name")`` — the decorated
        # class is passed positionally.
        def _decorator(klass: type[BaseAuth]) -> type[BaseAuth]:
            _register(name, klass)
            return klass

        return _decorator
    _register(name, cls)
    return None


def _register(name: str, cls: type[BaseAuth]) -> None:
    """Insert *cls* into the registry, warning on override."""
    if not name:
        raise ValueError("Provider name must be a non-empty string")
    if not isinstance(cls, type) or not issubclass(cls, BaseAuth):
        raise TypeError(
            f"Cannot register {cls!r}: must be a BaseAuth sub-class"
        )
    if name in AUTH_REGISTRY and AUTH_REGISTRY[name] is not cls:
        logger.debug(
            "Overriding existing auth provider %r (was %s, now %s)",
            name,
            AUTH_REGISTRY[name].__name__,
            cls.__name__,
        )
    AUTH_REGISTRY[name] = cls
    # Make sure the class's ``provider_name`` matches the registry
    # key when the author omitted one — avoids silent mismatches
    # like registering as ``"gh"`` but ``provider_name = "github"``.
    if not getattr(cls, "provider_name", ""):
        cls.provider_name = name


def get_auth(name: str, **kwargs: Any) -> BaseAuth | None:
    """Instantiate the provider registered under *name*.

    Args:
        name: Provider name (case-sensitive — registry keys are
            typically lowercase).
        **kwargs: Forwarded to the provider's ``__init__``.

    Returns:
        A configured provider instance, or ``None`` if no class is
        registered under that name.

    Raises:
        Any exception raised by the provider's ``__init__`` is
        propagated unchanged.
    """
    cls = AUTH_REGISTRY.get(name)
    if cls is None:
        logger.debug("No auth provider registered under %r", name)
        return None
    return cls(**kwargs)


def list_auth_providers() -> list[str]:
    """Return the sorted list of registered provider names."""
    return sorted(AUTH_REGISTRY.keys())


def unregister_auth(name: str) -> bool:
    """Remove a provider from the registry.  Returns True if removed.

    Mainly useful in tests; production code should leave the
    registry populated.
    """
    return AUTH_REGISTRY.pop(name, None) is not None


__all__ = [
    "AUTH_REGISTRY",
    "get_auth",
    "list_auth_providers",
    "register_auth",
    "unregister_auth",
]
