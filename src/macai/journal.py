"""Journal de toutes les actions (JSON lignes, rotation simple)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

TAILLE_MAX = 5 * 1024 * 1024


class Journal:
    def __init__(self, fichier: Path):
        self.fichier = Path(fichier)
        self._verrou = threading.Lock()

    def ecrire(self, type_: str, **donnees) -> None:
        ligne = json.dumps({"ts": round(time.time(), 3), "type": type_, **donnees},
                           ensure_ascii=False, default=str)
        with self._verrou:
            self.fichier.parent.mkdir(parents=True, exist_ok=True)
            if self.fichier.exists() and self.fichier.stat().st_size > TAILLE_MAX:
                self.fichier.replace(self.fichier.with_suffix(".1.jsonl"))
            with self.fichier.open("a", encoding="utf-8") as f:
                f.write(ligne + "\n")

    def derniers(self, n: int = 50) -> list[dict]:
        if not self.fichier.exists():
            return []
        lignes = self.fichier.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(l) for l in lignes if l.strip()]
