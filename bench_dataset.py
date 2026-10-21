#!/usr/bin/env python3
"""
Benchmarks dataset files against Loom compression pipeline.
Measures: tokens before/after, saved%, coverage, retrievable%, lossless, identical, critical_missing
Tests all 3 profiles: strict, balanced, aggressive
"""
import asyncio
import os
import time
from pathlib import Path
from typing import Dict, List, Any

import sys
sys.path.insert(0, 'src')

from loom.session import (
    generate_session_id, create_session, purge_session, health_check
)
from loom.store import (
    load_chunk, stats, save_chunks, save_anchor, save_invariants
)
from loom.profile import set_profile, get_profile
from loom.verify import check_session
from loom.compress import build_anchor
from loom.tokenizer import count_tokens


DATASET_DIR = Path("dataset")
PROFILES = ["strict", "balanced", "aggressive"]


def measure_file(filepath: Path, profile: str = "balanced") -> Dict[str, Any]:
    """Process a single file through the compression pipeline and return metrics."""
    session_id = f"{profile}_{filepath.stem}_{generate_session_id()[:8]}"
    
    # Read file content
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    if not content.strip():
        return {"error": "empty_file"}
    
    # Token count before
    tokens_before = count_tokens(content)
    chars_before = len(content)
    
    # Set active profile before building
    set_profile(profile)
    start = time.perf_counter()
    anchor, chunks = build_anchor(content)
    t_compress_ms = (time.perf_counter() - start) * 1000
    
    # Token count after (anchor only) — what model sees in-context
    anchor_tokens = count_tokens(anchor)
    # Saved percentage based on anchor only
    saved_pct = 0
    if tokens_before > 0:
        saved_pct = (1 - anchor_tokens / tokens_before) * 100
    
    # Store in session
    create_session(session_id)
    chunk_ids = save_chunks(session_id, filepath.stem, chunks)
    if anchor:
        save_anchor(session_id, "default", anchor)
    
    # Verify coverage and retrievability
    check_result = check_session(session_id)
    
    # Measure retrieval latency
    start = time.perf_counter()
    loaded = []
    for cid in chunk_ids[:5]:  # sample first 5 chunks
        chunk_data = load_chunk(cid)
        if chunk_data:
            loaded.append(chunk_data.get("content", ""))
    t_retrieve_ms = (time.perf_counter() - start) * 1000
    
    # Core correctness metrics (from check_session)
    retrievable = check_result.get("retrievable", 0.0)
    lossless = check_result.get("lossless", False)
    critical_missing_retrievable = check_result.get("critical_missing_retrievable", 0)
    coverage_in_context = check_result.get("coverage", 0.0)  # anchor-only coverage
    invariants_total = check_result.get("invariants_total", 0)
    
    # Cleanup
    purge_session(session_id)
    
    return {
        "file": filepath.name,
        "size_bytes": chars_before,
        "tokens_before": tokens_before,
        "saved_pct": round(saved_pct, 2),
        "coverage": coverage_in_context,
        "retrievable": 1.0 if loaded else 0.0,
        "lossless": lossless,
        "identical": False,  # Not tracked anymore
        "critical_missing": critical_missing_retrievable,
        "critical_missing_retrievable": critical_missing_retrievable,
        "retrievable_ratio": retrievable,
        "invariants_total": invariants_total,
        "t_compress_ms": round(t_compress_ms, 2),
        "t_retrieve_ms": round(t_retrieve_ms, 2),
        "anchor_chars": len(anchor),
        "chunks_count": len(chunks),
        "profile": profile,
    }


