# 🧵 Loom — Serveur MCP de contexte portable

> **« Tisser le contexte sans couper le fil. »**
> Serveur MCP portable qui garde le contexte LLM petit en le **déplaçant** hors du prompt — jamais en le résumant.

---

## Le problème

Un agent LLM brûle ses tokens sur du contexte volumineux : logs bruts, 100 fichiers lus,
sorties d'outils. Loom prend ce volume **hors du prompt** et le range dans un tiroir local.
Le modèle garde une ancre dense et courte, plus des **IDs stables**. Quand il a besoin du
détail, il redemande à Loom — **octet pour octet**.

| Méthode | Perte |
|---------|-------|
| **Déplacer** (Loom) — « le log est dans le tiroir #7 » | **zéro** — le contenu existe, récupérable |
| Résumer (les autres) — « le log dit que le build a échoué » | perte possible — les nombres exacts disparaissent |

Loom ne déplace rien d'autre. C'est toute la thèse du projet.

---

## État actuel

**v0.1 — cœur fonctionnel.** 13 outils MCP exposés, 38 tests verts, benchmark reproductible
sur 21 fichiers de corpus. Phase 2 (transport HTTP, rate-limiting et audit câblés sur les
5 derniers outils) en cours.

---

## Architecture

```
Contexte LLM
     │
     │  ctx_store / ctx_store_file / ctx_store_cmd
     ▼
┌──────────────────────────────────────────┐
│  ANCRAGE        anchors.py + compress.py │  ← invariants extraits, ancre condensée
│  RÉDUCTION      profile.py               │  ← strict / balanced / aggressive
│  GARANTIE       verify.py                │  ← filet de sécurité : rien ne disparaît
│  CHIFFREMENT    crypto.py                │  ← Fernet (colonne) / SQLCipher (DB)
│  ASSAINISSEMENT redact.py                │  ← secrets masqués avant stockage
│  CONFIANCE      sandbox.py + ratelimit.py│  ← exécution isolée + limitation de débit
│  TRAÇABILITÉ    audit.py                 │  ← logs JSONL structurés
└──────────────────────────────────────────┘
     │
     │  SQLite + FTS5 (store.py)
     ▼
   TIROIR LOCAL  (~/.loom/loom.db)
```

### Modules

| Module | Rôle |
|--------|------|
| `server.py` | Serveur FastMCP — 13 outils, couche mince, zéro logique métier |
| `anchors.py` | Extracteur d'invariants (nombres, chemins, URLs, versions, hashes, ports, contraintes) |
| `compress.py` | Construction de l'ancre + chunks, garantie byte-identical |
| `store.py` | Tiroir SQLite + index FTS5 : chunks, ancres, invariants |
| `verify.py` | Contrôle de couverture — preuve que rien n'a été perdu |
| `profile.py` | 3 profils : `strict` (zéro-perte), `balanced`, `aggressive` (lossy opt-in) |
| `tokenizer.py` | Comptage de tokens (tiktoken `cl100k_base`, fallback heuristique) |
| `crypto.py` | Chiffrement dual-mode : SQLCipher (BD) ou Fernet (colonnes) |
| `redact.py` | Masquage des secrets (`Bearer`, `sk-`, `password=`, `secret=`, `token=`) |
| `sandbox.py` | Sandbox d'exécution (Job Object Windows / bwrap-firejail Linux), fail-closed |
| `ratelimit.py` | Token bucket par session / IP |
| `audit.py` | Logs d'audit structlog JSONL, rotation 30 jours |
| `session.py` | Sessions UUIDv7, TTL, purge, isolation |

---

## Outils MCP exposés (13)

| Outil | Rôle |
|-------|------|
| `ctx_store` | Déplace un contenu volumineux dans le tiroir → ancre + IDs + rapport d'économie |
| `ctx_store_file` | Idem, lecture **côté serveur** (le volume ne transite jamais par le prompt) |
| `ctx_store_cmd` | Idem, depuis une commande — **opt-in** (`LOOM_STORE_CMD=1`) et sandboxée |
| `ctx_get` | Récupère un chunk, octet pour octet |
| `ctx_search` | Recherche FTS5 dans les chunks stockés → `chunk_id`, `score`, `snippet` |
| `ctx_check` | Vérifie qu'aucun invariant critique n'a été perdu (le filet de sécurité) |
| `ctx_stats` | Tokens avant/après, hit rate, ratio |
| `ctx_profile` | Bascule de profil : `strict` \| `balanced` \| `aggressive` |
| `ctx_list_sessions` | Liste les sessions (incluant expirées) |
| `ctx_purge_session` | Purge une session |
| `ctx_purge_expired` | Purge les sessions expirées (TTL) |
| `ctx_vacuum` | Compacte la base SQLite |
| `ctx_health` | État de santé du tiroir |

