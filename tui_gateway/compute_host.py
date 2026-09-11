"""Compute host manager for the TUI gateway.

Tracks local/remote execution hosts and their resource utilization.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class HostInfo:
    name: str
    os: str
    cpu_count: int
    memory_total_mb: int
    memory_available_mb: int
    disk_free_gb: float
    python_version: str
    uptime_s: float = field(default_factory=lambda: time.time())


@dataclass
class ComputeHost:
    name: str = "local"
    remote: bool = False
    endpoint: str | None = None
    last_check: float = 0.0

    def info(self, cache_seconds: float = 5.0) -> HostInfo:
        now = time.time()
        if now - self.last_check < cache_seconds:
            return self._cached  # type: ignore[return-value]
        info = self._probe()
        self._cached = info
        self.last_check = now
        return info

    def _probe(self) -> HostInfo:
        mem_total = mem_avail = 0
        try:
            import psutil  # type: ignore[import-not-found]

            vm = psutil.virtual_memory()
            mem_total = vm.total // (1024 * 1024)
            mem_avail = vm.available // (1024 * 1024)
        except Exception:
            pass

        try:
            du = shutil.disk_usage(os.getcwd())
            disk_free = du.free / (1024 ** 3)
        except OSError:
            disk_free = 0.0

        try:
            cpu_count = os.cpu_count() or 1
        except Exception:
            cpu_count = 1

        return HostInfo(
            name=self.name,
            os=f"{platform.system()} {platform.release()}",
            cpu_count=cpu_count,
            memory_total_mb=mem_total,
            memory_available_mb=mem_avail,
            disk_free_gb=round(disk_free, 2),
            python_version=platform.python_version(),
        )

    _cached: HostInfo | None = None


_HOSTS: dict[str, ComputeHost] = {"local": ComputeHost()}


def register_host(host: ComputeHost) -> None:
    _HOSTS[host.name] = host


def get_host(name: str = "local") -> ComputeHost:
    return _HOSTS[name]


def list_hosts() -> list[str]:
    return list(_HOSTS.keys())
