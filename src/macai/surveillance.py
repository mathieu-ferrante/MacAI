"""Alertes discrètes : batterie faible, mémoire saturée, disque plein, rendez-vous proche, téléchargement terminé.

Un fil de fond vérifie toutes les 60 s, sans modèle : quelques commandes système légères (pmset, sysctl) et un
listage de ~/Téléchargements. L'agenda n'est relu que toutes les 5 minutes, et seulement si macOS a DÉJÀ donné
l'accès (jamais de fenêtre d'autorisation déclenchée en arrière-plan).

Chaque alerte part par `emettre("alerte", titre=..., texte=..., type=...)`. Anti-répétition : une alerte d'un
type donné au plus une fois par heure ; la batterie une fois par décharge (on réarme en rebranchant) ; un
rendez-vous une seule fois par événement.

Les décisions sont des fonctions pures (`decider_*`, `rendez_vous_a_signaler`, `telechargements_finis`) pour être
testées hors macOS.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

INTERVALLE_S = 60
DELAI_REPETITION_S = 3600
BATTERIE_SEUIL = 20            # %
DISQUE_SEUIL = 10 * 1024 ** 3  # octets libres
RDV_AVANCE = timedelta(minutes=15)
AGENDA_TOUTES_S = 5 * 60
AGENDA_FENETRE = timedelta(minutes=20)   # relu toutes les 5 min : couvre le prochain quart d'heure
MEMOIRE_CRITIQUE = 4           # kern.memorystatus_vm_pressure_level : 1 normale, 2 tendue, 4 critique
MEMOIRE_PASSAGES = 2           # critique sur 2 vérifications de suite (une pointe brève ne compte pas)
PARTIELS = (".crdownload", ".download", ".part", ".partial", ".tmp", ".opdownload")
TYPES = ("batterie", "memoire", "disque", "rendez_vous", "telechargements")


# --- Décisions (fonctions pures) -----------------------------------------------------------

def lire_pmset(texte: str) -> tuple[int, bool] | None:
    """`pmset -g batt` → (pourcentage, sur secteur). None : pas de batterie (Mac de bureau) ou illisible."""
    m = re.search(r"(\d+)%", texte or "")
    if not m:
        return None
    secteur = "AC Power" in texte or re.search(r";\s*(charging|charged|finishing charge|AC attached)", texte) is not None
    return int(m.group(1)), secteur


def decider_batterie(pourcentage: int | None, secteur: bool, deja_alerte: bool,
                     seuil: int = BATTERIE_SEUIL) -> tuple[bool, bool]:
    """Renvoie (alerter maintenant, déjà alerté pour cette décharge). Rebrancher le chargeur réarme l'alerte."""
    if pourcentage is None or secteur:
        return False, False
    if pourcentage < seuil and not deja_alerte:
        return True, True
    return False, deja_alerte


def decider_memoire(niveaux: list[int], passages: int = MEMOIRE_PASSAGES) -> bool:
    """Pression mémoire critique sur les `passages` dernières vérifications."""
    return len(niveaux) >= passages and all(n >= MEMOIRE_CRITIQUE for n in niveaux[-passages:])


def decider_disque(libre: int | None, seuil: int = DISQUE_SEUIL) -> bool:
    return libre is not None and libre < seuil


def id_evenement(e: dict) -> str:
    """EventKit (via mac/agenda) ne renvoie pas d'identifiant : titre + heure de début en tiennent lieu."""
    debut = e.get("debut")
    return f"{e.get('titre', '')}|{debut.isoformat() if isinstance(debut, datetime) else debut}"


def rendez_vous_a_signaler(evenements: list[dict], maintenant: datetime, deja: set[str],
                           avance: timedelta = RDV_AVANCE) -> list[dict]:
    """Événements (hors journée entière) qui commencent dans les `avance` prochaines minutes, pas encore signalés."""
    sortie = []
    for e in evenements:
        debut = e.get("debut")
        if e.get("journee") or not isinstance(debut, datetime):
            continue
        if maintenant < debut <= maintenant + avance and id_evenement(e) not in deja:
            sortie.append(e)
    return sortie


def texte_rendez_vous(e: dict, maintenant: datetime) -> tuple[str, str]:
    minutes = max(1, round((e["debut"] - maintenant).total_seconds() / 60))
    lieu = f" — {e['lieu']}" if e.get("lieu") else ""
    return f"Rendez-vous dans {minutes} min", f"{e.get('titre') or '(sans titre)'} à {e['debut']:%H:%M}{lieu}"


def est_partiel(nom: str) -> bool:
    n = nom.lower()
    return n.startswith(".") or n.endswith(PARTIELS)


