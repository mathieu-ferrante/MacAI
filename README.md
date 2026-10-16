# MacAI

Assistant personnel **100 % local** pour ton MacBook Air M2 8 Go. Tu lui parles ou tu lui écris, et **il agit sur
ton Mac** : fichiers, applications, mails, agenda, web, Claude, ArtCraft, Onshape… Son IA tourne sur la puce M2
(Ollama, modèle `qwen3.5:4b`) : rien de ce que tu lui demandes ne part dans le cloud.

> **État (16/10/2026)** : installé et testé sur ton Mac. 285 tests automatiques, banc de 62 demandes réelles en
> français (`macai banc --scenarios`). Ce qui reste à essayer de ta part est listé dans [A_VALIDER.md](A_VALIDER.md).

---

## 1. Comment lui parler

| Raccourci | Ce que ça fait |
|---|---|
| **⌥ Espace** | Ouvre le panneau pour écrire une demande |
| **⌥ ⇧ Espace** (maintenus) | Parler à MacAI : la demande part quand tu relâches |
| **Fn** (maintenue) | **Dictée partout** : le texte s'écrit à l'endroit du curseur, dans n'importe quelle appli |
| **⌥ ⇧ T** | Menu sur le **texte sélectionné** : corriger, reformuler, traduire, résumer, expliquer, répondre, écouter, autre consigne |
| **⌥ ⇧ S** | Sélectionner une **zone de l'écran** : expliquer, traduire, extraire le texte, extraire un tableau (Excel), poser une question |
| **Échap** | Ferme le panneau, coupe la voix et l'écoute |

Dans le **Terminal** : `macai demander "range mes téléchargements"`.

### Mode vocal (menu 🧠 > Réponses)

- **Écrites**, **Orales** ou **Écrites et orales** : tu choisis comment MacAI répond.
- **Conversation vocale** : après sa réponse orale, MacAI réécoute tout seul. Tu enchaînes sans toucher au clavier ;
  « merci », « stop » ou « c'est tout » terminent.
- Les **confirmations** et les **plans** peuvent se valider à la voix : « oui », « vas-y » ou « non », « annule ».

---

## 2. Ce qu'il sait faire, avec des exemples

### Fichiers et documents
- « Retrouve ma facture EDF de mars » : il lit le **contenu** des PDF (même scannés), des documents, des captures
  et des photos, pas seulement les noms.
- « Résume le fichier rapport.pdf », « lis-moi ce document ».
- « Crée un document Word sur le bureau avec un plan de révision en 3 parties », « fais un tableur avec loyer 600,
  courses 250 », « une présentation de 5 diapositives sur le recyclage ».
- « Range mes téléchargements » : rangement par type, après confirmation.
- « Déplace facture.pdf dans Documents/Factures », « renomme scan1.pdf en contrat.pdf ».
- **« Annule »** remet en place la dernière action sur des fichiers : déplacement, rangement, Corbeille, renommage ou création.

### Texte et écran (dans n'importe quelle appli)
- Sélectionne un texte puis **⌥⇧T** :
  - corriger, reformuler ou traduire remplacent le texte sur place ;
  - résumer, expliquer ou « répondre à ce message » affichent le résultat dans le panneau ;
  - écouter le lit à voix haute.
- « Corrige / traduis / résume ce que j'ai copié » : travaille sur le presse-papiers.
- **⌥⇧S** sur un message d'erreur, une page en anglais, un tableau dans un PDF…
- « Qu'est-ce qu'il y a sur mon écran ? », « décris l'image photo.jpg ».

### Applications
- « Ouvre Safari », « ferme Spotify », « quelles applis sont ouvertes ? ».
- « Ouvre TextEdit et écris Bonjour », « dans TextEdit, exporte le document en PDF » : il lit la fenêtre et les
  menus, puis clique et tape.
- « Ouvre les réglages Bluetooth » (ou Wi-Fi, Son, Écrans, Batterie, Clavier, Notifications, Mode sombre…).
- **Guide** : « comment on fait pour exporter en PDF dans TextEdit ? ». Il donne le chemin du menu et **surligne**
  l'endroit à l'écran.
- « Ouvre la calculatrice et calcule 12 fois 7 ».

### Claude et ChatGPT
- « Demande à Claude quels sont les meilleurs claviers mécaniques » : il passe Claude en mode chat, ouvre une
  nouvelle conversation, envoie la question et te rapporte la réponse.
- « Écris à ChatGPT pour lui demander une recette de crêpes ».
- Il a accès à toutes les options de Claude, mais **ne demandera jamais de crédits d'utilisation**, même si la
  limite est atteinte.

