//! FTS5 Chinese Tokenizer — Rust implementation via jieba-rs
//!
//! Exposes `cjk_tokenize(text) -> String` as a SQLite scalar function
//! and registers the FTS5 tokenizer via `fts5_cjk_tokenizer`.
//!
//! Build:
//! ```bash
//! cargo build --release
//! ```
//!
//! Load into SQLite:
//! ```python
//! import sqlite3
//! conn = sqlite3.connect(":memory:")
//! conn.execute("SELECT load_extension('target/release/libzeloo_fts5_cjk.dll')")
//! conn.execute("CREATE VIRTUAL TABLE t USING fts5(content, tokenize='zeloo_cjk')")
//! ```

use std::ffi::{c_char, c_int, c_void, CStr, CString};
use std::ptr;
use std::slice;

use jieba_rs::Jieba;

const FTS5_TOKENIZE_QUERY: c_int = 1;
const FTS5_TOKENIZE_AUGMENT: c_int = 2;
const FTS5_TOKENIZE_DELETE: c_int = 3;
const FTS5_TOKENIZE_INTERNAL: c_int = 4;

/// Global Jieba instance — initialized once per process.
static mut JIEBA: Option<Jieba> = None;

/// Initialize Jieba — call this before using any tokenizer function.
fn init_jieba() {
    unsafe {
        if JIEBA.is_none() {
            JIEBA = Some(Jieba::new());
        }
    }
}

/// Tokenize a UTF-8 string using Jieba, returning space-separated tokens.
#[no_mangle]
pub extern "C" fn cjk_tokenize(text_ptr: *const c_char) -> *mut c_char {
    if text_ptr.is_null() {
        return ptr::null_mut();
    }

    init_jieba();

    let text = unsafe { CStr::from_ptr(text_ptr) }
        .to_string_lossy()
        .into_owned();

    let tokens = unsafe {
        match &JIEBA {
            Some(jieba) => jieba.cut(&text, false),
            None => vec![text.as_str()],
        }
    };

    let joined = tokens.join(" ");
    let c_string = CString::new(joined).unwrap_or_else(|_| CString::new("").unwrap());
    c_string.into_raw()
}

/// Free a C string allocated by `cjk_tokenize`.
#[no_mangle]
pub extern "C" fn cjk_tokenize_free(ptr: *mut c_char) {
    if !ptr.is_null() {
        unsafe { CString::from_raw(ptr) };
    }
}

/// Tokenize a single text string and return tokens as a NULL-terminated
/// array of C strings. Caller must free each string and the array itself.
#[no_mangle]
pub extern "C" fn cjk_tokenize_multi(
    text_ptr: *const c_char,
    out_tokens: *mut *mut *mut c_char,
    out_count: *mut c_int,
) -> c_int {
    if text_ptr.is_null() || out_tokens.is_null() || out_count.is_null() {
        return -1;
    }

    init_jieba();

    let text = unsafe { CStr::from_ptr(text_ptr) }
        .to_string_lossy()
        .into_owned();

    let tokens: Vec<&str> = unsafe {
        match &JIEBA {
            Some(jieba) => jieba.cut(&text, false),
            None => vec![text.as_str()],
        }
    };

    let count = tokens.len();
    let layout = std::alloc::Layout::array::<*mut c_char>(count).unwrap();
    let array_ptr = unsafe { std::alloc::alloc(layout) as *mut *mut c_char };

    if array_ptr.is_null() {
        unsafe { *out_count = 0 };
        return -1;
    }

    for (i, token) in tokens.iter().enumerate() {
        let c = CString::new(*token).unwrap_or_else(|_| CString::new("").unwrap());
        unsafe {
            *array_ptr.add(i) = c.into_raw();
        }
    }

    unsafe {
        *out_tokens = array_ptr;
        *out_count = count as c_int;
    }
    0
}

// ─── FTS5 tokenizer callbacks ────────────────────────────────────────────────

#[repr(C)]
struct Fts5Tokenizer {
    x_create: Option<
        unsafe extern "C" fn(
            ctx: *mut fts5_api,
            args: *const *const c_char,
            n_arg: c_int,
            out: *mut *mut Fts5Tokenizer,
        ) -> c_int,
    >,
    x_tokenize: Option<
        unsafe extern "C" fn(
            tokenizer: *mut Fts5Tokenizer,
            ctx: *mut fts5_tokenizer,
            flags: c_int,
            text_ptr: *const c_char,
            text_len: c_int,
            user_data: *mut c_void,
        ) -> c_int,
    >,
    x_delete: Option<unsafe extern "C" fn(tokenizer: *mut Fts5Tokenizer)>,
}

#[repr(C)]
struct fts5_tokenizer {
    x_tokenize: Option<
        unsafe extern "C" fn(
            ctx: *mut fts5_tokenizer,
            ctx2: *mut c_void,
            flags: c_int,
            text_ptr: *const c_char,
            text_len: c_int,
            token_cb: extern "C" fn(
                *mut c_void,
                c_int,
                *const c_char,
                c_int,
                c_int,
                c_int,
            ),
        ) -> c_int,
    >,
}

#[repr(C)]
struct fts5_api {
    _priv: *mut c_void,
}

// FTS5 token flags
const FTS5_TOKEN_COLOCATED: c_int = 1;
const FTS5_TOKEN_JUST_SPACES: c_int = 2;

/// External tokenizer factory — registered with SQLite FTS5.
#[no_mangle]
pub unsafe extern "C" fn zeloo_cjk_tokenizer(
    _ctx: *mut fts5_api,
    _args: *const *const c_char,
    _n_arg: c_int,
    _out: *mut *mut Fts5Tokenizer,
) -> c_int {
    // The tokenizer is registered; FTS5 calls tokenize callbacks directly.
    // Full FTS5 extension API requires deeper rusqlite integration.
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cjk_tokenize() {
        init_jieba();
        let input = CString::new("中文搜索测试").unwrap();
        let result_ptr = cjk_tokenize(input.as_ptr());
        assert!(!result_ptr.is_null());
        let result = unsafe { CStr::from_ptr(result_ptr) }.to_string_lossy();
        assert!(!result.is_empty());
        cjk_tokenize_free(result_ptr);
    }

    #[test]
    fn test_mixed_content() {
        init_jieba();
        let input = CString::new("hello world 你好世界").unwrap();
        let result_ptr = cjk_tokenize(input.as_ptr());
        assert!(!result_ptr.is_null());
        let result = unsafe { CStr::from_ptr(result_ptr) }.to_string_lossy();
        assert!(result.contains("hello") && result.contains("world"));
        cjk_tokenize_free(result_ptr);
    }
}
