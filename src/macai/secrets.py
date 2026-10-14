"""Secrets (clés d'API) dans le Trousseau macOS. Jamais dans le dépôt, jamais montrés au modèle."""
from __future__ import annotations

import getpass
import json
import re
import subprocess
import sys

from .config import dossier_donnees

PREFIXE = "MacAI-"


def _fichier():
    return dossier_donnees() / "secrets" / "secrets.json"   # poste de développement uniquement


def ecrire(nom: str, compte: str, secret: str) -> None:
    if sys.platform == "darwin":
        commande = f"add-generic-password -U -s {PREFIXE}{nom} -a {_echapper(compte)} -w {_echapper(secret)}\n"
        subprocess.run(["security", "-i"], input=commande, text=True, check=True, capture_output=True)
        return
    f = _fichier()
    f.parent.mkdir(parents=True, exist_ok=True)
    donnees = json.loads(f.read_text()) if f.exists() else {}
    donnees[nom] = [compte, secret]
    f.write_text(json.dumps(donnees))


def lire(nom: str) -> tuple[str, str] | None:
    if sys.platform == "darwin":
        r = subprocess.run(["security", "find-generic-password", "-s", PREFIXE + nom, "-w"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None
        info = subprocess.run(["security", "find-generic-password", "-s", PREFIXE + nom],
                              capture_output=True, text=True).stdout
        m = re.search(r'"acct"<blob>="([^"]*)"', info)
        return (m.group(1) if m else ""), r.stdout.strip()
    f = _fichier()
    if not f.exists():
        return None
    v = json.loads(f.read_text()).get(nom)
    return tuple(v) if v else None


def _echapper(s: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.@+-]+", s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def definir_interactif(nom: str) -> None:
    """`macai secret onshape` : saisie au clavier, rien n'est affiché ni enregistré dans l'historique."""
    aides = {"onshape": ("Clé d'accès (Access key)", "Clé secrète (Secret key)",
                         "Crée-les sur https://dev-portal.onshape.com/keys (API keys).")}
    l_compte, l_secret, aide = aides.get(nom, ("Identifiant", "Secret", ""))
    if aide:
        print(aide)
    compte = input(f"{l_compte} : ").strip()
    secret = getpass.getpass(f"{l_secret} (invisible) : ").strip()
    if not compte or not secret:
        print("Annulé.")
        return
    ecrire(nom, compte, secret)
    print(f"Enregistré dans le Trousseau ({PREFIXE}{nom}).")
