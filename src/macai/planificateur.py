"""Tâches planifiées : une demande en français rejouée à heure fixe (« résume mes mails chaque matin »).

Stockage : taches.json dans le dossier de données (0600). Heures locales « naïves » (sans fuseau) : 08:00 reste
08:00 au passage à l'heure d'été ou d'hiver. Une exécution manquée (Mac en veille) est rattrapée une fois au
réveil si le retard est de moins de 12 h ; au-delà, on passe à la suivante.

Sécurité : une tâche tourne sans personne devant l'écran. Les confirmations y sont donc REFUSÉES d'office
(voir Application.executer_tache) et les demandes d'envoi, de suppression ou d'achat refusées dès la création.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

FREQUENCES = ("quotidien", "jours_ouvres", "hebdomadaire", "horaire", "une_fois")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
RATTRAPAGE = timedelta(hours=12)
VERIFIER_TOUTES_S = 30
RESULTAT_MAX = 1000
LIBELLES = {"quotidien": "tous les jours", "jours_ouvres": "du lundi au vendredi", "hebdomadaire": "chaque",
            "horaire": "toutes les heures", "une_fois": "une fois"}
# Une tâche ne peut rien faire confirmer : ces intentions n'aboutiraient jamais (ou pire, ailleurs qu'ici).
INTERDIT = re.compile(r"\b(envoi\w*|envoy\w*|supprim\w*|effac\w*|achet\w*|achat\w*|paie\w*|paye\w*|payer|"
                      r"paiement\w*|postes?|poster|publi\w*|jette\w*|vide[rz]? la corbeille)\b")
# Demandes trop vagues pour être rejouées telles quelles : remplacées par une demande précise.
PRESETS = {
    "resume": "résume mes mails non lus et mon agenda du jour",
    "un resume": "résume mes mails non lus et mon agenda du jour",
    "resume du matin": "résume mes mails non lus et mon agenda du jour",
    "resume du jour": "résume mes mails non lus et mon agenda du jour",
    "briefing": "résume mes mails non lus et mon agenda du jour",
    "point du matin": "résume mes mails non lus et mon agenda du jour",
    "fais-moi un resume": "résume mes mails non lus et mon agenda du jour",
}
_VERROU = threading.Lock()


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFD", str(texte or "").lower().replace("’", "'"))
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip()


# --- Calcul des horaires (fonctions pures) ------------------------------------------------

def _heure(tache: dict) -> tuple[int, int]:
    h, m = (str(tache.get("heure") or "08:00").split(":") + ["0"])[:2]
    return int(h) % 24, int(m) % 60


def _date(texte) -> date | None:
    try:
        return date.fromisoformat(str(texte))
    except (TypeError, ValueError):
        return None


def _apres(tache: dict, apres: datetime) -> datetime | None:
    """Première occurrence prévue strictement après `apres` (None : plus aucune)."""
    h, m = _heure(tache)
    freq = tache.get("frequence")
    if freq == "horaire":
        c = apres.replace(minute=m, second=0, microsecond=0)
        return c if c > apres else c + timedelta(hours=1)
    if freq == "une_fois":
        d = _date(tache.get("date"))
        if d is None:
            return None
        c = datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m)
        return c if c > apres else None
    jour = JOURS.index(tache["jour"]) if freq == "hebdomadaire" and tache.get("jour") in JOURS else None
    for i in range(8):
        d = apres.date() + timedelta(days=i)
        c = datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m)
        if c <= apres:
            continue
        if freq == "jours_ouvres" and d.weekday() >= 5:
            continue
        if jour is not None and d.weekday() != jour:
            continue
        return c
    return None


def _reference(tache: dict, maintenant: datetime) -> datetime:
    for cle in ("derniere_execution", "cree"):
        try:
            return datetime.fromisoformat(str(tache[cle]))
        except (KeyError, TypeError, ValueError):
            continue
    return maintenant


def prochaine_execution(tache: dict, maintenant: datetime) -> datetime | None:
    """Prochaine exécution due. Renvoie une date passée (≤ maintenant) quand une exécution a été manquée de moins
    de 12 h : elle est à lancer tout de suite. Un retard plus grand est sauté. None : tâche terminée ou inactive."""
    if not tache.get("active", True) or tache.get("frequence") not in FREQUENCES:
        return None
    if tache["frequence"] == "une_fois" and tache.get("derniere_execution"):
        return None
    # Seule la dernière occurrence manquée compte : inutile de remonter au-delà de la fenêtre de rattrapage.
    ref = max(_reference(tache, maintenant), maintenant - RATTRAPAGE - timedelta(hours=1))
    occ = _apres(tache, ref)
    if occ is None or occ > maintenant:
        return occ
    suivante = _apres(tache, occ)
    while suivante is not None and suivante <= maintenant:
        occ, suivante = suivante, _apres(tache, suivante)
    return occ if maintenant - occ < RATTRAPAGE else suivante


def est_due(tache: dict, maintenant: datetime) -> bool:
    p = prochaine_execution(tache, maintenant)
    return p is not None and p <= maintenant


# --- Lecture des réglages donnés par l'utilisateur (ou le modèle) --------------------------

def lire_heure(texte: str) -> str:
    t = normaliser(texte) or "08:00"
    t = {"midi": "12:00", "minuit": "00:00", "matin": "08:00", "soir": "19:00"}.get(t, t)
    m = re.fullmatch(r"(?:a )?(\d{1,2})\s*(?:[h:.]\s*(\d{2})?)?\s*(?:h|heures?)?", t)
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise ValueError(f"Heure illisible : « {texte} » (exemple : 08:00 ou 8h30).")
    return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"


def lire_date(texte: str, aujourd_hui: date) -> date:
    t = normaliser(texte)
    if t in ("aujourd'hui", "aujourdhui", "ce soir", "ce matin", "tout a l'heure"):
        return aujourd_hui
    if t == "demain":
        return aujourd_hui + timedelta(days=1)
    if t in ("apres-demain", "apres demain"):
        return aujourd_hui + timedelta(days=2)
    if d := _date(t):
        return d
    m = re.fullmatch(r"(?:le )?(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", t)
    if m:
        annee = int(m.group(3)) if m.group(3) else aujourd_hui.year
        annee += 2000 if annee < 100 else 0
        d = date(annee, int(m.group(2)), int(m.group(1)))
        if not m.group(3) and d < aujourd_hui:
            d = d.replace(year=d.year + 1)
        return d
    raise ValueError(f"Date illisible : « {texte} » (exemple : demain ou 24/12/2026).")


def _jour_dans(texte: str) -> str:
    t = normaliser(texte)
    return next((j for j in JOURS if re.search(rf"\b{j}s?\b", t)), "")


def lire_frequence(frequence: str, jour: str = "", date_: str = "") -> tuple[str, str, str]:
    """« tous les jours » → quotidien, « en semaine » → jours_ouvres, « chaque lundi » → hebdomadaire + lundi,
    « toutes les heures » → horaire, « demain » / une date → une_fois. Renvoie (frequence, jour, date)."""
    t = normaliser(frequence).replace("-", " ").replace("_", " ")
    jour = _jour_dans(jour) or _jour_dans(t)
    if t in ("jours ouvres", "en semaine", "jours de semaine", "semaine", "weekdays") or re.search(
            r"\b(en semaine|jours? ouvr|du lundi au vendredi|sauf (le )?week|jours de (la )?semaine)", t):
        return "jours_ouvres", "", ""
    if t in ("horaire", "hourly") or re.search(r"\b(toutes les heures|chaque heure|par heure)\b", t):
        return "horaire", "", ""
    if t in ("hebdomadaire", "weekly") or jour or re.search(r"\b(chaque semaine|toutes les semaines)\b", t):
        if not jour:
            raise ValueError("Précise le jour de la semaine (lundi … dimanche).")
        return "hebdomadaire", jour, ""
    if t in ("quotidien", "quotidienne", "daily", "journalier") or re.search(
            r"\b(tous les (jours|matins|soirs)|chaque (jour|matin|soir)|par jour)\b", t):
        return "quotidien", "", ""
    if t in ("une fois", "unique", "once") or date_ or re.search(
            r"\b(demain|aujourd'?hui|ce soir|apres.demain|\d{1,2}[/.-]\d{1,2})", t):
        return "une_fois", "", date_ or t
    raise ValueError(f"Fréquence non reconnue : « {frequence} ». Choix : tous les jours, en semaine, "
                     "chaque lundi (ou autre jour), toutes les heures, une fois (demain, une date).")


def decrire(tache: dict) -> str:
    f = tache.get("frequence")
    if f == "hebdomadaire":
        quand = f"chaque {tache.get('jour')} à {tache.get('heure')}"
    elif f == "horaire":
        quand = f"toutes les heures à hh:{tache.get('heure', '00:00')[3:]}"
    elif f == "une_fois":
        d = _date(tache.get("date"))
        quand = f"le {d:%d/%m/%Y} à {tache.get('heure')}" if d else "une fois"
    else:
        quand = f"{LIBELLES.get(f, f)} à {tache.get('heure')}"
    return f"{tache.get('demande', '')} ({quand})"


# --- Stockage -----------------------------------------------------------------------------

def charger(fichier: Path) -> list[dict]:
    try:
        donnees = json.loads(Path(fichier).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [t for t in donnees if isinstance(t, dict) and t.get("id")] if isinstance(donnees, list) else []


def sauver(fichier: Path, taches: list[dict]) -> None:
    fichier = Path(fichier)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    temp = fichier.with_name(fichier.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(taches, f, ensure_ascii=False, indent=1)
    os.chmod(temp, 0o600)
    os.replace(temp, fichier)


def creer(demande: str, frequence: str, heure: str = "08:00", jour: str = "", date_: str = "",
          maintenant: datetime | None = None) -> dict:
    """Tâche validée (ValueError sinon), pas encore enregistrée."""
    maintenant = maintenant or datetime.now()
    demande = " ".join(str(demande or "").split())
    demande = PRESETS.get(normaliser(demande).rstrip(" ."), demande)
    if len(demande) < 4:
        raise ValueError("Dis ce que la tâche doit faire (ex. « résume mes mails non lus et mon agenda du jour »).")
    if INTERDIT.search(normaliser(demande)):
        raise ValueError("Refusé : une tâche planifiée tourne sans toi, je ne pourrais pas te demander de confirmer "
                         "un envoi, une suppression, une publication ou un paiement. Planifie plutôt une préparation "
                         "(résumer, lister, préparer un brouillon) et valide toi-même ensuite.")
    from .outils.base import ErreurOutil, interdire_achat
    try:
        interdire_achat(demande)
    except ErreurOutil as e:
        raise ValueError(str(e)) from None
    freq, jour, quand = lire_frequence(frequence, jour, date_)
    heure = lire_heure(heure)
    tache = {"id": uuid.uuid4().hex[:8], "demande": demande, "description": "", "frequence": freq,
             "heure": heure, "jour": jour, "date": "", "derniere_execution": None, "active": True,
             "cree": maintenant.isoformat(timespec="seconds")}
    if freq == "une_fois":
        if normaliser(quand) in ("une fois", "une_fois", "unique", "once", ""):
            h, m = _heure(tache)  # sans date : aujourd'hui si l'heure n'est pas passée, sinon demain
            quand = "aujourd'hui" if (h, m) > (maintenant.hour, maintenant.minute) else "demain"
        tache["date"] = lire_date(quand, maintenant.date()).isoformat()
        if _apres(tache, maintenant) is None:
            raise ValueError(f"Le {tache['date']} à {heure} est déjà passé.")
    tache["description"] = decrire(tache)
    return tache


def ajouter(fichier: Path, tache: dict) -> dict:
    with _VERROU:
        taches = charger(fichier)
        taches.append(tache)
        sauver(fichier, taches)
    return tache


def trouver(taches: list[dict], id_ou_description: str) -> list[dict]:
    cle = normaliser(id_ou_description)
    exact = [t for t in taches if t["id"] == str(id_ou_description).strip()]
    if exact or not cle:
        return exact
    return [t for t in taches if cle in normaliser(t.get("description", "") + " " + t.get("demande", ""))]


def supprimer(fichier: Path, ident: str) -> bool:
    with _VERROU:
        taches = charger(fichier)
        restantes = [t for t in taches if t["id"] != ident]
        if len(restantes) == len(taches):
            return False
        sauver(fichier, restantes)
    return True


def mettre_a_jour(fichier: Path, ident: str, **champs) -> None:
    with _VERROU:
        taches = charger(fichier)
        for t in taches:
            if t["id"] == ident:
                t.update(champs)
        sauver(fichier, taches)


def resume(tache: dict, maintenant: datetime | None = None) -> dict:
    p = prochaine_execution(tache, maintenant or datetime.now())
    return {"id": tache["id"], "description": tache.get("description") or decrire(tache),
            "frequence": tache.get("frequence"), "prochaine": p.isoformat(timespec="minutes") if p else None}


# --- Fil de fond --------------------------------------------------------------------------

class Planificateur:
    """Vérifie toutes les 30 s ; lance une tâche due quand le moteur est libre (sinon, au passage suivant).
    `executer(tache)` est fourni par l'application et doit être appelé verrou du moteur PRIS."""

    def __init__(self, fichier: Path, verrou: threading.Lock, executer, journal=None):
        self.fichier = Path(fichier)
        self.verrou = verrou
        self.executer = executer
        self.journal = journal
        self._fil: threading.Thread | None = None
        self._stop = threading.Event()

    def demarrer(self) -> None:
        if self._fil is None:
            self._fil = threading.Thread(target=self._boucle, daemon=True, name="planificateur")
            self._fil.start()

    def arreter(self) -> None:
        self._stop.set()

    def _boucle(self) -> None:
        while not self._stop.wait(VERIFIER_TOUTES_S):
            try:
                self.verifier()
            except Exception as e:  # noqa: BLE001 - le fil ne doit jamais mourir
                if self.journal is not None:
                    self.journal.ecrire("erreur_planificateur", texte=str(e))

    def verifier(self, maintenant: datetime | None = None) -> list[str]:
        """Lance les tâches dues (une à la fois). Renvoie les identifiants lancés."""
        lancees = []
        for tache in charger(self.fichier):
            if not est_due(tache, maintenant or datetime.now()):
                continue
            if not self.verrou.acquire(blocking=False):
                break  # moteur occupé : on réessaie au prochain passage
            try:
                quand = (maintenant or datetime.now()).isoformat(timespec="seconds")
                # Marquée AVANT de tourner : un plantage ne la fait pas relancer en boucle.
                mettre_a_jour(self.fichier, tache["id"], derniere_execution=quand,
                              **({"active": False} if tache.get("frequence") == "une_fois" else {}))
                debut = time.monotonic()
                ok, texte = self.executer(tache)
                mettre_a_jour(self.fichier, tache["id"], dernier_resultat=str(texte)[:RESULTAT_MAX],
                              dernier_ok=bool(ok), duree=round(time.monotonic() - debut, 1))
                lancees.append(tache["id"])
            finally:
                self.verrou.release()
        return lancees


