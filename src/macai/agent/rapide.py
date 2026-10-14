"""Commandes directes : reconnues par motifs, exécutées sans modèle (instantané, 0 Mo de RAM en plus).

Seules les formulations sans ambiguïté sont reconnues ; tout le reste part vers l'agent.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from .consignes import JOURS, MOIS

SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "google": "https://www.google.com",
    "netflix": "https://www.netflix.com", "onshape": "https://cad.onshape.com", "wikipedia": "https://fr.wikipedia.org",
    "google maps": "https://maps.google.com", "maps": "https://maps.google.com", "google drive": "https://drive.google.com",
    "twitch": "https://www.twitch.tv", "github": "https://github.com", "amazon": "https://www.amazon.fr",
    "leboncoin": "https://www.leboncoin.fr", "deezer": "https://www.deezer.com",
}
NE_PAS_INTERCEPTER = re.compile(r"\b(fichier|dossier|document|pdf|photo|image|et (fais|cree|ecris|clique|resume|dis))")


@dataclass
class Plan:
    actions: list[tuple[str, dict]] = field(default_factory=list)
    reponse: str = ""


def _norm(texte: str) -> str:
    """Minuscules sans accents, MÊME longueur que l'original (pour extraire les noms avec leur casse)."""
    return "".join(unicodedata.normalize("NFD", c)[0].lower() if c.strip() else " " for c in texte)


def _nettoyer(nom: str) -> str:
    nom = re.sub(r"^(l'|le |la |les |l’|un |une |des |du |de |d')", "", nom.strip(), flags=re.I)
    nom = re.sub(r"^(application|appli|app|logiciel|site)\s+", "", nom, flags=re.I)
    return nom.strip(" .!?,;\"'«»")


class CommandesRapides:
    def __init__(self):
        P = re.compile
        demande = r"(?:peux-tu |tu peux |stp |s'il te plait )?"
        self.motifs = [
            (P(rf"^{demande}(?:lance|ouvre|va sur) youtube et (?:cherche|recherche|trouve)(?: moi)? (?:une |des )?(?:videos? (?:de |sur |d')?)?(?P<q>.+)$"),
             self._youtube_chercher),
            (P(rf"^{demande}(?:mets|joue|lance|regarde)(?: moi)? (?:la |une )?(?:video|musique|chanson|clip)? ?(?:de |d')?(?P<q>.+?) sur youtube$"),
             self._youtube_lire),
            (P(rf"^{demande}(?:cherche|recherche)(?: moi)? (?P<q>.+?) sur (?P<site>google|youtube)$"), self._chercher_sur),
            (P(rf"^{demande}(?:ouvre|lance|demarre)(?: moi)? (?P<nom>.+)$"), self._ouvrir),
            (P(rf"^{demande}(?:ferme|quitte)(?: moi)? (?P<nom>.+)$"), self._quitter),
            (P(r"^(?:mets |regle |monte |baisse )?(?:le )?(?:volume|son) (?:a |au )?(?P<n>\d{1,3}) ?%?$"), self._volume),
            (P(r"^(?:monte|augmente) (?:le )?(?:son|volume)$"), lambda m, t: self._media("volume_plus")),
            (P(r"^(?:baisse|diminue) (?:le )?(?:son|volume)$"), lambda m, t: self._media("volume_moins")),
            (P(r"^(?:coupe le son|mute|silence|mets en sourdine)$"), lambda m, t: self._media("muet")),
            (P(r"^(?:pause|mets (?:en )?pause|stop la musique)$"), lambda m, t: self._media("pause")),
            (P(r"^(?:reprends|reprend|lecture|play|remets la musique)$"), lambda m, t: self._media("lecture")),
            (P(r"^(?:suivant|chanson suivante|musique suivante|next)$"), lambda m, t: self._media("suivant")),
            (P(r"^(?:precedent|chanson precedente|musique precedente)$"), lambda m, t: self._media("precedent")),
            (P(r"^(?:prends une |fais une )?capture d'ecran$"), lambda m, t: Plan([("capture_ecran", {})])),
            (P(r"^(?:quelle heure (?:est-il|il est)|il est quelle heure)$"), self._heure),
            (P(r"^(?:quel jour (?:sommes-nous|on est|est-on)|on est quel jour|quelle est la date)$"), self._date),
        ]

    def reconnaitre(self, demande: str, registre=None) -> Plan | None:
        original = demande.strip().rstrip(" ?!.")
        t = _norm(original)
        t_court = re.sub(r"\s+", " ", t)
        if t_court != t:  # espaces multiples : on repart d'un original compacté
            original = re.sub(r"\s+", " ", original)
            t = t_court
        for motif, action in self.motifs:
            m = motif.match(t)
            if m:
                plan = action(m, original)
                if plan is None:
                    continue
                if registre is not None and any(registre.get(n) is None for n, _ in plan.actions):
                    return None  # outil indisponible sur cette plateforme : laisser l'agent gérer
                return plan
        return None

    # --- Actions ------------------------------------------------------------

    @staticmethod
    def _extrait(m, original, groupe):
        return original[m.start(groupe):m.end(groupe)]

    def _youtube_chercher(self, m, original):
        q = _nettoyer(self._extrait(m, original, "q"))
        return Plan([("chrome_rechercher", {"requete": q, "site": "youtube"})], "Recherche YouTube ouverte : {0}")

    def _youtube_lire(self, m, original):
        q = _nettoyer(self._extrait(m, original, "q"))
        return Plan([("youtube_lire", {"requete": q})])

    def _chercher_sur(self, m, original):
        q = _nettoyer(self._extrait(m, original, "q"))
        return Plan([("chrome_rechercher", {"requete": q, "site": m.group("site")})])

    def _ouvrir(self, m, original):
        if NE_PAS_INTERCEPTER.search(m.group(0)) or " et " in m.group("nom"):
            return None
        nom = _nettoyer(self._extrait(m, original, "nom"))
        if not nom or len(nom.split()) > 4:
            return None
        cle = _norm(nom)
        if cle in SITES:
            return Plan([("ouvrir_url", {"url": SITES[cle]})], f"{nom} est ouvert.")
        if re.match(r"^(https?://|www\.)|^[a-z0-9-]+\.(com|fr|org|net|io|dev|tv)$", cle):
            return Plan([("ouvrir_url", {"url": nom if nom.startswith("http") else "https://" + nom})])
        return Plan([("ouvrir_application", {"nom": nom})])

    def _quitter(self, m, original):
        if NE_PAS_INTERCEPTER.search(m.group(0)) or " et " in m.group("nom"):
            return None
        nom = _nettoyer(self._extrait(m, original, "nom"))
        if not nom or len(nom.split()) > 4 or _norm(nom) in ("tout", "toutes les applis", "tout le monde"):
            return None
        return Plan([("quitter_application", {"nom": nom})])

    def _volume(self, m, original):
        return Plan([("regler_volume", {"niveau": min(int(m.group("n")), 100)})])

    @staticmethod
    def _media(action):
        return Plan([("controle_media", {"action": action})])

    @staticmethod
    def _heure(m, original):
        return Plan([], f"Il est {datetime.now():%H:%M}.")

    @staticmethod
    def _date(m, original):
        d = datetime.now()
        return Plan([], f"Nous sommes le {JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}.")
