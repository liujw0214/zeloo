"""Check all new files for syntax errors."""
import ast
import sys

files = [
    "main.py",
    "hermes_bootstrap.py",
    "hermes_startup_watchdog.py",
    "zeloo_cli/gateway.py",
    "gateway/status.py",
    "gateway/run.py",
]

ok = True
for f in files:
    with open(f, encoding="utf-8") as fh:
        src = fh.read()
    try:
        ast.parse(src)
        print(f"OK: {f}")
    except SyntaxError as e:
        print(f"FAIL: {f}: {e}")
        ok = False

sys.exit(0 if ok else 1)