### Mails, messages, notes, agenda
- « Qu'est-ce que j'ai demain ? » donne la journée complète : rendez-vous (récurrents compris) et rappels.
- « Mets un rappel demain à 9h pour appeler la banque », « ajoute un dentiste jeudi à 14h ».
- « Résume mes mails non lus ».
- « **Trie mes mails** » : il les classe en À traiter, À lire, Notifications, Pubs et newsletters. Il ne supprime
  jamais rien.
- « Réponds au dernier mail de Paul que je serai là jeudi » : un brouillon s'ouvre dans Mail, **non envoyé**.
- « Envoie un SMS à Maman : j'arrive » : confirmation obligatoire, avec le texte complet.
- « Retrouve le mail où Paul parlait du devis » : la recherche porte aussi sur les mails et les notes.
- « Crée une note avec la liste des courses », « ajoute du lait à la note Courses ».

### Argent et papiers
- « **Combien j'ai dépensé** en essence ce mois-ci ? » : total et détail tirés de tes factures et tickets indexés.
- « Fais-moi un tableur de mes dépenses du mois » : un fichier Excel sur le Bureau.
- « **Classe les papiers** de mes téléchargements » : factures, impôts, banque, assurance, santé, contrats, fiches de
  paie, billets.
  - Ils sont renommés (« 2026-10 EDF facture 84,20 € ») et rangés dans `Documents/Administratif/…`.
  - Tout est annulable.
  - Ça peut se faire tout seul : menu 🧠 > Classer automatiquement les téléchargements.

### Web
- « Quels sont les horaires de la poste de Toulon ? » : il lit les pages et **cite la source**. Il n'invente pas.
- « Mets la vidéo Daft Punk Get Lucky sur YouTube », « cherche des tutos Blender sur YouTube », « ouvre YouTube ».
- « Lis cette page et résume-la ».

### Logiciels ArtCraft et Onshape
- **PhotoCraft, VectorCraft, LightCraft, EffectCraft, FilmCraft** sont pilotables :
  - « avec PhotoCraft, convertis cette image en JPG » ;
  - « avec VectorCraft, dessine un cercle rouge et exporte-le » ;
  - « dans EffectCraft, crée une composition avec un titre animé ».
- Ils agissent **sans te demander confirmation à chaque étape**. Seuls supprimer, envoyer ou écraser un fichier existant sont confirmés.
- « Quelles compétences toutes prêtes tu proposes ? » liste les recettes ArtCraft : conversion d'images, logo texte,
  import de photos dans LightCraft… Elles s'installent sur demande.
- **Onshape** : « fais-moi un cube de 1 mètre », « un cylindre de 40 mm de diamètre » (après `macai secret onshape`).

### Système
- « Volume à 30 », « pause », « chanson suivante », « prends une capture d'écran ».
- « Pourquoi mon Mac rame ? », « combien de batterie il me reste ? », « quelle heure est-il ? ».
- « Exécute la commande ls -la ~/Documents » : sans confirmation si c'est une simple lecture, sinon il demande.

### Mémoire et compétences
- « Retiens que je préfère les réponses courtes », « qu'est-ce que tu sais de moi ? », « oublie ça ».
  - La mémoire est chiffrée.
  - Il refuse de retenir des mots de passe, codes ou numéros de carte.
- **Compétences**, des tâches qu'il sait refaire d'un coup :
  - quand tu refais **deux fois** la même tâche (au moins 3 étapes), il propose d'en faire une compétence, et
    seulement dans ce cas ;
  - **démonstration** : menu 🧠 > Enregistrer une démonstration. Tu fais la tâche une fois, il propose de
    l'apprendre.

### Automatique (menu 🧠)
- **Briefing du matin** à l'heure de ton choix : agenda du jour, mails importants, rappels.
- **Tâches planifiées** : « tous les lundis à 9h, range mes téléchargements », « chaque matin, résume mes mails ».
  Une notification s'affiche à la fin.
- **Alertes** : batterie sous 20 %, mémoire saturée, disque presque plein, rendez-vous dans 15 min, téléchargement
  terminé. Chacune s'active ou se désactive.
- **Plan avant d'agir** : pour une tâche d'au moins 3 étapes, il montre d'abord ce qu'il va faire. Tu choisis Valider,
  Modifier ou Annuler, ou « Toujours » / « Jamais » dans le menu.

---

## 3. Ce qu'il ne fait jamais, ou seulement avec ton accord

