"""Contexte partagé par l'agent et les outils."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import Config
from ..journal import Journal
from ..llm.ollama import Ollama
from ..outils.base import Registre


def _toujours_non(phrase: str, outil: str, args: dict) -> bool:
    return False


@dataclass
class Contexte:
    config: Config
    ollama: Ollama
    registre: Registre
    journal: Journal
    emettre: Callable[..., None] = lambda *a, **k: None
    demander_confirmation: Callable[[str, str, dict], bool] = _toujours_non
    arret: threading.Event = field(default_factory=threading.Event)
    services: dict[str, Any] = field(default_factory=dict)   # memoire, index, competences, mcp…

    def service(self, nom: str):
        return self.services.get(nom)

    def verifier_arret(self) -> None:
        if self.arret.is_set():
            raise InterruptedError("Arrêté par l'utilisateur.")
