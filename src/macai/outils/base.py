"""Registre des outils que l'agent peut utiliser.

Un outil = une fonction Python décorée par `@outil(...)`. Elle reçoit le contexte puis ses arguments
nommés, et renvoie un `Resultat` (ou une chaîne, considérée comme un succès).
"""
from __future__ import annotations

import importlib
import inspect
import os
import re
import sys
import threading
import time
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


# Jamais cliqué, choisi ni rempli par l'agent, quelle que soit l'application : rien qui dépense de l'argent
# ou demande des crédits / une utilisation supplémentaire (règle de Mathieu, même si une limite est atteinte).
ACHAT = re.compile(
    r"\bachet|\bachat|\bpayer\b|\bpaiement|\bpay now\b|\bcr[ée]dits? (d.utilisation|suppl|additionnel)|"
    r"\bbuy\b|\bpurchase|\bcheckout\b|\bpasser (à|au) (pro|max|plus|team|premium|l.offre)|\bupgrade (plan|to)\b|"
    r"\b(s.)?abonner\b|\bsouscri|\bsubscribe\b|\bforfait\b|\bfacturation\b|\bbilling\b|"
    r"(passer|valider|confirmer|finaliser) (la |ma |votre )?commande|\bplace (your |the )?order|\border now\b|"
    r"\bcommander\b|\bessai gratuit|\bfree trial|\b1[- ]?cli(c|ck)\b|\btop[- ]?up\b|"
    r"recharger (mon|le|votre|ma) (compte|solde|cr[ée]dit|carte)|\badd funds|ajouter des fonds|"
    r"(utilisation|usage) suppl[ée]mentaire|\bextra usage|\bmore usage|\bplus d.utilisation|"
    r"augmenter (la|ma|votre) limite|\bincrease (your )?limit|\bajouter au panier|\badd to (cart|bag|basket)\b|"
    r"\bpanier\b|\bcart\b", re.I)
AUTORISES = re.compile(r"d[ée]sabonn|unsubscribe|r[ée]silier|cancel subscription", re.I)
PRIX = re.compile(r"\d\s?(€|eur\b)|[€$£]\s?\d", re.I)


def interdire_achat(*textes, bouton: bool = False) -> None:
    """Lève ErreurOutil si l'action vise un achat, des crédits ou une utilisation payante. `bouton` : le libellé
    est celui d'un bouton ou d'un lien (un prix y signale un achat ; dans un simple texte, non)."""
    for t in textes:
        if not t or AUTORISES.search(str(t)):
            continue
        if ACHAT.search(str(t)) or (bouton and PRIX.search(str(t))):
            raise ErreurOutil(f"Refusé : « {str(t)[:80]} » ressemble à un achat, des crédits ou une utilisation "
                              "payante. MacAI ne fait jamais ce genre d'action ; c'est à toi de décider.")


IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ .-]?[A-Z0-9]{4}){2,7}(?:[ .-]?[A-Z0-9]{1,3})?\b")


def _luhn(chiffres: str) -> bool:
    total, double = 0, False
    for c in reversed(chiffres):
        n = int(c) * (2 if double else 1)
        total += n - 9 if n > 9 else n
        double = not double
    return total % 10 == 0


def interdire_donnees_bancaires(texte) -> None:
    """Jamais de numéro de carte (13 à 19 chiffres valides, quels que soient les séparateurs) ni d'IBAN."""
    t = str(texte or "")
    for bloc in re.findall(r"(?:\d[ .\-]?){13,19}", t):
        chiffres = re.sub(r"\D", "", bloc)
        if 13 <= len(chiffres) <= 19 and _luhn(chiffres):
            raise ErreurOutil("Ça ressemble à un numéro de carte : je ne saisis pas de données bancaires.")
    if IBAN.search(t.upper()):
        raise ErreurOutil("Ça ressemble à un IBAN : je ne saisis pas de données bancaires.")


# Applications où taper ou valider revient à exécuter du code, ou à envoyer un message à quelqu'un.
APPS_EXECUTION = {"terminal", "iterm", "iterm2", "warp", "ghostty", "alacritty", "kitty", "wezterm", "hyper",
                  "editeur de script", "script editor", "automator", "raccourcis", "shortcuts",
                  "trousseau d'acces", "keychain access", "utilitaire de disque", "disk utility",
                  "visual studio code", "code", "cursor", "xcode"}
APPS_MESSAGERIE = {"mail", "messages", "whatsapp", "slack", "discord", "telegram", "signal", "microsoft teams",
                   "teams", "outlook", "messenger", "spark", "thunderbird", "facetime", "skype", "zoom"}
ENVOI = re.compile(r"envoy|send|publi|post|partag|share|soumett|submit|r[ée]pond|reply|transf[ée]r|forward|"
                   r"supprim|delete|effac|vider|empty|erase|d[ée]sinstall|uninstall", re.I)


def nom_appli(nom: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", str(nom or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").replace("’", "'").strip()


