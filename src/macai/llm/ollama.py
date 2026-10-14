"""Client Ollama minimal (stdlib) : discussion avec outils, embeddings, gestion mémoire des modèles."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterator

HOTE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not HOTE.startswith("http"):
    HOTE = "http://" + HOTE


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
            return json.loads(r.read())

    # --- Discussion ---------------------------------------------------------

    def discuter(self, modele: str, messages: list[dict], outils: list[dict] | None = None,
                 reflexion: bool = False, sur_texte: Callable[[str], None] | None = None,
                 options: dict | None = None) -> Reponse:
        """Envoie la conversation ; diffuse le texte au fil de l'eau si `sur_texte` est donné."""
        corps = {
            "model": modele,
            "messages": messages,
            "stream": True,
            "keep_alive": self.garder,
            "think": reflexion,
            "options": {"num_ctx": self.contexte, "temperature": 0.2, **(options or {})},
        }
        if outils:
            corps["tools"] = outils
        rep = Reponse()
        for morceau in self._flux("/api/chat", corps):
            msg = morceau.get("message", {})
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
                rep.appels.append(AppelOutil(f.get("name", ""), args))
            if morceau.get("done"):
                rep.jetons_entree = morceau.get("prompt_eval_count", 0)
                rep.jetons_sortie = morceau.get("eval_count", 0)
                rep.duree_s = morceau.get("total_duration", 0) / 1e9
        return rep

    def _flux(self, chemin: str, corps: dict) -> Iterator[dict]:
        with self._requete(chemin, corps) as r:
            for ligne in r:
                ligne = ligne.strip()
                if not ligne:
                    continue
                morceau = json.loads(ligne)
                if "error" in morceau:
                    raise ErreurOllama(morceau["error"])
                yield morceau

    # --- Embeddings ---------------------------------------------------------

    def vecteurs(self, modele: str, textes: list[str], dimensions: int | None = None) -> list[list[float]]:
        corps = {"model": modele, "input": textes, "keep_alive": self.garder, "truncate": True}
        if dimensions:
            corps["dimensions"] = dimensions
        vecs = self._json("/api/embed", corps)["embeddings"]
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
