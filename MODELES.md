# Choix des modèles — MacBook Air M2 8 Go

Recherche d'octobre 2026. Les chiffres viennent de sources publiques (souvent déclarés par les éditeurs ou
estimés) : **à confirmer sur ton Mac avec `macai banc --candidats`**.

## Décision

| Rôle | Modèle | Taille | Pourquoi |
|---|---|---|---|
| Agent **et** vision | **`qwen3.5:4b`** | 3,3 Go (Q4_K_M) | Meilleur de sa taille en appels d'outils ; multimodal natif (texte + image), donc **un seul modèle** pour agir et regarder l'écran |
| Embeddings (recherche) | **`qwen3-embedding:0.6b`** | ~640 Mo | Meilleur score multilingue sous 1 milliard de paramètres ; dimensions réductibles (256 utilisées) |

Total à télécharger : ~4 Go (contre ~5 Go avant, pour trois modèles).

## Pourquoi un seul modèle multimodal change tout sur 8 Go

Avant : agent `qwen3:4b` + vision `qwen3-vl:2b`. Pour regarder l'écran, il fallait décharger l'agent (2,5 Go),
charger la vision (1,9 Go), puis recharger l'agent : quelques secondes perdues et des pics de mémoire à chaque fois.
Avec `qwen3.5:4b`, la vision est faite par le modèle déjà chargé : rien à échanger, mémoire stable.

## Comparatif des candidats (agent)

| Modèle | Taille | Appels d'outils | Vision | Vitesse estimée sur M2 8 Go | Verdict |
|---|---|---|---|---|---|
| **qwen3.5:4b** | 3,3 Go | 97,5 % sur un test indépendant de 40 cas (1er sur 13 modèles) ; TAU2 79,9 | oui | ~20-35 jetons/s | **Défaut** |
| qwen3.5:2b | ~1,9 Go | moins fiable (la fiabilité chute sous ~4 milliards de paramètres) | oui | plus rapide | Repli si la mémoire manque |
| nemotron-nano 4B | ~3 Go | 95 % sur le même test indépendant | non | ~20-30 jetons/s | Bon second, sans vision |
| phi4-mini (3,8B) | ~2,5 Go | solide, jetons d'outils entraînés | non | ~25-35 jetons/s | Choix prudent sans vision |
| gemma4:e4b | ~3,5 Go | TAU2 42,2 (nettement derrière Qwen3.5 4B) | oui | ~25-45 jetons/s | Rapide, mais moins bon agent |
| qwen3:4b | ~2,5 Go | bon | non | ~25-35 jetons/s | Génération précédente |

Aucune source ne mesure ces modèles **en français** sur des appels d'outils : c'est précisément ce que fait
`macai banc` (12 demandes réelles en français, outils simulés, rien n'est exécuté).

## Comparatif des candidats (embeddings)

| Modèle | Taille | Multilingue (MTEB) | Remarque |
|---|---|---|---|
| **qwen3-embedding:0.6b** | ~640 Mo | 64,3 | Défaut |
| embeddinggemma (300M) | ~620 Mo | 61,2 | Plus léger, contexte 2 K seulement |
| bge-m3 (567M) | ~1,2 Go | élevé | Plus lourd ; utile pour la recherche hybride |

`macai banc --candidats` les compare aussi sur 10 recherches en français (rappel@1).

## Optimisations appliquées

| Réglage | Effet |
|---|---|
| Quantification Q4_K_M (par défaut d'Ollama) | Le meilleur compromis qualité/mémoire ; l'8-bit (~5 Go) ne tient pas confortablement en 8 Go |
| `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` | Cache de contexte divisé par deux, sans perte notable |
| Contexte 8 192 jetons | Suffisant (consignes + 14 outils ≈ 3-4 K) ; plus grand = plus de mémoire |
| `OLLAMA_KEEP_ALIVE=2m` | Le modèle repart 2 min après la dernière demande |
| `OLLAMA_MAX_LOADED_MODELS=2`, `NUM_PARALLEL=1` | Agent + embeddings peuvent cohabiter (~4 Go), un seul calcul à la fois |
| Réflexion (« thinking ») désactivée sauf demande complexe | Réponses bien plus rapides ; activée pour « analyse », « compare », « planifie »… |
| Consignes système **identiques** d'une demande à l'autre (date et souvenirs en fin de message) | Ollama réutilise le calcul du début du prompt : réponse plus rapide |
| 14 outils au plus, triés par proximité avec la demande | Prompt 4× plus court mesuré (164 s → 35 s sur le PC de développement) |
| `num_predict` = 1 500 | Un modèle qui s'emballe ne bloque jamais le Mac |
| Commandes directes sans IA | « ouvre Safari », « volume à 30 »… en quelques millisecondes |

### Moteur MLX d'Ollama

Depuis 2026, Ollama utilise **MLX** (le moteur d'Apple) sur Apple Silicon, avec des gains annoncés de +50 à +90 %
en génération. D'après les sources, il a d'abord été réservé aux Mac de 32 Go et plus, puis activé par défaut
pour les modèles compatibles (versions 0.30 à 0.40 selon les sources, à vérifier). `installer.sh` installe la
dernière version d'Ollama via Homebrew : si MLX s'applique à ton Mac, il est utilisé automatiquement. Aucun
réglage à faire. `macai banc` affiche la vitesse réelle obtenue.

## Sources

- Test indépendant de 13 modèles locaux en appels d'outils (mars 2026) : https://www.jdhodges.com/blog/local-llms-on-tool-calling-2026-pt1-local-lm/
- Fiabilité des appels d'outils par modèle (BFCL 2026) : https://d-central.tech/local-llm-agent-capability/
- Meilleurs modèles locaux pour agents : https://vdf.ai/blog/best-local-llm-for-agents-tool-calling/
- Fiche Ollama `qwen3.5:4b` (vision, outils, réflexion, 3,3 Go) : https://ollama.com/library/qwen3.5:4b
- Qwen 3.5 multimodal natif à toutes les tailles : https://computingforgeeks.com/ollama-models-cheat-sheet/
- Gemma 4 contre Qwen 3.5 : https://gemma4all.com/blog/gemma-4-vs-qwen-3-5-benchmarks et https://ai.google.dev/gemma/docs/core/model_card_4
- Vitesses estimées sur MacBook Air : https://insiderllm.com/guides/best-local-llms-mac-2026/ , https://modelfit.io/macbook-air/ , https://llmcheck.net/guides/best-local-llm-macbook-air/
- Modèles de vision locaux : https://tinyweights.dev/posts/best-local-vision-language-models-2026/
- Embeddings Ollama (MTEB) : https://www.morphllm.com/ollama-embedding-models
- Ollama et MLX : https://yage.ai/share/mlx-apple-silicon-en-20260331.html , https://runaihome.com/blog/ollama-v030-mlx-stable-upgrade-2026/ , https://releasebot.io/updates/ollama
