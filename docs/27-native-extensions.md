# 27. 原生扩展开发计划

> Zeloo 通过 `native/` 目录提供原生扩展能力。本文档记录需要开发的原生扩展。

## 27.1 native/fts5_cjk/ FTS5 中文分词扩展（P3）

### 27.1.1 目标

SQLite FTS5 默认不支持中文分词。通过 Rust 编译的 FTS5 扩展（`fts5_cjk`）提供中文分词能力。

### 27.1.2 实现

```rust
// native/fts5_cjk/src/lib.rs

use rusqlite::functions::Function;
use jieba_rs::Jieba;

pub fn register_cjk_tokenizer(db: &Connection) -> Result<()> {
    db.create_scalar_function(
        "cjk_tokenize",
        1,  // argc
        |ctx| {
            let text: String = ctx.get_raw(0).as_str()?.to_string();
            let jieba = Jieba::new();
            let tokens: Vec<&str> = jieba.cut(&text, false);
            Ok(tokens.join(" "))
        },
    )?;
    Ok(())
}

// FTS5 tokenizer 注册
// CREATE VIRTUAL TABLE messages_fts USING fts5(
//     content,
//     tokenize='cjk_tokenize cjk'
// );
```

### 27.1.3 目录结构

```
native/fts5_cjk/
├── src/
│   └── lib.rs           # Rust 源码
├── vendor/              # 第三方依赖（jieba 词典）
│   └── dict/
│       ├── base_dict.dat
│       └── idf.dat
├── Cargo.toml
├── build.rs             # 构建脚本
└── README.md
```

### 27.1.4 使用方式

```python
# zeloo_state.py 中使用
conn.execute("""
    CREATE VIRTUAL TABLE messages_fts
    USING fts5(content, tokenize='cjk_tokenize cjk')
""")

# 中文搜索
results = conn.execute(
    "SELECT * FROM messages_fts WHERE content MATCH ?",
    ("中文 查询",)
).fetchall()
```

---

## 27.2 构建与分发

### 27.2.1 build.rs

```rust
// native/fts5_cjk/build.rs

fn main() {
    // 下载或检查 jieba 词典
    let dict_path = std::env::var("zeloo_DICT_PATH")
        .unwrap_or_else(|_| "vendor/dict".to_string());

    println!("cargo:rustc-env=zeloo_DICT_PATH={}", dict_path);
}
```

### 27.2.2 Cargo.toml

```toml
# native/fts5_cjk/Cargo.toml

[package]
name = "Zeloo-fts5-cjk"
version = "1.0.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
rusqlite = { version = "0.31", features = ["bundled"] }
jieba-rs = "0.6"
```
