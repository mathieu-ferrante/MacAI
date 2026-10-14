"""Exécution des commandes macOS (osascript, open, pbcopy…) — point unique, remplaçable en test."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..outils.base import ErreurOutil


def executer(cmd: list[str], delai: float = 30, entree: str | None = None, verifier: bool = True) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=delai, input=entree)
    except FileNotFoundError as e:
        raise ErreurOutil(f"Commande introuvable : {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise ErreurOutil(f"La commande {cmd[0]} a dépassé {delai:.0f} s.") from e
    if verifier and r.returncode != 0:
        erreur = (r.stderr or r.stdout).strip()
        raise ErreurOutil(_expliquer(erreur) or f"{cmd[0]} a échoué (code {r.returncode}).")
    return r.stdout


def _expliquer(erreur: str) -> str:
    """Traduit les erreurs macOS fréquentes en consignes compréhensibles."""
    if "-1743" in erreur or "Not authorized to send Apple events" in erreur:
        return ("macOS bloque l'automatisation : Réglages Système > Confidentialité et sécurité > "
                "Automatisation > autorise MacAI pour cette application.")
    if ("-25211" in erreur or "-1719" in erreur or "assistive access" in erreur.lower()
            or "accès d’aide" in erreur or "accès d'aide" in erreur):
        return ("macOS bloque le contrôle des fenêtres : Réglages Système > Confidentialité et sécurité > "
                "Accessibilité > active MacAI.")
    if "-1728" in erreur:
        return f"Élément introuvable dans l'application ({erreur[:200]})."
    if "-600" in erreur:
        return "L'application n'est pas ouverte."
    return erreur[:500]


def chaine_as(s: str) -> str:
    """Chaîne AppleScript littérale correctement échappée."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def osascript(script: str, javascript: bool = False, delai: float = 30) -> str:
    cmd = ["osascript"] + (["-l", "JavaScript"] if javascript else []) + ["-e", script]
    return executer(cmd, delai=delai).strip()


def notifier(titre: str, message: str) -> None:
    osascript(f"display notification {chaine_as(message)} with title {chaine_as(titre)}")


def chemin(c: str) -> Path:
    """Résout ~, les noms de dossiers en français, et renvoie un chemin absolu."""
    c = str(c).strip().strip('"').strip("'")
    alias = {"bureau": "~/Desktop", "téléchargements": "~/Downloads", "telechargements": "~/Downloads",
             "documents": "~/Documents", "images": "~/Pictures", "musique": "~/Music", "vidéos": "~/Movies",
             "videos": "~/Movies", "dossier personnel": "~", "maison": "~"}
    premier, _, reste = c.replace("\\", "/").partition("/")
    if premier.lower() in alias:
        c = alias[premier.lower()] + ("/" + reste if reste else "")
    for fr, en in (("~/Bureau", "~/Desktop"), ("~/Téléchargements", "~/Downloads")):
        if c.startswith(fr):
            c = en + c[len(fr):]
    return Path(c).expanduser().resolve()
