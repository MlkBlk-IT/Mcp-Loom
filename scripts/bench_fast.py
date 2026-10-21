"""Fast benchmark on real logs — capped so it finishes in ~1 min.

Caps are explicit and printed: the reader always knows whether a number is from the
full file or from a slice.
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
CAP = 10 * 1024 * 1024  # 10 MiB cap for the large case


def read_text_slice(path: Path, cap: int | None) -> tuple[str, int, int]:
    """Read up to `cap` bytes of REAL text from a log.

    Log files are often sparse: the head of the file can be a long run of NUL bytes
    (a pre-allocated buffer). Decoding that as text yields garbage and fake metrics,
    so we skip leading NUL padding and take the first `cap` bytes of real content.
    """
    raw = path.read_bytes()
    full_size = len(raw)
    start = 0
    while start < len(raw) and raw[start] == 0:
        start += 1
    raw = raw[start:]
    if cap:
        raw = raw[:cap]
    return raw.decode("utf-8", errors="replace"), full_size, start


CASES = [
    ("PETIT", LOGS / "action-security-audit.log", None),
    ("MOYEN", LOGS / "agent.log", None),
    ("GROS", LOGS / "gateway-stdio.log", CAP),
]

SECRET = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|token|bearer|authorization|cookie|"
    r"sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{8,})"
)


def redact(text: str) -> str:
    out = []
    for line in text.splitlines():
        if SECRET.search(line):
            line = SECRET.sub(lambda m: f"{m.group(0)[:4]}***REDACTED***", line)
        out.append(re.sub(r"(?<![\w])[A-Za-z0-9+/=_-]{40,}(?![\w])", "<BLOB>", line))
    return "\n".join(out)


def main() -> None:
    print(f"tokenizer : {encoder_name()}")
    print(f"store     : {Path(r'D:\\Loom\\bench.db')}")
    print(f"cap gros  : {CAP:,} bytes\n")

    rows = []
    for label, path, cap in CASES:
        if not path.exists():
            print(f"!! {label}: {path} missing")
            continue
        raw = path.read_bytes()
        full_size = len(raw)
        content, full_size, skipped = read_text_slice(path, cap)
        real_bytes = len(content.encode("utf-8", errors="replace"))

        session = f"bench_{label.lower()}"
        store.DB_PATH = Path(r"D:\Loom\bench.db")

        t0 = time.perf_counter()
        anchor, chunks = compress.build_anchor(content)
        t_anchor = time.perf_counter() - t0

        t0 = time.perf_counter()
        ids = store.save_chunks(session, path.name, chunks)
        store.save_anchor(session, path.name, anchor)
        invs = anchors.extract(content)
        store.save_invariants(session, [(i.kind, i.value, i.priority) for i in invs])
        t_store = time.perf_counter() - t0

        t0 = time.perf_counter()
        parts = [store.load_chunk(i)["content"] for i in ids]
        t_get = time.perf_counter() - t0
        identical = "".join(parts) == content

        t0 = time.perf_counter()
        rep = verify.check_session(session)
        t_verify = time.perf_counter() - t0

        tok_before = count_tokens(content)
        tok_after = count_tokens(anchor)
        saved = round(100 * (1 - tok_after / tok_before), 2) if tok_before else 0.0

        rows.append(
            (label, path.name, full_size, len(raw), len(ids), tok_before, tok_after, saved,
             identical, rep["coverage"], rep["critical_missing"], t_anchor, t_store, t_get,
             t_verify)
        )

        print("=" * 76)
        print(f"{label}  —  {path.name}")
        print("=" * 76)
        print(f"  taille fichier reel   : {full_size:,} bytes")
        if cap and full_size > cap:
            print(f"  taille utilisee       : {len(raw):,} bytes (CAP {cap:,})")
        print(f"  chunks produits       : {len(ids):,}")
        print(f"  tokens AVANT          : {tok_before:,}")
        print(f"  tokens APRES (ancre)  : {tok_after:,}")
        print(f"  reduction             : {saved} %")
        print(f"  relecture identique   : {identical}")
        print(f"  couverture invariants : {rep['coverage']}  (lossless={rep['lossless']})")
        print(f"  contraintes perdues   : {rep['critical_missing']}")
        print(f"  latence ancre         : {t_anchor*1000:,.0f} ms")
        print(f"  latence store         : {t_store*1000:,.0f} ms")
        print(f"  latence relecture     : {t_get*1000:,.0f} ms")
        print(f"  latence verification  : {t_verify*1000:,.0f} ms")
        print("  --- apercu ancre (redige) ---")
        for line in redact(anchor).splitlines()[:12]:
            print("   |", line[:150])
        print()

    print("=" * 76)
    print("SYNTHESE")
    print("=" * 76)
    print(
        f"{'cas':<7}{'octets':>13}{'chunks':>8}{'tok avant':>12}{'tok apres':>12}"
        f"{'red.':>9}{'ident.':>8}{'couv.':>8}{'relecture ms':>13}"
    )
    for r in rows:
        print(
            f"{r[0]:<7}{r[3]:>13,}{r[4]:>8,}{r[5]:>12,}{r[6]:>12,}{r[7]:>8}%"
            f"{str(r[8]):>8}{r[9]:>8}{r[13]*1000:>13,.0f}"
        )


if __name__ == "__main__":
    main()
