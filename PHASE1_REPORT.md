# Loom — Phase 1 Rapport de completion

## Phase 1 — Production Hardening

### 1.1 Chiffrement DB (Dual-mode)
- **SQLCipher**: tenté, échec build C (MSVC bug pysqlcipher3 1.2.0) — pas de wheel Windows
- **Fallback Fernet** (cryptography, installé): chiffrement colonne pour chunks/anchors
- FTS5 garde le plaintext pour search
- Contrôle: `LOOM_DB_PASSWORD` env var
- Fichiers: `src/loom/crypto.py` (nouveau), `src/loom/store.py` (patché x4)
- Tests: 25/25 pass

### 1.2 Sandbox ctx_store_cmd
- Windows: Job Object (memory, CPU rate, process count limits)
- Linux: bwrap/firejail fallback
- Fails closed si sandbox indisponible
- Opt-in: `LOOM_STORE_CMD=1`
- Fichiers: `src/loom/sandbox.py` (nouveau), `src/loom/server.py` (patché)

### 1.3 MCP Auth/Transport
- FastMCP streamable-http supporté
- TLS + token auth via env vars
- Fichiers: `src/loom/server.py` (main() modifié)

### 1.4 Rate Limiting
- Token bucket par session/IP
- Config: `LOOM_RATE_LIMIT`, `LOOM_RPM`, `LOOM_BURST`
- Fichiers: `src/loom/ratelimit.py` (nouveau)

### 1.5 Audit Logging
- structlog JSONL avec request_id, session_id, tool, latency, outcome
- Fichiers: `src/loom/audit.py` (nouveau)

## Benchmark Phase 1 — 21 fichiers × 3 profils

| Profil | Fichiers | Avg saved | Avg coverage | Lossless | Avg latency |
|--------|----------|-----------|--------------|----------|-------------|
| strict | 21 | 83.3% | 67.0% | ✅ | 144.65 ms |
| balanced | 21 | 89.5% | 53.8% | ✅ | 145.01 ms |
| aggressive | 21 | 94.2% | 40.8% | ✅ | 144.68 ms |

**Tous lossless: ✅ YES**

## Tests
- 25/25 pass
- pytest: 0 failures

## Limitations
- SQLCipher non disponible sur Windows (build C échoue) — Fernet fallback actif
- Sandbox nécessite pywin32 sur Windows (pip install pywin32)
- Rate limiting et audit logging non encore intégrés dans le flux MCP (modules créés, à câbler)

## Prochaine étape
Phase 2: MCP auth/transport complet, rate-limit middleware, audit middleware, performance profiling