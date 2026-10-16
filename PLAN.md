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
| D5 | Modèles par défaut : **`qwen3.5:4b-q4_K_M` pour l'agent et la vision** (un seul modèle multimodal, sans réflexion sauf demande complexe), embeddings `qwen3-embedding:0.6b` tronqués à 256 dimensions | Recherche d'octobre 2026 (voir MODELES.md) : meilleur de sa taille en appels d'outils, vision sans échange de modèle. Variante q4_K_M imposée : le tag par défaut donne sur Mac une version MLX de 4 Go qui sature la mémoire graphique (mesuré). |
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
| D22 | Embeddings avec contexte 512 ; reprise automatique (déchargement + nouvel essai) si Ollama signale une saturation mémoire | Mesuré : 2,2 Go → 1 Go ; agent + embeddings = 4,2 Go, sous la limite graphique (~5,3 Go) d'un 8 Go. |
| D23 | ArtCraft via ses `*-cli mcp` officiels (signés, notarisés) dans `~/.local/bin`, dossiers autorisés = dossier personnel, LightCraft `--compact` | Les applis n'exposent pas de MCP elles-mêmes ; 326 → 17 outils pour LightCraft. |
| D24 | Outils MCP : jusqu'à 9 par logiciel, classés par proximité (verbes français traduits en anglais), schémas compactés | Mesuré : un petit modèle ne trouvait pas `doc_open` parmi 25 outils pris dans l'ordre ; prompt 3× plus court. |
| D25 | Indexation : code des projets logiciels ignoré, dossiers personnels d'abord | Mesuré : 176 fichiers de code sur 240 au premier essai. |
| D26 | Outils « tout-en-un » pour les tâches d'interface fréquentes : `demander_a_claude`, `ecrire_et_envoyer`, `ouvrir_reglage` | Mesuré : le modèle 4B enchaîne mal 6 clics (mode, nouvelle conversation, saisie, envoi) ; un seul appel déterministe est fiable. Claude (IA distante) n'est utilisé que si l'utilisateur le demande. |
| D27 | Risque selon le contexte : taper/valider dans un Terminal = SENSIBLE ; valider dans une messagerie = SENSIBLE ; clic sur Envoyer/Supprimer/Publier = SENSIBLE | Relecture de sécurité : ces chemins contournaient les confirmations. |
| D28 | Commande Terminal en lecture seule exécutée **sans shell** (liste blanche, sous-commandes contrôlées), sinon zsh -f après confirmation | `ls\nid`, `cat <(id)`, `diskutil eraseVolume` passaient sans confirmation. |
| D29 | Écriture interdite dans les fichiers cachés, ~/Library (sauf iCloud Drive), les réglages et le code de MacAI ; lecture interdite des secrets (comparaison sans casse, liens résolus) | Persistance (~/.zshenv, LaunchAgents) et désactivation des garde-fous possibles depuis une page piégée. |
| D30 | Interdiction absolue (dans le code) d'acheter, payer, demander des crédits ou une utilisation supplémentaire, et de mémoriser des secrets | Exigence de Mathieu. |
| D31 | Chaque outil tourne dans un fil surveillé avec délai maximal | Vu en essai : une fenêtre d'autorisation macOS sans réponse bloquait le moteur indéfiniment. |
| D32 | Question explicative (« comment… », « pourquoi… ») : outils de lecture seulement | Vu en essai : « comment envoyer un mail ? » préparait des brouillons et lisait les mails. |
| D33 | Texte sélectionné (⌥⇧T) et zone de l'écran (⌥⇧S) traités sans boucle d'agent : une consigne fixe par action | Un petit modèle corrige, traduit, résume très bien en un appel ; la sélection est lue pendant que l'appli de l'utilisateur est encore devant. |
| D34 | Fn maintenue = dictée dans l'application au premier plan (réglable) ; ⌥⇧Espace maintenus = parler à MacAI | Dictée locale (SpeechAnalyzer), aucun modèle chargé, usage quotidien. |
| D35 | Agenda et rappels lus par EventKit (récurrences comprises), repli AppleScript ; création encore par AppleScript | Les réunions récurrentes manquaient ; création EventKit prête dans mac/agenda.py. |
| D36 | Annuler : pile des opérations inverses (50 dernières) pour déplacer, renommer, copier, écrire, ranger, Corbeille | Confiance : toute action sur les fichiers est réversible. |
| D37 | Tâches planifiées exécutées sans personne : confirmations refusées d'office, autonomie au plus « équilibre », envoi/suppression/achat refusés à la création | Rien de sensible ne peut se faire en l'absence de l'utilisateur. |
| D38 | Questions factuelles : rechercher_et_lire (3 pages lues, passages choisis sans modèle, sources citées) ; adresses locales/privées refusées | Vu en essai : horaires inventés ; et une page piégée ne doit pas interroger le Mac ou le réseau local. |
| D39 | `macai banc --scenarios` : 50 demandes réelles dans le vrai moteur, outils simulés, comparaison avec le passage précédent | Mesurer chaque changement et repérer les régressions. |

## Lots

| Lot | Contenu | État |
|---|---|---|
| L0 | Squelette, configuration, CLI, tests | `[x]` codé, testé, validé sur le Mac |
| L1 | Client Ollama, gestion des modèles | `[x]` codé, testé, validé sur le Mac |
| L2 | Agent : registre d'outils, boucle, niveaux de risque, confirmations, événements | `[x]` codé, testé, validé sur le Mac |
| L3 | Commandes directes (sans IA) | `[x]` codé, testé, validé sur le Mac |
| L4 | Outils système et applications | `[x]` codé, testé, validé sur le Mac |
| L5 | Outils fichiers (lire / créer / ranger) | `[x]` codé, testé, validé sur le Mac |
| L6 | Recherche par le sens + indexation | `[x]` codé, testé, validé sur le Mac |
| L7 | Chrome et web | `[x]` codé, testé, validé sur le Mac |
| L8 | Accessibilité (fenêtres) + vision | `[x]` codé, testé, validé sur le Mac |
| L9 | Organisation : Calendrier, Rappels, Notes, Mail | `[x]` codé, testé, validé sur le Mac |
| L10 | Client MCP + ArtCraft | `[x]` codé, testé, validé sur le Mac |
| L11 | Connecteur Onshape | `[x]` codé, testé, validé sur le Mac |
| L12 | Mémoire + compétences apprises | `[x]` codé, testé, validé sur le Mac |
| L13 | Serveur local (HTTP + SSE) | `[x]` codé, testé, validé sur le Mac |
| L14 | App Swift | `[x]` compilée et installée sur le Mac ; voix et touche Fn à essayer (autorisations) |
| L15 | Installation, vérification, banc, documentation | `[x]` codé, testé, validé sur le Mac |

## Validation

Installé et testé sur le MacBook Air (15/10/2026). Vérification complète le même jour : trois relectures (sécurité,
bugs du moteur, app Swift) puis corrections, 121 tests automatiques, et essais réels avec le modèle local
(documents, fichiers, mémoire, recherche, injection dans un fichier, commandes dangereuses, achats). Restent à
essayer avec Mathieu les scénarios d'interface (voir [A_VALIDER.md](A_VALIDER.md)).
