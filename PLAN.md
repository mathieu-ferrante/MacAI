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
| D40 | Plan à valider seulement si la demande touche à l'important (envoyer à quelqu'un, supprimer, ranger, installer, acheter…) ; ouvrir une appli, y taper, cliquer, interroger Claude/ChatGPT : on agit directement. « Envoyer » une question à une IA n'est plus sensible (supprimer y reste sensible) | Mathieu : accepter chaque étape pour « ouvre Claude et demande-lui… » faisait perdre l'intérêt de MacAI. Les étapes sensibles gardent leur confirmation. |
| D41 | **Bilan honnête** : la réponse finale d'une demande d'action est confrontée à la trace des outils ; si rien n'a eu d'effet, elle est remplacée par la raison réelle, et une étape restée en échec est signalée | Journal du Mac (oct.-nov.) : « j'ai déplacé le fichier » après deux échecs, « les services ont été fermés » alors que rien n'était ouvert. |
| D42 | `Resultat.sans_effet` : un outil qui réussit sans rien changer (appli déjà fermée) ne compte pas comme une action | Même cause : faux succès annoncés. |
| D43 | `ouvrir_application` : plus de « Vouliez-vous… ? » (le modèle ouvrait FilmCraft pour Minecraft) ; « Téléchargements », « Documents »… ouvrent le dossier ; Finder signalé comme non fermable | Journal du Mac du 23/10. |
| D44 | Plan rédigé avec les capacités réelles (descriptions des outils retenus, sans leur nom) ; étapes réduites à un nom d'outil écartées | Plans hors-sol (« cliquer sur Quitter dans la barre des applications ») suivis à la lettre. |
| D45 | Stop coupe la connexion à Ollama (socket fermée par un fil de veille) : arrêt immédiat même pendant le chargement du modèle ou la lecture du prompt | Avant, Stop n'agissait qu'entre deux étapes (jusqu'à 40 s d'attente). Mesuré sur le Mac : arrêt en 0 s avant le premier mot. |
| D46 | **Sécurité, règles centrales** (`securite.py`) : appli, touches, chemins et texte normalisés une seule fois, pour le calcul du risque ET l'exécution (« Messages.app », « maj+cmd+d », « ~/library », `/System/Volumes/Data`, Unicode) | Relecture de sécurité (3 audits indépendants, nov. 2026) : le risque portait sur la chaîne écrite par le modèle, l'exécution l'interprétait autrement → envois et écritures sans confirmation. |
| D47 | **Contenu lu** : après la lecture d'un contenu extérieur dans une demande, toute sortie (adresse web, question à une IA, recherche, saisie dans un navigateur / une messagerie, souvenir, compétence) contenant des données absentes de la demande est confirmée ; un lien lu tel quel reste libre | Une page piégée pouvait faire envoyer une clé lue dans une adresse ou à Claude sans aucune confirmation. Garde-fou dans le code, pas dans les consignes. |
| D48 | SENSIBLE toujours confirmé, quel que soit le mode ; `autonome` réglable seulement dans `macai.toml` (refusé par l'API) | En autonome, Entrée dans Messages ou un clic sur « Supprimer » partaient sans accord ; un programme lisant le jeton pouvait couper les confirmations. |
| D49 | Lecture interdite de tout fichier caché du dossier personnel et de Notes, Contacts, LaunchAgents, Préférences… ; `executer_commande` résout chaque argument dans son dossier de travail, refuse grep récursif, `ps e`, `tail -f`, `file -C` ; `ouvrir_fichier` en liste blanche de documents (lien et alias Finder suivis) | `cat id_ed25519` avec dossier ~/.ssh, `.terminal␠`, lien `doc.pdf → x.command` passaient sans confirmation. |
| D50 | `planifier_tache` toujours confirmé ; `creer_competence` confirmé (sauf bouton de l'app) et jamais d'écrasement ; « mon/ma/mes » ne vaut plus accord pour `retenir` | Persistance d'une consigne piégée qui s'exécuterait plus tard, sans témoin. |
| D51 | À la voix, une confirmation ou un plan peut être refusé mais jamais accepté | Un « oui » d'une vidéo ou d'une autre personne validait un envoi. |
| D52 | Serveur : jeton comparé en octets, Host local exigé, tout en-tête Origin refusé ; app : connexion seulement au pid du moteur qu'elle a lancé, Python `-I` et environnement minimal ; empreinte des modèles Ollama retenue au premier usage | DNS rebinding, faux moteur après un plantage, `PYTHONPATH`/`DYLD_*` hérités, modèle remplacé par un programme local (Ollama sans authentification). |
| D53 | Calculs exacts sans modèle (`calcul.py`, `ast`, jamais `eval`) ; commandes directes : fermer plusieurs applis, tout fermer sauf…, Wi-Fi, mode sombre | Journal : « combien font 5000-964 » partait en recherche web ; « ferme Chrome, Finder et Claude » échouait. |
| D54 | `installer_application` (.dmg, .zip, .app) : Gatekeeper exige signature + notarisation, toujours confirmé, annulable ; .pkg refusé (mot de passe admin) | Journal : « finis l'installation de Minecraft » impossible. |
| D55 | Préchargement du modèle (et de ses consignes) à l'ouverture du panneau ou au début de l'écoute, abandonné si la demande arrive | Mesuré : première réponse 27,8 s → 21,2 s (13,8 s modèle chaud). |
| D56 | Groupe mémoire plus ajouté à chaque demande ; routeur : outils du domaine gardés quand on pilote une appli, verbe de la demande favorisé | ~350 jetons de moins par demande ; essai réel : le modèle tapait « cat » dans le Terminal faute de lire_document. |
| D57 | Index : binaires exclus (.dll, .jar…), fichiers déplacés/jetés par MacAI oubliés aussitôt, résultats disparus écartés, indexation aussi sur batterie > 60 % (Mac inutilisé 10 min) | Index d'un mois de retard, 3/4 de binaires, fichiers proposés puis « introuvables ». |
| D58 | Remplacer un fichier existant (`ecraser`) : confirmé ; « écris une phrase… » sans fichier nommé = réponse directe | Essai réel : le modèle écrasait de lui-même un fichier du Bureau pour une simple phrase. |
| D59 | Contre-audit des protections : `find` en liste blanche de prédicats, options à valeur collée vérifiées comme chemins, `/dev/*` refusé ; aucune requête DNS pendant un calcul de risque (résolution dans l'outil, après confirmation) ; adresse avec identifiant ou port, ou plus de deux liens « vus » vers un même site après lecture → confirmé ; tout chiffre absent de la demande compte comme donnée lue ; coller dans un navigateur après lecture → confirmé ; mémoire après lecture : ordre explicite exigé ; supprimer une tâche ou une compétence → toujours confirmé ; rappel dans une liste nommée contrôlé comme un agenda nommé | Un quatrième audit, adverse, a contourné les protections de D46-D52 (`file -f/…/.ssh/id`, `find -fprint0` qui écrasait un fichier, secret dans un sous-domaine résolu avant confirmation, un caractère par lien). |
| D60 | **Classifieur de demandes** (principe des modèles de décision type Jev) : plus proches voisins (15, puissance 16) parmi 663 exemples étiquetés, avec `qwen3-embedding` déjà en mémoire ; donne intention et domaines au routeur ; ne retire des outils (rédaction, conversation) qu'au-dessus de 70 % de confiance et jamais si un fichier, une appli ou un destinataire est nommé | Jev lui-même : API en ligne seulement (interdit). Mesuré sur 147 demandes de test : routage qui couvre les domaines utiles 82 % → 96 %, intention 80 %, ~50 ms. Un classifieur dédié (CamemBERT, Laya) demanderait PyTorch : trop lourd pour 8 Go. |

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
