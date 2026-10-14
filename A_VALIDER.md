# À valider sur le Mac

Tout a été codé et testé sur le poste de développement (Windows, sans Mac). Voici, dans l'ordre, ce qu'il faut
lancer sur le MacBook Air pour valider — avec le résultat attendu. **Si une étape échoue, renvoie-moi la sortie
indiquée** : je corrige à partir de là.

| # | À faire | Résultat attendu | Si ça échoue, renvoie |
|---|---|---|---|
| V1 | `./installer.sh` | Se termine par le rapport de vérification et le cadre « MacAI est installé » | tout le texte du Terminal |
| V2 | (inclus dans V1) compilation de l'app | `✓ build/MacAI.app prête` | les lignes `error:` de `swift build` |
| V3 | `macai verifier` | Que des ✓ (les ! sur Onshape/MCP/Index sont normaux au début) ; « Essai de l'agent : appel d'outil correct » | `~/Desktop/MacAI-verification.txt` |
| V4 | Moniteur d'activité, MacAI ouvert depuis 5 min sans rien demander | MacAI + python + ollama < 120 Mo au total, ~0 % de processeur | capture du Moniteur d'activité |
| V5 | Option + Espace, taper « quelle heure est-il » | Panneau au centre, réponse instantanée | `~/Library/Application Support/MacAI/moteur.log` |
| V6 | « ouvre Safari », puis « volume à 30 », puis « pause » | Safari s'ouvre ; volume à 30 ; la musique s'arrête | `moteur.log` + message affiché |
| V7 | Maintenir Fn, dire « ouvre les notes », relâcher | Le texte s'écrit pendant que tu parles, Notes s'ouvre | message affiché dans le panneau |
| V8 | « mets la vidéo Daft Punk Get Lucky sur YouTube » | Chrome ouvre YouTube et lance la vidéo (si JavaScript Apple Events activé) | message affiché |
| V9 | « crée un document Word sur le bureau avec un plan de révision en 3 parties » | Fichier .docx sur le Bureau, titres et puces | message + `journal.jsonl` (dernières lignes) |
| V10 | « range mes téléchargements » | Carte orange « Ranger N fichiers… » → Confirmer → sous-dossiers créés | message affiché |
| V11 | `macai indexer --force --limite 300` puis « retrouve un document qui parle de … » (un vrai sujet de tes fichiers) | Le bon fichier dans les premiers résultats | sortie de `macai indexer` + la réponse |
| V12 | Ouvrir TextEdit, puis « dans TextEdit, écris Bonjour et enregistre sur le bureau » | Il lit la fenêtre, tape le texte, utilise le menu Fichier | message + `journal.jsonl` |
| V13 | « qu'est-ce qu'il y a sur mon écran ? » | Description correcte (après autorisation Enregistrement de l'écran) | message affiché |
| V14 | « retiens que je préfère les réponses courtes », puis plus tard « qu'est-ce que tu sais de moi ? » | Le fait est retenu et restitué | message affiché |
| V15 | Une tâche en 3 étapes ou plus (ex. « trouve ma dernière facture, lis-la et fais un tableur avec le montant ») | Carte « Je peux retenir cette tâche… » → Créer → `lister mes compétences` la montre | message + dossier `competences/` |
| V16 | `macai secret onshape` puis « fais-moi un cube de 1 mètre dans Onshape » | Nouveau document Onshape avec un cube de 1 m, ouvert dans Chrome | message affiché (ne jamais envoyer les clés) |
| V17 | `macai mcp detecter`, configurer un logiciel ArtCraft dans `macai.toml`, `macai mcp tester` | « photocraft : N outils » | sortie de `macai mcp tester` |
| V18 | `macai banc qwen3:4b llama3.2:3b` (autres modèles : `ollama pull` d'abord) | Tableau justesse/vitesse/RAM et un modèle recommandé | fichier JSON indiqué à la fin |

## Points incertains (à surveiller en priorité)

- **App Swift** : écrite sans pouvoir être compilée ici (SpeechAnalyzer est récent). Erreurs de compilation possibles en V2.
- **Touche Fn** : selon les réglages clavier, macOS peut l'intercepter (voir README, étape 2). Repli : menu 🧠 > Touche pour parler > Option droite.
- **Modèles** : `qwen3:4b` / `qwen3-vl:2b` / `qwen3-embedding:0.6b` sont des choix par défaut ; V18 tranche.
- **Onshape** : la création d'esquisse par l'API n'a pas pu être essayée sans compte ; si V16 échoue, renvoie le message d'erreur Onshape.
- **Mémoire au repos (V4)** : ~80 Mo est une estimation, à confirmer.
