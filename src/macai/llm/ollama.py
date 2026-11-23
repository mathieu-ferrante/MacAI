"""Client Ollama minimal (stdlib) : discussion avec outils, embeddings, gestion mémoire des modèles."""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterator

HOTE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not HOTE.startswith("http"):
    HOTE = "http://" + HOTE


# « Compute error » : message de llama.cpp quand la mémoire graphique est saturée (vu dans ollama.log).
MEMOIRE_SATUREE = re.compile(r"Insufficient Memory|out of memory|OutOfMemory|\bOOM\b|Compute error", re.I)
CONTEXTE_EMBEDDINGS = 512
# Coupure en cours de lecture (délai, connexion fermée, JSON tronqué) : traitée comme une erreur d'Ollama.
ERREURS_FLUX = (OSError, ValueError, http.client.HTTPException)


class ErreurOllama(RuntimeError):
    pass


@dataclass
class AppelOutil:
    nom: str
    arguments: dict


@dataclass
class Reponse:
    texte: str = ""
    appels: list[AppelOutil] = field(default_factory=list)
    reflexion: str = ""
    jetons_entree: int = 0
    jetons_sortie: int = 0
    duree_s: float = 0.0


class _FluxArretable:
    """Requête en flux que « Stop » peut couper à tout moment.

    urllib ne rend la main qu'à l'arrivée des en-têtes, c'est-à-dire après le chargement du modèle et la lecture
    du prompt (10 à 40 s sur un 8 Go) : impossible d'interrompre avant. Ici la connexion est ouverte à la main et
    un fil veille sur l'événement d'arrêt ; quand il est levé, la socket est fermée des deux côtés, la lecture
    en cours échoue aussitôt et Ollama abandonne le calcul (« client closing the connection »)."""

    def __init__(self, client: "Ollama", chemin: str, corps: dict, arret: threading.Event, delai: float = 300):
        self.client, self.chemin, self.corps, self.arret, self.delai = client, chemin, corps, arret, delai
        self.conn: http.client.HTTPConnection | None = None
        self.sock: socket.socket | None = None
        self.fini = threading.Event()

    def _veiller(self) -> None:
        while not self.fini.is_set():
            if self.arret.wait(0.2):
                if not self.fini.is_set():
                    try:
                        self.sock.shutdown(socket.SHUT_RDWR)
                    except (OSError, AttributeError):
                        pass  # déjà fermée : la lecture verra l'arrêt
                return

    def __enter__(self):
        u = urllib.parse.urlsplit(self.client.hote)
        classe = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        self.conn = classe(u.hostname or "127.0.0.1", u.port, timeout=self.delai)
        try:
            self.conn.connect()
            # Gardée à part : http.client oublie sa socket (conn.sock = None) dès que la réponse est de type
            # « jusqu'à la fermeture », alors que la lecture continue dessus.
            self.sock = self.conn.sock
            threading.Thread(target=self._veiller, daemon=True, name="ollama-arret").start()
            self.conn.request("POST", self.chemin, body=json.dumps(self.corps).encode(),
                              headers={"Content-Type": "application/json"})
            rep = self.conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            self.__exit__()
            if self.arret.is_set():
                raise InterruptedError("Arrêté par l'utilisateur.") from None
            raise ErreurOllama(f"Ollama injoignable sur {self.client.hote} ({e}). Est-il démarré ?") from e
        if rep.status >= 400:
            try:
                detail = rep.read().decode(errors="replace")[:300]
            except (OSError, http.client.HTTPException):
                detail = ""
            self.__exit__()
            raise ErreurOllama(f"Ollama {rep.status} : {detail}")
        return rep

    def __exit__(self, *a):
        self.fini.set()
        if self.conn is not None:
            self.conn.close()
        return False


