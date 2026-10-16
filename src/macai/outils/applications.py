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
            for p in [*dossier.glob("*.app"), *dossier.glob("*/*.app")]:  # ex. /Applications/ArtCraft/PhotoCraft.app
                apps.setdefault(normaliser(p.stem), p)
    # Noms affichés en français (« Réglages Système », « Calculatrice ») en plus des noms des paquets.
    try:
        from Foundation import NSFileManager
        fm = NSFileManager.defaultManager()
        for p in list(apps.values()):
            affiche = fm.displayNameAtPath_(str(p))
            if affiche:
                apps.setdefault(normaliser(str(affiche).removesuffix(".app")), p)
    except ImportError:
        pass
    _cache = (time.monotonic(), apps)
    return apps


def trouver_application(nom: str) -> Path | None:
    apps = applications_installees()
    cle = re.sub(r"^(l'|l’|le |la |les |l'application |l'appli |application |appli |app )", "",
                 normaliser(str(nom or "")).strip()).removesuffix(".app").strip()
    if len(cle) < 2:
        return None
    cle = normaliser(ALIAS.get(cle, cle))
    if cle in apps:
        return apps[cle]
    if len(cle) < 3:
        return None  # « m », « c » : trop court pour deviner
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


# Jamais fermés par l'agent : le moteur d'IA lui-même et les éléments vitaux de macOS.
PROTEGEES = {"ollama", "llamaserver", "llama", "macai", "python", "finder", "loginwindow", "windowserver",
             "dock", "systemuiserver", "controlcenter", "kernel_task", "launchd"}


@outil("quitter_application", "Quitte proprement une application (elle peut proposer d'enregistrer).",
       "applications", {"nom": ("string", "nom de l'application")}, risque=Risque.MODIFICATION,
       annonce=lambda a: f"Quitter {a['nom']}")
def quitter_application(ctx, nom):
    app = trouver_application(nom)
    if app is None:
        raise ErreurOutil(f"Aucune application « {nom} » installée. Vérifie le nom avec applications_ouvertes.")
    if normaliser(app.stem).replace(" ", "").replace("-", "") in PROTEGEES or \
            normaliser(nom).replace(" ", "").replace("-", "") in PROTEGEES:
        raise ErreurOutil(f"{app.stem} fait partie de MacAI ou de macOS : je ne le ferme pas. Le modèle d'IA se "
                          "décharge tout seul 2 minutes après la dernière demande.")
    from ..mac import accessibilite as ax
    ouvertes = [a for a in ax.applis_ouvertes() if a["paquet"] == app.stem]
    if not ouvertes:
        return f"{app.stem} n'était pas ouvert."
    commun.osascript(f"tell application {commun.chaine_as(app.stem)} to quit", delai=30)
    time.sleep(1)
    if any(a["paquet"] == app.stem for a in ax.applis_ouvertes()):
        return Resultat(False, f"{ouvertes[0]['nom']} est toujours ouvert (il attend peut-être une réponse : "
                               "document à enregistrer ?).")
    return f"{ouvertes[0]['nom']} est fermé."


@outil("applications_ouvertes", "Liste les applications actuellement ouvertes et celle au premier plan.",
       "applications", {})
def applications_ouvertes(ctx):
    sortie = commun.executer(["lsappinfo", "visibleProcessList"])
    # macOS 27 : ASN:0x0-0x16016-"Google_Chrome": (espaces remplacés par _) ; anciens : "Nom"-ASN
    noms = re.findall(r'ASN:[0-9a-fx-]+?-"([^"]+)"', sortie) or re.findall(r'"([^"]+)"-ASN', sortie)
    noms = [n.replace("_", " ") for n in noms]
    asn = commun.executer(["lsappinfo", "front"], verifier=False).strip()
    avant = commun.executer(["lsappinfo", "info", "-only", "name", asn], verifier=False) if asn else ""
    front = re.search(r'"LSDisplayName"="([^"]+)"', avant) or re.search(r'^"([^"]+)" ASN', avant.strip())
    texte = "Ouvertes : " + ", ".join(noms)
    if front:
        texte += f"\nAu premier plan : {front.group(1)}"
    return Resultat(True, texte, {"applications": noms})


# Ouvrir ces fichiers revient à exécuter du code (Terminal, Automator, AppleScript, installeurs, raccourcis web).
EXECUTABLES = {".command", ".terminal", ".sh", ".zsh", ".bash", ".tool", ".app", ".pkg", ".mpkg", ".dmg",
               ".workflow", ".scpt", ".scptd", ".applescript", ".webloc", ".fileloc", ".inetloc", ".jar", ".py",
               ".pl", ".rb", ".shortcut", ".prefpane", ".mobileconfig", ".kext", ".plist"}


def _risque_ouvrir(args: dict) -> Risque:
    from .base import APPS_EXECUTION, nom_appli
    if Path(str(args.get("chemin", ""))).suffix.lower() in EXECUTABLES:
        return Risque.SENSIBLE
    if nom_appli(str(args.get("application", ""))) in APPS_EXECUTION:
        return Risque.SENSIBLE
    return Risque.CREATION


@outil("ouvrir_fichier", "Ouvre un fichier ou un dossier avec son application par défaut, ou avec une "
       "application précise.", "applications",
       {"chemin": ("string", "chemin du fichier ou dossier"),
        "application": ("string", "application à utiliser, facultatif")}, requis=["chemin"],
       risque=_risque_ouvrir, annonce=lambda a: f"Ouvrir {a['chemin']}"
                                                + (f" avec {a['application']}" if a.get("application") else ""))
def ouvrir_fichier(ctx, chemin, application=""):
    if str(chemin).startswith(("mail://", "note://")):  # résultat de recherche dans les mails ou les notes
        from .recherche_outils import ouvrir_mail
        return ouvrir_mail(ctx, chemin)
    from .fichiers import verifier_chemin
    p = verifier_chemin(commun.chemin(chemin))
    if not p.exists():
        raise ErreurOutil(f"{p} n'existe pas. Utilise rechercher_fichiers pour le retrouver.")
    cmd = ["open"]
    if application:
        app = trouver_application(application)
        if app is None:
            raise ErreurOutil(f"Application « {application} » introuvable.")
        cmd += ["-a", str(app)]
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
