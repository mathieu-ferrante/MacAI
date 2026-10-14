# MacAI — cahier des charges

Assistant personnel **100 % local** pour MacBook Air M2 8 Go (macOS 27) : il comprend une demande
écrite ou parlée et **agit sur le Mac** — fichiers, applications, web, logiciels — sans aucune IA
dans le cloud.

## 1. Contraintes non négociables

| Code | Contrainte |
|---|---|
| C-01 | **Aucun appel à une IA distante**, jamais. Les modèles tournent sur le Mac (Ollama, frameworks Apple). |
| C-02 | **Léger au repos** : < 100 Mo de RAM pour l'ensemble (app + moteur + Ollama inactif), ~0 % de processeur. |
| C-03 | **Lourd seulement à la demande** : modèles chargés quand ils servent, déchargés après 2 min sans usage ; jamais deux gros modèles en même temps. |
| C-04 | Indexation et tâches longues : priorité basse, Mac sur secteur et inutilisé. |
| C-05 | Le contenu lu (fichier, page web, mail, écran) est une **donnée, jamais une instruction**. |
| C-06 | Secrets (clés Onshape, etc.) dans le Trousseau macOS ; jamais dans le dépôt, jamais montrés au modèle. |

## 2. Utilisation

- **Option + Espace** : panneau flottant pour écrire.
- **Touche maintenue** (Fn par défaut, réglable) : parler ; relâcher envoie la demande.
- Bouton **Écrit / Oral** : réponse seulement écrite, ou écrite + lue à voix haute.
- Icône dans la barre des menus (état, réglages, quitter). Lancement à l'ouverture de session.
- Une app `MacAI.app` dans Applications = le raccourci pour tout lancer.

## 3. Comment il agit (du plus fiable au moins fiable)

1. **Commandes directes** : reconnues sans IA (instantané) — « ouvre Safari », « lance YouTube et
   cherche … », « volume à 30 », « pause », « quelle heure ».
2. **Connecteurs** : un logiciel piloté par son interface officielle — MCP (suite ArtCraft et toute
   appli qui expose un serveur MCP), API Onshape, AppleScript (Finder, Mail, Calendrier, Rappels,
   Notes, Musique, Chrome).
3. **Lecture des fenêtres** (Accessibilité macOS) : l'IA voit la liste des boutons/champs d'une
   fenêtre et clique/tape.
4. **Vision** (dernier recours) : capture d'écran analysée par un modèle de vision, clic aux
   coordonnées.

## 4. Fonctions

| Code | Fonction |
|---|---|
| F-01 | Agent : comprend la demande, enchaîne les outils, vérifie le résultat, dit honnêtement s'il échoue. |
| F-02 | Fichiers : lire (PDF, Word, Excel, PowerPoint, texte, code, images avec OCR), créer (texte, Markdown, Word, Excel, CSV, PowerPoint), déplacer, renommer, ranger, mettre à la Corbeille. |
| F-03 | Recherche par le sens dans tout le dossier personnel (hors caches, bibliothèques, code généré), y compris images (étiquettes + texte lu dans l'image) et captures d'écran ; recherche hybride sens + mots-clés. |
| F-04 | Applications : ouvrir, quitter, basculer, lister ; menus et fenêtres via Accessibilité. |
| F-05 | Chrome : ouvrir une adresse, chercher (Google, YouTube), lancer une vidéo, lire la page, cliquer, remplir. |
| F-06 | Système : volume, médias, presse-papiers, notifications, capture d'écran, état mémoire (SwapGuard intégré), commandes Terminal. |
| F-07 | Organisation : Calendrier, Rappels, Notes, brouillons Mail (envoi toujours confirmé). |
| F-08 | Connecteurs MCP configurables (ArtCraft d'abord), démarrés à la demande, arrêtés après inactivité. |
| F-09 | Connecteur Onshape : créer documents et pièces simples (cube, pavé, cylindre). |
| F-10 | Mémoire : retient des faits sur l'utilisateur (dits ou appris), consultables et effaçables, chiffrés. |
| F-11 | **Compétences apprises** : après une tâche précise réussie, propose d'en faire une compétence ; la rejoue ensuite directement avec de nouveaux paramètres. |
| F-12 | Voix : transcription Apple SpeechAnalyzer (locale), synthèse Apple (voix française locale). |

## 5. Sécurité — niveau « équilibré »

| Niveau | Exemples | Comportement |
|---|---|---|
| Lecture | lire, chercher, lister, capture | libre |
| Création / ouverture | créer un fichier, ouvrir une appli/un site | libre |
| Modification | déplacer, renommer, écraser, quitter une appli, cliquer/taper dans une fenêtre | annoncé puis exécuté |
| Sensible | Corbeille, envoyer un message, commande Terminal non lecture, payer, se connecter | **confirmation obligatoire** |

Suppressions = Corbeille, jamais définitives. Journal de toutes les actions. Arrêt d'urgence :
bouton Stop / Échap.

## 6. Hors périmètre (assumé)

- Piloter de façon fiable un logiciel complexe uniquement par l'image (zone 3D, jeux) : possible
  en dernier recours, pas garanti.
- Taper des mots de passe ou des numéros de carte.
