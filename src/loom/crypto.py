"""Encryption layer for the Loom drawer.

Two modes:

1. SQLCipher (``pysqlcipher3``) - full-database encryption. The optional
   dependency is not installable in this environment, so that branch stays
   UNVERIFIED (see the escape handling of the password below).
2. Application-level encryption (Fernet) - encrypts the content columns only and
   keeps working with the stdlib ``sqlite3`` driver.

Key derivation (Fernet mode)
----------------------------
PBKDF2-HMAC-SHA256 with a random 16-byte salt, stored in the ``meta`` table of the
 drawer itself (``key='pbkdf2_salt'``, created on first use). The salt is not a
secret; it only makes the derived key unique per drawer.

Iteration count: 600 000, per the OWASP Password Storage Cheat Sheet
("If FIPS-140 compliance is required, use PBKDF2 with a work factor of 600,000
or more and set with an internal hash function of HMAC-SHA-256),
https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html,
consulted 2026-10-21. The same sheet lists Argon2id / scrypt as the preferred
choices, but PBKDF2-HMAC-SHA256 is the option backed by a FIPS-140-validated
implementation, which is why it is used here.

Fernet is **AES-128-CBC + HMAC-SHA256** - it is *not* AES-256. The 32-byte
derived key is split by the Fernet specification into a 16-byte encryption key
and a 16-byte signing key.

Caching rules (test isolation)
-------------------------------
* No path is ever bound at import time: ``get_encryption()`` resolves the drawer
  path on EVERY call, so a test pointing ``LOOM_DB`` at a temporary directory
  never touches the real ``~/.loom/loom.db``.
* Derived key material is cached per (password, salt). The salt lives in the
  drawer, so the cache stays valid across processes.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Optional

try:
    import sqlcipher3.dbapi2 as sqlcipher
    _HAS_SQLCIPHER = True
except ImportError:
    _HAS_SQLCIPHER = False

try:
    from cryptography.fernet import Fernet
    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False

# -- constants --------------------------------------------------------------

PBKDF2_ITERATIONS = 600_000
PBKDF2_DKLEN = 32
PBKDF2_SALT_BYTES = 16
PBKDF2_SALT_KEY = "pbkdf2_salt"

FERNET_TOKEN_PREFIX = "gAAAA"

META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""

# -- caches -----------------------------------------------------------------

_KEY_CACHE: dict[tuple[str, bytes], Fernet] = {}

# -- password handling --------------------------------------------------------

_PASSWORD_OVERRIDE: Optional[str] = None

# -- public API --------------------------------------------------------------

def reset_caches() -> None:
    """Drop every cached key/instance (used by the test suite)."""
    _KEY_CACHE.clear()


def _derive_fernet(password: str, salt: bytes) -> "Fernet":
    """Derive the Fernet key from a password + salt (cached)."""
    cache_key = (password, salt)
    cached = _KEY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=PBKDF2_DKLEN
    )
    fernet = Fernet(base64.urlsafe_b64encode(dk))
    _KEY_CACHE[cache_key] = fernet
    return fernet


def _ensure_salt(conn: sqlite3.Connection) -> bytes:
    """Return the drawer salt, creating the meta table + salt row on first use."""
    conn.execute(META_TABLE_SQL)
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (PBKDF2_SALT_KEY,)
    ).fetchone()
    if row is not None:
        try:
            return bytes.fromhex(row[0])
        except (TypeError, ValueError):
            pass
    salt = os.urandom(PBKDF2_SALT_BYTES)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (PBKDF2_SALT_KEY, salt.hex()),
    )
    conn.commit()
    return salt

class DatabaseEncryption:
    """Manages the encryption of a Loom drawer (SQLCipher or column-level Fernet)."""

    def __init__(self, db_path: Path | str, password: Optional[str] = None):
        self.db_path = Path(db_path)
        self.password = password if password is not None else _resolve_password()
        self._fernet: Optional["Fernet"] = None
        self._use_sqlcipher = False

        if self.password:
            if _HAS_SQLCIPHER:
                self._use_sqlcipher = True
            elif _HAS_FERNET:
                self._fernet = None  # derived lazily: the salt lives in the drawer
            else:
                raise RuntimeError(
                    "Encryption requested but neither pysqlcipher3 nor cryptography available"
                )

    # -- properties -----------------------------------------------------------

    @property
    def is_encrypted(self) -> bool:
        """True when a password is configured (column-level or full-DB)."""
        return bool(self.password)

    @property
    def encryption_mode(self) -> str:
        if not self.is_encrypted:
            return "none"
        return "sqlcipher" if self._use_sqlcipher else "fernet"

    @property
    def column_encrypted(self) -> bool:
        """True when the content columns are encrypted (Fernet mode)."""
        return self.is_encrypted and not self._use_sqlcipher

    # -- key handling ---------------------------------------------------------

    def _fernet_instance(self, conn: sqlite3.Connection | None = None) -> "Fernet":
        """Return the Fernet instance, deriving it from the drawer salt if needed."""
        if self._fernet is not None:
            return self._fernet
        if not self.password:
            raise RuntimeError("No password configured: cannot derive an encryption key")
        if conn is None:
            # No connection handed over: open a short-lived one on the drawer.
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path))
            try:
                salt = _ensure_salt(conn)
            finally:
                conn.close()
        else:
            salt = _ensure_salt(conn)
        self._fernet = _derive_fernet(self.password, salt)
        return self._fernet

    # -- connections ----------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """Create a database connection (encrypted when configured)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if self._use_sqlcipher:
            conn = sqlcipher.connect(str(self.db_path))
            # PRAGMA key does not accept bound parameters: escape the quotes.
            safe_password = self.password.replace("'", "''")
            conn.execute(f"PRAGMA key = '{safe_password}'")
            try:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            except Exception as exc:  # pragma: no cover - needs pysqlcipher3
                conn.close()
                raise RuntimeError("Invalid database password") from exc
        else:
            conn = sqlite3.connect(str(self.db_path))
            if self.is_encrypted:
                # Materialize the salt + derived key up-front.
                self._fernet_instance(conn)

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # -- content --------------------------------------------------------------

    def encrypt_content(self, content: str) -> str:
        """Encrypt a content string for column-level storage."""
        if not self.column_encrypted:
            return content
        return self._fernet_instance().encrypt(content.encode("utf-8")).decode("ascii")

    def decrypt_content(self, content: str) -> str:
        """Decrypt a stored content string.

        Legacy rows written before encryption was enabled are returned unchanged
        (they do not carry the Fernet token prefix). A Fernet token that cannot
        be decrypted raises ValueError: silently returning the ciphertext would
        hand back garbage as if it were plaintext.
        """
        if not self.column_encrypted:
            return content
        if not content.startswith(FERNET_TOKEN_PREFIX):
            # Legacy plaintext row.
            return content
        try:
            return self._fernet_instance().decrypt(content.encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise ValueError("wrong password or corrupted data") from exc


def _resolve_password() -> Optional[str]:
    """Password from the explicit override, else the environment."""
    if _PASSWORD_OVERRIDE is not None:
        return _PASSWORD_OVERRIDE
    return os.environ.get("LOOM_DB_PASSWORD") or None


def get_encryption(
    db_path: Path | str | None = None, password: Optional[str] = None
) -> DatabaseEncryption:
    """Return the encryption handler for a drawer (path resolved on every call)."""
    if db_path is None:
        from loom import store

        db_path = store.DB_PATH
    resolved = password if password is not None else _resolve_password()
    instance = DatabaseEncryption(db_path, resolved)
    return instance

def set_encryption_password(password: Optional[str]) -> None:
    """Force the password used by every drawer (call before the first DB access)."""
    global _PASSWORD_OVERRIDE
    _PASSWORD_OVERRIDE = password
    reset_caches()


def connect_encrypted(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection to a drawer, encrypted when a password is configured."""
    if db_path is None:
        from loom import store

        db_path = store.DB_PATH
    return get_encryption(db_path).connect()