SYNONYMES_ARGS = {
    "path": ("chemin", "source"), "file": ("chemin", "source"), "fichier": ("chemin", "source"),
    "filepath": ("chemin",), "chemin_fichier": ("chemin",), "src": ("source",), "from": ("source",),
    "de": ("source",), "origine": ("source",), "to": ("destination",), "dest": ("destination",),
    "vers": ("destination",), "cible": ("destination",), "dossier_destination": ("destination",),
    "target": ("destination",), "name": ("nom",), "application": ("nom", "application"), "app": ("nom", "application"),
    "appli": ("nom", "application"), "logiciel": ("nom", "application"), "text": ("texte",), "message": ("texte",),
    "content": ("contenu", "texte"), "body": ("corps", "contenu"), "query": ("requete",), "q": ("requete",),
    "recherche": ("requete",), "search": ("requete",), "link": ("url",), "lien": ("url",), "adresse": ("url",),
    "keys": ("touches",), "shortcut": ("touches",), "raccourci": ("touches",), "touche": ("touches",),
    "level": ("niveau",), "volume": ("niveau",), "number": ("numero",), "num": ("numero",), "element": ("numero",),
    "id": ("numero",), "command": ("commande",), "cmd": ("commande",), "question": ("question",),
    "title": ("titre",), "date": ("date",), "folder": ("dossier", "chemin"), "directory": ("dossier", "chemin"),
}


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
    delai_max: float = 120                            # au-delà, l'outil est abandonné (le moteur ne gèle jamais)

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

    def preparer(self, args: dict) -> tuple[dict, str]:
        """Arguments réellement utilisés (inventés ignorés, types corrigés) et message d'erreur éventuel. Sert
        aussi au calcul du risque, pour qu'il porte sur ce qui sera exécuté."""
        signature = inspect.signature(self.fonction)
        accepte_tout = any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values())
        propres = {k: v for k, v in args.items() if accepte_tout or k in signature.parameters}
        # Noms de paramètres que les petits modèles emploient à la place des vrais (anglais, synonymes).
        for k, v in args.items():
            if k not in propres:
                cible = next((c for c in SYNONYMES_ARGS.get(nom_appli(k), ()) if c in self.parametres
                              and c not in propres), None)
                if cible:
                    propres[cible] = v
        inconnus = [k for k in args if k not in propres and not any(
            c in self.parametres and propres.get(c) is args[k] for c in SYNONYMES_ARGS.get(nom_appli(k), ()))]
        manquants = [r for r in self.requis if r not in propres or str(propres[r]).strip() in ("", "None")]
        # Petit modèle : « application » au lieu de « nom », « path » au lieu de « chemin »… Un seul paramètre
        # obligatoire manquant et un seul argument inconnu : c'est forcément lui.
        if manquants and len(manquants) == len(inconnus):  # dans l'ordre : (source, destination) ← (a, b)
            for m, i in zip(manquants, inconnus):
                propres[m] = args[i]
        propres, invalides = self._corriger(propres)
        if invalides:
            return propres, "Valeur invalide : " + " ; ".join(invalides)
        manquants = [r for r in self.requis if r not in propres or str(propres[r]).strip() in ("", "None")]
        if manquants:
            attendus = ", ".join(f"{k} ({v.get('description', '')})" for k, v in self.parametres.items())
            return propres, f"Paramètre manquant : {', '.join(manquants)}. Paramètres de {self.nom} : {attendus}."
        return propres, ""

    def executer(self, ctx, args: dict) -> Resultat:
        propres, erreur = self.preparer(args)
        if erreur:
            return Resultat.echec(erreur)
        sortie: dict = {}

        def lancer():
            try:
                sortie["r"] = self.fonction(ctx, **propres)
            except BaseException as e:  # noqa: BLE001 - transmis au fil appelant
                sortie["e"] = e

        # L'outil tourne dans un fil surveillé : une fenêtre d'autorisation macOS restée sans réponse (accès au
        # Bureau…) bloquait le moteur indéfiniment (vu en essai réel).
        fil = threading.Thread(target=lancer, daemon=True, name=f"outil-{self.nom}")
        fil.start()
        fin = time.monotonic() + self.delai_max
        arret = getattr(ctx, "arret", None)
        while fil.is_alive() and time.monotonic() < fin:
            fil.join(0.25)
            if arret is not None and arret.is_set() and fil.is_alive():
                raise InterruptedError
        if fil.is_alive():
            return Resultat.echec(f"{self.nom} ne répond pas après {self.delai_max:.0f} s. Une fenêtre "
                                  "d'autorisation de macOS attend peut-être une réponse (accès au Bureau, aux "
                                  "Documents, à une application…) : dis-le à l'utilisateur.")
        if "e" in sortie:
            e = sortie["e"]
            if isinstance(e, InterruptedError):
                raise e
            if isinstance(e, ErreurOutil):
                return Resultat.echec(str(e))
            return Resultat.echec(f"Erreur inattendue ({type(e).__name__}) : {e}")
        r = sortie.get("r")
        if isinstance(r, Resultat):
            return r
        return Resultat(True, "" if r is None else str(r))

    def _corriger(self, args: dict) -> tuple[dict, list[str]]:
        """Rend les arguments d'un petit modèle exploitables : types convertis, valeurs hors liste écartées
        si le paramètre est facultatif (refusées s'il est obligatoire)."""
        sortie, invalides = {}, []
        for k, v in args.items():
            spec = self.parametres.get(k)
            if not spec or v is None:
                sortie[k] = v
                continue
            typ = spec.get("type")
            try:
                if typ == "integer" and not isinstance(v, bool):
                    v = int(float(str(v).replace(",", ".").strip())) if not isinstance(v, int) else v
                elif typ == "number" and not isinstance(v, (int, float)):
                    v = float(str(v).replace(",", ".").strip())
                elif typ == "boolean" and not isinstance(v, bool):
                    v = str(v).strip().lower() in ("true", "1", "oui", "yes", "vrai")
                elif typ == "string" and not isinstance(v, str):
                    v = str(v[0]) if isinstance(v, list) and len(v) == 1 else (
                        ", ".join(map(str, v)) if isinstance(v, list) else str(v))
                elif typ == "array" and isinstance(v, str):
                    import json as _json
                    try:
                        v = _json.loads(v)
                    except ValueError:
                        v = [x.strip() for x in v.split(",") if x.strip()]
            except (ValueError, TypeError):
                if k in self.requis:
                    invalides.append(f"{k} doit être de type {typ}")
                continue
            if "enum" in spec and v not in spec["enum"]:
                cle = nom_appli(v).replace(" ", "_").replace("-", "_")
                proche = [e for e in spec["enum"] if nom_appli(e).replace(" ", "_").replace("-", "_") == cle]
                if proche:
                    sortie[k] = proche[0]
                    continue
                if k in self.requis:
                    invalides.append(f"{k} doit valoir : {', '.join(map(str, spec['enum']))}")
                continue
            sortie[k] = v
        return sortie, invalides


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
        self._verrou = threading.Lock()  # compétences et découverte MCP modifient le registre en arrière-plan

    def ajouter(self, o: Outil) -> Outil:
        with self._verrou:
            self.outils = {**self.outils, o.nom: o}  # copie : une itération en cours n'est jamais perturbée
        return o

    def retirer(self, nom: str) -> None:
        with self._verrou:
            self.outils = {k: v for k, v in self.outils.items() if k != nom}

    def get(self, nom: str) -> Outil | None:
        return self.outils.get(nom)

    def groupes(self) -> dict[str, list[Outil]]:
        g: dict[str, list[Outil]] = {}
        for o in self.disponibles():
            g.setdefault(o.groupe, []).append(o)
        return g

    def disponibles(self) -> list[Outil]:
        # MACAI_TOUS_OUTILS=1 : montre aussi les outils macOS ailleurs (banc, tests sur le poste de dev).
        sur_mac = sys.platform == "darwin" or os.environ.get("MACAI_TOUS_OUTILS") == "1"
        # list() : la découverte MCP en arrière-plan peut ajouter des outils pendant qu'on parcourt.
        return [o for o in list(self.outils.values()) if sur_mac or not o.mac_seulement]

    def schemas(self, noms) -> list[dict]:
        return [self.outils[n].schema() for n in noms if n in self.outils]