# --- Briefing du matin (réglé depuis le panneau : une tâche quotidienne étiquetée « briefing ») -----------

BRIEFING_ETIQUETTE = "briefing"
BRIEFING_DEMANDE = ("Fais mon briefing du matin : mon agenda d'aujourd'hui, mes mails non lus importants résumés "
                    "en 3 lignes, et mes rappels du jour.")
BRIEFING_HEURE = "08:00"


def fichier_taches(source) -> Path:
    """taches.json à partir d'une Config (`.chemin`), d'une Application (`.cfg`) ou d'un chemin de fichier."""
    if hasattr(source, "cfg"):
        source = source.cfg
    if hasattr(source, "chemin"):
        return Path(source.chemin("taches.json"))
    return Path(source)


def _briefing(taches: list[dict]) -> dict | None:
    return next((t for t in taches if t.get("etiquette") == BRIEFING_ETIQUETTE), None)


def briefing_etat(source) -> dict:
    """{"actif": bool, "heure": "HH:MM"} (heure par défaut quand aucun briefing n'est programmé)."""
    t = _briefing(charger(fichier_taches(source)))
    if t is None:
        return {"actif": False, "heure": BRIEFING_HEURE}
    return {"actif": bool(t.get("active", True)), "heure": t.get("heure") or BRIEFING_HEURE}


