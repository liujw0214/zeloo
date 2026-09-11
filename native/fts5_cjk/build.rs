//! Build script for zeloo-fts5-cjk
//!
//! On Windows this ensures we link against the correct runtime libraries.
//! Most of the heavy lifting is handled by rusqlite's bundled SQLite.

use std::env;

fn main() {
    // Tell cargo to re-run this script if the source changes.
    println!("cargo:rerun-if-changed=src/lib.rs");
    println!("cargo:rerun-if-changed=build.rs");

    // Windows: ensure we use the static MSVC runtime to avoid DLL hell.
    // Linux/macOS: no special handling needed.
    if cfg!(target_os = "windows") {
        println!("cargo:rustc-link-arg=/NODEFAULTLIB:MSVCRT");
        println!("cargo:rustc-link-arg=/NODEFAULTLIB:MSVCRTD");
    }

    println!("cargo:warning=Build complete — load target/release/libzeloo_fts5_cjk.so/dll with SQLite");
}
