"""Isolation des tests: aucune écriture vers le vrai ~/.loom.

Ordre important: les variables d'environnement sont posées AVANT tout import de `loom`
(audit.AUDIT_DIR et store.DB_PATH sont lus à l'import).
"""
import os
import tempfile
from pathlib import Path

import pytest

_SESSION_TMP = Path(tempfile.mkdtemp(prefix="loom-tests-"))
os.environ["LOOM_DB"] = str(_SESSION_TMP / "loom.db")
os.environ["LOOM_AUDIT_DIR"] = str(_SESSION_TMP / "audit")
os.environ.pop("LOOM_DB_PASSWORD", None)

_REAL = Path.home() / ".loom"


def _stat(p: Path):
    try:
        s = p.stat()
        return (s.st_size, s.st_mtime_ns)
    except FileNotFoundError:
        return None


@pytest.fixture(scope="session", autouse=True)
def _real_loom_untouched():
    """Canari: le vrai ~/.loom ne doit pas changer pendant la run."""
    files = [_REAL / "loom.db", _REAL / "audit" / "audit.jsonl"]
    before = {str(f): _stat(f) for f in files}
    yield
    after = {str(f): _stat(f) for f in files}
    assert before == after, f"~/.loom modifié pendant les tests: {before} -> {after}"


@pytest.fixture(autouse=True)
def _isolate_loom(tmp_path, monkeypatch):
    db = tmp_path / "loom.db"
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOOM_DB", str(db))
    monkeypatch.setenv("LOOM_AUDIT_DIR", str(audit_dir))
    monkeypatch.delenv("LOOM_DB_PASSWORD", raising=False)

    import loom.store as store
    monkeypatch.setattr(store, "DB_PATH", db)
    try:  # code actuel: session.py copie DB_PATH à l'import
        import loom.session as session
        if hasattr(session, "DB_PATH"):
            monkeypatch.setattr(session, "DB_PATH", db)
    except ImportError:
        pass
    try:
        import loom.audit as audit
        if hasattr(audit, "AUDIT_DIR"):
            monkeypatch.setattr(audit, "AUDIT_DIR", audit_dir)
    except ImportError:
        pass

    try:
        import loom.crypto as crypto
        if hasattr(crypto, "reset_caches"):
            crypto.reset_caches()
    except ImportError:
        pass
    try:
        import loom.ratelimit as ratelimit
        if hasattr(ratelimit, "_rate_limiter"):
            monkeypatch.setattr(ratelimit, "_rate_limiter", None)
    except ImportError:
        pass
    yield
