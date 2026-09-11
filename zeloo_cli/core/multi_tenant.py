"""Multi-tenant isolation — tenant context and resource management."""

from __future__ import annotations

import logging
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class Tenant:
    """A tenant in the multi-tenant system."""

    tenant_id: str
    name: str
    config: dict[str, Any] = field(default_factory=dict)
    resource_limits: dict[str, Any] = field(default_factory=dict)
    api_keys: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: __import__("time").time())
    active: bool = True


@dataclass
class TenantContext:
    """Context manager for tenant scoping."""

    tenant: Tenant
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    metadata: dict[str, Any] = field(default_factory=dict)


class TenantManager:
    """Manages tenants and provides tenant context isolation."""

    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._lock = threading.Lock()
        self._default_tenant: Tenant | None = None
        self._current: list[TenantContext] = []
        self._thread_local = threading.local()

    def create_tenant(
        self,
        name: str,
        config: dict[str, Any] | None = None,
        resource_limits: dict[str, Any] | None = None,
    ) -> Tenant:
        """Create a new tenant."""
        tenant_id = uuid.uuid4().hex[:8]
        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            config=config or {},
            resource_limits=resource_limits or {},
        )
        with self._lock:
            self._tenants[tenant_id] = tenant
        logger.info("Created tenant %s (%s)", tenant_id, name)
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def list_tenants(self) -> list[Tenant]:
        with self._lock:
            return list(self._tenants.values())

    def deactivate_tenant(self, tenant_id: str) -> bool:
        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if tenant is None:
                return False
            tenant.active = False
        return True

    def set_default_tenant(self, tenant: Tenant) -> None:
        self._default_tenant = tenant

    @contextmanager
    def context(self, tenant_id: str | None = None) -> Any:
        """Context manager that activates a tenant for the duration."""
        tenant = self._tenants.get(tenant_id) if tenant_id else self._default_tenant
        if tenant is None:
            raise ValueError(f"No tenant '{tenant_id}'")
        ctx = TenantContext(tenant=tenant)
        self._current.append(ctx)
        self._thread_local.current = ctx
        try:
            yield ctx
        finally:
            if self._current:
                self._current.pop()
            self._thread_local.current = (
                self._current[-1] if self._current else None
            )

    @property
    def current(self) -> TenantContext | None:
        if hasattr(self._thread_local, "current"):
            return self._thread_local.current
        return self._current[-1] if self._current else None


__all__ = ["Tenant", "TenantContext", "TenantManager"]