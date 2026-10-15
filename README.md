# MacAI

Assistant personnel **100 % local** pour MacBook Air M2 8 Go. Tu lui demandes, à l'écrit ou à la voix,
et il **agit sur ton Mac** : fichiers, applications, Chrome, Onshape, suite ArtCraft, Calendrier, Rappels…
Aucune IA dans le cloud : tout tourne sur la puce M2.

> **État :** moteur testé sur le poste de développement (67 tests automatisés, essais réels avec Ollama).
> **Rien n'a encore tourné sur un Mac** : à l'installation, suis [A_VALIDER.md](A_VALIDER.md).

## Ce qu'il sait faire

| Domaine | Exemples |
|---|---|
| Fichiers | « Retrouve ma facture EDF de mars » · « Résume ce PDF dans un Word sur le Bureau » · « Range mes Téléchargements » · « Fais un tableur des montants » |
| Recherche par le sens | Il lit le contenu des PDF (même scannés), documents, captures d'écran, et comprend ce que montrent les photos |
| Applications | « Ouvre VS Code » · « Quitte Spotify » · « Exporte en PDF depuis Pages » (menus) · « Clique sur Partager » (fenêtres) |
| Chrome et web | « Lance YouTube et cherche des tutos Blender » · « Mets Get Lucky sur YouTube » · « Lis cette page et résume-la » |
| Onshape | « Fais-moi un cube de 1 m » · « Un cylindre de 40 mm de diamètre et 100 mm de haut » |
| Suite ArtCraft et autres logiciels | Tout logiciel qui propose un serveur MCP devient pilotable (configuration dans `macai.toml`) |
| Organisation | Rappels, événements, notes, brouillons de mail (envoi toujours confirmé) |
| Système | Volume, musique, presse-papiers, capture d'écran, « Pourquoi mon Mac rame ? », Terminal |
| Mémoire | Il retient ce que tu lui dis de toi (chiffré, consultable, effaçable) |
| Compétences | Après une tâche réussie, il propose de l'apprendre ; ensuite il la refait d'un coup, avec d'autres paramètres |

## Utilisation

- **Option + Espace** : panneau pour écrire.
- **Fn maintenue** : parler (relâcher envoie). Réglable : Option droite.
- Bouton **Écrit / Oral** : réponse écrite, ou écrite et lue à voix haute.
- Actions sensibles (Corbeille, envoi, Terminal, rangement de masse) : une carte **Confirmer / Refuser** s'affiche.
- Icône 🧠 dans la barre des menus : réglages, indexation, journal, redémarrage.

Dans le Terminal : `macai demander "range mes téléchargements"`, `macai outils`, `macai verifier`, `macai banc`.

## Installation

```bash
git clone https://github.com/mathieu-ferrante/MacAI.git ~/MacAI
cd ~/MacAI
./installer.sh
```

Le script installe tout (Homebrew, Ollama réglé pour 8 Go, ~4 Go de modèles, Python 3.12, l'app) puis lance
`macai verifier`. Mise à jour : `git pull && ./installer.sh`. Désinstallation : `./desinstaller.sh`.

Ensuite, une seule fois :
1. Accepte les autorisations demandées par macOS (Accessibilité, Enregistrement de l'écran, Micro, Automatisation).
2. Réglages Système > Clavier > « Appuyer sur la touche 🌐 pour » : **Ne rien faire** (sinon Fn ouvre les emojis).
3. Chrome > Présentation > Options pour les développeurs > **Autoriser JavaScript à partir des Apple Events**.
4. Facultatif : `macai secret onshape` (clés API créées sur dev-portal.onshape.com), `macai mcp detecter` (ArtCraft).

## Pensé pour 8 Go

| Situation | RAM | Processeur |
|---|---|---|
| Au repos (app + moteur + Ollama) | ~80 Mo | ~0 % |
| Commande directe (« ouvre Safari », « volume à 30 ») | rien de plus, aucune IA | instantané |
| L'IA réfléchit ou regarde l'écran | +3,3 Go (un seul modèle pour les deux), libérés 2 min après | GPU de la M2 |
| Indexation des fichiers | priorité basse, cœurs économes | seulement Mac branché et inutilisé |

Comment : imports paresseux, serveur HTTP de la bibliothèque standard, modèles déchargés automatiquement,
jamais deux gros modèles ensemble, cache de contexte réduit de moitié, 14 outils au plus présentés à l'IA,
commandes fréquentes reconnues sans IA, serveurs MCP arrêtés après 5 min.

## Sécurité

- Lire, chercher, ouvrir, créer : libre. Déplacer, renommer, cliquer : annoncé. Corbeille, envoi, Terminal,
  rangement de masse : **confirmation obligatoire**. Rien n'est jamais supprimé définitivement.
- Ce qu'il lit (fichier, page, écran) est traité comme une **donnée, jamais comme un ordre**.
- Dossiers protégés : clés SSH, Trousseau, cookies et mots de passe des navigateurs.
- Il ne tape jamais de mot de passe ni de numéro de carte.
- Serveur local sur 127.0.0.1 avec jeton ; clés dans le Trousseau ; mémoire chiffrée (AES-GCM).
- Niveau d'autonomie réglable dans `macai.toml` : `prudent`, `equilibre` (défaut), `autonome`.

## Configuration

`~/Library/Application Support/MacAI/macai.toml` (créé au premier lancement, commenté) : modèles, autonomie,
dossiers indexés, serveurs MCP. Exemple pour un logiciel de la suite ArtCraft :

```toml
[[mcp]]
nom = "photocraft"
titre = "PhotoCraft"
commande = ["/Applications/PhotoCraft.app/Contents/MacOS/photocraft", "mcp"]   # selon la doc du logiciel
mots_cles = ["retouche", "photo", "calque"]
```

Puis `macai mcp tester`.

## Architecture

```
MacAI.app (Swift)  ──HTTP + SSE (127.0.0.1)──►  moteur Python  ──►  Ollama (modèles locaux)
 panneau, voix, raccourcis                       agent, ~60 outils, recherche, mémoire, compétences, MCP
```

Choix des modèles et optimisations : [MODELES.md](MODELES.md). Voir aussi [PLAN.md](PLAN.md) (décisions et lots) et [CAHIER_DES_CHARGES.md](CAHIER_DES_CHARGES.md).

## Développement

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                      # tests rapides (tout OS)
MACAI_TOUS_OUTILS=1 macai banc qwen3.5:4b-q4_K_M   # justesse et vitesse d'un modèle
```