Les opérations d'administration (`purge`, `vacuum`, `health`, `list_sessions`) sont
également accessibles en CLI : `python -m loom <cmd>`.

---

## Profils

| Profil | Comportement | Perte |
|--------|--------------|-------|
| `strict` | Ancre élargie, tous les invariants visibles | **aucune** — mode par défaut |
| `balanced` | Ancre resserrée, invariants prioritaires conservés | aucune sur le contenu stocké |
| `aggressive` | Ancre minimale | l'ancre devient lossy — **opt-in explicite, toujours reporté** |

---

## Métriques — et ce qu'elles veulent vraiment dire

C'est le point le plus important du projet : des métriques mal nommées font mentir un
benchmark. Voici le sens exact de chaque mesure.

| Métrique | Définition | Ce qu'elle ne dit pas |
|----------|------------|----------------------|
| `saved_pct` | Tokens **économisés dans l'ancre** (ce que le modèle voit en contexte) | Ce n'est pas le volume total stocké — les chunks sont sur demande |
| `coverage` | Fraction des invariants **visibles dans l'ancre** sans récupération | Une couverture de 25 % n'est pas une perte : le reste est récupérable |
| `retrievable` | Fraction du contenu **récupérable via les chunks** | Toujours `1.0` dans les mesures ci-dessous |
| `lossless` | Aucun invariant critique perdu | Vérifié par `verify.py`, pas supposé |
| `gain_net` | (tokens ancre + tokens des chunks nécessaires) / tokens d'origine | Mesuré sur 10 faits plantés par fichier |
| `identical` | *Champ hérité, non suivi depuis la v2 du bench* | Toujours `false` dans `bench_results.json` — ne pas y lire une preuve |

---

## Faisabilité prouvée — benchmark mesuré

**Corpus** : 21 fichiers réels (6,87 Mo — code review, config, incident, doc, analyse,
session, migration) × 3 tailles × 3 profils = **63 mesures**, 1 405 483 tokens traités par
profil. Tokenizer `tiktoken:cl100k_base`. Corpus reproductible via `scripts/make_dataset.py`.

### Moyennes par profil (21 fichiers)

| Profil | Tokens économisés | Couverture ancre | Latence compression | Récupération | Lossless | Invariants critiques perdus |
|--------|--------------------|------------------|---------------------|-------------|----------|------------------------------|
| `strict` | **83,33 %** | 67,04 % | 144,6 ms | 28,7 ms | ✅ | **0** |
| `balanced` | **89,55 %** | 53,84 % | 144,9 ms | 28,6 ms | ✅ | **0** |
| `aggressive` | **94,17 %** | 40,77 % | 145,1 ms | 28,0 ms | ✅ | **0** |

`retrievable = 1.0` et `critical_missing_retrievable = 0` sur **les 63 mesures**.

### Détail par taille

| Profil | Small (13,6 k tok.) | Medium (168,3 k tok.) | Large (1 223,6 k tok.) |
|--------|---------------------|-----------------------|------------------------|
| `strict` | 56,68 % · 99,34 % couv. · 4,4 ms | 94,33 % · 76,78 % couv. · 52,7 ms | 98,99 % · 24,99 % couv. · 376,7 ms |
| `balanced` | 72,51 % · 94,56 % couv. · 4,4 ms | 96,54 % · 56,29 % couv. · 53,1 ms | 99,60 % · 10,68 % couv. · 377,4 ms |
| `aggressive` | 84,29 % · 80,03 % couv. · 4,4 ms | 98,37 % · 38,16 % couv. · 52,7 ms | 99,86 % · 4,12 % couv. · 378,2 ms |

**Lecture** : la latence est dominée par l'extraction des invariants (regex), pas par la
taille de l'ancre — d'où des latences quasi identiques entre profils sur un même fichier.
Sur un fichier de 1,2 M tokens, l'ancre `strict` passe à **~25 % de couverture visible**
mais **100 % du contenu reste récupérable** : c'est exactement le compromis visé.

### Reproduire

```bash
.venv/Scripts/python.exe bench_dataset.py   # → bench_results.json (63 mesures)
```

---

## Artefacts prouvés

| Artefact | Fichier | Preuve |
|----------|---------|--------|
| Serveur MCP | `src/loom/server.py` | 13 outils, 416 lignes |
| Filet de sécurité | `src/loom/verify.py` | couverture + invariants non perdus |
| Chiffrement | `src/loom/crypto.py` | PBKDF2-HMAC-SHA256 600k itérations → Fernet (AES-128-CBC + HMAC) |
| Sandbox | `src/loom/sandbox.py` | Job Object Windows (CPU, RAM, nb processus) / bwrap Linux |
| Redaction | `src/loom/redact.py` | 5 familles de patterns, `LOOM_REDACT=1` par défaut |
| Corpus | `dataset/` | 21 fichiers, 6,87 Mo, 7 types × 3 tailles |
| Benchmark | `bench_results.json` | 63 mesures, tokenizer réel |
| Tests | `tests/` | 38 tests, 361 lignes |

