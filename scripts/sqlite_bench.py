#!/usr/bin/env python3
"""SQLite performance benchmark for CI."""
import json
import sqlite3
import tempfile
import time

results = {}
for mode in ["WAL", "DELETE"]:
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    if mode == "WAL":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE test(id INTEGER PRIMARY KEY, data TEXT)")
    start = time.perf_counter()
    for i in range(1000):
        conn.execute("INSERT INTO test(data) VALUES (?)", (f"value_{i}",))
    conn.commit()
    insert_ms = (time.perf_counter() - start) * 1000
    conn.execute("CREATE INDEX idx_data ON test(data)")
    start = time.perf_counter()
    for _ in range(100):
        list(conn.execute("SELECT * FROM test WHERE data LIKE ?", ("value_%",)))
    query_ms = (time.perf_counter() - start) * 1000
    results[mode] = {"insert_ms": round(insert_ms, 2), "query_ms": round(query_ms, 2)}
    conn.close()

with open("sqlite-bench.json", "w") as f:
    json.dump(results, f)
print(f"WAL insert: {results['WAL']['insert_ms']}ms, query: {results['WAL']['query_ms']}ms")
