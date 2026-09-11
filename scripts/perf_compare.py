#!/usr/bin/env python3
"""Benchmark comparison script for CI."""
import json
import sys


def load_bench(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return {b["name"]: b.get("stats", {}).get("mean", 0) * 1000
                for b in data.get("benchmarks", [])}
    except Exception:
        return {}

baseline_path = sys.argv[1] if len(sys.argv) > 1 else "baseline.json"
current_path = sys.argv[2] if len(sys.argv) > 2 else "current.json"

baseline = load_bench(baseline_path)
current = load_bench(current_path)

degraded, improved = [], []
for name, c_val in current.items():
    b_val = baseline.get(name)
    if b_val is not None and b_val > 0:
        pct = ((c_val - b_val) / b_val) * 100
        if pct > 10:
            degraded.append({"name": name, "baseline_ms": round(b_val, 2), "current_ms": round(c_val, 2), "pct": round(pct, 1)})
        elif pct < -10:
            improved.append({"name": name, "baseline_ms": round(b_val, 2), "current_ms": round(c_val, 2), "pct": round(-pct, 1)})

result = {"degraded": degraded, "improved": improved}
with open("perf_compare.json", "w") as f:
    json.dump(result, f)

if degraded:
    print(f"REGRESSION: {len(degraded)} test(s) >10% slower")
    sys.exit(1)
else:
    print(f"OK: {len(improved)} test(s) improved, 0 regressed")
    sys.exit(0)