def telechargements_finis(actuel: dict[str, tuple[int, float]], precedent: dict[str, tuple[int, float]],
                          debut_moteur: float, deja: set[str]) -> list[str]:
    """Fichiers terminés : pas un fichier partiel, modifiés après le démarrage du moteur, et de taille identique sur
    deux vérifications de suite. `actuel` / `precedent` : {nom: (taille, date de modification)}."""
    finis = []
    for nom, (taille, mtime) in sorted(actuel.items()):
        if nom in deja or est_partiel(nom) or mtime < debut_moteur:
            continue
        avant = precedent.get(nom)
        if avant is not None and avant[0] == taille and taille > 0:
            finis.append(nom)
    return finis


class AntiRepetition:
    """Une alerte d'un type donné au plus une fois par `delai` secondes."""

    def __init__(self, delai: float = DELAI_REPETITION_S):
        self.delai = delai
        self.derniere: dict[str, float] = {}

    def autoriser(self, type_: str, maintenant: float) -> bool:
        d = self.derniere.get(type_)
        if d is not None and maintenant - d < self.delai:
            return False
        self.derniere[type_] = maintenant
        return True


def _go(n: float) -> str:
    return f"{n / 1024 ** 3:.1f}".replace(".", ",") + " Go"


# --- Lectures système (chacune renvoie None quand elle ne sait pas) ---------------------------