| Règle | Détail |
|---|---|
| **Jamais** | Acheter, payer, demander des crédits ou une utilisation supplémentaire, s'abonner ; taper un mot de passe ou un numéro de carte ; retenir un secret ; supprimer définitivement (tout passe par la Corbeille) |
| **Confirmation** | Mettre à la Corbeille ; envoyer un mail ou un message ; commandes Terminal qui modifient quelque chose ; écraser un fichier existant ; écrire dans un Terminal ; cliquer Envoyer / Publier / Partager / Supprimer |
| **Libre** | Tout le reste : ouvrir, lire, créer, ranger, cliquer, taper, piloter ArtCraft ou Claude… |
| **Protégé** | Clés SSH, Trousseau, mots de passe et cookies des navigateurs, messageries, fichiers de démarrage (~/.zshrc…), réglages et code de MacAI |
| **Pièges** | Ce qu'il lit (page web, mail, document, écran) est une **donnée, jamais un ordre** : un fichier piégé qui dit « supprime tout » est ignoré (testé) |
| **Sans toi** | Une tâche planifiée qui tournerait en ton absence ne peut rien confirmer : envoi, suppression et achat y sont refusés d'office |
| **Autorisation manquante** | Il s'arrête et te dit exactement quoi activer dans Réglages Système |

Niveau d'autonomie (menu 🧠 ou `macai.toml`) : `prudent`, `equilibre` (défaut) ou `autonome`.

---

## 4. Léger sur 8 Go

| Situation | Mémoire |
|---|---|
| Au repos (app + moteur + Ollama) | **~50 Mo** (mesuré : 18 + 20 + 11 Mo) |
| Commande directe (« ouvre Safari », « volume à 30 », « annule », heure, date…) | rien de plus, instantané, sans IA |
| L'IA réfléchit ou regarde l'écran | +3,2 Go le temps de la demande, libérés 2 minutes après |
| Indexation des fichiers, mails et notes | seulement Mac branché et inutilisé, priorité basse |

Une demande à l'IA prend en général **10 à 30 secondes**.

---

## 5. Installation et mise à jour

```bash
cd ~/MacAI && git pull && ./installer.sh
```

- La première fois, macOS peut demander « codesign veut utiliser la clé MacAI Local » : entre ton mot de passe et
  choisis **Toujours autoriser**. L'app est signée avec ce certificat local pour que macOS **garde tes autorisations**
  d'une mise à jour à l'autre.
- Accepte les autorisations demandées :
  - Accessibilité et Enregistrement de l'écran ;
  - Micro ;
  - Bureau, Documents et Téléchargements ;
  - Calendriers et Rappels ;
  - Automatisation de Mail, Notes et Chrome ;
  - Notifications.
- Pour que Fn serve à la dictée : Réglages Système > Clavier > « Appuyer sur la touche 🌐 pour » : **Ne rien faire**.
- Pour YouTube et la lecture des pages dans Chrome : Chrome > Présentation > Options pour les développeurs >
  **Autoriser JavaScript à partir des Apple Events**.
- Facultatif : `macai secret onshape` (clés API Onshape).

Désinstallation : `./desinstaller.sh`.

---

## 6. Si quelque chose ne marche pas

| Problème | Solution |
|---|---|
| « Autorisation manquante » | Réglages Système > Confidentialité et sécurité > la rubrique indiquée > active MacAI. S'il était déjà coché : retire-le (−), rajoute-le (+), puis relance MacAI |
| Il ne répond plus | Menu 🧠 > Redémarrer le moteur |
| Comprendre ce qu'il a fait | Menu 🧠 > Ouvrir le journal, ou `~/Library/Application Support/MacAI/journal.jsonl` |
| Vérifier l'installation | `macai verifier` (rapport sur le Bureau) |
| Mesurer la qualité | `macai banc --scenarios` (62 demandes, outils simulés : rien n'est exécuté) |

Commandes utiles : `macai outils` (liste des ~220 outils), `macai mcp tester` (ArtCraft), `macai indexer --force`.

---

## 7. Pour aller plus loin

- Réglages : `~/Library/Application Support/MacAI/macai.toml` (modèles, autonomie, dossiers indexés, alertes, logiciels MCP).
- Décisions techniques : [PLAN.md](PLAN.md). Choix des modèles : [MODELES.md](MODELES.md).
- Cahier des charges : [CAHIER_DES_CHARGES.md](CAHIER_DES_CHARGES.md). Ce qu'il reste à valider : [A_VALIDER.md](A_VALIDER.md).

```
MacAI.app (Swift) ──HTTP + flux d'événements (127.0.0.1, jeton)──► moteur Python ──► Ollama (modèles locaux)
 panneau, voix, dictée, raccourcis, alertes            agent, ~220 outils, recherche, mémoire, compétences, MCP
```

Développement : `.venv/bin/python -m pytest` (285 tests, ~5 s).
