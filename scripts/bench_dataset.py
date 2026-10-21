"""The real Loom benchmark — runs the FULL pipeline over the synthetic dataset.

What is measured, for every sample:
  * token count before / after the anchor  (real tiktoken, not an estimate)
  * byte-for-byte re-read                 (the core promise)
  * invariant coverage                     (what stays in context vs what is missing)
  * latencies                              (build / store / retrieve / verify)

Plus an end-to-end "agent loop" scenario: a simulated agent that would have carried
the full payload in context, and now carries only the anchor, then retrieves the
chunks it actually needs. That is the metric that matters to a user: how many tokens
reach the model, and does the answer stay correct.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loom import anchors, compress, store, verify  # noqa: E402
from loom.tokenizer import count_tokens, encoder_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"
DB = ROOT / "bench.db"
SIZES = ["small", "medium", "large"]


def run_sample(path: Path, size: str, kind: str) -> dict:
    content = path.read_text(encoding="utf-8")

    # --- 1. build the anchor + chunks -----------------------------------
    t0 = time.perf_counter()
    anchor, chunks = compress.build_anchor(content)
    t_build = time.perf_counter() - t0

    # --- 2. store ---------------------------------------------------------
    session = f"bench_{path.stem}"
    store.DB_PATH = DB
    t0 = time.perf_counter()
    ids = store.save_chunks(session, path.name, chunks)
    store.save_anchor(session, path.name, anchor)
    invs = anchors.extract(content)
    store.save_invariants(session, [(i.kind, i.value, i.priority) for i in invs])
    t_store = time.perf_counter() - t0

    # --- 3. retrieve: must be byte-identical -----------------------------
    # Two latencies matter:
    #   t_get      : re-read the WHOLE session (restore-from-scratch path)
    #   t_get_one  : read ONE chunk (the real interactive path — what an agent does
    #                when it needs a specific piece of the context back)
    t0 = time.perf_counter()
    parts = [store.load_chunk(i)["content"] for i in ids]
    t_get = time.perf_counter() - t0
    identical = "".join(parts) == content

    t0 = time.perf_counter()
    for _ in range(20):
        store.load_chunk(ids[len(ids) // 2])
    t_get_one = (time.perf_counter() - t0) / 20

    # --- 4. verify --------------------------------------------------------
    t0 = time.perf_counter()
    rep = verify.check_session(session)
    t_verify = time.perf_counter() - t0

    tok_before = count_tokens(content)
    tok_after = count_tokens(anchor)
    saved = round(100 * (1 - tok_after / tok_before), 2) if tok_before else 0.0

    # --- 5. realistic retrieval: the agent pulls 3 chunks, not all ------
    probe = "port timeout replicas migration root cause"
    picked = _pick_chunks(chunks, probe, k=3)
    tok_pulled = count_tokens("".join(p["text"] for p in picked))

    return {
        "file": path.name,
        "size": size,
        "kind": kind,
        "chars": len(content),
        "lines": content.count("\n") + 1,
        "chunks": len(ids),
        "tok_before": tok_before,
        "tok_after": tok_after,
        "saved_pct": saved,
        "identical": identical,
        "coverage": rep["coverage"],
        "coverage_weighted": rep["coverage_weighted"],
        "coverage_structured": rep["coverage_structured"],
        "retrievable": rep["retrievable"],
        "lossless": rep["lossless"],
        "critical_missing": rep["critical_missing"],
        "invariants": rep["invariants_total"],
        "t_build": t_build,
        "t_store": t_store,
        "t_get": t_get,
        "t_get_one": t_get_one,
        "t_verify": t_verify,
        "tok_pulled": tok_pulled,
    }


def _pick_chunks(chunks: list[dict], probe: str, k: int = 3) -> list[dict]:
    """Naive BM25-ish keyword pick — mimics what a retrieval layer would return."""
    terms = probe.lower().split()
    scored = []
    for c in chunks:
        low = c["text"].lower()
        score = sum(low.count(t) for t in terms)
        scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]]


def main() -> None:
    print(f"tokenizer : {encoder_name()}")
    print(f"dataset   : {DATASET}")
    print(f"store     : {DB}\n")

    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    results = []
    for m in manifest["samples"]:
        p = DATASET / m["file"]
        r = run_sample(p, m["size"], m["kind"])
        results.append(r)
        print(
            f"{r['file']:<34} {r['chars']:>10,} ch  {r['chunks']:>5} chunks  "
            f"{r['tok_before']:>8,} -> {r['tok_after']:>7,} tk ({r['saved_pct']:>6}%)  "
            f"ident={str(r['identical']):<5} ctx={r['coverage']:.3f} "
            f"retrouv={r['retrievable']:.3f}  "
            f"build={r['t_build']*1000:>7.0f}ms 1chunk={r['t_get_one']*1000:>5.1f}ms"
        )

    # ---------------- aggregates ----------------
    print("\n" + "=" * 100)
    print("PAR TAILLE")
    print("=" * 100)
    for size in SIZES:
        rs = [r for r in results if r["size"] == size]
        if not rs:
            continue
        med_build = statistics.median(r["t_build"] for r in rs) * 1000
        med_get = statistics.median(r["t_get"] for r in rs) * 1000
        med_get_one = statistics.median(r["t_get_one"] for r in rs) * 1000
        med_store = statistics.median(r["t_store"] for r in rs) * 1000
        med_verify = statistics.median(r["t_verify"] for r in rs) * 1000
        w_before = sum(r["tok_before"] for r in rs)
        w_after = sum(r["tok_after"] for r in rs)
        w_saved = round(100 * (1 - w_after / w_before), 2)
        all_ident = all(r["identical"] for r in rs)
        all_lossless = all(r["lossless"] for r in rs)
        min_retr = min(r["retrievable"] for r in rs)
        crit = sum(r["critical_missing"] for r in rs)
        print(
            f"\n  {size.upper()}  ({len(rs)} fichiers, "
            f"{sum(r['chars'] for r in rs):,} chars, {sum(r['chunks'] for r in rs):,} chunks)"
        )
        print(f"    tokens avant            : {w_before:,}")
        print(f"    tokens apres (ancre)    : {w_after:,}")
        print(f"    reduction               : {w_saved} %")
        print(f"    relecture identique     : {all_ident}  ({sum(1 for r in rs if r['identical'])}/{len(rs)})")
        print(f"    ZERO PERTE (recuperable): {all_lossless}  (min={min_retr:.4f})")
        print(f"    invariants dans ancre   : {statistics.mean(r['coverage'] for r in rs):.1%} en moyenne")
        print(f"    valeurs structurees     : {statistics.mean(r['coverage_structured'] for r in rs):.1%} en moyenne (priorite >= 2)")
        print(f"    couverture ponderee     : {statistics.mean(r['coverage_weighted'] for r in rs):.1%} en moyenne")
        print(f"    contraintes perdues     : {crit}")
        print(f"    latence mediane build   : {med_build:,.0f} ms")
        print(f"    latence mediane store   : {med_store:,.0f} ms")
        print(f"    latence 1 chunk (cible) : {med_get_one:,.2f} ms   <- chemin interactif")
        print(f"    latence relecture totale: {med_get:,.0f} ms   <- restauration complete")
        print(f"    latence mediane verify  : {med_verify:,.0f} ms")
        pulled = sum(r["tok_pulled"] for r in rs)
        print(f"    tokens si on tire 3 chunks: {pulled:,} (vs {w_before:,} en contexte plein)")

    print("\n" + "=" * 100)
    print("SCENARIO AGENT (contexte reel)")
    print("=" * 100)
    tot_full = sum(r["tok_before"] for r in results)
    tot_anchor = sum(r["tok_after"] for r in results)
    tot_pull = sum(r["tok_pulled"] for r in results)
    print(f"  contexte plein (avant Loom)      : {tot_full:,} tokens")
    print(f"  contexte avec ancre Loom          : {tot_anchor:,} tokens  "
          f"({round(100*(1-tot_anchor/tot_full),2)} % de moins)")
    print(f"  contexte ancre + 3 chunks tires   : {tot_anchor + tot_pull:,} tokens  "
          f"({round(100*(1-(tot_anchor+tot_pull)/tot_full),2)} % de moins)")
    print(f"  relecture byte-identique          : "
          f"{sum(1 for r in results if r['identical'])}/{len(results)}")

    (ROOT / "bench-report.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print("\n  rapport detaille -> bench-report.json")


if __name__ == "__main__":
    main()
