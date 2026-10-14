"""Applications : ouvrir, quitter, basculer, lister, ouvrir un fichier."""
from __future__ import annotations

import difflib
import re
import time
from pathlib import Path

from ..agent.routeur import normaliser
from ..mac import commun
from .base import ErreurOutil, Resultat, Risque, outil

DOSSIERS_APPS = ["/Applications", "/Applications/Utilities", "/System/Applications",
                 "/System/Applications/Utilities", "~/Applications", "/System/Library/CoreServices"]
# Noms courants -> nom réel de l'application.
ALIAS = {"vscode": "Visual Studio Code", "vs code": "Visual Studio Code", "code": "Visual Studio Code",
         "chrome": "Google Chrome", "terminal": "Terminal", "reglages": "System Settings",
         "parametres": "System Settings", "preferences systeme": "System Settings",
         "calculatrice": "Calculator", "calendrier": "Calendar", "rappels": "Reminders", "plans": "Maps",
         "musique": "Music", "photos": "Photos", "messages": "Messages", "mail": "Mail",
         "notes": "Notes", "moniteur d'activite": "Activity Monitor", "word": "Microsoft Word",
         "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint", "teams": "Microsoft Teams",
         "app store": "App Store", "apercu": "Preview", "finder": "Finder", "facetime": "FaceTime",
         "editeur de texte": "TextEdit", "textedit": "TextEdit", "horloge": "Clock", "meteo": "Weather"}

_cache: tuple[float, dict[str, Path]] | None = None


def applications_installees() -> dict[str, Path]:
    """{nom normalisé: chemin .app}, mis en cache 5 minutes."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < 300:
        return _cache[1]
    apps: dict[str, Path] = {}
    for d in DOSSIERS_APPS:
        dossier = Path(d).expanduser()
        if dossier.is_dir():
            for p in dossier.glob("*.app"):
                apps.setdefault(normaliser(p.stem), p)
            for p in dossier.glob("*/*.app"):  # ex. /Applications/ArtCraft/PhotoCraft.app
                apps.setdefault(normaliser(p.stem), p)
    _cache = (time.monotonic(), apps)
    return apps


def trouver_application(nom: str) -> Path | None:
    apps = applications_installees()
    cle = normaliser(nom).strip()
    cle = normaliser(ALIAS.get(cle, cle))
    if cle in apps:
        return apps[cle]
    # « photocraft » -> « PhotoCraft », « chrome » -> « Google Chrome », fautes de frappe.
    contient = [k for k in apps if cle in k.split() or k.startswith(cle) or cle.replace(" ", "") == k.replace(" ", "")]
    if len(contient) >= 1:
        return apps[min(contient, key=len)]
    proche = difflib.get_close_matches(cle, list(apps), n=1, cutoff=0.75)
    return apps[proche[0]] if proche else None


def suggestions(nom: str) -> list[str]:
    apps = applications_installees()
    return [apps[k].stem for k in difflib.get_close_matches(normaliser(nom), list(apps), n=3, cutoff=0.5)]


@outil("ouvrir_application", "Ouvre (ou met au premier plan) une application installée.", "applications",
       {"nom": ("string", "nom de l'application, ex. Safari, Spotify, PhotoCraft")}, risque=Risque.CREATION,
       annonce=lambda a: f"Ouvrir {a['nom']}")
def ouvrir_application(ctx, nom):
    app = trouver_application(nom)
    if app is None:
        from ..agent.rapide import SITES
        if normaliser(nom) in SITES:
            commun.executer(["open", SITES[normaliser(nom)]])
            return f"{nom} ouvert dans le navigateur."
        s = suggestions(nom)
        raise ErreurOutil(f"Application « {nom} » introuvable." + (f" Vouliez-vous : {', '.join(s)} ?" if s else ""))
    commun.executer(["open", "-a", str(app)])
    return Resultat(True, f"{app.stem} est ouvert.", {"application": app.stem})


@outil("quitter_application", "Quitte proprement une application (elle peut proposer d'enregistrer).",
       "applications", {"nom": ("string", "nom de l'application")}, risque=Risque.MODIFICATION,
       annonce=lambda a: f"Quitter {a['nom']}")
def quitter_application(ctx, nom):
    app = trouver_application(nom)
    nom_reel = app.stem if app else nom
    commun.osascript(f"tell application {commun.chaine_as(nom_reel)} to quit", delai=30)
    return f"{nom_reel} est fermé."


@outil("applications_ouvertes", "Liste les applications actuellement ouvertes et celle au premier plan.",
       "applications", {})
def applications_ouvertes(ctx):
    sortie = commun.executer(["lsappinfo", "visibleProcessList"])
    noms = re.findall(r'"([^"]+)"-ASN', sortie)
    asn = commun.executer(["lsappinfo", "front"], verifier=False).strip()
    avant = commun.executer(["lsappinfo", "info", "-only", "name", asn], verifier=False) if asn else ""
    front = re.search(r'"LSDisplayName"="([^"]+)"', avant)
    texte = "Ouvertes : " + ", ".join(noms)
    if front:
        texte += f"\nAu premier plan : {front.group(1)}"
    return Resultat(True, texte, {"applications": noms})


@outil("ouvrir_fichier", "Ouvre un fichier ou un dossier avec son application par défaut, ou avec une "
       "application précise.", "applications",
       {"chemin": ("string", "chemin du fichier ou dossier"),
        "application": ("string", "application à utiliser, facultatif")}, requis=["chemin"],
       risque=Risque.CREATION, annonce=lambda a: f"Ouvrir {a['chemin']}")
def ouvrir_fichier(ctx, chemin, application=""):
    p = commun.chemin(chemin)
    if not p.exists():
        raise ErreurOutil(f"{p} n'existe pas. Utilise rechercher_fichiers pour le retrouver.")
    cmd = ["open"]
    if application:
        app = trouver_application(application)
        cmd += ["-a", str(app) if app else application]
    commun.executer(cmd + [str(p)])
    return f"{p.name} est ouvert."


@outil("afficher_dans_finder", "Montre un fichier dans le Finder (le sélectionne dans son dossier).",
       "applications", {"chemin": ("string", "chemin du fichier")}, risque=Risque.CREATION)
def afficher_dans_finder(ctx, chemin):
    p = commun.chemin(chemin)
    if not p.exists():
        raise ErreurOutil(f"{p} n'existe pas.")
    commun.executer(["open", "-R", str(p)])
    return f"{p.name} affiché dans le Finder."
