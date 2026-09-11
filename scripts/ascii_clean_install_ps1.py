"""Strip non-ASCII punctuation from install.ps1 (PS 5.1 parser is finicky)."""
import sys
from pathlib import Path

src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("install.ps1")
data = src.read_bytes()
replacements = [
    ("\u2014".encode(), b"--"),   # em-dash
    ("\u2013".encode(), b"-"),    # en-dash
    ("\u2018".encode(), b"'"),    # left single quote
    ("\u2019".encode(), b"'"),    # right single quote
    ("\u201c".encode(), b'"'),    # left double quote
    ("\u201d".encode(), b'"'),    # right double quote
    ("\u2026".encode(), b"..."),  # ellipsis
    ("\u00a0".encode(), b" "),    # non-breaking space
    ("\u2500".encode(), b"-"),    # box-drawing horizontal
    ("\u2550".encode(), b"="),    # box-drawing double
    ("\u2502".encode(), b"|"),    # box-drawing vertical
    ("\u2022".encode(), b"*"),    # bullet
]
count = 0
for old, new in replacements:
    before = data.count(old)
    data = data.replace(old, new)
    count += before
src.write_bytes(data)
print(f"replaced {count} non-ASCII chars in {src}")
