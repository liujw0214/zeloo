"""Syntax check script."""
import ast
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    src = f.read()

try:
    ast.parse(src)
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)
