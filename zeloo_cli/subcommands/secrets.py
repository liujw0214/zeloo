"""Zeloo secrets subcommand — secure secrets management."""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime
from pathlib import Path

from zeloo_cli.subcommands import Subcommand, subcommand


@subcommand("secrets")
class SecretsCmd(Subcommand):
    name = "secrets"
    help = "Manage encrypted secrets (list, set, delete, check)"

    SECRETS_FILE = ".secrets"

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="secrets_action", help="Secrets action")

        sub.add_parser("list", help="List configured secrets (values hidden)")

        set_p = sub.add_parser("set", help="Set a secret value")
        set_p.add_argument("name", help="Secret name")
        set_p.add_argument("value", help="Secret value")

        delete_p = sub.add_parser("delete", help="Delete a secret")
        delete_p.add_argument("name", help="Secret name")

        sub.add_parser("check", help="Check secrets configuration integrity")

    def run(self, args: argparse.Namespace) -> int:
        action = getattr(args, "secrets_action", None)

        if action == "list":
            return self._list()
        if action == "set":
            return self._set(args.name, args.value)
        if action == "delete":
            return self._delete(args.name)
        if action == "check":
            return self._check()

        print("Usage: Zeloo secrets [list|set|delete|check]")
        return 1

    def _get_zeloo_home(self) -> Path:
        from agent.zeloo_constants import get_zeloo_home
        return get_zeloo_home()

    def _get_secrets_path(self) -> Path:
        secrets_dir = self._get_zeloo_home()
        return secrets_dir / self.SECRETS_FILE

    def _get_encryption_key(self) -> str:
        return os.environ.get("ZELOO_SECRET_KEY", os.environ.get("ZELOO_SECRETS_KEY", ""))

    def _load_secrets(self) -> dict:
        path = self._get_secrets_path()
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("secrets", {})
        except Exception:
            return {}

    def _save_secrets(self, secrets: dict) -> Path:
        path = self._get_secrets_path()
        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "secrets": secrets,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._apply_permissions(path)
        return path

    def _apply_permissions(self, path: Path) -> None:
        if os.name == "posix":
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass

    def _encode(self, value: str) -> str:
        key = self._get_encryption_key()
        if not key:
            return base64.b64encode(value.encode("utf-8")).decode("utf-8")
        key_bytes = key.encode("utf-8")
        value_bytes = value.encode("utf-8")
        key_len = len(key_bytes)
        encoded = bytes(v ^ key_bytes[i % key_len] for i, v in enumerate(value_bytes))
        return base64.b64encode(encoded).decode("utf-8")

    def _decode(self, encoded: str) -> str:
        key = self._get_encryption_key()
        if not key:
            try:
                return base64.b64decode(encoded.encode("utf-8")).decode("utf-8")
            except Exception:
                return encoded
        try:
            key_bytes = key.encode("utf-8")
            encoded_bytes = base64.b64decode(encoded.encode("utf-8"))
            key_len = len(key_bytes)
            decoded = bytes(v ^ key_bytes[i % key_len] for i, v in enumerate(encoded_bytes))
            return decoded.decode("utf-8")
        except Exception:
            return encoded

    def _list(self) -> int:
        secrets = self._load_secrets()

        if not secrets:
            print("No secrets configured.")
            print(f"Secrets file: {self._get_secrets_path()}")
            return 0

        print("Configured secrets:")
        print()
        for name in sorted(secrets.keys()):
            secret_data = secrets[name]
            if isinstance(secret_data, dict):
                created = secret_data.get("created_at", "?")
                has_value = bool(secret_data.get("value"))
            else:
                created = "?"
                has_value = bool(secret_data)
            status = "[set]" if has_value else "[empty]"
            print(f"  {name:<30} {status}  (created: {created})")

        print()
        print(f"Total: {len(secrets)} secret(s)")
        return 0

    def _set(self, name: str, value: str) -> int:
        secrets = self._load_secrets()

        existing = secrets.get(name)
        if existing and isinstance(existing, dict):
            created_at = existing.get("created_at", datetime.now().isoformat())
        else:
            created_at = datetime.now().isoformat()

        secrets[name] = {
            "value": self._encode(value),
            "created_at": created_at,
            "updated_at": datetime.now().isoformat(),
        }

        path = self._save_secrets(secrets)
        print(f"Secret '{name}' set successfully.")
        print(f"Saved to: {path}")
        return 0

    def _delete(self, name: str) -> int:
        secrets = self._load_secrets()

        if name not in secrets:
            print(f"Secret '{name}' not found.")
            return 1

        del secrets[name]
        self._save_secrets(secrets)
        print(f"Secret '{name}' deleted.")
        return 0

    def _check(self) -> int:
        path = self._get_secrets_path()
        secrets = self._load_secrets()

        print("Secrets configuration check:")
        print()

        if not path.exists():
            print("  [WARN] Secrets file does not exist yet.")
            print("         Run 'Zeloo secrets set <name> <value>' to create it.")
            print()
            return 0

        print(f"  Secrets file: {path}")
        print(f"  File size: {path.stat().st_size} bytes")
        print()

        key = self._get_encryption_key()
        if key:
            print("  [OK] Encryption key is configured (ZELOO_SECRET_KEY)")
        else:
            print("  [WARN] No encryption key found (ZELOO_SECRET_KEY not set)")
            print("         Secrets are base64-encoded only (not recommended for production)")
        print()

        if not secrets:
            print("  [INFO] No secrets configured yet.")
            return 0

        print(f"  Configured secrets: {len(secrets)}")
        for name in sorted(secrets.keys()):
            print(f"    - {name}")
        print()

        required_secrets = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
        found = []
        missing = []
        for req in required_secrets:
            if req in secrets:
                found.append(req)
            else:
                missing.append(req)

        if found:
            print(f"  [OK] Required secrets configured: {', '.join(found)}")
        if missing:
            print(f"  [WARN] Recommended secrets not set: {', '.join(missing)}")

        print()
        print("Check completed.")
        return 0
