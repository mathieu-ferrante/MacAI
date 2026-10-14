"""Client MCP (Model Context Protocol) sur stdio, sans dépendance.

Chaque serveur configuré dans macai.toml devient un groupe d'outils pour l'agent. Les serveurs sont
démarrés à la première utilisation et arrêtés après 5 minutes sans appel (RAM libérée).
La liste de leurs outils est mise en cache pour ne rien lancer au démarrage de MacAI.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from ..outils.base import Outil, Registre, Resultat, Risque

VERSION_PROTOCOLE = "2025-06-18"
INACTIVITE_S = 300


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
                env={**os.environ, **self.env}, text=True, encoding="utf-8", errors="replace", bufsize=1)
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

    def _requete(self, methode: str, params: dict | None = None) -> dict:
        with self._verrou:
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


def nom_outil(serveur: str, outil: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", f"{serveur}__{outil}")[:64]


def risque_mcp(definition: dict, force: str | None = None) -> Risque:
    if force:
        return {"lecture": Risque.LECTURE, "creation": Risque.CREATION, "modification": Risque.MODIFICATION,
                "sensible": Risque.SENSIBLE}.get(force, Risque.MODIFICATION)
    ann = definition.get("annotations") or {}
    if ann.get("destructiveHint") is True:
        return Risque.SENSIBLE
    if ann.get("readOnlyHint") is True:
        return Risque.LECTURE
    return Risque.MODIFICATION


class GestionnaireMCP:
    """Charge les serveurs de la configuration et expose leurs outils dans le registre."""

    def __init__(self, configs: list[dict], registre: Registre, cache: Path):
        self.registre = registre
        self.cache_fichier = Path(cache)
        self.serveurs: dict[str, ServeurMCP] = {}
        self.configs = {c["nom"]: c for c in configs if c.get("nom") and c.get("commande")}
        self.mots_routeur: dict[str, list[str]] = {}
        for nom, c in self.configs.items():
            cmd = c["commande"] if isinstance(c["commande"], list) else c["commande"].split()
            self.serveurs[nom] = ServeurMCP(nom, cmd, c.get("env"), float(c.get("delai", 60)))
            self.mots_routeur[f"mcp_{nom}"] = [nom.lower(), *[m.lower() for m in c.get("mots_cles", [])]]
        self._arret = threading.Event()

    def _cache(self) -> dict:
        try:
            return json.loads(self.cache_fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def enregistrer(self, decouvrir: bool = True) -> dict[str, str]:
        """Inscrit les outils (depuis le cache, ou en interrogeant les serveurs). Renvoie l'état par serveur."""
        cache, etats = self._cache(), {}
        for nom, serveur in self.serveurs.items():
            definitions = cache.get(nom)
            if definitions is None and decouvrir:
                try:
                    definitions = serveur.lister_outils()
                    cache[nom] = definitions
                    serveur.arreter()
                except ErreurMCP as e:
                    etats[nom] = f"erreur : {e}"
                    continue
            if definitions is None:
                etats[nom] = "non découvert"
                continue
            for d in definitions:
                self._inscrire(nom, d)
            etats[nom] = f"{len(definitions)} outils"
        self.cache_fichier.parent.mkdir(parents=True, exist_ok=True)
        self.cache_fichier.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        return etats

    def _inscrire(self, serveur: str, d: dict) -> None:
        cfg = self.configs[serveur]
        schema = d.get("inputSchema") or {"type": "object", "properties": {}}
        nom_reel = d["name"]

        def appeler(ctx, **args):
            ok, texte, fichiers = self.serveurs[serveur].appeler(nom_reel, args)
            return Resultat(ok, texte, {"fichiers": fichiers} if fichiers else None)

        o = Outil(nom=nom_outil(serveur, nom_reel),
                  description=f"[{cfg.get('titre', serveur)}] {d.get('description', nom_reel)}"[:1000],
                  fonction=appeler, groupe=f"mcp_{serveur}", parametres=schema.get("properties", {}),
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
        self.registre.ajouter(o)

    def surveiller(self) -> None:
        """Arrête les serveurs inactifs (fil d'exécution de fond)."""
        def boucle():
            while not self._arret.wait(30):
                for s in self.serveurs.values():
                    if s.actif() and time.monotonic() - s.derniere_utilisation > INACTIVITE_S:
                        s.arreter()
        threading.Thread(target=boucle, daemon=True, name="mcp-veille").start()

    def fermer(self) -> None:
        self._arret.set()
        for s in self.serveurs.values():
            s.arreter()
