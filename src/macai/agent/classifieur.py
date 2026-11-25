"""Classifieur de demandes, sur le principe des modèles de décision (Jev) : il ne rédige rien, il décide.

Pour chaque demande, il renvoie l'INTENTION (action, information, explication, redaction, planifier, conversation)
et les DOMAINES d'outils utiles (fichiers, web, organisation…), avec un degré de confiance. Le petit modèle d'IA
reçoit ainsi les bons outils, au lieu d'une sélection faite sur des mots-clés.

Méthode : les plus proches voisins parmi quelques centaines d'exemples français étiquetés
(`exemples_routage.jsonl`), comparés par le sens avec le modèle d'embeddings déjà utilisé pour la recherche
(`qwen3-embedding`, 1 Go, déjà en mémoire la plupart du temps). Aucune dépendance en plus, rien ne quitte le Mac,
~0,1 s par demande quand le modèle est chargé. Les vecteurs des exemples sont calculés une fois puis gardés en
cache (recalculés si les exemples ou le modèle changent).

Le classifieur n'est qu'un aiguilleur : il n'agit pas, ne contourne aucune confirmation, et s'il est indisponible
(Ollama arrêté, modèle absent), l'agent retombe sur le routage par mots-clés.
"""
from __future__ import annotations

import array
import hashlib
import json
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

FICHIER_EXEMPLES = Path(__file__).with_name("exemples_routage.jsonl")
INTENTIONS = ("action", "information", "explication", "redaction", "planifier", "conversation")
DOMAINES = ("applications", "fenetres", "fichiers", "recherche", "web", "organisation", "systeme", "memoire",
            "competences", "taches", "onshape")
DIMENSIONS = 256
VOISINS = 15
PUISSANCE = 16         # les voisins les plus proches pèsent beaucoup plus (réglé sur le jeu de test : 15 voisins, puissance 16)
SEUIL_DOMAINE = 0.3    # part des voisins (pondérée) qui doivent citer un domaine pour qu'il soit retenu


@dataclass
class Decision:
    intention: str
    confiance: float                       # part pondérée des voisins d'accord sur l'intention (0 à 1)
    domaines: list[tuple[str, float]] = field(default_factory=list)  # domaines retenus, du plus probable au moins
    voisins: list[tuple[str, float]] = field(default_factory=list)   # (exemple, similarité), pour comprendre

    def sure(self, seuil: float = 0.6) -> bool:
        return self.confiance >= seuil


def lire_exemples(fichier: Path = FICHIER_EXEMPLES, jeu: str | None = "entrainement") -> list[dict]:
    exemples = []
    try:
        lignes = fichier.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for ligne in lignes:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            e = json.loads(ligne)
        except ValueError:
            continue
        if not isinstance(e, dict) or not str(e.get("texte", "")).strip() or e.get("intention") not in INTENTIONS:
            continue
        if jeu is not None and e.get("jeu", "entrainement") != jeu:
            continue
        e["domaines"] = [d for d in e.get("domaines") or [] if d in DOMAINES]
        exemples.append(e)
    return exemples


def _normer(v) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Classifieur:
    def __init__(self, ollama, modele: str, cache: Path | None = None, exemples: list[dict] | None = None):
        self.ollama = ollama
        self.modele = modele
        self.cache = Path(cache) if cache else None
        self._exemples = exemples
        self._vecteurs: list[list[float]] | None = None
        self._verrou = threading.Lock()

    # --- Vecteurs des exemples (une fois, puis en cache) ------------------------------------------------------

    def _signature(self, exemples: list[dict]) -> str:
        h = hashlib.sha256(f"{self.modele}|{DIMENSIONS}".encode())
        for e in exemples:
            h.update(e["texte"].encode())
        return h.hexdigest()[:16]

    def _preparer(self) -> tuple[list[dict], list[list[float]]]:
        with self._verrou:
            if self._exemples is None:
                self._exemples = lire_exemples()
            if self._vecteurs is not None:
                return self._exemples, self._vecteurs
            exemples = self._exemples
            if not exemples:
                self._vecteurs = []
                return exemples, []
            signature = self._signature(exemples)
            vecteurs = self._lire_cache(signature, len(exemples))
            if vecteurs is None:
                vecteurs = []
                textes = [e["texte"] for e in exemples]
                for i in range(0, len(textes), 32):
                    vecteurs += [_normer(v) for v in self.ollama.vecteurs(self.modele, textes[i:i + 32], DIMENSIONS)]
                self._ecrire_cache(signature, vecteurs)
            self._vecteurs = vecteurs
            return exemples, vecteurs

    def _lire_cache(self, signature: str, nombre: int) -> list[list[float]] | None:
        if self.cache is None:
            return None
        try:
            brut = self.cache.read_bytes()
        except OSError:
            return None
        entete, _, corps = brut.partition(b"\n")
        if entete.decode(errors="replace") != f"{signature} {nombre} {DIMENSIONS}":
            return None
        valeurs = array.array("f")
        try:
            valeurs.frombytes(corps)
        except ValueError:
            return None
        if len(valeurs) != nombre * DIMENSIONS:
            return None
        return [list(valeurs[i * DIMENSIONS:(i + 1) * DIMENSIONS]) for i in range(nombre)]

    def _ecrire_cache(self, signature: str, vecteurs: list[list[float]]) -> None:
        if self.cache is None:
            return
        try:
            valeurs = array.array("f", [x for v in vecteurs for x in v])
            tmp = self.cache.with_name(self.cache.name + ".tmp")
            tmp.write_bytes(f"{signature} {len(vecteurs)} {DIMENSIONS}\n".encode() + valeurs.tobytes())
            tmp.replace(self.cache)
        except OSError:
            pass  # le cache n'est qu'une économie de temps

    # --- Décision ---------------------------------------------------------------------------------------------

    def classer(self, demande: str) -> Decision | None:
        """Décision pour une demande, ou None si le classifieur est indisponible (on garde alors les mots-clés)."""
        texte = " ".join(str(demande or "").split())
        if not texte:
            return None
        try:
            exemples, vecteurs = self._preparer()
            if not vecteurs:
                return None
            q = _normer(self.ollama.vecteurs(self.modele, [texte[:2000]], DIMENSIONS)[0])
        except Exception:  # noqa: BLE001 - jamais bloquant : routage par mots-clés à la place
            return None
        sims = sorted(((sum(a * b for a, b in zip(q, v)), i) for i, v in enumerate(vecteurs)), reverse=True)[:VOISINS]
        poids = [(max(s, 0.0) ** PUISSANCE, i) for s, i in sims]
        total = sum(p for p, _ in poids) or 1.0
        intentions: dict[str, float] = {}
        domaines: dict[str, float] = {}
        for p, i in poids:
            e = exemples[i]
            intentions[e["intention"]] = intentions.get(e["intention"], 0.0) + p / total
            for d in e["domaines"]:
                domaines[d] = domaines.get(d, 0.0) + p / total
        intention, confiance = max(intentions.items(), key=lambda x: x[1])
        retenus = sorted(((d, s) for d, s in domaines.items() if s >= SEUIL_DOMAINE), key=lambda x: -x[1])
        return Decision(intention=intention, confiance=round(confiance, 3),
                        domaines=[(d, round(s, 3)) for d, s in retenus],
                        voisins=[(exemples[i]["texte"], round(s, 3)) for s, i in sims[:3]])

    def prechauffer(self) -> None:
        """Calcule (ou relit) les vecteurs des exemples et charge le modèle d'embeddings."""
        self.classer("bonjour")
