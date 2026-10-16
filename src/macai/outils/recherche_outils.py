"""Recherche de fichiers, de mails et de notes par le sens (index local) + Spotlight en complément."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .base import ErreurOutil, Resultat, Risque, outil

GENRES = ["image", "capture", "pdf", "document", "tableur", "presentation", "code", "autre", "mail", "note"]
APPLE = ["mail", "note"]  # entrées « mail://… » et « note://… » (indexées depuis Mail et Notes)
SOURCES = ["tout", "fichiers", "mails", "notes"]


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
                                       dossier=str(d) if d else None, apres=_date_min(periode),
                                       exclure=None if genres else APPLE)
    lignes = [ligne_trouvaille(t) for t in trouvailles]
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


def ligne_trouvaille(t) -> str:
    """Fichier : chemin, genre, date, extrait. Mail / note : l'en-tête (expéditeur, sujet, date) d'abord."""
    entete, _, corps = t.extrait.partition("\n")
    if t.genre in APPLE:
        extrait = re.sub(r"\s+", " ", corps)[:220]
        return f"- {entete}\n  adresse : {t.chemin}" + (f"\n  « {extrait} »" if extrait else "")
    date = time.strftime("%d/%m/%Y", time.localtime(t.mtime or 0))
    extrait = re.sub(r"\s+", " ", corps or entete)[:220]
    return f"- {t.chemin}  ({t.genre}, modifié le {date})\n  « {extrait} »"


def genres_de_sources(sources: str) -> tuple[list[str] | None, list[str] | None]:
    """(genres retenus, genres exclus) pour « tout », « fichiers », « mails », « notes » (ou « mails, notes »)."""
    s = str(sources or "tout").lower()
    voulus = set()
    if "mail" in s or "courriel" in s:
        voulus.add("mail")
    if "note" in s:
        voulus.add("note")
    if "fichier" in s or "document" in s:
        if voulus:
            return None, [g for g in APPLE if g not in voulus]
        return None, APPLE
    return (sorted(voulus), None) if voulus else (None, None)


@outil("chercher_partout", "Cherche à la fois dans les fichiers, les mails (Réception et Envoyés) et les notes, par "
       "le sens ou par mots (ex. « le devis de la cuisine », « mail de Paul sur les vacances »). Donne "
       "l'expéditeur, le sujet et la date des mails ; ouvrir_mail ouvre un résultat mail:// ou note://.",
       "recherche", {"requete": ("string", "description de ce qu'on cherche"),
                     "sources": ("string", "où chercher", SOURCES),
                     "periode": ("string", "ex. « cette semaine », « 3 mois », facultatif"),
                     "nombre": ("integer", "nombre de résultats (8 par défaut)")}, requis=["requete"],
       mac_seulement=False, mots_cles=["dans mes mails", "dans mes notes", "un mail de", "le mail de", "mail sur",
                                       "partout", "dans une note", "mail ou", "mails recus", "mail envoye"])
def chercher_partout(ctx, requete, sources="tout", periode="", nombre=8):
    index = ctx.service("index")
    if index is None:
        return Resultat(False, "Recherche indisponible (index absent).")
    genres, exclus = genres_de_sources(sources)
    trouvailles = index.rechercher(requete, int(nombre or 8), genres=genres, exclure=exclus,
                                   apres=_date_min(periode))
    if not trouvailles:
        n_apple = len(index.chemins("mail://")) + len(index.chemins("note://"))
        conseil = "" if n_apple else (" Aucun mail ni note n'est encore indexé (indexation Mac branché et inutilisé, "
                                      "Mail et Notes ouverts).")
        return Resultat(True, f"Rien trouvé pour « {requete} ».{conseil}", {"resultats": []})
    return Resultat(True, "\n".join(ligne_trouvaille(t) for t in trouvailles),
                    {"resultats": [t.chemin for t in trouvailles]})


def url_message(ident: str) -> str:
    """Adresse « message:// » que Mail sait ouvrir (identifiant entre chevrons, encodé)."""
    from urllib.parse import quote
    ident = str(ident).strip().removeprefix("mail://").strip().strip("<>")
    return "message://" + quote(f"<{ident}>", safe="@")


@outil("ouvrir_mail", "Ouvre dans Mail (ou Notes) un résultat de chercher_partout : adresse mail://… ou note://….",
       "recherche", {"chemin": ("string", "adresse mail://… ou note://… donnée par chercher_partout")},
       risque=Risque.CREATION, annonce=lambda a: f"Ouvrir {a['chemin']}")
def ouvrir_mail(ctx, chemin):
    from ..mac import commun
    c = str(chemin or "").strip()
    if c.startswith("note://"):
        ident = c.removeprefix("note://")
        commun.osascript(f'tell application "Notes"\n    show note id {commun.chaine_as(ident)}\n    activate\n'
                         'end tell', delai=30)
        return "Note ouverte dans Notes."
    if not c.startswith("mail://") and "@" not in c:
        raise ErreurOutil("Donne l'adresse mail://… ou note://… indiquée par chercher_partout.")
    subprocess.run(["open", url_message(c)], capture_output=True, timeout=15, check=False)
    return "Mail ouvert dans Mail."


@outil("etat_index", "Indique combien de fichiers sont indexés pour la recherche et quand date le dernier passage.",
       "recherche", {}, mac_seulement=False)
def etat_index(ctx):
    index = ctx.service("index")
    if index is None:
        return "Recherche indisponible."
    s = index.stats()
    dernier = index.etat("dernier_passage")
    quand = time.strftime("%d/%m à %H:%M", time.localtime(float(dernier))) if dernier else "jamais"
    mails, notes = len(index.chemins("mail://")), len(index.chemins("note://"))
    fichiers = s["fichiers"] - mails - notes
    apple = f" Mails : {mails}, notes : {notes}." if mails or notes else ""
    return (f"{fichiers} fichiers indexés ({s['extraits']} extraits au total, {s['taille_mo']} Mo).{apple} "
            f"Dernier passage : {quand}.")


@outil("indexer_maintenant", "Lance l'indexation des fichiers tout de suite, même si le Mac est utilisé "
       "(priorité basse, sur les cœurs économes).", "recherche", {}, mac_seulement=False)
def indexer_maintenant(ctx):
    from ..recherche.indexeur import lancer_en_arriere_plan
    lancer_en_arriere_plan(force=True)
    return "Indexation lancée en arrière-plan. Elle reste discrète : tu peux continuer à travailler."
