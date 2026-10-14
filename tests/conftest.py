from __future__ import annotations

import pytest

from macai import config
from macai.agent.contexte import Contexte
from macai.journal import Journal
from macai.llm.ollama import AppelOutil, Reponse
from macai.outils.base import Registre


class FauxOllama:
    """Rejoue une liste de réponses préparées et garde les messages reçus."""

    def __init__(self, reponses=None):
        self.reponses = list(reponses or [])
        self.recus = []

    def discuter(self, modele, messages, outils=None, reflexion=False, sur_texte=None, options=None):
        self.recus.append({"messages": [dict(m) for m in messages], "outils": outils, "reflexion": reflexion})
        r = self.reponses.pop(0) if self.reponses else Reponse(texte="fin")
        if sur_texte and r.texte:
            sur_texte(r.texte)
        return r

    def vecteurs(self, modele, textes, dimensions=None):
        # Vecteur déterministe : sac de lettres, suffisant pour tester la mécanique.
        out = []
        for t in textes:
            v = [0.0] * (dimensions or 32)
            for i, c in enumerate(t.lower()):
                v[ord(c) % len(v)] += 1.0
            out.append(v)
        return out

    def decharger(self, modele):
        pass


def appel(nom, **args):
    return Reponse(appels=[AppelOutil(nom, args)])


@pytest.fixture
def cfg(tmp_path):
    return config.charger(tmp_path / "donnees")


@pytest.fixture
def ctx(cfg):
    evenements = []
    c = Contexte(config=cfg, ollama=FauxOllama(), registre=Registre(),
                 journal=Journal(cfg.chemin("journal.jsonl")),
                 emettre=lambda t, **d: evenements.append((t, d)))
    c.evenements = evenements
    return c
