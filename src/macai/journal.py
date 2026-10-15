"""Journal de toutes les actions (JSON lignes, rotation simple)."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

TAILLE_MAX = 5 * 1024 * 1024
TEXTE_MAX = 300  # caractères gardés par valeur : le journal n'est pas une copie des documents lus


def abreger(valeur):
    """Tronque les longues chaînes, y compris dans les listes et dictionnaires."""
    if isinstance(valeur, str):
        return valeur if len(valeur) <= TEXTE_MAX else valeur[:TEXTE_MAX] + f"… [{len(valeur)} caractères]"
    if isinstance(valeur, dict):
        return {k: abreger(v) for k, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [abreger(v) for v in valeur]
    return valeur


class Journal:
    def __init__(self, fichier: Path):
        self.fichier = Path(fichier)
        self._verrou = threading.Lock()
        try:
            if self.fichier.exists():
                os.chmod(self.fichier, 0o600)  # journaux créés avant cette règle
        except OSError:
            pass

    def ecrire(self, type_: str, **donnees) -> None:
        ligne = json.dumps({"ts": round(time.time(), 3), "type": type_, **abreger(donnees)},
                           ensure_ascii=False, default=str)
        with self._verrou:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            if self.fichier.exists() and self.fichier.stat().st_size > TAILLE_MAX:
                self.fichier.replace(self.fichier.with_suffix(".1.jsonl"))  # rotation : un seul ancien gardé
            # Droits 0600 : le journal contient des demandes et des chemins personnels.
            fd = os.open(self.fichier, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(ligne + "\n")

    def derniers(self, n: int = 50) -> list[dict]:
        if not self.fichier.exists():
            return []
        lignes = self.fichier.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        sortie = []
        for l in lignes:
            try:
                sortie.append(json.loads(l))
            except ValueError:
                continue  # ligne tronquée (arrêt brutal)
        return sortie
