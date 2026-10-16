"""Compétences toutes faites (dossier modeles/) : recettes prêtes pour les logiciels connectés (ArtCraft…).

Jamais installées d'office : competences_proposees les liste (seulement celles dont tous les outils existent),
installer_competence_modele en ajoute une à la bibliothèque de l'utilisateur.
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from ..outils.base import Registre
from .competences import Bibliotheque, Competence, nom_valide

DOSSIER = Path(__file__).with_name("modeles")
CHAMPS = {f.name for f in fields(Competence)}


def charger_modeles(dossier: Path = DOSSIER) -> list[dict]:
    modeles = []
    for f in sorted(Path(dossier).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"Modèle de compétence illisible {f.name} : {e}")
            continue
        if isinstance(d, dict) and d.get("nom") and d.get("etapes"):
            d.setdefault("source", "modele")
            modeles.append(d)
    return modeles


def outils_requis(modele: dict) -> set[str]:
    return {e.get("outil", "") for e in modele.get("etapes", [])}


def modeles_disponibles(registre: Registre, dossier: Path = DOSSIER) -> list[dict]:
    """Modèles dont chaque étape utilise un outil présent dans le registre (logiciel connecté)."""
    return [m for m in charger_modeles(dossier) if all(registre.get(o) is not None for o in outils_requis(m))]


def installer_modele(bibliotheque: Bibliotheque, nom: str, dossier: Path = DOSSIER) -> Competence:
    """Ajoute le modèle à la bibliothèque (KeyError s'il n'existe pas ou n'est pas utilisable ici, ValueError si
    la recette est invalide)."""
    cible = nom_valide(nom)
    tous = charger_modeles(dossier)
    modele = next((m for m in tous if nom_valide(m["nom"]) == cible), None)
    if modele is None:
        noms = ", ".join(m["nom"] for m in tous) or "aucun"
        raise KeyError(f"Compétence toute faite « {nom} » introuvable (disponibles : {noms}).")
    manquants = sorted(o for o in outils_requis(modele) if bibliotheque.registre.get(o) is None)
    if manquants:
        raise KeyError(f"« {modele['nom']} » a besoin d'outils absents ({', '.join(manquants)}) : le logiciel "
                       "concerné n'est pas connecté.")
    c = Competence(**{k: v for k, v in modele.items() if k in CHAMPS and k not in ("cree_le", "utilisations")})
    return bibliotheque.ajouter(c)
