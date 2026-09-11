# Native FTS5 Chinese Tokenizer (P3)

Rust implementation of an FTS5 tokenizer for CJK text using `jieba-rs`.

## Status

✅ **Rust 实现已完成**：`src/lib.rs` + `build.rs` 已创建。需安装 Rust 工具链后编译：

```bash
# 安装 Rust（首次）
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
# 或 Windows: winget install Rustlang.Rustup

cd native/fts5_cjk
cargo build --release
```

编译产物（`libzeloo_fts5_cjk.dll` / `.so`）通过 `conn.execute("SELECT load_extension(...)")` 加载到 SQLite。
Python-side fallback is available via the package's `__init__.py` —
it uses `jieba` (Python) if installed, otherwise character-by-character
tokenization.

## Build (future)

```bash
cd native/fts5_cjk
cargo build --release
```

The compiled `cdylib` will be loaded by SQLite via the FTS5 extension
mechanism. Until then, the Python fallback is used.

## Files

```
native/fts5_cjk/
├── __init__.py        # Python bridge — jieba fallback + FTS5 wiring
├── Cargo.toml         # Rust crate manifest
├── src/lib.rs         # Rust FTS5 tokenizer (jieba-rs)
├── build.rs           # Build script
└── README.md
```

## Python usage

```python
from native.fts5_cjk import tokenize_cjk, create_fts5_table
import sqlite3

conn = sqlite3.connect(":memory:")
create_fts5_table(conn, "messages_fts", ["content"])
conn.execute("INSERT INTO messages_fts(content) VALUES (?)",
             (tokenize_cjk("中文搜索测试 hello"),))
```