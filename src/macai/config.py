"""Chemins et configuration (fichier TOML commenté, créé au premier lancement)."""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def dossier_donnees() -> Path:
    if env := os.environ.get("MACAI_HOME"):
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/MacAI"
    return Path.home() / ".macai"


CONFIG_PAR_DEFAUT = """\
# Configuration de MacAI. Les lignes commençant par # sont des commentaires.
# Après modification : menu MacAI > Redémarrer le moteur.

[modeles]
# Modèles Ollama (locaux). Confirmés par `macai banc` sur ton Mac.
agent = "qwen3:4b"
vision = "qwen3-vl:2b"
embeddings = "qwen3-embedding:0.6b"
# Durée pendant laquelle un modèle reste en mémoire après usage.
garder_en_memoire = "2m"
contexte = 8192

[agent]
# "equilibre" (recommandé), "prudent" ou "autonome"
autonomie = "equilibre"
etapes_max = 10
# Proposer de créer une compétence après une tâche réussie d'au moins N actions.
competence_apres_actions = 3

[recherche]
# Dossiers indexés (~ = dossier personnel).
dossiers = ["~"]
ignorer = ["Library", ".Trash", "node_modules", ".git", ".venv", "venv", "__pycache__",
           ".cache", "Caches", "DerivedData", "Pods", "build", "dist", ".npm", ".gradle",
           "Applications", "Movies", "Music"]
images = true
# N'indexer que sur secteur et après N minutes sans utilisation du Mac.
secteur_seulement = true
inactivite_minutes = 5
taille_max_mo = 50

[chrome]
application = "Google Chrome"

[voix]
# "ecrit" ou "oral" (modifiable depuis le panneau).
reponse = "ecrit"

# Serveurs MCP : chaque logiciel qui en propose un devient pilotable.
# [[mcp]]
# nom = "photocraft"
# commande = ["/Applications/PhotoCraft.app/Contents/MacOS/photocraft", "mcp"]
"""


@dataclass
class Config:
    donnees: Path
    modeles: dict = field(default_factory=dict)
    agent: dict = field(default_factory=dict)
    recherche: dict = field(default_factory=dict)
    chrome: dict = field(default_factory=dict)
    voix: dict = field(default_factory=dict)
    mcp: list = field(default_factory=list)

    @property
    def fichier(self) -> Path:
        return self.donnees / "macai.toml"

    def chemin(self, nom: str) -> Path:
        return self.donnees / nom


def charger(dossier: Path | None = None) -> Config:
    dossier = Path(dossier or dossier_donnees())
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / "macai.toml"
    if not fichier.exists():
        fichier.write_text(CONFIG_PAR_DEFAUT, encoding="utf-8")
    defaut = tomllib.loads(CONFIG_PAR_DEFAUT)
    try:
        perso = tomllib.loads(fichier.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        print(f"macai.toml invalide ({e}) : valeurs par défaut utilisées.", file=sys.stderr)
        perso = {}
    sections = {k: {**defaut.get(k, {}), **perso.get(k, {})}
                for k in ("modeles", "agent", "recherche", "chrome", "voix")}
    return Config(donnees=dossier, mcp=perso.get("mcp", []), **sections)
