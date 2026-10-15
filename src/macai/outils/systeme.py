"""Outils système : son, médias, presse-papiers, capture, mémoire, infos, Terminal."""
from __future__ import annotations

import getpass
import re
import shlex
import time
from pathlib import Path

from ..mac import commun
from .base import ErreurOutil, Resultat, Risque, outil

# Touches multimédia (NX_KEYTYPE_*) : pilotent aussi YouTube dans Chrome, Spotify, Musique…
TOUCHES_MEDIA = {"lecture": 16, "pause": 16, "suivant": 17, "precedent": 18}


def _touche_media(code: int) -> None:
    """Simule une touche multimédia du clavier (nécessite l'autorisation Accessibilité)."""
    import Quartz  # pyobjc, chargé seulement ici
    from AppKit import NSEvent

    for appui in (True, False):
        ev = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            14, (0, 0), 0xA00 if appui else 0xB00, 0, 0, None, 8,
            (code << 16) | ((0xA if appui else 0xB) << 8), -1)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev.CGEvent())


@outil("regler_volume", "Règle le volume de sortie du Mac (0 à 100).", "systeme",
       {"niveau": ("integer", "volume de 0 à 100")}, risque=Risque.CREATION,
       annonce=lambda a: f"Volume à {a['niveau']} %")
def regler_volume(ctx, niveau):
    n = max(0, min(100, int(niveau)))
    commun.osascript(f"set volume output volume {n} without output muted")
    return f"Volume réglé à {n} %."


@outil("controle_media", "Lecture, pause, morceau suivant/précédent, volume plus/moins, muet "
       "(fonctionne avec Musique, Spotify, YouTube dans Chrome…).", "systeme",
       {"action": ("string", "action", ["lecture", "pause", "suivant", "precedent", "volume_plus",
                                        "volume_moins", "muet"])}, risque=Risque.CREATION)
def controle_media(ctx, action):
    if action in ("volume_plus", "volume_moins"):
        actuel = int(commun.osascript("output volume of (get volume settings)") or 50)
        nouveau = max(0, min(100, actuel + (10 if action == "volume_plus" else -10)))
        commun.osascript(f"set volume output volume {nouveau}")
        return f"Volume : {nouveau} %."
    if action == "muet":
        commun.osascript("set volume with output muted")
        return "Son coupé."
    if action not in TOUCHES_MEDIA:
        raise ErreurOutil(f"Action inconnue : {action}")
    try:
        _touche_media(TOUCHES_MEDIA[action])
    except ImportError:
        # Repli : piloter directement Spotify ou Musique s'ils sont ouverts.
        verbe = {"lecture": "play", "pause": "pause", "suivant": "next track", "precedent": "previous track"}[action]
        for appli in ("Spotify", "Music"):
            if commun.osascript(f'application "{appli}" is running') == "true":
                commun.osascript(f'tell application "{appli}" to {verbe}')
                break
        else:
            raise ErreurOutil("Aucun lecteur ouvert.")
    return {"lecture": "Lecture.", "pause": "Pause.", "suivant": "Morceau suivant.",
            "precedent": "Morceau précédent."}[action]


@outil("lire_presse_papiers", "Renvoie le texte actuellement copié dans le presse-papiers.", "systeme", {})
def lire_presse_papiers(ctx):
    texte = commun.executer(["pbpaste"])
    return texte if texte else "Le presse-papiers est vide (ou contient autre chose que du texte)."


@outil("copier_presse_papiers", "Copie un texte dans le presse-papiers.", "systeme",
       {"texte": ("string", "texte à copier")}, risque=Risque.CREATION)
def copier_presse_papiers(ctx, texte):
    commun.executer(["pbcopy"], entree=texte)
    return f"Copié ({len(texte)} caractères)."


@outil("capture_ecran", "Prend une capture de tout l'écran et l'enregistre sur le Bureau.", "systeme",
       {"nom": ("string", "nom du fichier, facultatif")}, requis=[], risque=Risque.CREATION)
def capture_ecran(ctx, nom=""):
    nom = re.sub(r"[/:]", "-", nom or f"Capture {time.strftime('%Y-%m-%d à %H.%M.%S')}")
    dest = commun.chemin(f"~/Desktop/{nom}.png")
    commun.executer(["screencapture", "-x", str(dest)])
    return Resultat(True, f"Capture enregistrée : {dest}", {"fichier": str(dest)})


@outil("etat_memoire", "État de la RAM et du swap du Mac, et applications qui consomment le plus "
       "(utile si le Mac est lent).", "systeme", {})
def etat_memoire(ctx):
    from ..mac import memoire as m
    s = m.collect()
    lignes = [f"Pression mémoire : {s.pressure_label}",
              f"RAM utilisée : {m.fmt_bytes(s.used)} / {m.fmt_bytes(s.ram_total)} "
              f"(applis {m.fmt_bytes(s.app_mem)}, compressée {m.fmt_bytes(s.compressed)})",
              f"Swap sur le SSD : {m.fmt_bytes(s.swap_used)}", "Applications les plus gourmandes :"]
    for a in s.apps[:8]:
        nom = a["name"]
        if nom in ("llama-server", "ollama") or nom.startswith("ollama"):
            nom += " (modèle d'IA de MacAI : se libère seul 2 min après la dernière demande, ne pas fermer)"
        lignes.append(f"- {nom} : {m.fmt_bytes(a['rss'])}" + (" (appli)" if a.get("is_app") else ""))
    return "\n".join(lignes)


