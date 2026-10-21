"""Benchmark Loom on REAL logs from this machine.

Three sizes: small / medium / large. Real files, real tiktoken counts, real SQLite.
Nothing is printed that could leak a secret: the anchor sample is redacted before
display, and the console shows counts + timings only.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loom import anchors, compress, store, verify  # noqa: E402
from loom.tokenizer import count_tokens, encoder_name  # noqa: E402

LOGS = Path(r"C:\Users\Tech\AppData\Local\hermes\logs")

CASES = [
    ("PETIT  (small)", LOGS / "action-security-audit.log", None),
    ("MOYEN  (medium)", LOGS / "agent.log", None),
    ("GROS  (large)", LOGS / "gateway-stdio.log", None),
]

SECRET = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|token|bearer|authorization|cookie|"
    r"sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{8,}|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)


def redact(text: str) -> str:
    """Mask anything that looks like a credential before it reaches the console."""
    out = []
    for line in text.splitlines():
        if SECRET.search(line):
            line = SECRET.sub(lambda m: f"{m.group(0)[:4]}***REDACTED***", line)
        # mask long hex/base64 blobs
        line = re.sub(r"(?<![\w])[A-Za-z0-9+/=_-]{40,}(?![\w])", "<BLOB-REDACTED>", line)
        out.append(line)
    return "\n".join(out)


def bench(label: str, path: Path, limit: int | None) -> dict:
    if not path.exists():
        return {"label": label, "error": "file missing"}

    raw = path.read_bytes()
    if limit:
        raw = raw[:limit]
    content = raw.decode("utf-8", errors="replace")

    # --- store (the "move" operation) ---
    t0 = time.perf_counter()
    anchor, chunks = compress.build_anchor(content)
    t_anchor = time.perf_counter() - t0

    session = f"bench_{label.split()[0].lower()}"
    store.DB_PATH = Path(r"D:\Loom\bench.db")
    t0 = time.perf_counter()
    ids = store.save_chunks(session, path.name, chunks)
    store.save_anchor(session, path.name, anchor)
    invs = anchors.extract(content)
    store.save_invariants(session, [(i.kind, i.value, i.priority) for i in invs])
    t_store = time.perf_counter() - t0

    # --- retrieve (must be byte-identical) ---
    t0 = time.perf_counter()
    parts = [store.load_chunk(i)["content"] for i in ids]
    t_get = time.perf_counter() - t0
    identical = "".join(parts) == content

    # --- verify ---
    t0 = time.perf_counter()
    rep = verify.check_session(session)
    t_verify = time.perf_counter() - t0

    tok_before = count_tokens(content)
    tok_after = count_tokens(anchor)

    return {
        "label": label,
        "file": path.name,
        "bytes": len(raw),
        "chunks": len(ids),
        "tok_before": tok_before,
        "tok_after": tok_after,
        "saved_pct": round(100 * (1 - tok_after / tok_before), 2) if tok_before else 0.0,
        "identical": identical,
        "coverage": rep["coverage"],
        "lossless": rep["lossless"],
        "invariants": rep["invariants_total"],
        "critical_missing": rep["critical_missing"],
        "t_anchor": t_anchor,
        "t_store": t_store,
        "t_get": t_get,
        "t_verify": t_verify,
        "anchor_preview": redact(anchor)[:900],
    }


def main() -> None:
    print(f"tokenizer: {encoder_name()}")
    print(f"store: {store.DB_PATH}\n")

    results = []
    for label, path, limit in CASES:
        r = bench(label, path, limit)
        results.append(r)
        if "error" in r:
            print(f"!! {label}: {r['error']}")
            continue

        print("=" * 78)
        print(f"{r['label']}  —  {r['file']}")
        print("=" * 78)
        print(f"  taille reelle         : {r['bytes']:,} bytes")
        print(f"  chunks produits       : {r['chunks']:,}")
        print(f"  tokens AVANT          : {r['tok_before']:,}")
        print(f"  tokens APRES (anchor) : {r['tok_after']:,}")
        print(f"  reduction             : {r['saved_pct']} %")
        print(f"  relecture identique   : {r['identical']}   <-- promesse byte-for-byte")
        print(f"  invariants detectes   : {r['invariants']:,}")
        print(f"  couverture            : {r['coverage']}   (lossless={r['lossless']})")
        print(f"  contraintes perdues   : {r['critical_missing']}")
        print(
            f"  latence anchor/store  : {r['t_anchor']*1000:.1f} ms / {r['t_store']*1000:.1f} ms"
        )
        print(f"  latence relecture     : {r['t_get']*1000:.1f} ms")
        print(f"  latence verification  : {r['t_verify']*1000:.1f} ms")
        print("  --- apercu ancre (redige) ---")
        for line in r["anchor_preview"].splitlines()[:18]:
            print("   |", line)
        print()

    print("=" * 78)
    print("SYNTHESE")
    print("=" * 78)
    print(
        f"{'cas':<16}{'octets':>12}{'tokens avant':>15}{'tokens apres':>15}"
        f"{'reduction':>11}{'identique':>12}{'couverture':>13}"
    )
    for r in results:
        if "error" in r:
            continue
        print(
            f"{r['label']:<16}{r['bytes']:>12,}{r['tok_before']:>15,}{r['tok_after']:>15,}"
            f"{r['saved_pct']:>10}%f{str(r['identical']):>12}{r['coverage']:>13}"
        )


if __name__ == "__main__":
    main()
