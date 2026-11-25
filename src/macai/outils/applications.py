"""Applications : ouvrir, quitter, basculer, lister, ouvrir un fichier."""
from __future__ import annotations

import difflib
import os
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


# « Ouvre Téléchargements », « ouvre le Bureau » : un dossier, pas une application (vu dans le journal du Mac :
# le modèle appelait ouvrir_application("Documents") puis ouvrait Raccourcis, proposé à la place).
DOSSIERS_CONNUS = {"bureau": "~/Desktop", "desktop": "~/Desktop", "telechargements": "~/Downloads",
                   "downloads": "~/Downloads", "documents": "~/Documents", "applications": "/Applications",
                   "images": "~/Pictures", "pictures": "~/Pictures", "films": "~/Movies", "movies": "~/Movies",
                   "dossier personnel": "~", "dossier utilisateur": "~", "home": "~", "icloud drive":
                   "~/Library/Mobile Documents/com~apple~CloudDocs"}


def dossier_connu(nom: str) -> Path | None:
    """Dossier courant désigné par son nom (« Téléchargements », « le dossier Documents », « mon bureau »)."""
    cle = re.sub(r"^(le |la |les |mon |ma |mes |l'|l’)?(dossier (des |de |du |d')?)?(mon |ma |mes )?", "",
                 normaliser(str(nom or "")).strip()).strip()
    chemin = DOSSIERS_CONNUS.get(cle) or DOSSIERS_CONNUS.get(normaliser(str(nom or "")).strip())
    if chemin is None or cle in applications_installees():
        return None
    p = Path(chemin).expanduser()
    return p if p.is_dir() else None


@outil("ouvrir_application", "Ouvre (ou met au premier plan) une application installée.", "applications",
       {"nom": ("string", "nom de l'application, ex. Safari, Spotify, PhotoCraft")}, risque=Risque.CREATION,
       annonce=lambda a: f"Ouvrir {a['nom']}")
def ouvrir_application(ctx, nom):
    dossier = dossier_connu(nom)
    if dossier is not None:
        commun.executer(["open", str(dossier)])
        return Resultat(True, f"Dossier {dossier.name} ouvert dans le Finder.", {"dossier": str(dossier)})
    app = trouver_application(nom)
    if app is None:
        from ..agent.rapide import SITES
        if normaliser(nom) in SITES:
            commun.executer(["open", SITES[normaliser(nom)]])
            return f"{nom} ouvert dans le navigateur."
        # Pas de « Vouliez-vous… ? » : trouver_application accepte déjà les noms proches (fautes de frappe).
        # Les propositions plus lointaines envoyaient le modèle ouvrir une AUTRE appli (FilmCraft pour Minecraft,
        # JavaLauncher pour ArtCraft Launcher) puis annoncer un succès.
        raise ErreurOutil(f"Application « {nom} » introuvable : elle n'est pas installée sur ce Mac. N'ouvre pas "
                          "une autre application à la place : dis-le à l'utilisateur.")
    commun.executer(["open", "-a", str(app)])
    return Resultat(True, f"{app.stem} est ouvert.", {"application": app.stem})


# Jamais fermés par l'agent : le moteur d'IA lui-même et les éléments vitaux de macOS.
MOTEUR_IA = {"ollama", "llamaserver", "llama", "macai", "python"}
PROTEGEES = MOTEUR_IA | {"finder", "loginwindow", "windowserver", "dock", "systemuiserver", "controlcenter",
                         "kernel_task", "launchd"}


def _protegee(nom: str) -> bool:
    return normaliser(str(nom or "")).replace(" ", "").replace("-", "").replace("_", "") in PROTEGEES


@outil("quitter_application", "Quitte proprement une application (elle peut proposer d'enregistrer).",
       "applications", {"nom": ("string", "nom de l'application")}, risque=Risque.MODIFICATION,
       annonce=lambda a: f"Quitter {a['nom']}")