def _commande(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def lire_batterie() -> tuple[int, bool] | None:
    return lire_pmset(_commande(["pmset", "-g", "batt"])) if sys.platform == "darwin" else None


def lire_pression() -> int | None:
    if sys.platform != "darwin":
        return None
    t = _commande(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip()
    return int(t) if t.isdigit() else None


def application_gourmande() -> tuple[str, int] | None:
    """Application qui occupe le plus de mémoire (lue seulement quand la pression est critique)."""
    from .mac import memoire
    apps = memoire.group_by_app(memoire.parse_ps(_commande(["ps", "-axo", "pid=,rss=,comm="])))
    apps = [a for a in apps if a["is_app"]] or apps
    return (apps[0]["name"], apps[0]["rss"]) if apps else None


def lire_disque_libre() -> int | None:
    for chemin in ("/System/Volumes/Data", str(Path.home()), "/"):
        if os.path.isdir(chemin):
            try:
                return shutil.disk_usage(chemin).free
            except OSError:
                continue
    return None


def lire_agenda(debut: datetime, fin: datetime) -> list[dict] | None:
    """Événements, ou None si EventKit est absent ou si l'accès n'a pas déjà été accordé."""
    if sys.platform != "darwin":
        return None
    from .mac import agenda
    if not agenda.disponible():
        return None
    import EventKit
    statut = EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent)
    if statut != agenda.ACCES_COMPLET:
        return None  # jamais de fenêtre d'autorisation en arrière-plan
    return agenda.evenements(debut, fin)


def dossier_telechargements() -> Path:
    return Path.home() / "Downloads"


def lister_dossier(dossier: Path) -> dict[str, tuple[int, float]]:
    sortie = {}
    try:
        with os.scandir(dossier) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        sortie[e.name] = (st.st_size, st.st_mtime)
                except OSError:
                    continue
    except OSError:
        pass
    return sortie


# --- Fil de surveillance ---------------------------------------------------------------------

class Surveillance:
    """`Surveillance(cfg, emettre, ctx).demarrer()` ; `arreter()` à la fermeture. `verifier()` fait un passage
    (appelé par le fil toutes les 60 s, ou directement dans les tests). Les lectures système sont des attributs
    remplaçables (`lire_batterie`, `lire_pression`, …) pour les tests."""

    def __init__(self, cfg, emettre, ctx=None, horloge=time.time):
        self.cfg = cfg
        self.emettre = emettre
        self.ctx = ctx
        self.horloge = horloge
        self.debut = horloge()
        self.anti = AntiRepetition()
        self._fil: threading.Thread | None = None
        self._stop = threading.Event()
        # État d'un passage à l'autre
        self.batterie_alertee = False
        self.niveaux_memoire: list[int] = []
        self.rdv_signales: set[str] = set()
        self._agenda: list[dict] = []
        self._agenda_lu = 0.0
        self._fichiers: dict[str, tuple[int, float]] | None = None
        self.telechargements_vus: set[str] = set()
        # Lectures (remplaçables)
        self.lire_batterie = lire_batterie
        self.lire_pression = lire_pression
        self.application_gourmande = application_gourmande
        self.lire_disque_libre = lire_disque_libre
        self.lire_agenda = lire_agenda
        self.dossier = dossier_telechargements()

    def actif(self, type_: str) -> bool:
        reglages = getattr(self.cfg, "alertes", None) or {}
        return bool(reglages.get(type_, True))

    def demarrer(self) -> None:
        if self._fil is None:
            self._stop.clear()
            self._fil = threading.Thread(target=self._boucle, daemon=True, name="surveillance")
            self._fil.start()

    def arreter(self) -> None:
        self._stop.set()
        self._fil = None

    def _boucle(self) -> None:
        while not self._stop.wait(INTERVALLE_S):
            self.verifier()

    def _alerter(self, type_: str, titre: str, texte: str) -> None:
        self.emettre("alerte", titre=titre, texte=texte, type=type_)
        journal = getattr(self.ctx, "journal", None)
        if journal is not None:
            journal.ecrire("alerte", type=type_, texte=texte)

    def verifier(self, maintenant: datetime | None = None) -> None:
        """Un passage : chaque vérification est isolée (une erreur n'empêche pas les autres)."""
        for type_, verif in (("batterie", self._batterie), ("memoire", self._memoire), ("disque", self._disque),
                             ("rendez_vous", self._rendez_vous), ("telechargements", self._telechargements)):
            if not self.actif(type_):
                continue
            try:
                verif(maintenant or datetime.now())
            except Exception as e:  # noqa: BLE001 - le fil ne doit jamais mourir
                journal = getattr(self.ctx, "journal", None)
                if journal is not None:
                    journal.ecrire("erreur_surveillance", type=type_, texte=str(e)[:300])

    def _batterie(self, maintenant: datetime) -> None:
        lu = self.lire_batterie()
        pct, secteur = lu if lu else (None, True)
        alerter, self.batterie_alertee = decider_batterie(pct, secteur, self.batterie_alertee)
        if alerter:
            self._alerter("batterie", "Batterie faible", f"Batterie à {pct} % : branche le chargeur.")

    def _memoire(self, maintenant: datetime) -> None:
        niveau = self.lire_pression()
        if niveau is None:
            return
        self.niveaux_memoire = (self.niveaux_memoire + [niveau])[-MEMOIRE_PASSAGES:]
        if decider_memoire(self.niveaux_memoire) and self.anti.autoriser("memoire", self.horloge()):
            top = self.application_gourmande()
            detail = (f" L'application qui en prend le plus : {top[0]} ({_go(top[1])}). Ferme-la ou ferme des "
                      "onglets." if top else " Ferme les applications inutiles.")
            self._alerter("memoire", "Mémoire saturée", "La mémoire du Mac est saturée, il ralentit." + detail)

    def _disque(self, maintenant: datetime) -> None:
        libre = self.lire_disque_libre()
        if decider_disque(libre) and self.anti.autoriser("disque", self.horloge()):
            self._alerter("disque", "Disque presque plein",
                          f"Il ne reste que {_go(libre)} libres. Vide la Corbeille ou range les Téléchargements.")

    def _rendez_vous(self, maintenant: datetime) -> None:
        if self.horloge() - self._agenda_lu >= AGENDA_TOUTES_S or not self._agenda_lu:
            self._agenda_lu = self.horloge()
            try:
                lus = self.lire_agenda(maintenant, maintenant + AGENDA_FENETRE)
            except Exception:  # noqa: BLE001 - pas d'autorisation, EventKit absent : on se tait
                lus = None
            self._agenda = lus or []
        for e in rendez_vous_a_signaler(self._agenda, maintenant, self.rdv_signales):
            self.rdv_signales.add(id_evenement(e))
            self._alerter("rendez_vous", *texte_rendez_vous(e, maintenant))
        if len(self.rdv_signales) > 500:  # la journée passée n'a plus d'intérêt
            self.rdv_signales = set(list(self.rdv_signales)[-100:])

    def _telechargements(self, maintenant: datetime) -> None:
        actuel = lister_dossier(self.dossier)
        if self._fichiers is None:  # premier passage : ce qui est déjà là n'est pas nouveau
            self._fichiers = actuel
            self.telechargements_vus.update(n for n, (_, m) in actuel.items() if m < self.debut)
            return
        finis = telechargements_finis(actuel, self._fichiers, self.debut, self.telechargements_vus)
        self._fichiers = actuel
        if not finis:
            return
        self.telechargements_vus.update(finis)
        if self.anti.autoriser("telechargements", self.horloge()):
            noms = ", ".join(finis[:3]) + (f" et {len(finis) - 3} autre(s)" if len(finis) > 3 else "")
            self._alerter("telechargements", "Téléchargement terminé", f"{noms} : dans Téléchargements.")
