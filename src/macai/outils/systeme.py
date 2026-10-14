"""Outils système : son, médias, presse-papiers, capture, mémoire, infos, Terminal."""
from __future__ import annotations

import re
import shlex
import time

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
    lignes += [f"- {a['name']} : {m.fmt_bytes(a['rss'])}" + (" (appli)" if a.get("is_app") else "")
               for a in s.apps[:8]]
    return "\n".join(lignes)


@outil("infos_systeme", "Batterie, espace disque libre, version de macOS, durée depuis le démarrage.",
       "systeme", {})
def infos_systeme(ctx):
    batt = commun.executer(["pmset", "-g", "batt"], verifier=False)
    pct = re.search(r"(\d+)%;\s*([^;]+);", batt)
    disque = commun.executer(["df", "-h", "/System/Volumes/Data"], verifier=False).splitlines()
    libre = disque[1].split()[3] if len(disque) > 1 else "?"
    version = commun.executer(["sw_vers", "-productVersion"], verifier=False).strip()
    depuis = commun.executer(["uptime"], verifier=False).strip()
    return "\n".join([
        f"Batterie : {pct.group(1)} % ({pct.group(2)})" if pct else "Batterie : inconnue",
        f"Disque : {libre} libres", f"macOS {version}", f"Allumé : {depuis}",
    ])


@outil("notifier", "Affiche une notification macOS.", "systeme",
       {"titre": ("string", "titre"), "message": ("string", "message")}, risque=Risque.CREATION)
def notifier(ctx, titre, message):
    commun.notifier(titre, message)
    return "Notification affichée."


# --- Terminal -----------------------------------------------------------------

LECTURE_SEULE = {"ls", "cat", "head", "tail", "wc", "df", "du", "find", "grep", "ps", "pwd", "whoami",
                 "sw_vers", "date", "uptime", "which", "mdfind", "file", "stat", "echo", "uname",
                 "system_profiler", "diskutil", "pmset", "top", "vm_stat", "sysctl", "defaults"}
DANGEREUX = re.compile(r"[;&|`>]|\$\(|\bsudo\b|\brm\b|\bwrite\b|\bdelete\b|-delete|-exec")


def risque_commande(args: dict) -> Risque:
    cmd = args.get("commande", "")
    try:
        mots = shlex.split(cmd)
    except ValueError:
        return Risque.SENSIBLE
    if mots and mots[0] in LECTURE_SEULE and not DANGEREUX.search(cmd):
        if mots[0] == "defaults" and (len(mots) < 2 or mots[1] != "read"):
            return Risque.SENSIBLE
        return Risque.LECTURE
    return Risque.SENSIBLE


@outil("executer_commande", "Exécute une commande dans le Terminal (zsh) et renvoie sa sortie. "
       "Les commandes qui modifient quelque chose demandent confirmation.", "systeme",
       {"commande": ("string", "commande shell complète"),
        "dossier": ("string", "dossier de travail, facultatif")}, requis=["commande"],
       risque=risque_commande, annonce=lambda a: f"Exécuter dans le Terminal : {a['commande']}")
def executer_commande(ctx, commande, dossier="~"):
    import subprocess
    try:
        r = subprocess.run(["/bin/zsh", "-lc", commande], capture_output=True, text=True, timeout=120,
                           cwd=str(commun.chemin(dossier)))
    except subprocess.TimeoutExpired:
        raise ErreurOutil("Commande arrêtée après 120 s.") from None
    sortie = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
    return Resultat(r.returncode == 0, f"Code de sortie {r.returncode}\n{sortie or '(aucune sortie)'}")