def quitter_application(ctx, nom):
    app = trouver_application(nom)
    if app is None:
        raise ErreurOutil(f"Aucune application « {nom} » installée. Vérifie le nom avec applications_ouvertes.")
    if _protegee(app.stem) or _protegee(nom):
        if {normaliser(app.stem).replace(" ", ""), normaliser(nom).replace(" ", "").replace("-", "")} & MOTEUR_IA:
            raise ErreurOutil(f"{app.stem} fait partie de MacAI : je ne le ferme pas. Le modèle d'IA se décharge "
                              "tout seul 2 minutes après la dernière demande.")
        raise ErreurOutil(f"{app.stem} fait partie de macOS et reste toujours ouvert : je ne le ferme pas.")
    from ..mac import accessibilite as ax
    ouvertes = [a for a in ax.applis_ouvertes() if a["paquet"] == app.stem]
    if not ouvertes:
        return Resultat(True, f"{app.stem} n'était pas ouvert.", sans_effet=True)
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
    # Finder et consorts ne se ferment pas : séparés, sinon « ferme toutes mes applis » s'acharne dessus.
    fermables = [n for n in noms if not _protegee(n)]
    texte = "Ouvertes : " + (", ".join(fermables) or "aucune")
    if len(fermables) < len(noms):
        texte += "\nToujours actifs (macOS ou MacAI, ne se ferment pas) : " + ", ".join(
            n for n in noms if _protegee(n))
    if front:
        texte += f"\nAu premier plan : {front.group(1)}"
    return Resultat(True, texte, {"applications": noms})


# Ouvrir un fichier peut revenir à exécuter du code (.command, .terminal, .app, .pkg, .webloc, alias Finder…).
# Liste BLANCHE (relecture de sécurité : la liste noire se contournait avec « x.terminal␠ », un lien
# symbolique « doc.pdf → x.command », ou une extension oubliée) : documents, images, sons, vidéos, archives.
# Tout le reste (y compris un dossier-paquet) demande confirmation.
OUVRABLES = {".pdf", ".txt", ".md", ".rtf", ".rtfd", ".doc", ".docx", ".odt", ".pages", ".epub", ".xls", ".xlsx",
             ".csv", ".numbers", ".ods", ".ppt", ".pptx", ".key", ".odp", ".jpg", ".jpeg", ".png", ".gif", ".heic",
             ".heif", ".webp", ".tiff", ".tif", ".bmp", ".svg", ".raw", ".cr2", ".nef", ".dng", ".psd", ".mp4",
             ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".aiff",
             ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".stl", ".step", ".stp", ".obj", ".3mf",
             ".f3d", ".blend", ".json", ".xml", ".log", ".yaml", ".yml", ".ics", ".srt"}
EXECUTABLES = {".command", ".terminal", ".sh", ".zsh", ".bash", ".tool", ".app", ".pkg", ".mpkg", ".dmg",
               ".workflow", ".scpt", ".scptd", ".applescript", ".webloc", ".fileloc", ".inetloc", ".jar", ".py",
               ".pl", ".rb", ".shortcut", ".prefpane", ".mobileconfig", ".kext", ".plist"}  # pour mémoire (tests)
ALIAS_FINDER = b"book\x00\x00\x00\x00mark"


def _risque_ouvrir(args: dict) -> Risque:
    from .. import securite
    chemin = str(args.get("chemin", ""))
    if chemin.startswith(("mail://", "note://")):
        return Risque.CREATION
    application = str(args.get("application", "") or "")
    if application and securite.categorie_appli(application) == "execution":
        return Risque.SENSIBLE
    try:
        p = commun.chemin(chemin)  # même résolution que l'outil : guillemets, espaces, liens symboliques
    except (OSError, ValueError):
        return Risque.SENSIBLE
    if p.is_dir():
        # Un dossier ordinaire s'ouvre dans le Finder ; un dossier-paquet (.app, .saver, .workflow…) s'exécute.
        return Risque.CREATION if p.suffix.lower() in OUVRABLES | {"", ".rtfd"} or not re.fullmatch(
            r"\.[a-z0-9]{2,12}", p.suffix.lower()) else Risque.SENSIBLE
    if p.suffix.lower() not in OUVRABLES:
        return Risque.SENSIBLE
    try:
        with open(p, "rb") as f:
            if f.read(16).startswith(ALIAS_FINDER):
                return Risque.SENSIBLE  # alias Finder déguisé en document
    except OSError:
        pass
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


