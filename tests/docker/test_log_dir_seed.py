"""Runtime smoke test for Docker $ZELOO_HOME/logs/gateways seeding.

Build the real image and verify logs/ and logs/gateways/ exist and are
owned by the Zeloo user after container boot.

Regression guard for #45258: if the first gateway log service runs in
root context, logs/gateways/ is created root-owned; every profile
registered later runs its log service as the dropped Zeloo user and
s6-log crash-loops on mkdir: Permission denied.
"""
from __future__ import annotations

from tests.docker.conftest import (
    docker_exec_sh,
    restart_container,
    start_container,
)


def test_logs_gateways_seeded_and_zeloo_owned(
    built_image: str, container_name: str,
) -> None:
    """logs/ and logs/gateways/ must exist and be owned by Zeloo after boot."""
    start_container(built_image, container_name)

    # Both directories must exist
    r = docker_exec_sh(
        container_name,
        "test -d /opt/data/logs && "
        "test -d /opt/data/logs/gateways && "
        "echo DIRS_OK || echo DIRS_MISSING",
        timeout=10,
    )
    assert "DIRS_OK" in r.stdout, (
        f"logs/ or logs/gateways/ not seeded: {r.stdout}"
    )

    # Both must be owned by Zeloo
    r = docker_exec_sh(
        container_name,
        'logs_owner=$(stat -c "%U" /opt/data/logs); '
        'gateways_owner=$(stat -c "%U" /opt/data/logs/gateways); '
        'echo "logs=$logs_owner gateways=$gateways_owner"',
        timeout=10,
    )
    assert "logs=Zeloo" in r.stdout, (
        f"logs/ not owned by Zeloo: {r.stdout}"
    )
    assert "gateways=Zeloo" in r.stdout, (
        f"logs/gateways/ not owned by Zeloo: {r.stdout}"
    )