class Ollama:
    def __init__(self, hote: str = HOTE, garder: str = "2m", contexte: int = 8192):
        self.hote = hote.rstrip("/")
        self.garder = garder
        self.contexte = contexte

    # --- HTTP ---------------------------------------------------------------

    def _requete(self, chemin: str, corps: dict | None = None, delai: float = 300):
        donnees = json.dumps(corps).encode() if corps is not None else None
        req = urllib.request.Request(self.hote + chemin, data=donnees,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if corps is not None else "GET")
        try:
            return urllib.request.urlopen(req, timeout=delai)
        except urllib.error.HTTPError as e:
            raise ErreurOllama(f"Ollama {e.code} : {e.read().decode(errors='replace')[:300]}") from e
        except (urllib.error.URLError, OSError) as e:
            raise ErreurOllama(f"Ollama injoignable sur {self.hote} ({e}). Est-il démarré ?") from e

    def _json(self, chemin: str, corps: dict | None = None, delai: float = 300) -> dict:
        with self._requete(chemin, corps, delai) as r:
            try:
                return json.loads(r.read())
            except ERREURS_FLUX as e:
                raise ErreurOllama(f"réponse d'Ollama interrompue ({type(e).__name__} : {e})") from e

    # --- Discussion ---------------------------------------------------------

    def discuter(self, modele: str, messages: list[dict], outils: list[dict] | None = None,
                 reflexion: bool = False, sur_texte: Callable[[str], None] | None = None,
                 options: dict | None = None, arret: threading.Event | None = None) -> Reponse:
        """Envoie la conversation ; diffuse le texte au fil de l'eau si `sur_texte` est donné.

        `arret` : événement « Stop » de l'utilisateur. Dès qu'il est levé, la connexion est coupée (Ollama
        abandonne aussitôt le calcul) et InterruptedError est levée, même pendant le chargement du modèle ou la
        lecture du prompt."""
        corps = {
            "model": modele,
            "messages": messages,
            "stream": True,
            "keep_alive": self.garder,
            "think": reflexion,
            # num_predict : plafond de longueur — un petit modèle qui s'emballe ne bloque jamais le Mac.
            "options": {"num_ctx": self.contexte, "temperature": 0.2, "num_predict": 1500, **(options or {})},
        }
        if outils:
            corps["tools"] = outils
        diffuse = []  # texte déjà montré : réessayer le doublerait à l'écran

        def relais(t: str) -> None:
            diffuse.append(True)
            sur_texte(t)
        return self._sans_saturation(lambda: self._discuter(corps, relais if sur_texte else None, arret),
                                     deja_diffuse=lambda: bool(diffuse))

    def _sans_saturation(self, appel: Callable, deja_diffuse: Callable[[], bool] = lambda: False):
        """Mémoire graphique saturée (8 Go) : on décharge tous les modèles et on réessaie une fois
        (sauf si une partie de la réponse a déjà été diffusée)."""
        try:
            return appel()
        except ErreurOllama as e:
            if not MEMOIRE_SATUREE.search(str(e)) or deja_diffuse():
                raise
            try:
                for m in self.charges():
                    self.decharger(m.get("name", ""))
            except Exception:  # noqa: BLE001 - un déchargement raté ne doit pas masquer l'erreur d'origine
                raise e from None
            time.sleep(2)
            return appel()

    def _discuter(self, corps: dict, sur_texte: Callable[[str], None] | None,
                  arret: threading.Event | None = None) -> Reponse:
        rep = Reponse()
        for morceau in self._flux("/api/chat", corps, arret):
            msg = morceau.get("message") or {}
            if t := msg.get("content"):
                rep.texte += t
                if sur_texte:
                    sur_texte(t)
            rep.reflexion += msg.get("thinking") or ""
            for appel in msg.get("tool_calls") or []:
                f = appel.get("function", {})
                args = f.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                if not isinstance(args, dict):  # « [1, 2] » ou « "texte" » : inutilisable comme arguments
                    args = {}
                rep.appels.append(AppelOutil(f.get("name", ""), args))
            if morceau.get("done"):
                rep.jetons_entree = morceau.get("prompt_eval_count", 0)
                rep.jetons_sortie = morceau.get("eval_count", 0)
                rep.duree_s = morceau.get("total_duration", 0) / 1e9
        return rep

    def _flux(self, chemin: str, corps: dict, arret: threading.Event | None = None) -> Iterator[dict]:
        def arrete() -> bool:
            return arret is not None and arret.is_set()

        with (self._requete(chemin, corps) if arret is None else _FluxArretable(self, chemin, corps, arret)) as r:
            lignes = iter(r)
            while True:
                try:
                    ligne = next(lignes, None)
                    if arrete():  # connexion coupée par « Stop » : ni une erreur d'Ollama ni une réponse complète
                        raise InterruptedError("Arrêté par l'utilisateur.")
                    if ligne is None:
                        return
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    morceau = json.loads(ligne)
                except InterruptedError:
                    raise
                except ERREURS_FLUX as e:
                    if arrete():
                        raise InterruptedError("Arrêté par l'utilisateur.") from None
                    raise ErreurOllama(f"réponse d'Ollama interrompue ({type(e).__name__} : {e})") from e
                if not isinstance(morceau, dict):
                    continue
                if "error" in morceau:
                    raise ErreurOllama(str(morceau["error"]))
                yield morceau

    # --- Embeddings ---------------------------------------------------------

    def vecteurs(self, modele: str, textes: list[str], dimensions: int | None = None) -> list[list[float]]:
        # Contexte 512 : les extraits font ~250 jetons ; avec le contexte par défaut (4 096), le modèle
        # d'embeddings occupe 2,2 Go au lieu de 1 Go et sature la mémoire graphique à côté de l'agent (mesuré).
        corps = {"model": modele, "input": textes, "keep_alive": self.garder, "truncate": True,
                 "options": {"num_ctx": CONTEXTE_EMBEDDINGS}}
        if dimensions:
            corps["dimensions"] = dimensions
        vecs = self._sans_saturation(lambda: self._json("/api/embed", corps))["embeddings"]
        if dimensions and vecs and len(vecs[0]) > dimensions:
            vecs = [v[:dimensions] for v in vecs]  # troncature Matryoshka si non gérée côté serveur
        return vecs

    # --- Mémoire ------------------------------------------------------------

    def decharger(self, modele: str) -> None:
        """Libère immédiatement la RAM occupée par un modèle."""
        try:
            self._json("/api/generate", {"model": modele, "keep_alive": 0}, delai=30)
        except ErreurOllama:
            pass

    def charges(self) -> list[dict]:
        return self._json("/api/ps", delai=5).get("models", [])

    def decharger_tout_sauf(self, modele: str) -> None:
        for m in self.charges():
            if m.get("name") != modele and m.get("model") != modele:
                self.decharger(m.get("name") or m.get("model"))

    def installes(self) -> list[str]:
        return [m["name"] for m in self._json("/api/tags", delai=5).get("models", [])]

    def disponible(self) -> bool:
        try:
            self._json("/api/version", delai=2)
            return True
        except ErreurOllama:
            return False
