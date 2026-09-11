"""Stamp helper — invoked by ``install.ps1`` / ``install.sh`` to record
the install method so ``zeloo_cli.dep_ensure`` can locate the installer
script later.

Usage:
    python stamp_install_method.py ZELOO_HOME INSTALL_DIR REF_KIND REF_VALUE

All four args are positional. REF_KIND is one of {commit, tag, branch}.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(
            "usage: stamp_install_method.py ZELOO_HOME INSTALL_DIR REF_KIND REF_VALUE",
            file=sys.stderr,
        )
        return 2

    _, zeloo_home, install_dir, ref_kind, ref_value = argv
    home = Path(zeloo_home).expanduser()
    home.mkdir(parents=True, exist_ok=True)

    marker = home / ".install_method"
    marker.write_text(
        json.dumps(
            {
                "kind": "git",
                "install_dir": install_dir,
                "ref_kind": ref_kind,
                "ref_value": ref_value,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[OK] install_method stamped at {marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
