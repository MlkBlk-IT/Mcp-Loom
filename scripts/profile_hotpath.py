"""Profile the hot path on the big log: which stage costs what."""

from __future__ import annotations

import cProfile
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loom import anchors, compress  # noqa: E402

LOG = Path(r"C:\Users\Tech\AppData\Local\hermes\logs\gateway-stdio.log")
content = LOG.read_bytes().decode("utf-8", errors="replace")
print(f"content: {len(content):,} chars")

t0 = time.perf_counter()
inv = anchors.extract(content)
t_extract = time.perf_counter() - t0
print(f"anchors.extract : {t_extract:8.1f} ms  -> {len(inv):,} invariants")

t0 = time.perf_counter()
anchor, chunks = compress.build_anchor(content)
t_anchor = time.perf_counter() - t0
print(f"build_anchor     : {t_anchor:8.1f} ms  -> {len(chunks):,} chunks")

print("\n--- cProfile of build_anchor ---")
pr = cProfile.Profile()
pr.enable()
compress.build_anchor(content)
pr.disable()
pstats.Stats(pr).sort_stats("cumulative").print_stats(14)

# --- clean repeats, no profiler distortion -------------------------------
print("\n--- clean repeats ---")
for i in range(3):
    t0 = time.perf_counter()
    inv = anchors.extract(content)
    t1 = time.perf_counter()
    anchor, chunks = compress.build_anchor(content)
    t2 = time.perf_counter()
    print(
        f"run {i}: extract {1000*(t1-t0):8.1f} ms ({len(inv):,} inv) | "
        f"build_anchor {1000*(t2-t1):8.1f} ms ({len(chunks):,} chunks)"
    )

kinds: dict[str, int] = {}
for v in inv:
    kinds[v.kind] = kinds.get(v.kind, 0) + 1
print("\ninvariant kinds:", kinds)
print("sample env_var:", [v.value for v in inv if v.kind == "env_var"][:12])
print("sample number  :", [v.value for v in inv if v.kind == "number"][:12])