---

## Suite de tests

```
$ .venv/Scripts/python.exe -m pytest -q
......................................                                  [100%]
38 passed in 7.35s
```

| Fichier | Tests | Garantie |
|---------|-------|----------|
| `test_safety_net.py` | 16 | Chunks byte-identical, `strict` non lossy, couverture en cas limites |
| `test_anchor_vectors.py` | 9 | Extraction d'invariants sur vecteurs de référence |
| `test_compress_anchor.py` | 4 | Construction ancre + chunks, budget d'invariants |
| `test_roundtrip.py` | 4 | Store → retrieve byte-identical sur un vrai tiroir SQLite |
| `test_server_integration.py` | 4 | Parcours MCP complet (store/get/check/profile) |
| `test_stdio_server.py` | 1 | Le serveur répond réellement en transport STDIO |

**3 bugs réels trouvés par les tests** (ils n'auraient jamais émergé autrement) :

1. `FastMCP 4.x` n'accepte plus `readOnlyHint=` en kwarg → contourné par `annotations=ToolAnnotations(...)`.
2. `chunk_id` typé `int` alors que les clients MCP envoient des **chaînes** → signature tolérante `str | int`.
3. Le split des chunks perdait des octets (`strip("\n")`) → cassait la promesse « byte-identical ». Corrigé, avec filet de sécurité + cas de test paramétrés.

---

## Configuration (variables d'environnement)

| Variable | Défaut | Effet |
|----------|--------|-------|
| `LOOM_DB` | `~/.loom/loom.db` | Chemin du tiroir SQLite |
| `LOOM_DB_PASSWORD` | *(vide)* | Active le chiffrement (Fernet ou SQLCipher) |
| `LOOM_REDACT` | `1` | Masquage des secrets (`0` = désactivé) |
| `LOOM_STORE_CMD` | `0` | Active `ctx_store_cmd` (sandboxé) |
| `LOOM_TTL_DAYS` | `30` | Expiration des sessions |
| `LOOM_RATE_LIMIT` | *(on)* | Token bucket par session / IP |
| `LOOM_RPM` / `LOOM_BURST` | — | Débit et burst du token bucket |
| `LOOM_LOG_LEVEL` | `INFO` | Verbosité des logs |

---

## Limites connues

- `ctx_store_cmd` n'est pas sandboxé sur toutes les plateformes : il **refuse** de s'exécuter si aucun sandbox n'est disponible (fail-closed).
- La redaction casse l'identité byte-à-byte des zones masquées — c'est un compromis assumé, et il est reporté dans le rapport.
- Pas de chiffrement de base de données complet sur Windows : SQLCipher n'a pas de wheel precompilé (échec de build C) → fallback Fernet au niveau colonne, l'index FTS5 restant en clair pour la recherche.
- `chmod 600` est ignoré sur NTFS → protéger le répertoire du tiroir manuellement.
- Le transport HTTP (streamable-http) et l'authentification par token ne sont pas encore testés de bout en bout.
- Le rate-limiting et l'audit sont câblés sur 8 des 13 outils ; 5 restent à raccorder.

---

## Méthodologie

- **Le filet de sécurité d'abord** : l'extracteur d'invariants et le vérificateur sont écrits *avant* la logique de compression. Si le vérificateur ne peut pas prouver qu'une chose a survécu, l'outil refuse de compresser.
- **Extraction déterministe** : regex et heuristiques uniquement, jamais de LLM. Un vérificateur qui dépend d'un LLM ne peut pas *prouver* une couverture.
- **Mesure honnête** : chaque rapport donne les tokens avant/après **comptés par un vrai tokenizer**, jamais estimés.
- **Audit avant action** : benchmark reproductible, corpus versionné, rapport de chaque session dans `docs/`.
- **Portable par construction** : SQLite + FTS5, aucun SDK propriétaire, aucune API payante.

---

## Ce que ce projet démontre

1. **Déplacer ≠ résumer** — la compression avec perte est un choix, pas une nécessité technique. Loom le prouve par `retrievable = 1.0` sur 63 mesures.
2. **Le budget de tokens est un problème d'architecture, pas de prompt** — la bonne réponse est un tiroir local indexé, pas un prompt plus court.
3. **Les métriques honnêtes font plus de travail que les métriques flatteuses** — nommer `coverage` « visible dans l'ancre » et non « couvert » évite un benchmark qui ment.
4. **Un projet IA peut être 100 % CPU et 100 % local** — Python + SQLite, aucun GPU, aucune API payante.

---

## Auteur

**Malik** — étudiant DEP Soutien Informatique, autodidacte
Spécialisation : Sysadmin + Cyber + AI + Cloud

---

> *« Le contexte est un tirage, pas une condensation. »* — Loom tire le fil ; il ne le coupe pas.
