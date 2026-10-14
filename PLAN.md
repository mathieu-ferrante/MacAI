# MacAI — plan et décisions

## Architecture

```
MacAI.app (Swift, ~25 Mo)                    moteur Python (~35 Mo au repos)          Ollama (~20 Mo au repos)
  barre des menus, panneau ⌥Espace   HTTP     agent, outils, recherche, mémoire,  HTTP   modèles chargés à la demande
  push-to-talk (SpeechAnalyzer)    ───────►   compétences, MCP, connecteurs     ─────►   agent / vision / embeddings
  voix (AVSpeechSynthesizer)       ◄─────── événements (SSE)
  lance et surveille le moteur
```

- L'app lance le moteur comme sous-processus : les autorisations macOS (Accessibilité, Automatisation,
  Micro, Enregistrement de l'écran) accordées à **MacAI.app** couvrent le moteur (processus responsable).
- Communication sur `127.0.0.1` avec un jeton aléatoire (fichier 0600) ; aucune écoute réseau extérieure.

## Décisions

| # | Décision | Pourquoi |
|---|---|---|
| D1 | Moteur en **Python** (3.12 via uv), app native en **Swift** minimale | Toute la logique testable sur le poste de développement (Windows) ; l'app n'a que de l'interface. |
| D2 | Serveur HTTP **stdlib** (pas FastAPI) | ~30 Mo de RAM économisés au repos. |
| D3 | Client Ollama **stdlib** (urllib) | Aucune dépendance, démarrage instantané. |
| D4 | **Imports paresseux** : pypdf, docx, openpyxl, numpy, pyobjc chargés dans l'outil qui s'en sert | Repos léger. |
| D5 | Modèles par défaut : **`qwen3.5:4b` pour l'agent et la vision** (un seul modèle multimodal, sans réflexion sauf demande complexe), embeddings `qwen3-embedding:0.6b` tronqués à 256 dimensions | Recherche d'octobre 2026 (voir MODELES.md) : meilleur de sa taille en appels d'outils, vision sans échange de modèle. **Provisoire**, confirmé par `macai banc --candidats` sur le Mac. |
| D21 | Consignes système fixes, date et souvenirs en fin de message utilisateur | Le cache de préfixe d'Ollama est réutilisé d'une demande à l'autre. |
| D6 | Ollama : `KEEP_ALIVE=2m`, `MAX_LOADED_MODELS=2`, `NUM_PARALLEL=1`, `FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0`, contexte 8192 | Agent + petit modèle d'embeddings peuvent cohabiter (~3,3 Go) ; le modèle agent est déchargé explicitement avant la vision : jamais deux gros modèles. Cache de contexte réduit de moitié. |
| D7 | Recherche : SQLite **FTS5** (mots) + vecteurs float16 256 dim en fichier mappé (sens), fusion RRF | ~50 Mo de disque pour 100 000 extraits, recherche < 100 ms, pas de base vectorielle à installer. |
| D8 | Images : **Apple Vision** (OCR + étiquettes) pendant l'indexation, légende par modèle de vision en option | Rapide, natif, gratuit. |
| D9 | Voix : **SpeechAnalyzer** (macOS 26+) et **AVSpeechSynthesizer** | Natif, local, aucun modèle à télécharger, rien dans le moteur. |
| D10 | Chrome piloté par AppleScript + JavaScript (« Autoriser JavaScript depuis les Apple Events ») | Chrome 136+ interdit le débogage distant sur le profil principal ; l'utilisateur reste connecté à ses sites. |
| D11 | Client **MCP** maison (JSON-RPC sur stdio, ~200 lignes) | Pas de SDK lourd ; chaque serveur démarré à la demande, arrêté après 5 min. |
| D12 | Compétences = recettes déclaratives (suite d'appels d'outils paramétrés), fichiers JSON lisibles | Rejouables sans IA, vérifiables, modifiables à la main. |
| D13 | Mémoire chiffrée (AES-GCM, clé dans le Trousseau) | Exigence utilisateur. |
| D14 | App construite par **SwiftPM** + script d'assemblage du `.app` (pas de projet Xcode) | Reproductible, `installer.sh` fait tout. |
| D15 | Mémoire : faits pertinents trouvés **par mots-clés**, sans modèle | Aucun chargement de modèle à chaque demande ; suffisant pour quelques centaines de faits. |
| D16 | Routeur : 14 outils max, classés par proximité lexicale avec la demande (+ verbes équivalents) | Mesuré avec Ollama : prompt 4× plus court (164 s → 35 s sur CPU), meilleur choix d'outil. |
| D17 | `num_predict` = 1500 | Un modèle qui s'emballe ne bloque plus le Mac (observé en essai réel). |
| D18 | Service Ollama propre à MacAI (LaunchAgent avec ses variables) au lieu de `brew services` | Les réglages mémoire sont garantis au démarrage. |
| D19 | Arguments des modèles corrigés avant exécution (types, valeurs hors liste, dossiers inventés, noms mal recopiés) | Observé en essai réel : les petits modèles inventent des paramètres. |
| D20 | Outils propres au Mac testés avec AppleScript simulé | Seul moyen de couvrir ce code sans Mac. |

## Lots

| Lot | Contenu | État |
|---|---|---|
| L0 | Squelette, configuration, CLI, tests | `[x]` codé et testé (hors Mac) |
| L1 | Client Ollama, gestion des modèles | `[x]` codé et testé (hors Mac) |
| L2 | Agent : registre d'outils, boucle, niveaux de risque, confirmations, événements | `[x]` codé et testé (hors Mac) |
| L3 | Commandes directes (sans IA) | `[x]` codé et testé (hors Mac) |
| L4 | Outils système et applications | `[x]` codé et testé (hors Mac) |
| L5 | Outils fichiers (lire / créer / ranger) | `[x]` codé et testé (hors Mac) |
| L6 | Recherche par le sens + indexation | `[x]` codé et testé (hors Mac) |
| L7 | Chrome et web | `[x]` codé et testé (hors Mac) |
| L8 | Accessibilité (fenêtres) + vision | `[x]` codé et testé (hors Mac) |
| L9 | Organisation : Calendrier, Rappels, Notes, Mail | `[x]` codé et testé (hors Mac) |
| L10 | Client MCP + ArtCraft | `[x]` codé et testé (hors Mac) |
| L11 | Connecteur Onshape | `[x]` codé et testé (hors Mac) |
| L12 | Mémoire + compétences apprises | `[x]` codé et testé (hors Mac) |
| L13 | Serveur local (HTTP + SSE) | `[x]` codé et testé (hors Mac) |
| L14 | App Swift | `[~]` écrit, **jamais compilé** (pas de Mac) |
| L15 | Installation, vérification, banc, documentation | `[x]` codé et testé (hors Mac) |

## Validation

Le moteur est testé sur le poste de développement (Windows) avec des sorties macOS réelles et
Ollama. **Rien n'a encore tourné sur le Mac** : l'utilisateur installe à la fin et lance
`macai verifier`. Voir [A_VALIDER.md](A_VALIDER.md).
