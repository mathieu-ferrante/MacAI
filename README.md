# MacAI

**Un assistant personnel qui agit sur ton Mac, et dont l'intelligence tourne entièrement sur ton Mac.**

Tu lui écris ou tu lui parles en français, et il fait le travail : il retrouve un fichier par son contenu, range tes
téléchargements, lit et résume tes mails, prépare une réponse, met un rappel, cherche une information sur le web en
citant sa source, pilote n'importe quelle application (Claude, TextEdit, Réglages, les logiciels ArtCraft…), calcule,
installe une application, ferme ce qui consomme de la mémoire.

Son « cerveau » est un modèle d'IA de 4 milliards de paramètres (`qwen3.5:4b`) qui tourne sur la puce M2 grâce à
Ollama. **Aucune demande, aucun fichier, aucun mail ne part dans le cloud.** Il est conçu pour un MacBook Air M2 de
8 Go : au repos, l'ensemble occupe environ 50 Mo de mémoire.

> **État au 25/11/2026** : installé et utilisé sur le MacBook Air (macOS 27). 442 tests automatiques, un banc de
> 68 demandes réelles passées dans le vrai moteur avec le vrai modèle (68/68), et quatre relectures de sécurité. Ce qui reste à
> essayer de ton côté est listé dans [A_VALIDER.md](A_VALIDER.md).

---

## Sommaire

