# NOTE PROJET — Loom

> Contexte technique de la machine, dépendances, et décisions.
> Date : 2026-10-21 · Hôte : Windows 11 · Matériel : Latitude 5420, 32 Go RAM, Iris Xe (0 VRAM) → **tout local = CPU only**

---

## 1. Environnement Python de la machine (inventaire vérifié)

| Version | Chemin | Rôle | Paquets |
|---|---|---|---|
| **3.12.10** | `C:\Users\Tech\AppData\Local\Programs\Python\Python312\python.exe` | **Principal** (defaut `py`) | **426** |
| **3.13** | — | *inexistant* | 0 |
| **3.14.8** | `C:\Python314\python.exe` | Secondaire (ML/quant) | 65 |
| 3.11.15 | `...\uv\python\cpython-3.11.15-...` (Astral) | via uv | — |

⚠️ `pip` global pointe vers **3.12**, `python3` vers **3.14** → mismatch classique. Toujours passer par `py -3.12` ou le venv.

### 3.12 — laMine (427 paquets)

**Ce qui est directement utile à Loom :**

| Paquet | Version | Usage Loom |
|---|---|---|
| `mcp` + `mcp-types` | 2.3.0 | SDK MCP officiel (⚠️ ≠ version 1.x de l'API Python) |
| `chromadb` | 1.5.9 | store vectoriel optionnel |
| `rank-bm25` | 0.2.2 | **recherche lexicale** — déjà présente, on la réutilise |
| `sentence-transformers` | 6.1.0 | embeddings locaux CPU |
| `transformers` | 5.20.2 | reranking local |
| `tiktoken` | 0.14.0 | **comptage de tokens** — identique à celui de l'env Loom |
| `pydantic` | 2.14.1 | schémas outils MCP |
| `httpx` / `aiohttp` | 0.28.1 / 3.14.5 | client HTTP (mode streamable) |
| `duckdb` | 1.5.6 | alternative à SQLite pour l'analyse |
| `orjson` | 3.13.0 | sérialisation rapide |
| `tree-sitter-json` | 0.24.8 | parsing JSON robuste (utile : invariants dans du JSON) |
| `psutil` | 7.2.2 | métriques (RAM, CPU) |
| `anthropic` / `openai` | 1.15.0 / 3.35.1 | clients API pour le mode SDK/middleware |
| `langchain` / `langgraph` | 1.4.6 / 1.2.16 | **intégration possible en middleware** |
| `codegraph-mcp-server` | 0.8.0 | serveur MCP déjà installé → modèle de packaging à copier |

**Écosystème ML (3.12) :** `torch 2.14.1+cpu` (CUDA=False), `numpy 2.5.4`, `pandas 3.0.6`, `scikit-learn 1.9.1`, `pyarrow 26.0.0`, `sqlalchemy 2.1.5`, `redis 8.1.0`, `onnxruntime 1.31.0`.

### 3.14 — ML/quant (65 paquets)

`torch 2.13.0`, `transformers 5.18.0`, `accelerate 1.15.0`, `peft 0.21.2`, `trl 1.16.0`, `bitsandbytes 0.50.2`, `datasets 5.1.0`, `evaluate 0.40.6`, `huggingface_hub 1.33.0`, `sentencepiece`, `safetensors`.
→ C'est l'env de **fine-tuning**, pas celui de Loom.

### Node / npm

`node v26.8.1`, `npm 12.2.0`. Serveurs MCP déjà installés en global npm :
`mcp-local-rag`, `mcp-server-memory`, `mcp-server-filesystem`, `context7-mcp`, `playwright-mcp`, `codex`, `clawdhub`.
→ Preuve que le format npm (`npx <pkg>`) est la voie d'adoption la plus réaliste pour les non-Python.

---

## 2. Services locaux DÉJÀ actifs (à réutiliser, pas à recoder)

| Service | Endpoint | Détail |
|---|---|---|
| **LM Studio** | `http://localhost:1234` | Modèles : `text-embedding-qwen3-embedding-4b`, `step-3.7-flash`, `granite-4.2-8b`… **L'API embeddings fonctionne** (vérifié) |
| **Qdrant** | `http://127.0.0.1:6333` | Collection `hermes_qwen3_memory` |
| **Chroma** | `C:\AI\EmbeddingDB\data` | `chromadb.PersistentClient` |
| **EmbeddingsDB venv** | `C:\AI\EmbeddingDB\.venv` | `chromadb 1.5.9`, `mcp 1.30.0`, `qdrant-client 1.19.1`, `rank-bm25` |
| **MCP qwen-chroma** | config Hermes | `C:\AI\EmbeddingDB\hermes_qdrant_mcp.py`, `hybrid_search`, BM25 natif |

### Modèles locaux en cache HF (`~/.cache/huggingface/hub`)

- `unsloth/bge-small-en-v1.5` → embeddings **CPU**, léger, ideal pour Loom
- `nomic-ai/nomic-embed-text-v1.5` → embeddings longs (8192 ctx)
- `cross-encoder/ms-marco-MiniLM-L-12-v2` → **reranker** (pertinence) — parfait pour re-ranker les chunks récupérés
- `sentence-transformers/all-MiniLM-L6-v2`, `Qwen3-0.6B`, `Qwen3-1.7B`, `gemma-3-1b-it`

→ **Zéro dollar** : embeddings + rerank locaux sont déjà là.

---

## 3. Décisions d'isolation

**Principe : Loom ne touche jamais les globales.**

| Element | Choix |
|---|---|
| Env Loom | `D:\Loom\.venv` (uv, Python **3.12.10**) |
| Commande | `uv venv --python 3.12 .venv` puis `uv pip install --python .venv/Scripts/python.exe -e ".[dev]"` |
| Store par défaut | `~/.loom/loom.db` (Surchargeable via `LOOM_DB`) |
| Modèles | optionnels, chargé à la demande depuis le cache HF (jamais téléchargé au runtime) |

Contenu réel de `.venv` installé : `fastmcp`, `mcp`, `tiktoken 0.14.0`, `pytest 9.1.1`, `pytest-asyncio`, `ruff 0.17.1`, `uvicorn`, `starlette`, `sse-starlette`, `websockets`, `pydantic 2.x`, `httpx`.

### Commandes utiles

```bash
cd /d/Loom
uv run pytest -q                      # tests
uv run python scripts/smoke.py        # smoke test
.venv/Scripts/python.exe -m pytest -q # sans passer par uv
```

---

## 4. Ce qui est déjà fait vs reste à faire

**Fait et vérifié :**
- [x] Squelette complet du repo (20 fichiers)
- [x] `anchors.py` — extraction d'invariants (nombres, chemins, URLs, versions, contraintes)
- [x] `compress.py` — construction d'anchor + chunks **byte-identiques**
- [x] `store.py` — tiroir SQLite + FTS5 + persistance des anchors
- [x] `verify.py` — contrôle de couverture
- [x] `server.py` — 5 outils MCP exposés (FastMCP 4.1.3)
- [x] Env isolé installé (`fastmcp 4.1.3`, `mcp 2.3.0`, `tiktoken 0.14.0`)
- [x] **25 tests passent** (dont un test stdio réel qui spawn le serveur)
- [x] Smoke test `coverage = 1.0`

**3 bugs réels trouvés et corrigés par les tests** (ils ne seraient jamais apparus autrement) :
1. `FastMCP 4.x` n'accepte plus `readOnlyHint=` en kwarg → passe par `annotations=ToolAnnotations(...)` (champs snake_case).
2. `chunk_id` typé `int` mais les clients MCP envoient des **chaînes** → signature tolérante `str | int`.
3. **Le split des chunks perdait des octets** (le `strip("\n")`) → ça cassait la promesse « byte-identical ». Corrigé, avec un filet de sécurité + 8 cas de test paramétrés.

**Reste :**
- [ ] Mode HTTP streamable
- [ ] Export : `uv build` → PyPI ; wrapper npm `npx loom-mcp`
- [ ] Rétrieval hybride BM25 (`rank-bm25`) + embeddings locaux (`bge-small`) + reranker (`ms-marco-MiniLM`)
- [ ] `ctx_search` (recherche FTS exposed comme outil)
- [ ] Harness d'évaluation (tokens vs qualité)

---

## 5. Notes de conception tirées de l'inventaire

1. **`rank-bm25` + `cross-encoder` sont déjà installés** → le plan « retrieval hybride » ne demande aucune installation et reste 100 % gratuit/local.
2. **LM Studio sert déjà des embeddings** → on peut tester le semantic layer immédiatement, sans téléchargement.
3. **`mcp 2.3.0` en global vs `mcp 1.x` dans l'env EmbeddingDB vs `mcp` de l'env Loom** → ne pas mixer les APIs ; le code Loom doit cibler l'API de l'env `.venv` uniquement.
4. **`codegraph-mcp-server`** → modèle de packaging MCP déjà présent en Python : s'inspirer de son `pyproject.toml` pour le build PyPI.
5. **`mcp-local-rag` (npm)** → c'est le concurrent le plus proche en local. L differentiation de Loom reste **la preuve de zéro-perte** (le RAG local ne garantit rien) + le fait qu'on **déplace** au lieu de **ré-embedder**.
6. **`starlette-compress`** (3.12) → utile seulement pour le transport HTTP, pas pour le contexte.

---

## 6. Export

```bash
cd /d/Loom
uv build                      # → dist/loom_mcp-0.1.0-py3-none-any.whl + sdist
```

Publication : PyPI (`uv publish` ou `twine`) + npm wrapper (`npx loom-mcp` → appelle le wheel Python).
À faire **après** : tests verts, README à jour, licence, `py.typed`, et un `smoke` d'installation propre dans un venv vierge (vérifier qu'aucune dep globale n'est requise).