# --- Fermer plusieurs applications ------------------------------------------------------------------------------

def _a_fermer(sauf: str) -> list[dict]:
    """Applications ouvertes à fermer : toutes sauf celles nommées, macOS (Finder…) et MacAI lui-même."""
    from ..mac import accessibilite as ax
    garder = set()
    for n in re.split(r",|\bet\b", str(sauf or ""), flags=re.I):
        n = n.strip()
        if n and (app := trouver_application(n)) is not None:
            garder.add(app.stem)
        elif n:
            garder.add(n)
    garder_norm = {normaliser(g) for g in garder}
    return [a for a in ax.applis_ouvertes()
            if a["paquet"] not in garder and normaliser(a["nom"]) not in garder_norm
            and normaliser(a["paquet"]) not in garder_norm and not _protegee(a["paquet"]) and not _protegee(a["nom"])]


def _annonce_fermer(a: dict) -> str:
    try:
        noms = [x["nom"] for x in _a_fermer(a.get("sauf", ""))]
    except Exception:  # noqa: BLE001 - liste illisible : annonce générique
        noms = []
    liste = f" : {', '.join(noms)}" if noms else ""
    return f"Fermer {len(noms) or 'toutes les'} application{'s' if len(noms) != 1 else ''}{liste}" + (
        f" (je garde {a['sauf']})" if a.get("sauf") else "")


@outil("fermer_applications", "Ferme toutes les applications ouvertes, sauf celles indiquées (jamais le Finder ni "
       "MacAI). Chaque appli peut proposer d'enregistrer.", "applications",
       {"sauf": ("string", "applications à garder ouvertes, séparées par des virgules, facultatif")}, requis=[],
       risque=Risque.SENSIBLE, annonce=_annonce_fermer, delai_max=180)
def fermer_applications(ctx, sauf=""):
    from ..mac import accessibilite as ax
    cibles = _a_fermer(sauf)
    if not cibles:
        return Resultat(True, "Aucune application à fermer.", sans_effet=True)
    for a in cibles:
        try:
            commun.osascript(f"tell application id {commun.chaine_as(a['id'])} to quit" if a.get("id") else
                             f"tell application {commun.chaine_as(a['paquet'] or a['nom'])} to quit", delai=20)
        except ErreurOutil:
            pass
    time.sleep(1.5)
    restantes = {a["pid"] for a in ax.applis_ouvertes()}
    fermees = [a["nom"] for a in cibles if a["pid"] not in restantes]
    ouvertes = [a["nom"] for a in cibles if a["pid"] in restantes]
    texte = (f"Fermé : {', '.join(fermees)}." if fermees else "Rien n'a pu être fermé.") + (
        f" Encore ouvert (document à enregistrer ?) : {', '.join(ouvertes)}." if ouvertes else "")
    return Resultat(bool(fermees), texte, {"fermees": fermees, "ouvertes": ouvertes})


# --- Installer une application ----------------------------------------------------------------------------------

APPLICATIONS = Path("/Applications")


def _evaluation_gatekeeper(app: Path) -> tuple[bool, str]:
    """Gatekeeper (spctl) : l'app est-elle signée par un développeur identifié ET notariée par Apple ?"""
    import subprocess
    r = subprocess.run(["/usr/sbin/spctl", "--assess", "--type", "execute", "-vv", str(app)],
                       capture_output=True, text=True, timeout=60)
    sortie = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 and "accepted" in sortie and re.search(r"source=(Notarized Developer ID|Apple System|"
                                                                    r"Mac App Store|Apple)", sortie) is not None
    return ok, sortie


@outil("installer_application", "Installe une application à partir d'un fichier .dmg, .zip ou .app téléchargé "
       "(la copie dans Applications), seulement si elle est signée et notariée par Apple. Les .pkg s'installent "
       "à la main.", "applications", {"chemin": ("string", "chemin du .dmg, .zip ou .app")},
       risque=Risque.SENSIBLE, toujours_confirmer=True, delai_max=300,
       annonce=lambda a: f"Installer l'application contenue dans {a['chemin']} (vérifiée par Gatekeeper)")