REGISTRE = Registre()


def outil(nom: str, description: str, groupe: str, parametres: dict | None = None,
          requis: list | None = None, risque=Risque.LECTURE, toujours_confirmer: bool = False,
          mac_seulement: bool = True, annonce=None, mots_cles=None, registre: Registre | None = None,
          delai_max: float = 120):
    """Décorateur : `@outil("lire_fichier", "Lit un fichier…", "fichiers", {"chemin": ("string", "…")})`."""
    params = {k: _param(v) for k, v in (parametres or {}).items()}

    def deco(f):
        (registre or REGISTRE).ajouter(Outil(
            nom=nom, description=description, fonction=f, groupe=groupe, parametres=params,
            requis=list(requis if requis is not None else params.keys()), risque=risque,
            toujours_confirmer=toujours_confirmer, mac_seulement=mac_seulement, annonce=annonce,
            mots_cles=list(mots_cles or []), delai_max=delai_max,
        ))
        return f
    return deco


MODULES = ["systeme", "applications", "fichiers", "documents", "recherche_outils", "chrome",
           "fenetres", "discussions", "organisation", "memoire_outils", "competences_outils", "onshape_outils",
           "taches", "texte_outils"]


# Outils lents par nature (modèle de vision, OCR, réponse d'une autre IA, gros dossiers) : délai plus long.
DELAIS_LONGS = {"demander_a_claude": 200, "executer_commande": 135, "attendre": 75, "decrire_image": 240,
                "voir_ecran": 240, "cliquer_ecran": 240, "lire_document": 240, "ranger_dossier": 300,
                "indexer_maintenant": 60, "onshape_creer_piece": 180, "youtube_lire": 60}


def charger_tous() -> Registre:
    for m in MODULES:
        importlib.import_module(f"macai.outils.{m}")
    for nom, delai in DELAIS_LONGS.items():
        if (o := REGISTRE.get(nom)) is not None:
            o.delai_max = delai
    return REGISTRE