ETATS_BATTERIE = {"discharging": "sur batterie", "charging": "en charge", "charged": "chargée",
                  "AC attached": "sur secteur", "finishing charge": "fin de charge"}


@outil("infos_systeme", "Batterie, espace disque libre, version de macOS, durée depuis le démarrage.",
       "systeme", {})
def infos_systeme(ctx):
    batt = commun.executer(["pmset", "-g", "batt"], verifier=False)
    pct = re.search(r"(\d+)%;\s*([^;]+);", batt)
    disque = commun.executer(["df", "-h", "/System/Volumes/Data"], verifier=False).splitlines()
    libre = disque[1].split()[3].replace("Gi", " Go").replace("Ti", " To") if len(disque) > 1 else "?"
    version = commun.executer(["sw_vers", "-productVersion"], verifier=False).strip()
    brut = commun.executer(["uptime"], verifier=False).strip()
    m = re.search(r"up\s+(.*?),\s+\d+\s+users?", brut)
    depuis = m.group(1).replace("days", "jours").replace("day", "jour").replace("mins", "min") if m else brut
    return "\n".join([
        f"Batterie : {pct.group(1)} % ({ETATS_BATTERIE.get(pct.group(2).strip(), pct.group(2).strip())})" if pct else "Batterie : inconnue",
        f"Disque : {libre} libres", f"macOS {version}", f"Allumé : {depuis}",
    ])


@outil("notifier", "Affiche une notification macOS.", "systeme",
       {"titre": ("string", "titre"), "message": ("string", "message")}, risque=Risque.CREATION)
def notifier(ctx, titre, message):
    commun.notifier(titre, message)
    return "Notification affichée."


# --- Terminal -----------------------------------------------------------------

# Commandes sans effet, exécutées SANS shell (pas de ; | $() ni retour à la ligne possibles) : pas de confirmation.
LECTURE_SEULE = {"ls", "cat", "head", "tail", "wc", "df", "du", "find", "grep", "ps", "pwd", "whoami",
                 "sw_vers", "date", "uptime", "which", "mdfind", "file", "stat", "echo", "uname",
                 "system_profiler", "diskutil", "pmset", "vm_stat", "sysctl", "defaults", "top"}
# Caractères qui feraient du shell (enchaîner, rediriger, substituer, développer) : la commande passe alors
# par zsh, donc confirmation. Constat de la relecture : « ls\nid » ou « cat <(id) » passaient en lecture.
SHELL = re.compile(r"[\n\r;&|`$<>(){}*?!\\]")
# Sous-commandes autorisées en lecture seule, ou options interdites.
SOUS_COMMANDES = {"diskutil": {"list", "info"}, "defaults": {"read"}, "pmset": {"-g"}}
OPTIONS_INTERDITES = {"find": ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls"),
                      "sysctl": ("-w",), "top": ()}


def analyser_commande(cmd: str) -> list[str] | None:
    """Mots de la commande si elle est sûre à exécuter sans shell ni confirmation, sinon None."""
    if not cmd or SHELL.search(cmd) or len(cmd) > 500:
        return None
    try:
        mots = shlex.split(cmd)
    except ValueError:
        return None
    if not mots or mots[0] not in LECTURE_SEULE:
        return None
    nom, reste = mots[0], mots[1:]
    if nom in SOUS_COMMANDES and (not reste or reste[0] not in SOUS_COMMANDES[nom]):
        return None
    if any(m in OPTIONS_INTERDITES.get(nom, ()) or "=" in m and nom == "sysctl" for m in reste):
        return None
    mots = [str(Path(m).expanduser()) if m.startswith("~") else m for m in mots]  # pas de shell : on développe ~
    reste = mots[1:]
    if nom == "top":  # sans -l, top tourne indéfiniment
        mots = ["top", "-l", "1", "-n", "15"]
    # Les fichiers lus passent par les mêmes interdits que lire_document (clés, mots de passe, cookies…).
    from .fichiers import chemin_interdit
    if any(chemin_interdit(m) for m in reste if "/" in m or m.startswith(".")):
        return None
    return mots


def risque_commande(args: dict) -> Risque:
    return Risque.LECTURE if analyser_commande(str(args.get("commande", ""))) else Risque.SENSIBLE


@outil("executer_commande", "Exécute une commande dans le Terminal (zsh) et renvoie sa sortie. "
       "Les commandes qui modifient quelque chose demandent confirmation.", "systeme",
       {"commande": ("string", "commande shell complète"),
        "dossier": ("string", "dossier de travail, facultatif")}, requis=["commande"],
       risque=risque_commande, toujours_confirmer=False,
       annonce=lambda a: f"Exécuter dans le Terminal : {a['commande']}")