def regler_briefing(source, actif: bool, heure: str = BRIEFING_HEURE, maintenant: datetime | None = None) -> dict:
    """Active (crée ou met à jour l'heure) ou désactive (supprime) le briefing quotidien. ValueError si l'heure est
    illisible. Renvoie le nouvel état, comme briefing_etat."""
    fichier = fichier_taches(source)
    with _VERROU:
        taches = charger(fichier)
        existant = _briefing(taches)
        if not actif:
            if existant is not None:
                sauver(fichier, [t for t in taches if t is not existant])
            return {"actif": False, "heure": (existant or {}).get("heure") or BRIEFING_HEURE}
        heure = lire_heure(heure or BRIEFING_HEURE)
        if existant is None:
            tache = creer(BRIEFING_DEMANDE, "quotidien", heure, maintenant=maintenant)
            tache["etiquette"] = BRIEFING_ETIQUETTE
            taches.append(tache)
        else:
            if existant.get("heure") != heure:
                # Nouvelle heure : on repart de maintenant (pas de rattrapage d'une heure qu'on vient de choisir).
                existant["derniere_execution"] = (maintenant or datetime.now()).isoformat(timespec="seconds")
            existant.update(demande=BRIEFING_DEMANDE, frequence="quotidien", heure=heure, jour="", date="",
                            active=True)
            existant["description"] = decrire(existant)
        sauver(fichier, taches)
    return {"actif": True, "heure": heure}
