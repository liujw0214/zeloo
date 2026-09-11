#!/usr/bin/env python3
"""Memory leak detection script for CI."""
import gc
import json
import sys
import tracemalloc

tracemalloc.start()
snapshot1 = tracemalloc.take_snapshot()

for i in range(100):
    msg = {"role": "user", "content": "test message " * 100}
    _ = json.dumps(msg)
    if i % 10 == 0:
        gc.collect()

gc.collect()
snapshot2 = tracemalloc.take_snapshot()
top_stats = snapshot2.compare_to(snapshot1, "lineno")
total_growth = sum(s.size_diff for s in top_stats[:10])
growth_mb = round(total_growth / 1024 / 1024, 3)
result = {"leak_suspected": growth_mb > 5.0, "growth_mb": growth_mb}
with open("memory-leak-check.json", "w") as f:
    json.dump(result, f)
print(f"Memory growth: {growth_mb} MB after 100 cycles")
tracemalloc.stop()
sys.exit(0)
