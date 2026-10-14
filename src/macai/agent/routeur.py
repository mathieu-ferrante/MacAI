"""Choisit les outils à montrer au modèle pour une demande.

Un petit modèle (4 milliards de paramètres) se trompe davantage quand on lui présente 80 outils :
on ne lui donne que les groupes pertinents (≈ 10 à 20 outils), choisis par mots-clés.
"""
from __future__ import annotations

import re
import unicodedata

from ..outils.base import Registre

MOTS_GROUPES: dict[str, list[str]] = {
    "systeme": ["volume", "son", "muet", "musique", "pause", "lecture", "suivant", "precedent",
                "presse-papier", "copie", "colle", "capture", "screenshot", "memoire", "ram", "lent",
                "rame", "ralenti", "batterie", "notification", "terminal", "commande", "shell",
                "heure", "date", "disque", "stockage", "espace", "wifi", "luminosite", "veille"],
    "applications": ["ouvre", "ouvrir", "lance", "lancer", "ferme", "fermer", "quitte", "quitter",
                     "appli", "application", "logiciel", "app", "programme", "bascule", "demarre"],
    "fichiers": ["fichier", "dossier", "document", "pdf", "word", "docx", "excel", "xlsx", "tableur",
                 "tableau", "csv", "powerpoint", "pptx", "presentation", "texte", "markdown", "cree",
                 "creer", "ecris", "ecrire", "redige", "range", "ranger", "deplace", "renomme",
                 "supprime", "efface", "corbeille", "bureau", "telechargement", "lis", "lire", "resume",
                 "resumer", "analyse", "convertis", "contenu", "image", "photo"],
    "recherche": ["trouve", "trouver", "cherche", "chercher", "retrouve", "ou est", "ou sont", "photo",
                  "image", "facture", "capture", "scan", "fichier", "indexe", "indexation"],
    "web": ["chrome", "youtube", "google", "site", "page", "video", "internet", "web", "navigateur",
            "onglet", "url", "http", "www", "recherche sur", "regarde", "musique", "wikipedia", "lien"],
    "fenetres": ["clique", "cliquer", "bouton", "menu", "fenetre", "tape", "taper", "ecran", "champ",
                 "formulaire", "selectionne", "coche", "fais defiler", "dans l'appli", "dans le logiciel"],
    "organisation": ["rappel", "rappelle-moi", "calendrier", "agenda", "rendez-vous", "rdv", "reunion",
                     "evenement", "note", "notes", "mail", "e-mail", "email", "courriel", "message"],
    "memoire": ["souviens", "souvenir", "retiens", "retenir", "oublie", "oublier", "rappelle-toi",
                "sais-tu", "prefere", "preference", "je m'appelle", "mon nom", "qui suis-je", "j'aime"],
    "competences": ["competence", "skill", "recette", "automatise", "comme la derniere fois"],
    "onshape": ["onshape", "cao", "3d", "cube", "piece", "cylindre", "pave", "modelise", "extrusion",
                "esquisse", "cad"],
}

GROUPES_DEFAUT = ["applications", "fichiers", "recherche", "web", "systeme"]
TOUJOURS = ["memoire"]
MAX_OUTILS = 22


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _contient(texte: str, mot: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(mot)}", texte) is not None


def choisir(demande: str, registre: Registre, mots_extra: dict[str, list[str]] | None = None) -> list[str]:
    """Renvoie les noms d'outils à proposer au modèle, les plus pertinents d'abord."""
    t = normaliser(demande)
    mots = {**MOTS_GROUPES, **(mots_extra or {})}
    groupes = registre.groupes()

    scores = {g: sum(_contient(t, normaliser(m)) for m in ms) for g, ms in mots.items() if g in groupes}
    choisis = [g for g, s in sorted(scores.items(), key=lambda x: -x[1]) if s > 0]
    if not choisis:
        choisis = [g for g in GROUPES_DEFAUT if g in groupes]

    noms: list[str] = []
    # Outils désignés précisément par leurs mots-clés (compétences, connecteurs MCP).
    for o in registre.disponibles():
        if o.mots_cles and any(_contient(t, normaliser(m)) for m in o.mots_cles):
            noms.append(o.nom)
    for g in choisis + [g for g in TOUJOURS if g in groupes]:
        noms += [o.nom for o in groupes[g] if o.nom not in noms]
    return noms[:MAX_OUTILS]
