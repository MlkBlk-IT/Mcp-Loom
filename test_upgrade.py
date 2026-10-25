"""Loom upgrade validation — P1 (semantic), P2 (cross-session), P3 (auto-store).

Runs the 4 tests specified in the upgrade prompt.
Uses a temp DB to avoid polluting production data.
"""
import os, sys, time, tempfile, json

# Use a temp DB for testing
tmpdir = tempfile.mkdtemp(prefix="loom-test-")
os.environ["LOOM_DB"] = os.path.join(tmpdir, "test.db")
os.environ["LOOM_VECTORS"] = os.path.join(tmpdir, "vectors")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

results = []

def test(name, fn):
    t0 = time.time()
    try:
        fn()
        elapsed = round(time.time() - t0, 2)
        results.append(("PASS", name, elapsed))
        print(f"  ✓ {name} ({elapsed}s)")
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        results.append(("FAIL", name, f"{e} ({elapsed}s)"))
        print(f"  ✗ {name}: {e} ({elapsed}s)")
        import traceback; traceback.print_exc()


# =========================================================================
print("\n=== P1: Semantic Search ===")

def test_p1_store():
    """Store content about CUDA OOM."""
    from loom import store
    content = """
    def train_model(data_loader, epochs=100):
        model = LargeTransformer().cuda()
        optimizer = AdamW(model.parameters(), lr=1e-4)
        for epoch in range(epochs):
            for batch in data_loader:
                outputs = model(batch)
                loss = criterion(outputs, labels)
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()
    # Error: RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB.
    # GPU 0 has a total capacity of 8.0 GiB, 6.5 GiB already allocated.
    """
    # Build chunks manually
    chunks = [{"text": content, "tokens": 120}]
    saved = store.save_all(
        "test-semantic", "train_model.py", chunks, anchor="def train_model(...): CUDA OOM",
        invariants=[], source_meta={"tokens_before": 120, "anchor_tokens": 10}
    )
    assert saved["chunk_ids"], "No chunks stored"
    assert "embedded" in saved, "Missing 'embedded' key"
    print(f"    stored {saved['n_chunks']} chunks, embedded={saved.get('embedded', 'N/A')}")

def test_p1_search():
    """Search 'erreur CUDA mémoire' — different words, same meaning."""
    from loom import store
    from loom import vector_index
    assert vector_index.available(), "Embedding backend not available"
    # Save the index
    vector_index.save()
    results = store.search_semantic("erreur CUDA mémoire GPU", limit=5)
    assert results, "Semantic search returned no results!"
    top = results[0]
    print(f"    top result: id={top['id']}, score={top.get('score', 'N/A')}")
    print(f"    label: {top['label']}")
    assert "CUDA" in top["content"] or "cuda" in top["content"].lower(), "Top result doesn't mention CUDA"
    print(f"    ✓ Found CUDA-related chunk via semantic search (score={top.get('score', 'N/A')})")

# =========================================================================
print("\n=== P2: Cross-Session Transfer ===")

def test_p2_store():
    """Store content in debug-1 session."""
    from loom import store
    content = "Traceback: ValueError at line 42 in handler.py — session='debug-1' log error"
    chunks = [{"text": content, "tokens": 20}]
    saved = store.save_all(
        "debug-1", "error.log", chunks, anchor="ValueError handler.py",
        invariants=[], source_meta={"tokens_before": 20, "anchor_tokens": 5}
    )
    assert saved["chunk_ids"], "No chunks stored in debug-1"
    print(f"    stored chunk {saved['chunk_ids'][0]} in session debug-1")

def test_p2_transfer():
    """Transfer chunks from debug-1 to fix-2."""
    from loom import store, cross_session
    # Get chunk IDs from debug-1
    conn = store._connect()
    rows = conn.execute("SELECT id FROM chunks WHERE session_id = 'debug-1'").fetchall()
    conn.close()
    chunk_ids = [r["id"] for r in rows]
    result = cross_session.transfer("debug-1", "fix-2", chunk_ids)
    assert result["transferred"] > 0, f"Transfer failed: {result}"
    print(f"    transferred {result['transferred']} chunks debug-1 → fix-2")

def test_p2_get_cross():
    """Retrieve chunk from fix-2 session."""
    from loom import cross_session
    conn = __import__("sqlite3").connect(os.environ["LOOM_DB"])
    conn.row_factory = __import__("sqlite3").Row
    row = conn.execute("SELECT id FROM chunks WHERE session_id = 'debug-1' LIMIT 1").fetchone()
    conn.close()
    chunk = cross_session.get_cross_session(row["id"], "fix-2")
    assert chunk is not None, "Cross-session get returned None"
    assert "ValueError" in chunk["content"], "Wrong chunk retrieved"
    print(f"    ✓ Retrieved chunk {row['id']} from fix-2 (originally in debug-1)")

# =========================================================================
print("\n=== P3: Auto-Store Hook ===")

def test_p3_small():
    """Small output should passthrough unchanged."""
    from loom.auto_store import auto_store

    @auto_store(threshold_tokens=500)
    def small_func():
        return "hello world"

    result = small_func()
    assert result == "hello world", f"Small output should passthrough, got: {result}"
    print(f"    ✓ Small output passed through ({len(result)} chars)")

def test_p3_large():
    """Large output should be auto-stored."""
    from loom.auto_store import auto_store

    @auto_store(threshold_tokens=100, session_id="test-auto")
    def big_func():
        return "ERROR: " + "CUDA out of memory. " * 100  # ~700 tokens

    result = big_func()
    assert isinstance(result, dict), f"Large output should return dict, got {type(result)}"
    assert result.get("stored") is True, "Not marked as stored"
    assert "anchor" in result, "Missing anchor"
    assert "chunk_ids" in result, "Missing chunk_ids"
    assert result["tokens_before"] > 100, f"tokens_before too low: {result['tokens_before']}"
    ratio = result.get("saved_ratio", 0)
    print(f"    ✓ Large output stored: {result['tokens_before']} → {result['tokens_after']} tokens ({ratio*100:.1f}% saved)")
    print(f"    anchor: {result['anchor'][:80]}...")

# =========================================================================
# RUN ALL TESTS
print("\n" + "=" * 60)
print("LOOM UPGRADE VALIDATION")
print("=" * 60)

test("P1: Store CUDA content", test_p1_store)
test("P1: Semantic search 'erreur CUDA mémoire'", test_p1_search)
test("P2: Store in debug-1", test_p2_store)
test("P2: Transfer debug-1 → fix-2", test_p2_transfer)
test("P2: Get cross-session", test_p2_get_cross)
test("P3: Small output passthrough", test_p3_small)
test("P3: Large output auto-stored", test_p3_large)

# Summary
print("\n" + "=" * 60)
passed = sum(1 for r in results if r[0] == "PASS")
failed = sum(1 for r in results if r[0] == "FAIL")
print(f"RESULTS: {passed}/{len(results)} passed, {failed} failed")
for status, name, info in results:
    marker = "✓" if status == "PASS" else "✗"
    print(f"  {marker} {name} ({info})")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
