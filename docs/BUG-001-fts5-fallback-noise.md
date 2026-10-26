# BUG-001 — Loom FTS5 fallback retourne du bruit sans score sur query hors-sujet

**Date**: 2026-10-26
**Sévérité**: Low-Medium (UX/recherche bruitée, pas de crash)
**Statut**: Open
**Composant**: `ctx_search` — fallback FTS5 ( quand le semantic backend ne retourne rien )
**Découvert par**: test 2 semantic search — query négative (hors-sujet)

## Symptôme

Quand `ctx_search(query, semantic=True)` ne trouve **aucun match sémantique**, le fallback FTS5 (SQLite full-text search) retourne **tous les chunks de la session** sans score de pertinence, même si la query est totalement hors-sujet.

Résultat : une query hors-sujet retourne du bruit comme si c'était pertinent, sans moyen de filtrer par score.

## Reproduction

```python
# Setup: stocker 2 chunks sur des sujets distincts
ctx_store(content="MITRE ATT&CK T1027 obfuscation...", label="mitre-obf", session_id="loom-test")
ctx_store(content="IcyCache proxy hash cache...", label="icycache-desc", session_id="loom-test")

# Query SEMANTIC pertinente → marche bien
ctx_search(query="how do attackers hide malware contents from analysis",
           semantic=True, session_id="loom-test")
# → mode=semantic, score=0.42, 1 résultat pertinent ✓

# Query HORS-SUJET (aucun rapport avec les chunks stockés)
ctx_search(query="weather forecast tomorrow in tokyo",
           semantic=True, session_id="loom-test")
# BUG: mode=fts, 2 résultats retournés (les 2 chunks), AUCUN score, AUCUN filtrage
```

## Preuve (sortie de test)

**Query pertinente** (`"how do attackers hide malware contents from analysis"`) :
```json
{
  "mode": "semantic",
  "results": [{"chunk_id": 57077, "score": 0.42, ...}],
  "count": 1
}
```
→ 1 résultat, score 0.42, pertinent ✓

**Query hors-sujet** (`"weather forecast tomorrow in tokyo"`) :
```json
{
  "mode": "fts",
  "results": [
    {"chunk_id": 57077, "label": "test2-mitre-obfuscation", ...},  // aucun rapport
    {"chunk_id": 57076, "label": "test1-plain-text", ...}          // aucun rapport
  ],
  "count": 2
}
```
→ 2 résultats, **aucun score**, **aucun filtrage** ❌ — tous les chunks retournés

## Cause probable (hypothèse à vérifier dans le code)

`ctx_search` implémente ce fallback :
1. Essayer semantic (FAISS HNSW) → si results vides → fallback FTS5
2. FTS5 (`WHERE content MATCH query`) sur la table des chunks
3. Le problème : FTS5 avec une query qui ne match aucun token retombe sur un `MATCH` large ou un `LIKE` qui retourne tout, **sans appliquer de score BM25/rank**

Hypothèses à vérifier :
- La requête FTS5 utilise peut-être un `OR` implicite ou un wildcard qui match tout
- Le `rank`/`bm25()` de FTS5 n'est pas sélectionné/trié dans le fallback
- Le seuil de score sémantique est trop haut → 0 résultat semantic → fallback déclenché même quand il ne devrait pas l'être

## Impact

- **Recherche bruitée** : une query qui ne trouve rien de pertinent retourne du bruit au lieu d'un résultat vide. L'utilisateur (ou l'agent qui consomme le résultat) croit qu'il y a match.
- **Pas de filtrage par score** : sans score, impossible de distinguer un vrai match d'un faux positif côté consommateur.
- **Cas concret** : un agent qui fait `ctx_search("erreur compilation rust")` sur une session qui ne contient que des logs Python récupère tous les chunks Python comme si c'était pertinent → hallucination de contexte.

## Fichiers à inspecter

- `D:/Loom/src/loom/server.py` — handler `ctx_search` (recherche semantic + fallback FTS5)
- Chercher : `fts`, `MATCH`, `bm25`, `rank`, `semantic`, `fallback`, `mode == "fts"`, `results.empty`
- Vérifier le seuil sémantique (cosine similarity cutoff) qui déclenche le fallback

## Fix suggéré (à valider ensemble)

1. **Ne pas fallback sur FTS5 si le semantic backend est dispo** — retourner un résultat vide plutôt que du bruit. Le semantic est la source de vérité pour la pertinence.
2. **Si fallback FTS5 nécessaire** (backend absent) : appliquer `bm25()` ranking + seuil minimal, et **exclure** les résultats sous le seuil plutôt que tout retourner.
3. **Toujours retourner un score** (même en mode FTS5) pour que le consommateur puisse filtrer.
4. **Test de régression** : query hors-sujet sur session non-vide → doit retourner `count: 0`, pas tous les chunks.

## Recommandation

Option 1 (ne pas fallback si semantic dispo) — simplest, préserve la qualité. Si le backend semantic est up (ce qui est le cas ici vu que test 2 pertinent a marché), le fallback FTS5 ne devrait jamais se déclencher pour une query hors-sujet. Le déclenchement actuel suggère que le seuil sémantique est trop strict (aucun chunk > seuil même pour query pertinente avec score 0.42) ou que le fallback se lance trop tôt.

À investiguer : pourquoi la query hors-sujet est passée en FTS5 alors que la query pertinente est restée en semantic ? Est-ce que le semantic retourne [] (vide) quand aucun chunk > seuil, puis le FTS5 prend le relais sans check de pertinence ?

## Contexte matériel

- Loom MCP server v18 tools, FastMCP 4.1.3, mcp 2.3.0
- Backend semantic : FAISS HNSW (embeddings)
- Fallback : SQLite FTS5
- Qdrant non utilisé par Loom (Loom a son propre FAISS)
- Dell Latitude 5420, i7-1185G7, 32 GB RAM, CPU-only