def installer_application(ctx, chemin):
    import shutil
    import subprocess
    import tempfile

    from .fichiers import verifier_chemin
    source = verifier_chemin(commun.chemin(chemin))
    if not source.exists():
        raise ErreurOutil(f"{source} n'existe pas. Utilise rechercher_fichiers pour le retrouver.")
    ext = source.suffix.lower()
    if ext in (".pkg", ".mpkg"):
        raise ErreurOutil("C'est un installateur .pkg : il demande ton mot de passe administrateur, ouvre-le toi-même "
                          "(double-clic) et suis ses étapes.")
    if ext not in (".dmg", ".zip", ".app"):
        raise ErreurOutil("Je sais installer une application depuis un .dmg, un .zip ou un .app.")
    montage = temporaire = None
    try:
        if ext == ".dmg":
            montage = Path(tempfile.mkdtemp(prefix="macai-dmg-"))
            r = subprocess.run(["/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen",
                                "-mountpoint", str(montage), str(source)], capture_output=True, text=True,
                               timeout=180, input="Y\n")  # accepte l'affichage de licence éventuel
            if r.returncode != 0:
                raise ErreurOutil(f"Impossible d'ouvrir l'image disque : {r.stderr.strip()[:200]}")
            dossier = montage
        elif ext == ".zip":
            temporaire = Path(tempfile.mkdtemp(prefix="macai-zip-"))
            r = subprocess.run(["/usr/bin/ditto", "-x", "-k", str(source), str(temporaire)], capture_output=True,
                               text=True, timeout=180)
            if r.returncode != 0:
                raise ErreurOutil(f"Impossible de décompresser : {r.stderr.strip()[:200]}")
            dossier = temporaire
        else:
            dossier = None
        if dossier is None:
            apps = [source]
        else:
            apps = [p for p in dossier.glob("*.app") if not p.is_symlink()] or \
                   [p for p in dossier.glob("*/*.app") if not p.is_symlink()]
        if not apps:
            raise ErreurOutil("Aucune application (.app) dans ce fichier. S'il contient un installateur, ouvre-le "
                              "toi-même.")
        if len(apps) > 1:
            raise ErreurOutil("Plusieurs applications dans ce fichier : " + ", ".join(a.name for a in apps)
                              + ". Installe celle que tu veux à la main.")
        app = apps[0]
        ok, avis = _evaluation_gatekeeper(app)
        if not ok:
            raise ErreurOutil(f"Refusé : {app.name} n'est pas signée et notariée par Apple (Gatekeeper : "
                              f"{avis[:160]}). Ne l'installe que si tu fais confiance à sa source.")
        cible_dossier = APPLICATIONS if os.access(APPLICATIONS, os.W_OK) else Path.home() / "Applications"
        cible_dossier.mkdir(exist_ok=True)
        cible = cible_dossier / app.name
        if cible.exists():
            return Resultat(True, f"{app.stem} est déjà installé dans {cible_dossier}. Pour le mettre à jour, "
                                  "mets d'abord l'ancienne version à la Corbeille.", sans_effet=True)
        r = subprocess.run(["/usr/bin/ditto", str(app), str(cible)], capture_output=True, text=True, timeout=240)
        if r.returncode != 0:
            shutil.rmtree(cible, ignore_errors=True)
            raise ErreurOutil(f"Copie impossible : {r.stderr.strip()[:200]}")
        from .. import annulation
        annulation.enregistrer(ctx, f"Installation de {app.stem}", [{"type": "desinstaller_app", "chemin": str(cible)}])
        global _cache
        _cache = None  # la nouvelle appli doit être trouvable tout de suite
        return Resultat(True, f"{app.stem} est installé dans {cible_dossier} (signé et notarié). Ouvre-le avec "
                              "ouvrir_application.", {"application": app.stem, "chemin": str(cible)})
    finally:
        if montage is not None:
            subprocess.run(["/usr/bin/hdiutil", "detach", str(montage), "-quiet", "-force"], capture_output=True,
                           timeout=60)
            try:
                montage.rmdir()
            except OSError:
                pass
        if temporaire is not None:
            shutil.rmtree(temporaire, ignore_errors=True)
