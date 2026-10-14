"""Registre des outils que l'agent peut utiliser.

Un outil = une fonction Python décorée par `@outil(...)`. Elle reçoit le contexte puis ses arguments
nommés, et renvoie un `Resultat` (ou une chaîne, considérée comme un succès).
"""
from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable


class Risque(IntEnum):
    LECTURE = 0        # lire, chercher, lister
    CREATION = 1       # créer un fichier, ouvrir une appli ou un site
    MODIFICATION = 2   # déplacer, renommer, écraser, cliquer dans une fenêtre, quitter une appli
    SENSIBLE = 3       # Corbeille, envoyer, Terminal, se connecter : confirmation obligatoire


@dataclass
class Resultat:
    ok: bool
    texte: str
    donnees: Any = None

    @classmethod
    def echec(cls, texte: str) -> "Resultat":
        return cls(False, texte)


class ErreurOutil(Exception):
    """Erreur attendue (fichier introuvable, appli absente…) : message montré tel quel."""


@dataclass
class Outil:
    nom: str
    description: str
    fonction: Callable
    groupe: str
    parametres: dict = field(default_factory=dict)   # nom -> {"type", "description", "enum"?}
    requis: list = field(default_factory=list)
    risque: Risque | Callable[[dict], Risque] = Risque.LECTURE
    toujours_confirmer: bool = False                  # même en mode autonome (supprimer, envoyer, payer)
    mac_seulement: bool = True
    annonce: Callable[[dict], str] | None = None      # phrase lisible : « Mettre rapport.pdf à la Corbeille »
    mots_cles: list = field(default_factory=list)     # aide le routeur à proposer cet outil précis

    def risque_pour(self, args: dict) -> Risque:
        return self.risque(args) if callable(self.risque) else self.risque

    def phrase(self, args: dict) -> str:
        if self.annonce:
            try:
                return self.annonce(args)
            except Exception:  # noqa: BLE001 - une annonce ratée ne doit pas bloquer l'action
                pass
        details = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"{self.nom}({details})"

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.nom,
                "description": self.description,
                "parameters": {"type": "object", "properties": self.parametres, "required": self.requis},
            },
        }

    def executer(self, ctx, args: dict) -> Resultat:
        # Ignore les arguments inventés par le modèle, signale les manquants.
        signature = inspect.signature(self.fonction)
        accepte_tout = any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values())
        propres = {k: v for k, v in args.items() if accepte_tout or k in signature.parameters}
        manquants = [r for r in self.requis if r not in propres or propres[r] in ("", None)]
        if manquants:
            return Resultat.echec(f"Paramètre manquant : {', '.join(manquants)}.")
        try:
            r = self.fonction(ctx, **propres)
        except ErreurOutil as e:
            return Resultat.echec(str(e))
        except Exception as e:  # noqa: BLE001 - l'agent doit pouvoir réagir à toute erreur
            return Resultat.echec(f"Erreur inattendue ({type(e).__name__}) : {e}")
        if isinstance(r, Resultat):
            return r
        return Resultat(True, "" if r is None else str(r))


def _param(spec) -> dict:
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, tuple):
        typ, desc, *reste = spec
        d = {"type": typ, "description": desc}
        if reste:
            d["enum"] = list(reste[0])
        return d
    return {"type": "string", "description": str(spec)}


class Registre:
    def __init__(self):
        self.outils: dict[str, Outil] = {}

    def ajouter(self, o: Outil) -> Outil:
        self.outils[o.nom] = o
        return o

    def retirer(self, nom: str) -> None:
        self.outils.pop(nom, None)

    def get(self, nom: str) -> Outil | None:
        return self.outils.get(nom)

    def groupes(self) -> dict[str, list[Outil]]:
        g: dict[str, list[Outil]] = {}
        for o in self.disponibles():
            g.setdefault(o.groupe, []).append(o)
        return g

    def disponibles(self) -> list[Outil]:
        sur_mac = sys.platform == "darwin"
        return [o for o in self.outils.values() if sur_mac or not o.mac_seulement]

    def schemas(self, noms) -> list[dict]:
        return [self.outils[n].schema() for n in noms if n in self.outils]


REGISTRE = Registre()


def outil(nom: str, description: str, groupe: str, parametres: dict | None = None,
          requis: list | None = None, risque=Risque.LECTURE, toujours_confirmer: bool = False,
          mac_seulement: bool = True, annonce=None, mots_cles=None, registre: Registre | None = None):
    """Décorateur : `@outil("lire_fichier", "Lit un fichier…", "fichiers", {"chemin": ("string", "…")})`."""
    params = {k: _param(v) for k, v in (parametres or {}).items()}

    def deco(f):
        (registre or REGISTRE).ajouter(Outil(
            nom=nom, description=description, fonction=f, groupe=groupe, parametres=params,
            requis=list(requis if requis is not None else params.keys()), risque=risque,
            toujours_confirmer=toujours_confirmer, mac_seulement=mac_seulement, annonce=annonce,
            mots_cles=list(mots_cles or []),
        ))
        return f
    return deco


MODULES = ["systeme", "applications", "fichiers", "documents", "recherche_outils", "chrome",
           "fenetres", "organisation", "memoire_outils", "competences_outils", "onshape_outils"]


def charger_tous() -> Registre:
    for m in MODULES:
        importlib.import_module(f"macai.outils.{m}")
    return REGISTRE