def executer_commande(ctx, commande, dossier="~"):
    import subprocess
    mots = analyser_commande(commande)
    # Lecture seule : exécutée directement, sans shell. Sinon (confirmée par l'utilisateur) : zsh sans fichiers
    # de démarrage (-f), pour qu'un ~/.zshenv modifié ne s'exécute pas à chaque commande.
    cmd = mots if mots else ["/bin/zsh", "-fc", commande]
    env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home()),
           "LANG": "fr_FR.UTF-8", "USER": getpass.getuser()}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env,
                           cwd=str(commun.chemin(dossier or "~")))
    except subprocess.TimeoutExpired:
        raise ErreurOutil("Commande arrêtée après 120 s.") from None
    except FileNotFoundError:
        raise ErreurOutil(f"Commande introuvable : {cmd[0]}") from None
    sortie = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
    return Resultat(r.returncode == 0, f"Code de sortie {r.returncode}\n{sortie or '(aucune sortie)'}")


# --- Réglages Système : ouverture directe d'une rubrique ---------------------------------------
# Plus fiable que de naviguer à la souris dans la fenêtre (un petit modèle s'y perd) : adresse interne de macOS.
RUBRIQUES = {
    "bluetooth": "com.apple.BluetoothSettings", "wifi": "com.apple.wifi-settings-extension",
    "reseau": "com.apple.Network-Settings.extension", "son": "com.apple.Sound-Settings.extension",
    "ecrans": "com.apple.Displays-Settings.extension", "batterie": "com.apple.Battery-Settings.extension",
    "clavier": "com.apple.Keyboard-Settings.extension", "trackpad": "com.apple.Trackpad-Settings.extension",
    "souris": "com.apple.Mouse-Settings.extension", "notifications": "com.apple.Notifications-Settings.extension",
    "confidentialite": "com.apple.settings.PrivacySecurity.extension",
    "accessibilite": "com.apple.Accessibility-Settings.extension",
    "apparence": "com.apple.Appearance-Settings.extension", "bureau et dock": "com.apple.Desktop-Settings.extension",
    "fond d'ecran": "com.apple.Wallpaper-Settings.extension", "concentration": "com.apple.Focus-Settings.extension",
    "temps d'ecran": "com.apple.Screen-Time-Settings.extension",
    "ecran verrouille": "com.apple.Lock-Screen-Settings.extension",
    "utilisateurs": "com.apple.Users-Groups-Settings.extension",
    "mise a jour": "com.apple.Software-Update-Settings.extension", "general": "com.apple.systempreferences.GeneralSettings",
    "date et heure": "com.apple.Date-Time-Settings.extension", "imprimantes": "com.apple.Print-Scan-Settings.extension",
    "siri": "com.apple.Siri-Settings.extension", "spotlight": "com.apple.Spotlight-Settings.extension",
    "stockage": "com.apple.settings.Storage", "partage": "com.apple.Sharing-Settings.extension",
    "comptes internet": "com.apple.Internet-Accounts-Settings.extension",
    "touch id": "com.apple.Touch-ID-Settings.extension",
}
SYNONYMES_RUBRIQUES = {"wi-fi": "wifi", "audio": "son", "volume": "son", "ecran": "ecrans", "moniteur": "ecrans",
                       "energie": "batterie", "securite": "confidentialite", "vie privee": "confidentialite",
                       "dock": "bureau et dock", "mode sombre": "apparence", "theme": "apparence",
                       "ne pas deranger": "concentration", "mises a jour": "mise a jour", "langue": "general",
                       "heure": "date et heure", "imprimante": "imprimantes", "disque": "stockage",
                       "compte": "utilisateurs", "mot de passe": "touch id", "internet": "reseau"}


@outil("ouvrir_reglage", "Ouvre directement une rubrique des Réglages Système (Bluetooth, Wi-Fi, Son, Écrans, "
       "Batterie, Clavier, Notifications, Confidentialité, Apparence, Bureau et Dock, Concentration, Mise à jour…).",
       "systeme", {"rubrique": ("string", "rubrique, ex. « Bluetooth », « Wi-Fi », « Son »")},
       risque=Risque.CREATION, annonce=lambda a: f"Ouvrir les Réglages : {a['rubrique']}",
       mots_cles=["reglage", "reglages", "parametres", "preferences", "bluetooth", "wifi", "wi-fi",
                  "mode sombre", "fond d'ecran", "ne pas deranger"])
def ouvrir_reglage(ctx, rubrique):
    from ..agent.routeur import normaliser
    cle = normaliser(str(rubrique)).strip()
    cle = SYNONYMES_RUBRIQUES.get(cle, cle)
    if cle not in RUBRIQUES:
        proches = [k for k in RUBRIQUES if cle in k or k in cle]
        if not proches:
            raise ErreurOutil(f"Rubrique « {rubrique} » inconnue. Disponibles : {', '.join(sorted(RUBRIQUES))}.")
        cle = proches[0]
    commun.executer(["open", f"x-apple.systempreferences:{RUBRIQUES[cle]}"])
    return f"Réglages Système ouverts sur « {cle} ». Pour y changer quelque chose : lire_fenetre puis cliquer."
