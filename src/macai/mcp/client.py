"""Client MCP (Model Context Protocol) sur stdio, sans dépendance.

Chaque serveur configuré dans macai.toml devient un groupe d'outils pour l'agent. Les serveurs sont
démarrés à la première utilisation et arrêtés après 5 minutes sans appel (RAM libérée).
La liste de leurs outils est mise en cache pour ne rien lancer au démarrage de MacAI.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

from ..outils.base import Outil, Registre, Resultat, Risque, interdire_achat

VERSION_PROTOCOLE = "2025-06-18"
INACTIVITE_S = 300
# Variables transmises aux serveurs (plus celles de leur configuration) : jamais tout l'environnement de MacAI.
ENV_TRANSMIS = ("PATH", "HOME", "LANG", "USER", "TMPDIR")
# Noms d'outils qui exécutent, effacent ou envoient : confirmation, quoi que le serveur annonce.
NOM_SENSIBLE = re.compile(r"run|exec|command|script|shell|delete|remove|erase|send|publish|upload", re.I)


class ErreurMCP(RuntimeError):
    pass


class ServeurMCP:
    def __init__(self, nom: str, commande: list[str], env: dict | None = None, delai: float = 60):
        self.nom = nom
        self.commande = commande
        self.env = env or {}
        self.delai = delai
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._verrou = threading.Lock()
        self.derniere_utilisation = 0.0
        self.info: dict = {}

    # --- Cycle de vie --------------------------------------------------------

    def demarrer(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        try:
            self.proc = subprocess.Popen(
                self.commande, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=environnement(self.env), text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as e:
            raise ErreurMCP(f"Impossible de lancer le serveur MCP « {self.nom} » ({self.commande[0]}) : {e}") from e
        rep = self._requete("initialize", {"protocolVersion": VERSION_PROTOCOLE, "capabilities": {},
                                           "clientInfo": {"name": "MacAI", "version": "0.1"}})
        self.info = rep.get("serverInfo", {})
        self._notifier("notifications/initialized")

    def arreter(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
        self.proc = None

    def actif(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # --- JSON-RPC --------------------------------------------------------------

    def _envoyer(self, message: dict) -> None:
        if not self.actif():
            raise ErreurMCP(f"Le serveur MCP « {self.nom} » s'est arrêté.")
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _notifier(self, methode: str, params: dict | None = None) -> None:
        self._envoyer({"jsonrpc": "2.0", "method": methode, **({"params": params} if params else {})})

    def occupe(self) -> bool:
        return self._verrou.locked()

    def arreter_si_inactif(self, delai: float = INACTIVITE_S) -> bool:
        """Arrête le serveur inactif ; jamais pendant un appel (verrou pris le temps de la vérification)."""
        if not self._verrou.acquire(blocking=False):
            return False
        try:
            if self.actif() and time.monotonic() - self.derniere_utilisation > delai:
                self.arreter()
                return True
            return False
        finally:
            self._verrou.release()

    def _requete(self, methode: str, params: dict | None = None) -> dict:
        with self._verrou:
            self.derniere_utilisation = time.monotonic()  # dès le début : jamais arrêté en plein appel
            self._id += 1
            ident = self._id
            self._envoyer({"jsonrpc": "2.0", "id": ident, "method": methode, "params": params or {}})
            fin = time.monotonic() + self.delai
            resultat: dict = {}
            evenement = threading.Event()

            def lire():
                try:
                    _lire()
                except (OSError, ValueError) as e:
                    resultat["erreur"] = f"lecture impossible ({e})"
                evenement.set()

            def _lire():
                while True:
                    ligne = self.proc.stdout.readline()
                    if not ligne:
                        resultat["erreur"] = "le serveur a fermé la connexion"
                        break
                    try:
                        msg = json.loads(ligne)
                    except ValueError:
                        continue  # journal du serveur sur stdout : ignoré
                    if msg.get("id") == ident and ("result" in msg or "error" in msg):
                        resultat.update(msg)
                        break
                    if "method" in msg and "id" in msg:  # requête du serveur (ex. ping) : réponse vide
                        self._envoyer({"jsonrpc": "2.0", "id": msg["id"], "result": {}})

            threading.Thread(target=lire, daemon=True).start()
            if not evenement.wait(max(0.0, fin - time.monotonic())):
                self.arreter()
                raise ErreurMCP(f"« {self.nom} » n'a pas répondu à {methode} en {self.delai:.0f} s.")
            self.derniere_utilisation = time.monotonic()
            if "erreur" in resultat:
                raise ErreurMCP(f"« {self.nom} » : {resultat['erreur']}")
            if "error" in resultat:
                e = resultat["error"]
                raise ErreurMCP(f"« {self.nom} » : {e.get('message', e)}")
            return resultat.get("result", {})

    # --- API ---------------------------------------------------------------------

    def lister_outils(self) -> list[dict]:
        self.demarrer()
        outils, curseur = [], None
        while True:
            rep = self._requete("tools/list", {"cursor": curseur} if curseur else {})
            outils += rep.get("tools", [])
            curseur = rep.get("nextCursor")
            if not curseur:
                return outils

    def appeler(self, outil: str, arguments: dict) -> tuple[bool, str, list]:
        self.demarrer()
        rep = self._requete("tools/call", {"name": outil, "arguments": arguments})
        textes, fichiers = [], []
        for bloc in rep.get("content", []):
            if bloc.get("type") == "text":
                textes.append(bloc.get("text", ""))
            elif bloc.get("type") == "resource":
                res = bloc.get("resource", {})
                textes.append(res.get("text") or f"[ressource {res.get('uri', '')}]")
            elif bloc.get("type") == "resource_link":
                fichiers.append(bloc.get("uri"))
                textes.append(f"[fichier {bloc.get('uri')}]")
            elif bloc.get("type") == "image":
                textes.append("[image renvoyée]")
        if rep.get("structuredContent") and not textes:
            textes.append(json.dumps(rep["structuredContent"], ensure_ascii=False))
        return not rep.get("isError", False), "\n".join(textes) or "(aucun contenu)", fichiers


def environnement(propre: dict | None) -> dict:
    env = {k: os.environ[k] for k in ENV_TRANSMIS if k in os.environ}
    return {**env, **{str(k): str(v) for k, v in (propre or {}).items()}}


def commande_de(config: dict) -> list[str]:
    """`commande` en liste, ou en chaîne découpée comme le ferait le shell (guillemets, espaces échappés)."""
    c = config["commande"]
    return [str(x) for x in c] if isinstance(c, list) else shlex.split(str(c))


def empreinte(config: dict) -> str:
    """Change quand la commande ou l'environnement du serveur change : outils redécouverts."""
    brut = json.dumps([commande_de(config), config.get("env") or {}], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(brut.encode()).hexdigest()[:16]


def textes_de(valeur) -> list[str]:
    if isinstance(valeur, str):
        return [valeur]
    if isinstance(valeur, dict):
        return [t for v in valeur.values() for t in textes_de(v)]
    if isinstance(valeur, list):
        return [t for v in valeur for t in textes_de(v)]
    return []


def _resumer(texte: str, limite: int) -> str:
    """Premières phrases d'une description, sans dépasser la limite (un petit modèle lit mal les pavés)."""
    texte = " ".join(str(texte).split())
    if len(texte) <= limite:
        return texte
    coupe = texte[:limite]
    fin = coupe.rfind(". ")
    return coupe[:fin + 1] if fin > limite // 3 else coupe.rstrip() + "…"


def _type_simple(spec: dict) -> str:
    t = spec.get("type")
    if isinstance(t, list):  # ["string", "null"] : facultatif, on garde le vrai type
        t = next((x for x in t if x != "null"), "string")
    if not t:
        variantes = spec.get("anyOf") or spec.get("oneOf") or []
        t = next((v.get("type") for v in variantes if v.get("type") not in (None, "null")), "object")
    return t if isinstance(t, str) else "string"


def compacter(proprietes: dict) -> dict:
    """Schémas MCP allégés : type, description courte, valeurs permises. Divise la taille par 3 à 5
    (mesuré sur ArtCraft) sans changer ce que le serveur reçoit."""
    sortie = {}
    for nom, spec in (proprietes or {}).items():
        if not isinstance(spec, dict):
            continue
        p = {"type": _type_simple(spec)}
        if spec.get("description"):
            p["description"] = _resumer(spec["description"], 160)
        if spec.get("enum"):
            p["enum"] = [v for v in spec["enum"] if v is not None]
        if p["type"] == "array" and isinstance(spec.get("items"), dict):
            p["items"] = {"type": _type_simple(spec["items"])}
        sortie[nom] = p
    return sortie


def developper_chemins(valeur):
    """« ~/Desktop/x.png » → chemin absolu : les logiciels tiers ne connaissent pas le « ~ » du shell."""
    if isinstance(valeur, str) and (valeur == "~" or valeur.startswith("~/")):
        return os.path.expanduser(valeur)
    if isinstance(valeur, dict):
        return {k: developper_chemins(v) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [developper_chemins(v) for v in valeur]
    return valeur


def nom_outil(serveur: str, outil: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", f"{serveur}__{outil}")[:64]


def risque_mcp(definition: dict, force: str | None = None) -> Risque:
    if force:
        return {"lecture": Risque.LECTURE, "creation": Risque.CREATION, "modification": Risque.MODIFICATION,
                "sensible": Risque.SENSIBLE}.get(force, Risque.MODIFICATION)
    ann = definition.get("annotations") or {}
    if ann.get("destructiveHint") is True or NOM_SENSIBLE.search(str(definition.get("name", ""))):
        return Risque.SENSIBLE
    if ann.get("readOnlyHint") is True:
        return Risque.LECTURE
    return Risque.SENSIBLE  # rien d'annoncé : on ne sait pas ce que fait l'outil, confirmation


class GestionnaireMCP:
    """Charge les serveurs de la configuration et expose leurs outils dans le registre."""

    def __init__(self, configs: list[dict], registre: Registre, cache: Path):
        self.registre = registre
        self.cache_fichier = Path(cache)
        self.serveurs: dict[str, ServeurMCP] = {}
        self.configs = {c["nom"]: c for c in configs if c.get("nom") and c.get("commande")}
        self.mots_routeur: dict[str, list[str]] = {}
        for nom, c in self.configs.items():
            self.serveurs[nom] = ServeurMCP(nom, commande_de(c), c.get("env"), float(c.get("delai", 60)))
            self.mots_routeur[f"mcp_{nom}"] = [nom.lower(), *[m.lower() for m in c.get("mots_cles", [])]]
        self._arret = threading.Event()

    def _cache(self) -> dict:
        try:
            return json.loads(self.cache_fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def enregistrer(self, decouvrir: bool = True) -> dict[str, str]:
        """Inscrit les outils (depuis le cache, ou en interrogeant les serveurs). Renvoie l'état par serveur."""
        cache, etats, nouveaux, remplaces = self._cache(), {}, {}, set()
        for nom, serveur in self.serveurs.items():
            cle = empreinte(self.configs[nom])
            entree = cache.get(nom)
            anciennes = entree.get("outils") if isinstance(entree, dict) else entree  # ancien format : liste
            # Configuration modifiée (commande, env) : outils redécouverts ; d'ici là, l'ancienne liste sert.
            definitions = anciennes if isinstance(entree, dict) and entree.get("empreinte") == cle else None
            if definitions is None and decouvrir:
                try:
                    definitions = serveur.lister_outils()
                    cache[nom] = {"empreinte": cle, "outils": definitions}
                    remplaces.add(f"mcp_{nom}")
                    serveur.arreter_si_inactif(0)
                except ErreurMCP as e:
                    etats[nom] = f"erreur : {e}"
                    continue
            if definitions is None:
                definitions = anciennes if isinstance(anciennes, list) and not decouvrir else None
            if definitions is None:
                etats[nom] = "non découvert"
                continue
            for d in definitions:
                o = self._outil(nom, d)
                nouveaux[o.nom] = o
            etats[nom] = f"{len(definitions)} outils"
        # Remplacement d'un bloc : la découverte tourne en fond pendant que l'agent parcourt le registre ;
        # le dictionnaire en cours de lecture n'est jamais modifié.
        gardes = {n: o for n, o in self.registre.outils.items() if o.groupe not in remplaces}
        self.registre.outils = {**gardes, **nouveaux}
        self.cache_fichier.parent.mkdir(parents=True, exist_ok=True)
        self.cache_fichier.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return etats

    def _outil(self, serveur: str, d: dict) -> Outil:
        cfg = self.configs[serveur]
        schema = d.get("inputSchema") or {"type": "object", "properties": {}}
        nom_reel = d["name"]

        def appeler(ctx, **args):
            interdire_achat(*textes_de(args))  # même règle que pour les applis : jamais d'achat ni de crédits
            ok, texte, fichiers = self.serveurs[serveur].appeler(nom_reel, developper_chemins(args))
            return Resultat(ok, texte, {"fichiers": fichiers} if fichiers else None)

        o = Outil(nom=nom_outil(serveur, nom_reel),
                  description=f"[{cfg.get('titre', serveur)}] {_resumer(d.get('description') or nom_reel, 300)}",
                  fonction=appeler, groupe=f"mcp_{serveur}", parametres=compacter(schema.get("properties", {})),
                  requis=schema.get("required", []), risque=risque_mcp(d, (cfg.get("risques") or {}).get(nom_reel)),
                  mac_seulement=False, mots_cles=[serveur.lower(), *[m.lower() for m in cfg.get("mots_cles", [])]])
        # Erreurs MCP : messages lisibles plutôt qu'« Erreur inattendue ».
        fonction = o.fonction

        def protegee(ctx, **args):
            try:
                return fonction(ctx, **args)
            except ErreurMCP as e:
                return Resultat.echec(str(e))
        o.fonction = protegee
        return o

    def surveiller(self) -> None:
        """Arrête les serveurs inactifs (fil d'exécution de fond)."""
        def boucle():
            while not self._arret.wait(30):
                for s in self.serveurs.values():
                    s.arreter_si_inactif()
        threading.Thread(target=boucle, daemon=True, name="mcp-veille").start()

    def fermer(self) -> None:
        self._arret.set()
        for s in self.serveurs.values():
            s.arreter()
