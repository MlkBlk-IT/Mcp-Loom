"""Real integration tests for loom.crypto using actual cryptography on tmp_path."""

import pytest
import hashlib
from pathlib import Path

import loom.crypto as crypto
import loom.store as store
from loom.crypto import DatabaseEncryption, get_encryption, connect_encrypted, reset_caches


# -- tests ----------------------------------------------------------------

def test_round_trip(tmp_path):
    """Encrypt + decrypt returns original content."""
    db = tmp_path / "test.db"
    enc = get_encryption(db, "correct_password")
    
    content = "secret message"
    encrypted = enc.encrypt_content(content)
    assert encrypted != content
    assert enc.decrypt_content(encrypted) == content


def test_wrong_password(tmp_path):
    """Decrypting with wrong password raises ValueError."""
    db = tmp_path / "test.db"
    enc = get_encryption(db, "correct_password")
    
    content = "secret message"
    encrypted = enc.encrypt_content(content)
    
    # Create new encryption instance with wrong password
    enc_wrong = get_encryption(db, "wrong_password")
    with pytest.raises(ValueError, match="wrong password or corrupted data"):
        enc_wrong.decrypt_content(encrypted)


def test_corrupted_data(tmp_path):
    """Decrypting corrupted ciphertext raises ValueError."""
    db = tmp_path / "test.db"
    enc = get_encryption(db, "password")
    
    content = "secret message"
    encrypted = enc.encrypt_content(content)
    
    # Corrupt the ciphertext
    corrupted = encrypted[:-1] + ("X" if encrypted[-1] != "X" else "Y")
    with pytest.raises(ValueError, match="wrong password or corrupted data"):
        enc.decrypt_content(corrupted)


def test_legacy_plaintext(tmp_path):
    """Legacy plaintext rows (no Fernet prefix) are returned unchanged."""
    db = tmp_path / "test.db"
    enc = get_encryption(db, "password")
    
    legacy = "plaintext without gAAAA prefix"
    assert enc.decrypt_content(legacy) == legacy


def test_two_dbs_different_salts(tmp_path):
    """Two different DBs get different salts (read from meta table)."""
    db1 = tmp_path / "test1.db"
    db2 = tmp_path / "test2.db"
    
    enc1 = get_encryption(db1, "same_password")
    enc2 = get_encryption(db2, "same_password")
    
    # Trigger salt creation by encrypting
    enc1.encrypt_content("data1")
    enc2.encrypt_content("data2")
    
    # Read salts directly from meta table
    import sqlite3
    conn1 = sqlite3.connect(str(db1))
    conn2 = sqlite3.connect(str(db2))
    try:
        salt1 = conn1.execute("SELECT value FROM meta WHERE key = 'pbkdf2_salt'").fetchone()[0]
        salt2 = conn2.execute("SELECT value FROM meta WHERE key = 'pbkdf2_salt'").fetchone()[0]
        assert salt1 != salt2
    finally:
        conn1.close()
        conn2.close()


def test_same_password_salt_single_derivation(tmp_path, monkeypatch):
    """Same (password, salt) pair derives key only once (counter on pbkdf2_hmac)."""
    db = tmp_path / "test.db"
    enc = get_encryption(db, "password")
    
    # Counter wrapper around real pbkdf2_hmac
    call_count = {"count": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac
    
    def counting_pbkdf2(*args, **kwargs):
        call_count["count"] += 1
        return real_pbkdf2(*args, **kwargs)
    
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting_pbkdf2)
    
    # First use
    enc._ferret_instance = None  # force re-derivation
    f1 = enc._fernet_instance()
    
    # Second use (should hit cache)
    f2 = enc._fernet_instance()
    
    assert f1 is f2
    assert call_count["count"] == 1


def test_reset_caches_forces_new_derivation(tmp_path, monkeypatch):
    """reset_caches() forces a new key derivation."""
    db = tmp_path / "test.db"
    enc = get_encryption(db, "password")
    
    call_count = {"count": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac
    
    def counting_pbkdf2(*args, **kwargs):
        call_count["count"] += 1
        return real_pbkdf2(*args, **kwargs)
    
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting_pbkdf2)
    
    # First derivation
    f1 = enc._fernet_instance()
    count_after_first = call_count["count"]
    
    # Reset caches
    reset_caches()
    
    # Create NEW instance (simulating new process/connection after cache reset)
    enc2 = get_encryption(db, "password")
    
    # Second derivation (should derive again because module cache was cleared)
    f2 = enc2._fernet_instance()
    count_after_second = call_count["count"]
    
    assert f1 is not f2
    assert count_after_second == count_after_first + 1


def test_get_encryption_uses_current_store_dbpath(tmp_path, monkeypatch):
    """Changing store.DB_PATH between calls uses the new DB."""
    db1 = tmp_path / "test1.db"
    db2 = tmp_path / "test2.db"
    
    monkeypatch.setenv("LOOM_DB_PASSWORD", "pw")
    crypto.reset_caches()
    
    # First call with db1 (no explicit db_path -> reads store.DB_PATH)
    monkeypatch.setattr(store, "DB_PATH", db1)
    enc1 = get_encryption()
    assert enc1.db_path == db1
    enc1.encrypt_content("data1")
    
    # Second call with db2 (no explicit db_path -> reads store.DB_PATH)
    monkeypatch.setattr(store, "DB_PATH", db2)
    enc2 = get_encryption()
    assert enc2.db_path == db2
    enc2.encrypt_content("data2")
    
    # Verify the encryption instances are different
    assert enc1 is not enc2
    
    # Verify the Fernet instances are different (different DB paths -> different salts -> different keys)
    assert enc1._fernet_instance() is not enc2._fernet_instance()
