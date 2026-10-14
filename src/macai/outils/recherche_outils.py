"""Recherche de fichiers par le sens (index local) + Spotlight en complément."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .base import Resultat, outil

GENRES = ["image", "capture", "pdf", "document", "tableur", "presentation", "code", "autre"]


def _date_min(periode: str) -> float | None:
    p = (periode or "").lower()
    maintenant = datetime.now()
    if not p:
        return None
    if "aujourd" in p:
        return maintenant.replace(hour=0, minute=0).timestamp()
    if "hier" in p:
        return (maintenant - timedelta(days=1)).replace(hour=0, minute=0).timestamp()
    if m := re.search(r"(\d+)\s*(jour|semaine|mois|an)", p):
        n, unite = int(m.group(1)), m.group(2)
        jours = {"jour": 1, "semaine": 7, "mois": 31, "an": 365}[unite] * n
        return (maintenant - timedelta(days=jours)).timestamp()
    if "semaine" in p:
        return (maintenant - timedelta(days=7)).timestamp()
    if "mois" in p:
        return (maintenant - timedelta(days=31)).timestamp()
    return None


def spotlight(requete: str, nombre: int = 10) -> list[str]:
    """Complément quand l'index est vide ou incomplet : Spotlight (noms et contenus)."""
    if sys.platform != "darwin":
        return []
    mots = [m for m in re.findall(r"\w{3,}", requete)][:5]
    if not mots:
        return []
    expr = " && ".join(f'(kMDItemDisplayName == "*{m}*"cd || kMDItemTextContent == "{m}"cd)' for m in mots)
    try:
        r = subprocess.run(["mdfind", "-onlyin", str(Path.home()), expr], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return []
    return [l for l in r.stdout.splitlines() if "/Library/" not in l and "/." not in l][:nombre]


@outil("rechercher_fichiers", "Retrouve des fichiers sur le Mac en décrivant leur contenu ou leur nom "
       "(ex. « facture EDF de mars », « photo du chat sur le canapé », « cours sur TCP »). Comprend le sens, "
       "lit le texte des PDF, scans, captures d'écran et ce que montrent les photos.", "recherche",
       {"requete": ("string", "description de ce qu'on cherche"),
        "genre": ("string", "type de fichier, facultatif", GENRES),
        "periode": ("string", "ex. « aujourd'hui », « cette semaine », « 3 mois », facultatif"),
        "dossier": ("string", "limiter à un dossier, facultatif"),
        "nombre": ("integer", "nombre de résultats (8 par défaut)")}, requis=["requete"], mac_seulement=False)
def rechercher_fichiers(ctx, requete, genre="", periode="", dossier="", nombre=8):
    index = ctx.service("index")
    trouvailles = []
    if index is not None:
        from ..mac.commun import chemin
        genres = [genre] if genre else None
        if genre == "image":
            genres = ["image", "capture"]
        d = chemin(dossier) if dossier else None
        if d is not None and not d.is_dir():
            d = None  # dossier inventé par le modèle : ignoré plutôt que de tout filtrer
        trouvailles = index.rechercher(requete, int(nombre or 8), genres=genres,
                                       dossier=str(d) if d else None, apres=_date_min(periode))
    lignes = []
    for t in trouvailles:
        date = time.strftime("%d/%m/%Y", time.localtime(t.mtime or 0))
        extrait = re.sub(r"\s+", " ", t.extrait.split("\n", 1)[-1])[:220]
        lignes.append(f"- {t.chemin}  ({t.genre}, modifié le {date})\n  « {extrait} »")
    deja = {t.chemin for t in trouvailles}
    complements = [c for c in spotlight(requete) if c not in deja][: max(0, 5 - len(trouvailles))]
    lignes += [f"- {c}  (trouvé par Spotlight)" for c in complements]
    etat = index.stats() if index else {"fichiers": 0}
    conseil = " L'index est encore vide : l'indexation se fait Mac branché et inutilisé." if not etat["fichiers"] else ""
    if not lignes:
        return Resultat(True, f"Aucun fichier trouvé pour « {requete} ».{conseil}", {"resultats": []})
    if conseil:
        lignes.append(f"(Recherche par le sens indisponible :{conseil})")
    return Resultat(True, "\n".join(lignes), {"resultats": [t.chemin for t in trouvailles] + complements})


@outil("etat_index", "Indique combien de fichiers sont indexés pour la recherche et quand date le dernier passage.",
       "recherche", {}, mac_seulement=False)
def etat_index(ctx):
    index = ctx.service("index")
    if index is None:
        return "Recherche indisponible."
    s = index.stats()
    dernier = index.etat("dernier_passage")
    quand = time.strftime("%d/%m à %H:%M", time.localtime(float(dernier))) if dernier else "jamais"
    return (f"{s['fichiers']} fichiers indexés ({s['avec_contenu']} avec leur contenu, {s['extraits']} extraits, "
            f"{s['taille_mo']} Mo). Dernier passage : {quand}.")


@outil("indexer_maintenant", "Lance l'indexation des fichiers tout de suite, même si le Mac est utilisé "
       "(priorité basse, sur les cœurs économes).", "recherche", {}, mac_seulement=False)
def indexer_maintenant(ctx):
    from ..recherche.indexeur import lancer_en_arriere_plan
    lancer_en_arriere_plan(force=True)
    return "Indexation lancée en arrière-plan. Elle reste discrète : tu peux continuer à travailler."
