"""Syntax check for hermes_bootstrap.py."""
import ast
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    src = f.read()

try:
    ast.parse(src)
    print("hermes_bootstrap.py: SYNTAX OK")
except SyntaxError as e:
    print(f"hermes_bootstrap.py: SYNTAX ERROR: {e}")
    sys.exit(1)