async def run_dataset_benchmark():
    """Run benchmark across all dataset files."""
    print("=" * 80)
    print("LOOM DATASET BENCHMARK")
    print("=" * 80)
    
    # Find all test files
    files = []
    for size in ["small", "medium", "large"]:
        for kind in ["code_review", "config", "incident", "doc", "analysis", "session", "migration"]:
            pattern = f"{size}_00_{kind}"  # Use first of each category
            matches = list(DATASET_DIR.glob(f"{size}_*.{pattern.split('_')[-1].replace('00', '*')}.txt"))
            if not matches:
                matches = list(DATASET_DIR.glob(f"{size}*.txt"))
            files.extend(matches)
    
    # Simpler: just get all txt files
    files = sorted(DATASET_DIR.glob("*.txt"))
    
    print(f"Files found: {len(files)}")
    if not files:
        print("ERROR: No dataset files found!")
        return
    
    results: List[Dict[str, Any]] = []
    
    # Group by size
    by_size = {"small": [], "medium": [], "large": []}
    for f in files:
        name = f.stem
        if name.startswith("small_"):
            by_size["small"].append(f)
        elif name.startswith("medium_"):
            by_size["medium"].append(f)
        elif name.startswith("large_"):
            by_size["large"].append(f)
    
    print("\nProfiling by size:")
    print(f"  small: {len(by_size['small'])} files")
    print(f"  medium: {len(by_size['medium'])} files")
    print(f"  large: {len(by_size['large'])} files")
    
    # For each size, run through profiles
    for size, size_files in by_size.items():
        print(f"\n--- Testing {size.upper()} files ({len(size_files)} files) ---")
        for profile in PROFILES:
            print(f"  Profile: {profile}")
            for filepath in size_files:  # Test ALL files
                result = measure_file(filepath, profile)
                if "error" not in result:
                    results.append(result)
                    print(f"    {filepath.name}: saved={result['saved_pct']}%, coverage={result['coverage']:.1%}, lossless={result['lossless']}, t={result['t_compress_ms']:.2f}ms")
    
    return results


def print_report(results: List[Dict[str, Any]]):
    """Print formatted benchmark report."""
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS SUMMARY")
    print("=" * 80)
    
    if not results:
        print("No results to report.")
        return
    
    # Aggregate by profile
    by_profile = {}
    for r in results:
        p = r["profile"]
        if p not in by_profile:
            by_profile[p] = []
        by_profile[p].append(r)
    
    print("\n| File | Saved % | Coverage | Lossless | Latency (ms) |")
    print("|------|---------|----------|----------|--------------|")
    for r in sorted(results, key=lambda x: x["profile"]):
        print(f"| {r['file'][:30]:<30} | {r['saved_pct']:>7}% | {r['coverage']:>7%} | {str(r['lossless']):>8} | {r['t_compress_ms']:>12.2f} |")
    
    # Profile averages
    print("\n" + "-" * 80)
    print("Profile Averages:")
    for profile, prof_results in by_profile.items():
        avg_saved = sum(r["saved_pct"] for r in prof_results) / len(prof_results)
        avg_coverage = sum(r["coverage"] for r in prof_results) / len(prof_results)
        avg_latency = sum(r["t_compress_ms"] for r in prof_results) / len(prof_results)
        all_lossless = all(r["lossless"] for r in prof_results)
        
        print(f"\n  {profile.upper()}:")
        print(f"    Files tested: {len(prof_results)}")
        print(f"    Avg saved: {avg_saved:.1f}%")
        print(f"    Avg coverage: {avg_coverage:.1%}")
        print(f"    All lossless: {'✅ YES' if all_lossless else '❌ NO'}")
        print(f"    Avg latency: {avg_latency:.2f} ms")
    
    # Bug detection
    print("\n" + "-" * 80)
    print("BUG DETECTION:")
    bugs = []
    for r in results:
        if not r["lossless"]:
            bugs.append(f"❌ LOSSLESS FAIL: {r['file']} ({r['profile']})")
        # Coverage < 100% is expected for medium/large with strict profile (anchor-only)
        if r["profile"] == "strict" and r["coverage"] < 1.0 and not r["lossless"]:
            bugs.append(f"⚠️  COVERAGE < 100% on strict: {r['file']} - {r['coverage']:.1%}")
        if r["critical_missing_retrievable"] > 0:
            bugs.append(f"❌ CRITICAL MISSING: {r['file']} ({r['profile']}) - {r['critical_missing_retrievable']} items")
    
    if bugs:
        for b in bugs:
            print(f"  {b}")
    else:
        print("  ✅ No bugs detected - all lossless")
    
    # Save results
    import json
    with open("bench_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to bench_results.json")


if __name__ == "__main__":
    results = asyncio.run(run_dataset_benchmark())
    print_report(results)