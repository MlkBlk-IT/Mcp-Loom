# Loom — l'histoire du projet, en langage humain

> Mis à jour le 2026-10-21 (soir). Ce document décrit ce qui a été fait, ce qui est prouvé, et ce qui ne l'est pas encore.
> Il ne contient aucun claim de performance : la mesure officielle (go/no-go) n'a pas encore été faite.

## C'est quoi, Loom ?

Quand on travaille avec une IA, on lui colle souvent de gros documents (logs, rapports, code). Ça coûte cher en tokens et ça sature le contexte.

Loom est un serveur MCP qui fait autre chose :

1. Le gros document est rangé **hors du prompt**, dans un « tiroir » (drawer) SQLite avec recherche plein texte (FTS5).
2. Dans le prompt, on ne met qu'une **ancre** : un résumé dense des éléments clés.
3. Quand l'IA a besoin d'un détail, elle le **récupère** via des outils (`ctx_get`, `ctx_search`).
4. On peut **prouver** que rien n'a été perdu : le document récupéré est identique, octet pour octet, à l'original.

La différence avec les concurrents : eux **résument** (donc perdent de l'info). Loom est **lossless** et vérifiable.

Cible réelle : les IA cloud. LM Studio sur CPU sert seulement de banc d'essai.

## Ce qui a été fait

### Réparation et solidification du code
- Sauvegarde complète avant toute modification.
- `anchors.py` et `compress.py` réparés.
- `crypto.py` v3 : dérivation de clé PBKDF2-HMAC-SHA256 (600 000 itérations). Ce fichier est **gelé** : on n'y touche plus.
- `store.py` et `session.py` réécrits : écriture en une seule transaction, UPSERT, expiration (TTL), purge de l'index FTS, échappement des requêtes FTS.
- Vrais tests, sans mocks : conftest, crypto, isolation, store/session.

### Sécurité et fiabilité des fichiers
- `ctx_store_file` lit maintenant en binaire avec décodage UTF-8 strict (limite configurable `LOOM_MAX_FILE_MB`, dossiers autorisés via `LOOM_ALLOWED_DIRS`).
- Nouvel outil `ctx_verify` : revérifie qu'un document stocké est identique à sa source (SHA-256).
- Limiteur de débit (`ratelimit.py`).
- **Bug trouvé et corrigé** : l'ancienne lecture de fichier convertissait les fins de ligne Windows (CRLF → LF). Résultat : des octets perdus, alors que l'outil de contrôle affichait « lossless: true ». Un faux positif sérieux, maintenant corrigé. Le roundtrip est byte-identique sur les 3 tailles testées.

### Bug de recherche trouvé grâce au benchmark (corrigé)
- Symptôme : l'agent cherchait « billing outage ticket id » et Loom répondait « 0 résultat », alors que le fait existait dans la base.
- Cause : les mots de la requête étaient tous obligatoires (AND strict). Un seul mot absent du texte (« id ») faisait tout rejeter.
- Correctif : si la recherche stricte ne trouve rien, on relance en OR, classé par pertinence (bm25). Le comportement normal est inchangé quand la recherche stricte réussit.
- 4 tests ajoutés. Prouvé en conditions réelles : la question concernée passe de ratée à réussie.
- Limite connue : l'OR est plus bruyant, et on n'a pas encore mesuré sa précision sur de gros documents.

### Décisions verrouillées
- Si le chiffrement (Fernet) est actif, la recherche plein texte est désactivée (rien n'est indexé en clair).
- 14 outils exposés (13 + `ctx_verify`).
- « Lossless » = zéro redaction. Le mode « aggressive » ne fait que raccourcir l'ancre.
- Pas de packaging (PyPI/npm) avant le verdict go/no-go.

## Ce qui est prouvé (sorties brutes)

- Suite de tests : **72 passed**, 0 failed (68 avant le correctif de recherche, +4).
- Fichiers sources vérifiés par SHA-256 : inchangés entre les vérifications (sauf `store.py`, modifié volontairement).
- Smoke de compression de l'ancre (client MCP, fichiers de test) :

| Taille | Tokens avant | Ancre | Chunks |
|---|---|---|---|
| small (~11 Ko) | 2666 | 1015 | 6 |
| medium (~73 Ko) | 17240 | 1500 | 33 |
| large (~1,2 Mo) | 283935 | 1887 | 524 |

**Attention : ces chiffres mesurent seulement la taille de l'ancre.** Ils ne comptent ni le coût des outils, ni la récupération, ni la tâche. Ils ne prouvent pas d'économie réelle.

## Le test qui compte : go/no-go (figé)

Le critère a été écrit et figé **avant** le benchmark (`_repair/GO_NOGO.md`, non modifiable) :

> Même taux de succès avec **au moins 35 % de tokens totaux (in + out) en moins**, retrieval tax et tool tax inclus, N ≥ 5 par bras, médiane.

Si ce n'est pas atteint : pivot ou arrêt. C'est une règle qu'on s'est imposée pour ne pas se mentir.

## Smokes sur LM Studio (pas le verdict)

Protocole : document small (~2,8k tokens), 5 questions de type « aiguille » (faits plantés, seed fixe), contexte 24k, CPU. Deux bras : baseline (document entier dans le prompt) contre Loom (ancre + 14 outils). Succès = la valeur exacte est dans la réponse.

| Run | Baseline | Loom | Appels d'outils (Loom) |
|---|---|---|---|
| qwen3.8-4b, sans raisonnement | 5/5 | 1/5 | 0 sur 5 questions |
| qwen3.8-4b, avec raisonnement | 5/5 | 1/5 | 4 questions à 0 ; une question a bouclé 6 fois (19 539 tokens) et échoué |
| gemma-4-e4b, avant correctif de recherche | 5/5 | 2/5 | 1 question |
| gemma-4-e4b, correctif + prompt durci (froid, puis chaud) | 5/5 | 2/5 | 1 question |

Ce qu'on en retient, honnêtement :
- **Loom ne bat pas la baseline sur small.** Chaque appel Loom embarque environ 2,5k tokens fixes (ancre + schémas des outils). Sur un document de 2,8k tokens, il ne peut pas gagner. Sur la seule question qui a demandé une récupération, Loom a coûté environ +60 % de tokens (5883 contre 3686).
- **Les petits modèles n'appellent pas l'outil.** Dans 3 questions sur 5, le modèle répond depuis l'ancre, ou dit qu'il n'a pas l'info, sans jamais chercher. Un prompt plus strict (« tu DOIS appeler l'outil ») n'a eu aucun effet sur gemma.
- **Risque de réponse fausse affirmée.** Sur une question, le modèle a répondu avec assurance deux codes d'erreur issus de l'ancre, alors que la bonne valeur était à une recherche de distance. C'est exactement le risque que Loom doit mesurer : une ancre dense qui induit en erreur.
- **Une question réussie sans outil** parce que l'ancre contenait déjà la réponse : ça ne teste pas la récupération.
- **Les chiffres de « réduction » affichés par le script (11,4 %, 31 %, -14 %) portent sur 1 ou 2 questions** : sans valeur statistique, à ne pas citer.
- **Un peu de bruit d'une exécution à l'autre** (même seed, longueur de réponse légèrement différente) : raison de plus pour exiger une médiane sur N ≥ 5.
- **Le cache de préfixe** change le temps (125 s à froid contre 1,4 s à chaud pour 3,7k tokens), pas le nombre de tokens.
- Le bras Loom du bench a été modifié en cours de route (prompt durci) : les runs ne sont pas tous à prompt égal. C'est noté ici pour l'honnêteté de la comparaison.

Ce sont des smokes : petits modèles (~4B), CPU, tâche aiguille. Ce n'est pas le go/no-go figé.

## Incident documenté

Le dossier `~\.loom` (utilisé hors tests) doit rester en lecture seule. Entre deux vérifications, ses fichiers ont changé (écriture à 19:43). Ni la suite de tests (deux runs) ni les scripts de vérification ne l'ont touché (vérifié par hash). Cause **supposée**, non prouvée : un run de l'agent de code (Hermes) sans isolation. Règle adoptée : tout run pointe `LOOM_DB` et `LOOM_AUDIT_DIR` vers un dossier de test.

Depuis, la suite de tests et le benchmark LM Studio ont été vérifiés : `~\.loom` inchangé.

## Méthode de travail

- Un « worker » (agent de code) écrit le code, un « brain » vérifie. Aucun rapport du worker n'est cru sans sortie brute (il a déjà rapporté de faux succès).
- Chaque affirmation est étiquetée : SOURCÉ, INFÉRÉ, HYPOTHÈSE ou UNVERIFIED.
- Pas de chiffre inventé, pas de claim de performance avant mesure.
- Le script de bench affiche maintenant, pour chaque appel : question, valeur attendue, réponse brute, appels d'outils, tokens, durée. Il accepte `--max-tokens` pour les modèles avec raisonnement.

## Problèmes connus

- L'ancre est peu informative (beaucoup de nombres nus). La corriger exige de toucher `anchors.py`/`compress.py`, verrouillés : décision requise.
- Le modèle n'appelle pas toujours l'outil de récupération. Piste : un modèle plus gros, ou forcer le premier appel d'outil (support à vérifier).
- Documentation périmée : `README.md` (anciens chiffres, 13 outils, « 38 tests »), `docs/NOTE-PROJET.md`, `_repair/PROGRESS.md`, et les anciens rapports. À corriger avec des ERRATA datés.
- Packaging (`mcp.example.json`, `dist/`) inutilisable : paquet non publié, ancien code.

## Ce qui reste à faire

1. Même test small avec un modèle plus gros qui supporte vraiment le tool calling, avec et sans raisonnement (budget limité).
2. Tests medium et large avec **plusieurs** appels d'outils par question.
3. Phases de code restantes : `verify.py`, `redact.py` (masquage de secrets), `audit.py` propre, tests de déterminisme de l'ancre, `sandbox.py`.
4. Mesure finale : baseline contre Loom, avec un vrai modèle cloud, puis verdict GO/NO-GO à 35 %.
5. Mise à jour de la documentation, puis commit/push (seulement sur ordre explicite).

## Limites à garder en tête

- Seulement deux petits modèles testés, sur CPU (iGPU Intel Iris Xe, 32 Go de RAM).
- Tâche « aiguille » uniquement : ne représente pas tous les usages.
- Aucune économie de tokens n'est démontrée à ce jour. Le projet est en phase de mesure.