1. [En deux minutes](#1-en-deux-minutes)
2. [Installer et mettre à jour](#2-installer-et-mettre-à-jour)
3. [Toutes les façons de lui parler](#3-toutes-les-façons-de-lui-parler)
4. [Comment il travaille](#4-comment-il-travaille)
5. [Ce qu'il sait faire, domaine par domaine](#5-ce-quil-sait-faire-domaine-par-domaine)
6. [Sécurité : ce qu'il ne fait jamais, ou seulement avec ton accord](#6-sécurité--ce-quil-ne-fait-jamais-ou-seulement-avec-ton-accord)
7. [Limites : ce qu'il ne sait pas (encore) faire](#7-limites--ce-quil-ne-sait-pas-encore-faire)
8. [Vitesse et mémoire](#8-vitesse-et-mémoire)
9. [Réglages (macai.toml et menu 🧠)](#9-réglages-macaitoml-et-menu-)
10. [Ligne de commande](#10-ligne-de-commande)
11. [Si quelque chose ne marche pas](#11-si-quelque-chose-ne-marche-pas)
12. [Où sont tes données](#12-où-sont-tes-données)
13. [Architecture et développement](#13-architecture-et-développement)

---

## 1. En deux minutes

| Pour… | Fais… |
|---|---|
| Écrire une demande | **⌥ Espace**, tape, Entrée |
| Parler à MacAI | **maintiens ⌥ ⇧ Espace**, parle, relâche |
| Dicter dans n'importe quelle appli | **maintiens Fn**, parle, relâche : le texte s'écrit au curseur |
| Agir sur un texte sélectionné | sélectionne-le, **⌥ ⇧ T** : corriger, traduire, résumer… |
| Agir sur une zone de l'écran | **⌥ ⇧ S**, entoure la zone : expliquer, traduire, extraire un tableau… |
| Arrêter une demande | bouton **Stop** ou **Échap** (arrêt en moins d'une seconde) |
| Défaire la dernière action sur des fichiers | dire « annule », ou menu 🧠 > Annuler la dernière action |

Exemples pour commencer :

- « Retrouve ma facture EDF de mars »
- « Qu'est-ce que j'ai demain ? »
- « Résume mes mails non lus »
- « Range mes téléchargements » (puis « annule » si le résultat ne te plaît pas)
- « Quels sont les horaires de la poste de Toulon ? »
- « Demande à Claude quels sont les meilleurs claviers mécaniques »
- « Combien font 5000 − 964 » (instantané, sans IA)
- « Ferme tout sauf Claude »

---

## 2. Installer et mettre à jour

### Installation (une commande)

```bash
cd ~/MacAI && git pull && ./installer.sh
```

Le script fait tout, et peut être relancé sans risque (il sert aussi aux mises à jour) :

1. vérifie macOS, la puce et les outils de développement Apple ;
2. installe Homebrew, Ollama et uv s'ils manquent ;
3. règle Ollama pour 8 Go (modèles déchargés après 2 minutes, un seul calcul à la fois, cache réduit) et le lance
   comme service ;
4. télécharge les modèles (~4 Go la première fois) et **enregistre leur empreinte** (voir la sécurité) ;
5. installe le moteur Python (3.12) et la commande `macai` ;
6. compile l'app Swift, la signe avec un certificat local « MacAI Local » et la copie dans /Applications ;
7. lance `macai verifier` et enregistre un rapport sur le Bureau.

Durée : 5 à 15 minutes la première fois (téléchargement des modèles), 2 à 5 minutes ensuite (compilation de l'app).

Pendant la signature, macOS peut afficher « codesign veut utiliser la clé MacAI Local » : saisis ton mot de passe de
session et choisis **Toujours autoriser**. Grâce à ce certificat, macOS **garde tes autorisations** d'une mise à jour
à l'autre. Déverrouille l'écran avant de lancer l'installation.

### Autorisations macOS (une seule fois)

MacAI te les demande au premier usage. Accepte :

| Autorisation | À quoi elle sert |
|---|---|
| **Accessibilité** | lire les fenêtres des applis, cliquer, taper, raccourcis clavier, touche Fn |
| **Enregistrement de l'écran** | « qu'est-ce qu'il y a sur mon écran ? », ⌥⇧S, clic par la vision |
| **Micro** | parler à MacAI, dictée (reconnaissance vocale d'Apple, locale) |
| **Bureau, Documents, Téléchargements** | lire, ranger, créer des fichiers |
| **Calendriers, Rappels** | agenda, rendez-vous, rappels |
| **Automatisation** (Mail, Notes, Chrome, Finder, Messages, System Events) | mails, notes, pages web, messages |
| **Notifications** | alertes, briefing du matin, fin des tâches planifiées |

Après avoir accordé l'Accessibilité : menu 🧠 > Quitter MacAI, puis rouvre MacAI. Si MacAI était déjà coché sans
effet : retire-le (−) et rajoute-le (+) dans Réglages Système > Confidentialité et sécurité > Accessibilité.

### Deux réglages à faire à la main

- **Touche Fn pour dicter** : Réglages Système > Clavier > « Appuyer sur la touche 🌐 pour » : **Ne rien faire**.
- **Chrome** (YouTube, lecture et clic dans les pages) : Chrome > Présentation > Options pour les développeurs >
  **Autoriser JavaScript à partir des Apple Events**. Sans ce réglage, MacAI ouvre les pages mais ne peut ni les lire
  ni y cliquer.

### Facultatif

- `macai secret onshape` : enregistre tes clés API Onshape dans le Trousseau.
- `macai mcp detecter` : trouve les logiciels qui exposent un serveur MCP (suite ArtCraft…).

### Désinstaller

`./desinstaller.sh` retire l'app, le service Ollama de MacAI, la commande `macai` et les autorisations macOS
accordées à MacAI. Il propose aussi de supprimer les modèles (~4 Go), puis tes données (mémoire, index, compétences,
réglages) et les clés du Trousseau ; réponds « o » ou « N » à chaque question.

---

## 3. Toutes les façons de lui parler

### Le panneau (⌥ Espace)

Une fenêtre flottante s'ouvre au centre de l'écran. Tu tapes ta demande et tu valides avec Entrée. Pendant que
MacAI travaille, tu vois :

- **chaque étape** (« Ouvrir Safari », « Lire rapport.pdf ») avec son état : en cours, réussie, échouée ;
- **le texte** de la réponse qui s'écrit au fil de l'eau ;
- **les cartes de confirmation** pour les actions sensibles (Confirmer / Refuser), avec le détail complet : destinataire,
  texte entier du message, adresse web, fichier concerné ;
- **la carte de plan** quand il propose un plan avant d'agir (Valider / Modifier / Annuler).

Dès que le panneau s'ouvre, MacAI **précharge le modèle** pendant que tu écris : la première réponse arrive environ
7 secondes plus tôt.

**Échap** ferme le panneau (la demande en cours continue). Le bouton **Stop** l'arrête.

### La voix

| Geste | Effet |
|---|---|
| **⌥ ⇧ Espace maintenus** | tu parles à MacAI ; la demande part quand tu relâches |
| **Fn maintenue** (réglable) | **dictée** dans l'application au premier plan : le texte s'écrit pendant que tu parles, le panneau ne s'ouvre pas |
| Menu 🧠 > Touche Fn maintenue | choisir « Dicter dans l'application » ou « Parler à MacAI », ou utiliser **Option droite** au lieu de Fn |

La reconnaissance vocale est celle d'Apple (SpeechAnalyzer), **sur le Mac**, sans modèle à télécharger.

**Réponses orales** (menu 🧠 > Réponses) : « Écrites », « Orales » ou « Écrites et orales ». En mode oral, MacAI lit sa
réponse avec la voix française d'Apple.

**Conversation vocale** (menu 🧠 > Réponses) : après sa réponse orale, MacAI réécoute tout seul ; tu enchaînes sans
toucher au clavier. « Merci », « stop », « c'est tout » terminent.

**Confirmer à la voix** : tu peux **refuser** une confirmation ou un plan en disant « non » ou « annule ». Pour
**accepter**, il faut **cliquer**. Un « oui » entendu pourrait venir d'une vidéo ou de quelqu'un d'autre dans la pièce.

### Le texte sélectionné (⌥ ⇧ T)

Sélectionne un texte dans n'importe quelle application (Mail, Notes, Safari, Word, Messages…), puis ⌥ ⇧ T :

| Action | Résultat |
|---|---|
| **Corriger** | orthographe, grammaire, accents, ponctuation ; le texte est **remplacé sur place** |
| **Reformuler** | plus clair et plus fluide, même sens ; remplacé sur place |
| **Traduire** | en français (ou en anglais s'il est déjà en français) ; remplacé sur place |
| **Résumer** | 3 à 6 puces dans le panneau |
| **Expliquer** | ce que dit le texte, termes techniques définis |
| **Répondre à ce message** | un brouillon de réponse dans la langue du message, à copier |
| **Écouter** | lecture à voix haute (Échap arrête) |
| **Autre consigne** | tu écris ce qu'il faut faire du texte |

Un seul appel au modèle, sans boucle d'agent : rapide et prévisible. Limite : environ 9 000 caractères.

### Une zone de l'écran (⌥ ⇧ S)

Le curseur devient une croix : entoure une zone (message d'erreur, tableau dans un PDF, page en anglais, graphique),
puis choisis :

| Action | Résultat |
|---|---|
| **Expliquer** | ce que montre la zone ; pour une erreur, sa cause probable et comment la résoudre |
| **Traduire** | tout le texte visible, traduit en français |
| **Extraire le texte** | le texte reconnu (OCR d'Apple), copié |
| **Extraire le tableau (Excel)** | un fichier .xlsx sur le Bureau |
| **Autre question** | tu poses ta question sur la zone |

### Le Terminal

```bash
macai demander "range mes téléchargements"
```

Pratique pour tester ou pour enchaîner dans un script. Sans interface, les confirmations sont refusées.

### Le menu 🧠 (barre des menus)

| Entrée | Rôle |
|---|---|
| Ouvrir le panneau ⌥Espace | |
| Annuler la dernière action | défait la dernière action sur des fichiers |
| Tâches planifiées | liste, avec Supprimer pour chacune |
| Réponses | Écrites / Orales / Écrites et orales, Conversation vocale |
| Touche Fn maintenue | Dicter / Parler à MacAI / Option droite au lieu de Fn |
| Enregistrer une démonstration | tu montres une tâche, il propose de l'apprendre |
| Montrer le plan avant d'agir | « Pour les tâches importantes » (défaut), « Toujours », « Jamais » |
| Alertes | batterie, mémoire, disque, rendez-vous, téléchargements |
| Briefing du matin, Heure du briefing… | une notification chaque matin |
| Classer automatiquement les téléchargements | factures, impôts… rangés au fil de l'eau |
| Indexer mes fichiers maintenant | lance l'indexation tout de suite |
| Ouvrir les réglages (macai.toml) | |
| Ouvrir le journal | tout ce qu'il a fait |
| Redémarrer le moteur | si quelque chose est bloqué |
| Quitter MacAI | |

---

## 4. Comment il travaille

### Trois façons de traiter une demande, de la plus fiable à la plus souple

1. **Commande directe, sans IA** : les demandes courantes et sans ambiguïté sont reconnues par des règles et
   exécutées **instantanément** (moins d'une seconde, aucune mémoire en plus). Voir la liste complète
   [section 5.1](#51-commandes-instantanées-sans-ia).
2. **L'agent** : le modèle local lit ta demande, choisit parmi **102 outils** (dont il ne voit qu'une quinzaine à la
   fois, les plus proches de la demande), les appelle un par un, lit leurs résultats et continue jusqu'au bout
   (10 étapes au plus). Compte 10 à 30 secondes.
3. **Les connecteurs** : quand un logiciel a une interface officielle (serveur MCP des logiciels ArtCraft, API Onshape,
   AppleScript de Mail, Notes, Calendrier, Rappels, Chrome), MacAI passe par elle plutôt que par l'écran. En dernier
   recours, il lit la fenêtre (Accessibilité), puis regarde l'écran (vision).

### Le classifieur : un « modèle de décision » qui épaule l'agent

Avant que l'agent réfléchisse, un **classifieur** range la demande, sur le principe des modèles de décision comme
Jev : il ne rédige rien, il décide.

- **Intention** : action, information, explication, rédaction, tâche à programmer ou simple conversation.
- **Domaines** : fichiers, web, mails et agenda, pilotage d'une appli, système…

Il compare ta demande, par le sens, à **663 exemples français étiquetés** (`src/macai/agent/exemples_routage.jsonl`),
avec le petit modèle d'embeddings déjà utilisé pour la recherche. Rien de plus à installer, rien ne quitte le Mac,
environ **50 ms** par demande.

Ce qu'il change :
- l'agent reçoit **les bons outils** : sur 147 demandes de test, le routage couvre les domaines utiles dans **96 %**
  des cas, contre 82 % avec les seuls mots-clés ;
- une rédaction (« un petit poème sur l'automne ») ou une conversation (« merci ») est servie **sans outils** : la
  réponse est le texte, aucun fichier n'est créé par erreur ;
- une question « comment faire… » ne reçoit que des outils de lecture ;
- une demande récurrente met l'outil de programmation en tête.

Il n'est qu'un **aiguilleur** : il n'agit pas et ne contourne aucune confirmation. S'il hésite (confiance sous 70 %),
ou si un fichier, une appli ou un destinataire est nommé, ses conseils ne retirent jamais d'outils. S'il est
indisponible, les mots-clés prennent le relais. Mesure : `macai classifieur` (`--erreurs` pour voir ce qu'il rate).
Pour lui apprendre une tournure, ajoute une ligne d'exemple au fichier.

### Ce qui se passe pendant une demande

- **Annonce** : une action qui modifie quelque chose (déplacer, renommer, cliquer dans une appli) est affichée avant
  d'être faite.
- **Confirmation** : une action sensible (envoyer, supprimer, exécuter, payer…) attend ton clic. Sans réponse en
  2 minutes, c'est **non**.
- **Plan** : pour une tâche en plusieurs étapes qui touche à l'important (envoyer, supprimer, ranger, installer…),
  il propose d'abord un plan numéroté, rédigé d'après les outils dont il dispose vraiment. Tu le valides, le corriges
  (« non, envoie-le à Paul plutôt ») ou l'annules. Une fois validé, seules les étapes sensibles redemandent ton accord.
- **Bilan honnête** : sa réponse finale est confrontée à ce que les outils ont **réellement** fait. S'il prétend avoir
  agi alors que tout a échoué, sa réponse est remplacée par la vraie raison (« Je n'ai pas réussi : /…/x.dmg n'existe
  pas »). Si une étape a échoué sans être rattrapée, elle est signalée. S'il n'y avait rien à faire (« Safari n'était
  pas ouvert »), il le dit.
- **Stop** : coupe immédiatement le calcul du modèle, même pendant son chargement.
- **Annuler** : les 50 dernières actions sur les fichiers (déplacer, renommer, copier, écrire, ranger, classer,
  Corbeille, installer une app) sont réversibles avec « annule ».
- **Mémoire de la conversation** : les derniers échanges sont gardés, tu peux enchaîner (« et pour jeudi ? »,
  « ouvre-le »).

---

## 5. Ce qu'il sait faire, domaine par domaine

Pour chaque domaine : des exemples à dire tels quels, ce qui se passe, et le niveau d'accord demandé
(**libre**, **annoncé** = affiché puis fait, **confirmé** = attend ton clic).

### 5.1 Commandes instantanées (sans IA)

Reconnues mot pour mot, exécutées en moins d'une seconde :

| Tu dis | Il fait |
|---|---|
| « Quelle heure est-il ? », « On est quel jour ? » | répond directement |
| « Combien font 5000 − 964 », « calcule 12 fois 7 », « 20 % de 150 », « racine carrée de 144 », « 2^10 », « 5 000 divisé par 3 » | calcul exact (jamais de recherche web) |
| « Volume à 30 », « monte le son », « baisse le son », « coupe le son » | règle le volume |
| « Pause », « reprends », « suivant », « précédent » | contrôle la musique ou la vidéo en cours |
| « Prends une capture d'écran » | capture sur le Bureau |
| « Batterie », « espace disque », « infos système » | état du Mac |
| « Pourquoi mon Mac rame ? », « état de la mémoire » | pression mémoire, applis qui consomment le plus |
| « Ouvre Safari », « lance Spotify », « ouvre YouTube », « ouvre github.com » | ouvre l'appli ou le site |
| « Ouvre Téléchargements », « ouvre le Bureau » | ouvre le dossier dans le Finder |
| « Ferme Spotify » | quitte l'appli (annoncé) |
| « Ferme Chrome, Finder et Claude », « quitte Notes et Rappels » | quitte chacune (Finder reste : il fait partie de macOS) |
| « Ferme tout », « ferme toutes mes applications sauf Claude et Mail » | liste les applis concernées, **confirmé** |
| « Coupe le wifi », « active le wifi » | Wi-Fi (annoncé) |
| « Passe en mode sombre », « mode clair » | apparence de macOS (annoncé) |
| « Ouvre les réglages Bluetooth » (ou Wi-Fi, Son, Écrans, Batterie, Clavier, Notifications…) | Réglages Système, sur la bonne rubrique |
| « Mets Daft Punk Get Lucky sur YouTube » | lance la vidéo |
| « Cherche des recettes de crêpes sur YouTube / sur Google » | ouvre la recherche |
| « Demande à Claude quels sont les meilleurs claviers » | pose la question à l'app Claude et rapporte la réponse |
| « Tous les matins à 8 h, fais-moi un résumé de mes mails », « chaque lundi à 9 h, range mes téléchargements », « toutes les heures, … » | programme la tâche (**confirmé**, avec la demande complète) |
| « Annule » | défait la dernière action sur des fichiers |

Tout ce qui n'est pas reconnu passe à l'agent : tu peux formuler librement.

### 5.2 Fichiers et documents

**Lire** (libre)
- « Résume le fichier ~/Documents/rapport.pdf », « lis-moi ce document », « qu'est-ce qu'il y a dans le dossier
  Factures ? »
- Formats lus : PDF (même **scannés**, avec l'OCR d'Apple), Word (.docx, .doc), Excel (.xlsx), PowerPoint (.pptx),
  Pages, Numbers, Keynote, RTF, OpenDocument, texte, Markdown, CSV, JSON, code, sous-titres, et **images** (texte
  visible + description).
- « Décris l'image photo.jpg », « qu'est-ce qu'on voit sur cette capture ? » (modèle de vision local).

**Créer** (libre)
- « Crée un document Word sur le Bureau avec un plan de révision en 3 parties » : titres, sous-titres, puces, listes
  numérotées, gras, tableaux.
- « Fais un tableur avec loyer 600, courses 250, essence 80 » : fichier Excel dont les nombres (même « 1 284,50 € »)
  sont de vrais nombres, calculables.
- « Une présentation de 5 diapositives sur le recyclage » : PowerPoint, une diapositive de titre puis une par point.
- « Crée un fichier notes.md avec… », « fais un CSV des participants ».
- « Crée un dossier Projets/2026 ».
- « Écris-moi une phrase sur la mer », « rédige un poème », « donne-moi 3 idées de cadeaux » : la réponse est
  écrite directement dans le panneau, **aucun fichier n'est créé**. Pour un fichier, nomme-le (« écris un fichier
  notes.md sur le Bureau avec… »).
- Un fichier existant n'est **jamais écrasé** sans ton accord : un nouveau nom est choisi (« notes (2).md »). Pour le
  remplacer, il demande **confirmation** (l'ancienne version va à la Corbeille).

**Organiser**
- « Range mes téléchargements » (**confirmé**) : les fichiers vont dans Images, PDF, Documents, Tableurs,
  Présentations, Archives, Installeurs, Vidéos, Audio, Code, 3D. Les sous-dossiers existants ne bougent pas.
- « Déplace facture.pdf dans Documents/Factures », « renomme scan1.pdf en contrat.pdf », « copie ce dossier sur le
  Bureau » (annoncé).
- « Mets vieux.txt à la Corbeille » (**confirmé**, toujours la Corbeille, jamais de suppression définitive).
- « Annule » remet tout en place.

**Garde-fous** : il ne touche jamais aux fichiers cachés, à la Bibliothèque (sauf iCloud Drive), aux réglages ni au
code de MacAI ; il ne déplace ni ne renomme les dossiers principaux (Bureau, Documents, Téléchargements…) ;
déplacer ou copier hors de ton dossier personnel (clé USB, volume réseau) est **confirmé**.

### 5.3 Retrouver (recherche par le sens)

- « Retrouve ma facture EDF de mars », « la photo du chat sur le canapé », « le cours sur TCP », « le devis de la
  cuisine ».
- La recherche comprend le **sens** (pas seulement les mots) et lit le **contenu** : texte des PDF et des scans, OCR
  des captures d'écran, étiquettes des photos (ce qu'elles montrent).
- Filtres : type (« une image », « un PDF »), période (« de cette semaine », « des 3 derniers mois »), dossier.
- « Cherche partout le mail de Paul sur les vacances » : fichiers, **mails** (Réception et Envoyés, 2 000 derniers
  de chaque) et **notes** ensemble ; « ouvre-le » l'ouvre dans Mail ou Notes.
- **Spotlight** complète quand l'index ne connaît pas encore un fichier.
- « Où en est l'index ? » : nombre de fichiers, date du dernier passage ; « indexe maintenant ».

**Comment l'index se construit** : en arrière-plan, priorité basse, sur les cœurs économes, quand le Mac est
inutilisé depuis 5 minutes sur secteur (10 minutes sur batterie au-dessus de 60 %). Bureau, Documents et
Téléchargements d'abord. Il ignore les fichiers cachés, la Bibliothèque, le code des projets logiciels, les binaires
(.dll, .jar…), les fichiers iCloud non téléchargés et tout ce qui est protégé (clés, cookies…). Un fichier que MacAI
déplace ou jette est oublié tout de suite ; un fichier disparu n'est plus proposé.

### 5.4 Applications

- « Ouvre Pages », « quitte Spotify », « quelles applis sont ouvertes ? ».
- « Ferme tout sauf Claude » (**confirmé**, la liste est affichée ; chaque appli peut te proposer d'enregistrer).
- « Montre rapport.pdf dans le Finder ».
- « Ouvre ce document avec Aperçu ».
- **Installer une application** : « installe Minecraft, le .dmg est dans mes téléchargements ». MacAI ouvre l'image
  disque, vérifie avec **Gatekeeper** que l'app est **signée et notariée par Apple**, la copie dans Applications,
  puis referme l'image. **Toujours confirmé**, annulable (« annule » la remet à la Corbeille). Formats : .dmg, .zip,
  .app. Refusés : les apps non notariées, et les .pkg (ils demandent ton mot de passe administrateur : ouvre-les
  toi-même).
- Une application absente est signalée comme telle : il n'en ouvre jamais une autre à la place.

### 5.5 Piloter n'importe quelle application

Quand il n'y a pas d'outil dédié, MacAI utilise l'application comme toi :

- il **lit la fenêtre** (boutons, champs, cases, onglets, numérotés), **clique**, **écrit** dans un champ, **tape** au
  clavier, utilise les **raccourcis** et les **menus** (« Fichier > Exporter > PDF… ») ;
- en dernier recours, il **regarde l'écran** (vision) et clique à l'endroit décrit.

Exemples :
- « Dans TextEdit, crée un nouveau document et écris Bonjour »
- « Dans TextEdit, exporte le document en PDF »
- « Ouvre les réglages Bluetooth et dis-moi si le Bluetooth est activé »
- « Ouvre la calculatrice et calcule 12 fois 7 »

**Guide** (il montre sans faire) : « comment on fait pour exporter en PDF dans Pages ? » donne le chemin du menu et
**surligne** l'endroit à l'écran.

Garde-fous : il ne tape jamais dans un champ de mot de passe, ni à l'aveugle (l'appli doit être au premier plan) ; il
ne clique pas sur un bouton d'achat ; dans une messagerie, un navigateur ou un Terminal, valider (Entrée, ⌘↩) est
**confirmé** ; cliquer « Envoyer », « Supprimer », « Publier », « Corbeille » est **confirmé** partout.

### 5.6 Claude et ChatGPT

- « Demande à Claude quels sont les meilleurs claviers mécaniques » : il passe Claude en mode chat, ouvre une nouvelle
  conversation, envoie la question, attend la réponse et te la rapporte. **Sans confirmation** : poser une question à
  une IA n'engage personne.
- « Écris à ChatGPT pour lui demander une recette de crêpes ».
- Claude et ChatGPT sont des IA **distantes** : MacAI ne les utilise **que si tu le demandes**.
- Si la question contient des informations que tu n'as pas tapées (lues dans un mail ou un fichier), elle est
  **confirmée** avec le texte complet.
- Il n'écrit jamais dans Claude en mode Code sans que tu parles de Claude Code, et **ne demande jamais de crédits ni
  d'utilisation supplémentaire**, même si la limite est atteinte.

### 5.7 Mails, messages, notes, agenda, rappels

**Agenda et rappels**
- « Qu'est-ce que j'ai demain ? » : la journée complète, rendez-vous (récurrents compris, avec lieux) et rappels.
- « Mets un rappel demain à 9 h pour appeler la banque », « un rappel à 20 h 40 et un autre à 20 h 45 ».
- « Ajoute un rendez-vous chez le dentiste jeudi à 14 h » (1 h par défaut).
- « Quels sont mes rappels ? »

**Mails** (app Mail)
- « Résume mes mails non lus », « quels sont mes derniers mails ? »
- « **Trie mes mails** » : en « À traiter », « À lire », « Notifications », « Pubs et newsletters ». Il propose de les
  ranger dans des boîtes ; **il ne supprime jamais rien**.
- « Réponds au dernier mail de Paul que je serai là jeudi » : un brouillon s'ouvre dans Mail, **non envoyé**.
- « Prépare un mail à Paul pour la réunion » : brouillon affiché, non envoyé.
- « Envoie un mail à … » : **confirmé**, avec le destinataire, le sujet et **le texte complet**.
- « Retrouve le mail où Paul parlait du devis » (recherche par le sens).

**Messages**
- « Envoie un SMS à Maman : j'arrive dans 10 minutes » : **confirmé**, avec le texte complet. Le destinataire peut
  être un nom de Contacts, un numéro ou une adresse.

**Notes**
- « Crée une note avec la liste des courses », « ajoute du lait à la note Courses », « cherche dans mes notes le code
  du portail ».

### 5.8 Argent et papiers administratifs

- « **Combien j'ai dépensé** en essence ce mois-ci ? », « mes dépenses de courses depuis 3 mois » : total et lignes,
  d'après les factures, tickets et mails de paiement indexés (catégories : énergie, carburant, courses, télécom,
  abonnements, transport…). Seuls les justificatifs indexés sont comptés.
- « Fais-moi un tableur de mes dépenses du mois » : Excel sur le Bureau (date, marchand, catégorie, montant, fichier
  source, total).
- « **Classe les papiers** de mes téléchargements » : factures, relevés bancaires, impôts, assurances, santé,
  contrats, fiches de paie, billets, garanties et notices. Chacun est renommé (« 2026-10 EDF facture 84,20 € ») et
  rangé dans `Documents/Administratif/…`. Annulable. Peut se faire automatiquement (menu 🧠 > Classer
  automatiquement les téléchargements, toutes les 3 minutes sur secteur).

### 5.9 Web et Chrome

- « Quels sont les horaires de la poste de Toulon ? », « qui a gagné le match hier ? », « combien coûte un
  Raspberry Pi 5 ? » : il cherche, lit les meilleures pages et **cite ses sources**. Il n'invente pas un horaire ou un
  prix : s'il ne trouve pas, il le dit.
- « Mets la vidéo Daft Punk Get Lucky sur YouTube », « cherche des tutos Blender sur YouTube ».
- « Ouvre twitch.tv », « ouvre la page de suivi de mon colis ».
- « Lis la page ouverte et résume-la », « clique sur Connexion », « remplis le champ recherche avec … ».
- « Quels onglets sont ouverts ? », « ferme l'onglet 3 », « page précédente », « descends ».

Garde-fous : jamais de clic sur une page de paiement sans **confirmation** ; valider un formulaire web est
**confirmé** ; les adresses du réseau local (box, imprimante, le Mac lui-même) sont **confirmées** à l'ouverture et
**refusées** à la lecture ; une page ne peut pas faire interroger le Mac en le redirigeant.

### 5.10 Système

- « Volume à 30 », « pause », « chanson suivante », « prends une capture d'écran ».
- « Pourquoi mon Mac rame ? » : pression mémoire, swap, applis qui consomment le plus.
- « Combien de batterie il me reste ? », « combien d'espace disque ? », « version de macOS ».
- « Coupe le wifi », « passe en mode sombre ».
- « Ouvre les réglages » sur une rubrique : Bluetooth, Wi-Fi, Réseau, Son, Écrans, Batterie, Clavier, Trackpad,
  Souris, Notifications, Confidentialité, Accessibilité, Apparence, Bureau et Dock, Fond d'écran, Concentration,
  Temps d'écran, Écran verrouillé, Utilisateurs, Mise à jour, Général, Date et heure, Imprimantes, Siri, Spotlight,
  Stockage, Partage, Comptes internet.
- « Copie ce texte », « qu'est-ce que j'ai copié ? », « affiche une notification … ».
- **Terminal** : « exécute ls -la ~/Documents ».
  - Les commandes de **lecture** (ls, cat, head, tail, wc, df, du, find, grep, ps, mdfind, file, stat, diskutil list,
    defaults read, pmset -g, sysctl, top…) s'exécutent **sans shell** et sans confirmation, sauf si elles touchent
    un fichier protégé, lisent récursivement (grep -r) ou l'environnement des processus (ps e).
  - Toute autre commande est **confirmée** et s'exécute dans un zsh sans fichiers de démarrage.

### 5.11 Mémoire

- « Retiens que je préfère les réponses courtes », « retiens que j'habite à Toulon ».
- « Qu'est-ce que tu sais de moi ? », « oublie ce que tu sais sur mon travail » (**confirmé**).
- Il apprend aussi seul ce que tu dis de toi (« je travaille de nuit ») et te le signale.
- Les souvenirs sont **chiffrés** (AES-GCM, clé dans le Trousseau) et repris dans les demandes où ils sont utiles.
- Il **refuse** de retenir mots de passe, codes, numéros de carte ou de sécurité sociale, IBAN, clés.
- Un fait qui viendrait d'un contenu lu (page, mail) n'est retenu qu'avec ton accord.

### 5.12 Compétences (tâches apprises)

Une compétence est une recette : une suite d'actions qu'il rejoue d'un coup, avec de nouveaux paramètres.

- **Proposées automatiquement** quand tu refais **deux fois** la même tâche d'au moins 3 actions (jamais pour une
  tâche faite une seule fois).
- **Par démonstration** : menu 🧠 > Enregistrer une démonstration, tu fais la tâche toi-même, puis Terminer ; il
  propose d'en faire une compétence.
- **Sur demande** : « crée une compétence mode travail : ouvre VS Code et Slack, volume à 20 » (**confirmé**).
- **Toutes prêtes** : « quelles compétences toutes prêtes tu proposes ? » : convertir une image en JPG ou PNG,
  redimensionner une photo, créer un logo texte, composer une image (EffectCraft), importer des médias (FilmCraft),
  importer des photos (LightCraft).
- « Quelles compétences tu connais ? », « supprime la compétence … ».
- Au rejeu, chaque étape repasse par les mêmes confirmations qu'à la première fois.

### 5.13 Automatique

- **Tâches planifiées** : « tous les lundis à 9 h, range mes téléchargements », « chaque matin à 8 h, résume mes mails
  et mon agenda », « toutes les heures, … », « demain à 18 h, … ». Fréquences : tous les jours, du lundi au vendredi,
  chaque semaine (un jour donné), toutes les heures, une fois. **Confirmé** à la création, avec la demande complète.
  Une notification donne le résultat. Une tâche tourne **sans toi** : tout ce qui demanderait une confirmation y est
  refusé d'office, et elle ne peut ni envoyer, ni supprimer, ni payer.
- **Briefing du matin** (menu 🧠) : agenda du jour, mails importants, rappels, à l'heure choisie.
- **Alertes discrètes** (menu 🧠 > Alertes), vérifiées chaque minute sans IA, au plus une fois par heure chacune :
  batterie sous 20 % (une fois par décharge), mémoire saturée (critique deux fois de suite), disque sous 10 Go,
  rendez-vous dans 15 minutes, téléchargement terminé.

### 5.14 Logiciels ArtCraft, Onshape et autres connecteurs (MCP)

- **ArtCraft** : PhotoCraft, VectorCraft, LightCraft, EffectCraft, FilmCraft sont pilotés par leurs serveurs MCP
  officiels :
  - « avec PhotoCraft, convertis cette image en JPG » ;
  - « avec VectorCraft, dessine un cercle rouge et exporte-le » ;
  - « dans EffectCraft, crée une composition avec un titre animé ».
  Créer, dessiner, modifier, exporter vers un nouveau fichier : sans confirmation. Supprimer, envoyer, exécuter une
  commande système, écraser un fichier existant : **confirmé**.
- **Onshape** : « fais-moi un cube de 1 mètre », « un cylindre de 40 mm de diamètre et 10 cm de haut », « un pavé
  20 × 10 × 5 cm », puis il ouvre le document dans Chrome. Il faut d'abord `macai secret onshape`.
- **Tout logiciel qui propose un serveur MCP** devient pilotable : il suffit de l'ajouter dans `macai.toml` (voir la
  section 9). Chaque serveur est démarré à la demande et arrêté après 5 minutes d'inactivité.

---

## 6. Sécurité : ce qu'il ne fait jamais, ou seulement avec ton accord

MacAI a des autorisations étendues (Accessibilité, écran, micro, automatisation) : quiconque le contrôlerait
contrôlerait ton Mac. La sécurité est donc **dans le code**, pas dans les consignes données au modèle, et elle part du
principe que le modèle peut être trompé par un contenu piégé (une page web, un mail, un document qui lui
« ordonne » quelque chose).

| Règle | Détail |
|---|---|
| **100 % local** | aucune IA distante (sauf Claude ou ChatGPT quand **tu** le demandes) ; le moteur n'écoute que sur 127.0.0.1, avec un jeton aléatoire |
| **Jamais** | acheter, payer, réserver, s'abonner, demander des crédits ou une utilisation supplémentaire (dans toutes les langues, même déguisé) ; taper un mot de passe ou un numéro de carte ; retenir un secret ; supprimer définitivement (tout passe par la Corbeille) ; installer une app non notariée |
| **Confirmé, toujours** | mettre à la Corbeille ; envoyer un mail ou un message ; valider (Entrée, ⌘↩) dans une messagerie, un navigateur ou un Terminal ; valider un formulaire web ; cliquer Envoyer / Publier / Supprimer / Corbeille, un bouton sans nom dans une page, ou sur une page de paiement ; commande Terminal autre qu'une simple lecture ; remplacer un fichier existant ; déplacer ou copier hors de ton dossier ; ouvrir autre chose qu'un document (appli, script, raccourci web, alias) ; installer une app ; fermer toutes les applis ; programmer une tâche ; créer une compétence ; oublier un souvenir |
| **Contenu lu** | après avoir lu une page, un mail, un fichier ou l'écran, tout ce qui sortirait du Mac **avec des informations que tu n'as pas tapées** (adresse web, question à une IA, recherche, texte dans un navigateur ou une messagerie, souvenir) est **confirmé**, avec le contenu complet. C'est ainsi qu'une page piégée essaierait de voler des données. Suivre tel quel un lien lu reste libre |
| **Protégé** | clés SSH, Trousseau, mots de passe et cookies des navigateurs, Messages, Mail, Notes, Contacts, tous les fichiers cachés de ton dossier (~/.zshrc…), LaunchAgents, Préférences, réglages et code de MacAI, quelle que soit la façon d'écrire le chemin (majuscules, liens, `/System/Volumes/Data/…`) |
| **Annoncé** | déplacer, renommer, quitter une appli, cliquer ou taper dans une appli, Wi-Fi, mode sombre |
| **Libre** | lire, chercher, ouvrir, créer, résumer… |
| **Pièges** | ce qu'il lit est une **donnée, jamais un ordre** (testé avec un mail de phishing qui lui ordonnait d'ouvrir une adresse avec un code : refusé) |
| **Sans toi** | une tâche planifiée ne peut rien confirmer : envoi, suppression, achat refusés d'office |
| **À la voix** | refuser oui, accepter non (il faut cliquer) |
| **Modèle remplacé** | l'empreinte des modèles est retenue ; si un programme remplace le modèle par un autre, MacAI refuse de s'en servir (`macai modeles --accepter` après une mise à jour volontaire) |
| **Autorisation manquante** | il s'arrête et te dit exactement quoi activer, au lieu de tourner en rond |
| **Journal** | tout ce qu'il fait est noté dans `journal.jsonl` (lisible par toi seul) |

**Niveau d'autonomie** (`macai.toml`, `[agent] autonomie`) : `equilibre` (défaut : les actions sensibles sont
confirmées) ou `prudent` (les modifications le sont aussi). `autonome` retire seulement les annonces, **jamais** les
confirmations. Il ne peut être réglé qu'à la main dans le fichier, pas par un autre programme.

Le détail des protections, des relectures de sécurité et de leurs limites est dans [PLAN.md](PLAN.md) (décisions
D27 à D58) et [A_VALIDER.md](A_VALIDER.md) (« Limites connues »).

---

## 7. Limites : ce qu'il ne sait pas (encore) faire

Il faut le savoir pour ne pas être déçu.

### Liées au modèle (4 milliards de paramètres, sur 8 Go)

- **Il se trompe parfois de méthode** : il peut choisir un outil maladroit (ouvrir un Terminal pour lire un fichier),
  s'arrêter à mi-chemin ou mal comprendre une demande longue et ambiguë. Les garde-fous l'empêchent de faire des
  dégâts, et le bilan honnête t'empêche d'être trompé, mais il faut parfois **reformuler**, plus court et plus précis.
- **Les tâches longues** (plus de 10 étapes) ou qui demandent beaucoup de réflexion sont hors de portée : découpe-les.
- **Ses connaissances générales** sont limitées et peuvent être anciennes : pour un fait précis, il cherche sur le web.
  Pour une question complexe, demande-lui de **demander à Claude**.
- **Vitesse** : 10 à 30 s par demande passée à l'IA (les commandes directes sont instantanées).

### Liées au Mac et aux applications

- **Sans les autorisations macOS**, une bonne partie ne marche pas (voir la section 2).
- **Chrome** : sans « Autoriser JavaScript à partir des Apple Events », il ne peut ni lire ni cliquer dans les pages
  (YouTube s'ouvre, la vidéo ne se lance pas toute seule). Safari et Firefox ne sont pas pilotés page par page.
- **Applis sans accessibilité** (jeux, zones 3D, certaines applis Java ou Electron mal faites) : seule la vision peut
  aider, sans garantie.
- **Messages** : il peut envoyer, mais **pas lire** l'historique de tes conversations (protégé). WhatsApp, Slack,
  Discord : pilotés comme des applis ordinaires, chaque envoi confirmé.
- **Mails** : app Mail uniquement (pas Gmail dans le navigateur, pas Outlook). Pas d'étiquettes Gmail.
- **Installations** : pas de .pkg (mot de passe administrateur), pas d'app non notariée, pas de mise à jour d'une app
  déjà installée.
- **Mots de passe, double authentification, connexions** : jamais. C'est à toi de te connecter.
- **Bluetooth, luminosité, Ne pas déranger** : il ouvre la bonne rubrique des Réglages et peut cliquer, mais n'a pas
  d'interrupteur direct.
- **Fichiers iCloud non téléchargés** : ni lus ni indexés (les lire déclencherait leur téléchargement).
- **Historique de navigation, comptes en ligne** (« lance la vidéo la plus récente de mon historique YouTube ») : il
  n'y a pas accès.

### Liées à la sécurité (voulues)

- Les **confirmations** prennent un clic ; c'est le prix pour qu'un contenu piégé ne puisse rien faire à ta place.
  Par exemple, après avoir lu un fichier, ouvrir une adresse qui contient une information de ce fichier (un numéro
  de colis) demande ton accord.
- Ce qui **n'est pas couvert**, en connaissance de cause : un logiciel malveillant déjà installé sous ton compte ; un
  petit mot de passe en lettres seules glissé dans une question à une IA ; un numéro de carte réparti dans plusieurs
  champs. Détails dans [A_VALIDER.md](A_VALIDER.md).

### Langue

Pensé pour le **français** (commandes directes, voix, confirmations). Il comprend l'anglais, mais les commandes
instantanées ne reconnaissent que le français.

---

## 8. Vitesse et mémoire

Mesuré sur le MacBook Air M2 8 Go :

| Situation | Mémoire | Temps |
|---|---|---|
| Au repos (app + moteur + Ollama) | **~50 Mo** | 0 % de processeur |
| Commande directe (heure, calcul, volume, ouvrir, fermer, Wi-Fi…) | rien de plus | **< 1 s** |
| Demande à l'IA, modèle déjà chargé | +3,3 Go | 10 à 20 s |
| Première demande après 2 min de repos (chargement du modèle) | +3,3 Go | ~20 s avec le préchargement (~28 s sans) |
| Recherche par le sens | +1 Go (modèle d'embeddings) | 1 à 5 s |
| Vision (écran, image) | même modèle que l'agent | 10 à 30 s |
| Indexation | +1 Go, priorité basse | ~1 à 3 s par fichier, Mac inutilisé |

Les modèles sont **déchargés 2 minutes** après la dernière demande. Jamais deux gros modèles en même temps. Le modèle
écrit environ 20 jetons (morceaux de mots) par seconde et en lit environ 200 : c'est surtout la longueur de ce qu'il
doit lire (consignes, outils, documents) qui fait le temps de réponse.

---

## 9. Réglages (macai.toml et menu 🧠)

Fichier : `~/Library/Application Support/MacAI/macai.toml` (menu 🧠 > Ouvrir les réglages). Après modification :
menu 🧠 > Redémarrer le moteur.

```toml
[modeles]
agent = "qwen3.5:4b-q4_K_M"       # modèle qui comprend et agit
vision = "qwen3.5:4b-q4_K_M"      # écran et images (le même : rien à échanger en mémoire)
embeddings = "qwen3-embedding:0.6b" # recherche par le sens
garder_en_memoire = "2m"           # déchargé après 2 minutes sans usage
contexte = 8192                    # taille de la conversation que le modèle voit

[agent]
autonomie = "equilibre"            # "prudent" ou "equilibre" ("autonome" ne retire que les annonces)
etapes_max = 10                    # étapes au plus par demande
competence_apres_actions = 3       # taille minimale d'une tâche pour proposer une compétence
plan = "complexe"                  # plan avant d'agir : "complexe", "toujours" ou "jamais"

[recherche]
mails = true                       # indexer les mails (Réception et Envoyés)
notes = true                       # indexer les notes
lancer_apps = false                # ne jamais lancer Mail ou Notes pour indexer
dossiers = ["~"]                   # dossiers indexés
ignorer = ["Library", ".Trash", "node_modules", ...]  # noms de dossiers ignorés
images = true                      # indexer les images (OCR + étiquettes)
secteur_seulement = true           # sur batterie : seulement au-dessus de batterie_min
inactivite_minutes = 5             # Mac inutilisé depuis… avant d'indexer
batterie_min = 60                  # % minimal pour indexer sur batterie
taille_max_mo = 50                 # fichiers plus gros ignorés

[chrome]
application = "Google Chrome"

[alertes]                          # aussi dans le menu 🧠 > Alertes
batterie = true
memoire = true
disque = true
rendez_vous = true
telechargements = true

[voix]
reponse = "ecrit"                  # aussi dans le menu 🧠 > Réponses

[diagnostic]
actif = false                      # accès de diagnostic pour les essais : laisser à false

# Un logiciel qui propose un serveur MCP :
[[mcp]]
nom = "photocraft"
commande = ["/Users/math/.local/bin/photocraft-cli", "mcp"]
# env = { CLE = "…" }                           # variables d'environnement propres à ce serveur
# risques = { draw_shape = "modification" }     # alléger (ou durcir) la confirmation d'un outil précis
```

Changer de modèle : `macai banc --candidats` compare les modèles adaptés à 8 Go sur ton Mac ; voir aussi
[MODELES.md](MODELES.md). Après un changement de modèle volontaire : `macai modeles --accepter`.

---

## 10. Ligne de commande

| Commande | Rôle |
|---|---|
| `macai demander "…"` | pose une demande dans le Terminal (confirmations refusées) |
| `macai verifier` | contrôle toute l'installation (modèles, réglages d'Ollama, autorisations, Chrome, MCP, index, moteur) et écrit un rapport sur le Bureau |
| `macai outils` | liste des 102 outils |
| `macai indexer [--force] [--limite N]` | indexe maintenant (`--force` : même sur batterie ou Mac utilisé) |
| `macai modeles [--accepter]` | empreintes des modèles ; `--accepter` après une mise à jour volontaire |
| `macai classifieur [--erreurs]` | justesse du classifieur sur ses 147 demandes de test, et ce qu'il rate |
| `macai secret onshape` | enregistre des clés dans le Trousseau |
| `macai mcp tester` / `macai mcp detecter` | teste les serveurs MCP configurés / cherche ceux installés |
| `macai banc --scenarios [filtre]` | 68 demandes réelles passées dans le vrai moteur avec le vrai modèle, outils **simulés** (rien n'est exécuté) ; compare avec le passage précédent |
| `macai banc --candidats` | compare la vitesse et la justesse de plusieurs modèles |
| `macai serveur` | démarre le moteur (normalement lancé par l'app) |

---

## 11. Si quelque chose ne marche pas

| Problème | Solution |
|---|---|
| « Autorisation manquante » | Réglages Système > Confidentialité et sécurité > la rubrique indiquée > active MacAI ; s'il était déjà coché : retire-le (−), rajoute-le (+), relance MacAI |
| Il ne répond plus / reste « occupé » | bouton Stop, puis menu 🧠 > Redémarrer le moteur |
| « Le modèle local ne répond pas » | `macai verifier` ; Ollama doit tourner (le service se relance seul au démarrage du Mac) |
| « Le modèle … a changé depuis son installation » | si tu as mis le modèle à jour toi-même : `macai modeles --accepter` ; sinon, ne l'accepte pas et relance `./installer.sh` |
| Il ne trouve pas un fichier récent | « indexe maintenant », ou attends que le Mac soit inutilisé ; Spotlight complète en attendant |
| YouTube s'ouvre mais la vidéo ne démarre pas | autorise JavaScript à partir des Apple Events dans Chrome |
| La touche Fn ouvre les emojis | Réglages Système > Clavier > « Appuyer sur la touche 🌐 pour » : Ne rien faire |
| Il a mal compris | reformule plus court ; nomme l'appli et le fichier ; « annule » pour défaire |
| Comprendre ce qu'il a fait | menu 🧠 > Ouvrir le journal |
| Après une mise à jour, macOS redemande les autorisations | normal si le certificat « MacAI Local » a été recréé ; accepte-les de nouveau |

---

## 12. Où sont tes données

Tout est dans `~/Library/Application Support/MacAI/` (dossier lisible par toi seul) :

| Fichier | Contenu |
|---|---|
| `macai.toml` | réglages |
| `journal.jsonl` | tout ce qu'il a fait (demandes, outils, réponses ; textes longs raccourcis), 5 Mo au plus + un ancien |
| `index.db` | index de recherche : extraits de tes documents, mails et notes, vecteurs de sens |
| `memoire.db` | souvenirs, **chiffrés** |
| `competences/` | compétences apprises (fichiers JSON lisibles) |
| `taches.json` | tâches planifiées |
| `annulations.json` | les 50 dernières actions annulables |
| `reglages.json` | choix faits dans le menu 🧠 |
| `modeles_empreintes.json` | empreintes des modèles |
| `serveur.json` | port et jeton du moteur (pendant qu'il tourne) |
| `moteur.log`, `ollama.log` | journaux techniques (aucun texte de demande dans celui d'Ollama) |

Rien de tout cela ne quitte le Mac. Supprimer le dossier efface tout (MacAI repart de zéro).

---

## 13. Architecture et développement

```
MacAI.app (Swift, ~25 Mo)                 moteur Python (~35 Mo au repos)              Ollama (~20 Mo au repos)
  barre des menus, panneau ⌥Espace  HTTP    agent (boucle), routeur, commandes    HTTP   modèles chargés à la
  voix (SpeechAnalyzer, Apple)     ───────►  directes, 102 outils, recherche,     ─────►  demande, déchargés
  dictée Fn, ⌥⇧T, ⌥⇧S, alertes     ◄───────  mémoire, compétences, MCP, tâches            après 2 min
  lance et surveille le moteur    événements
```

- L'app lance le moteur (Python isolé, environnement minimal) et le relance s'il s'arrête ; les autorisations
  accordées à MacAI.app couvrent le moteur.
- Code : `src/macai/` (Python 3.12, stdlib au maximum, imports paresseux), `app/` (Swift, SwiftPM),
  `installer.sh`. Structure détaillée dans [CLAUDE.md](CLAUDE.md), décisions dans [PLAN.md](PLAN.md), cahier des
  charges dans [CAHIER_DES_CHARGES.md](CAHIER_DES_CHARGES.md).
- Tests : `.venv/bin/python -m pytest` (442 tests, ~10 s ; le code propre au Mac est testé avec AppleScript simulé,
  ce qui permet de développer aussi sur Windows).
- Qualité réelle : `macai banc --scenarios` (68 demandes, vrai modèle, outils simulés ; 68/68 le 25/11, 13 s par
  demande en moyenne).
- Sécurité : `tests/test_securite.py` rejoue chaque attaque trouvée lors des relectures.
