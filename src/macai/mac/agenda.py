"""Calendrier et Rappels par EventKit (pyobjc importé à l'usage : rien n'est chargé au repos).

EventKit déplie les événements récurrents (AppleScript ne renvoie que l'occurrence d'origine) et ne lance pas
les applications Calendrier ou Rappels. Les dates Python sont « naïves » en heure locale, comme lire_date ;
la conversion passe par l'horodatage Unix, donc le fuseau du Mac est appliqué sans ambiguïté.
"""
from __future__ import annotations

import threading
from datetime import datetime

from ..outils.base import ErreurOutil

DELAI_AUTORISATION = 60   # fenêtre d'autorisation de macOS : l'utilisateur a le temps de répondre
DELAI_LECTURE = 30
ACCES_COMPLET = 3         # EKAuthorizationStatusFullAccess (même valeur que l'ancien « Authorized »)
REFUSES = (1, 2)          # Restricted, Denied

_magasin = None
_verrou = threading.Lock()
_autorises: set[int] = set()


def disponible() -> bool:
    """EventKit est-il utilisable (pyobjc-framework-EventKit installé) ?"""
    try:
        import EventKit  # noqa: F401
        return True
    except ImportError:
        return False


def magasin():
    """EKEventStore unique (le créer coûte cher ; il reste valable toute la session)."""
    global _magasin
    with _verrou:
        if _magasin is None:
            import EventKit
            _magasin = EventKit.EKEventStore.alloc().init()
        return _magasin


def message_refus(rappels: bool) -> str:
    rubrique = "Rappels" if rappels else "Calendriers"
    return ("AUTORISATION MANQUANTE (à accorder par l'utilisateur) : macOS refuse l'accès aux "
            f"{rubrique.lower()}. Réglages Système > Confidentialité et sécurité > {rubrique} > active MacAI "
            "(accès complet), puis relance MacAI.")


def autoriser(rappels: bool = False) -> None:
    """Demande l'accès complet aux événements (ou aux rappels) ; lève ErreurOutil si refusé."""
    import EventKit
    entite = EventKit.EKEntityTypeReminder if rappels else EventKit.EKEntityTypeEvent
    if entite in _autorises:
        return
    statut = EventKit.EKEventStore.authorizationStatusForEntityType_(entite)
    if statut == ACCES_COMPLET:
        _autorises.add(entite)
        return
    if statut in REFUSES:
        raise ErreurOutil(message_refus(rappels))
    # Non demandé, ou accès « écriture seule » : la fenêtre de macOS s'affiche (réponse dans un autre fil).
    fini, reponse = threading.Event(), {}

    def retour(accorde, erreur):
        reponse["ok"] = bool(accorde)
        fini.set()

    s = magasin()
    if rappels:
        s.requestFullAccessToRemindersWithCompletion_(retour)
    else:
        s.requestFullAccessToEventsWithCompletion_(retour)
    if not fini.wait(DELAI_AUTORISATION):
        raise ErreurOutil(message_refus(rappels).replace(
            "macOS refuse l'accès", "la fenêtre d'autorisation de macOS est restée sans réponse pour l'accès"))
    if not reponse.get("ok"):
        raise ErreurOutil(message_refus(rappels))
    _autorises.add(entite)


def vers_nsdate(d: datetime):
    from Foundation import NSDate
    return NSDate.dateWithTimeIntervalSince1970_(d.timestamp())  # naïve = heure locale du Mac


def depuis_nsdate(n) -> datetime | None:
    return None if n is None else datetime.fromtimestamp(float(n.timeIntervalSince1970()))


def _composantes(d: datetime):
    from Foundation import NSDateComponents
    c = NSDateComponents.alloc().init()
    c.setYear_(d.year)
    c.setMonth_(d.month)
    c.setDay_(d.day)
    c.setHour_(d.hour)
    c.setMinute_(d.minute)
    return c


def _echeance(composantes) -> tuple[datetime | None, bool]:
    """Échéance d'un rappel et présence d'une heure (un rappel « pour mardi » n'en a pas)."""
    if composantes is None:
        return None, False
    from Foundation import NSCalendar
    n = NSCalendar.currentCalendar().dateFromComponents_(composantes)
    heure = composantes.hour()
    return depuis_nsdate(n), 0 <= heure < 24  # NSDateComponentUndefined vaut NSIntegerMax


def _texte(v) -> str:
    return str(v) if v is not None else ""


def evenements(debut: datetime, fin: datetime) -> list[dict]:
    """Événements (récurrences dépliées) qui touchent [debut, fin[, triés par heure de début."""
    autoriser(False)
    s = magasin()
    predicat = s.predicateForEventsWithStartDate_endDate_calendars_(vers_nsdate(debut), vers_nsdate(fin), None)
    sortie = []
    for e in s.eventsMatchingPredicate_(predicat) or []:
        cal = e.calendar()
        sortie.append({"titre": _texte(e.title()) or "(sans titre)", "debut": depuis_nsdate(e.startDate()),
                       "fin": depuis_nsdate(e.endDate()), "lieu": _texte(e.location()),
                       "journee": bool(e.isAllDay()), "calendrier": _texte(cal.title()) if cal else ""})
    return sorted(sortie, key=lambda x: (x["debut"] or datetime.min, x["titre"]))


def rappels(debut: datetime | None = None, fin: datetime | None = None, liste: str = "") -> list[dict]:
    """Rappels non terminés (échéance dans [debut, fin[ si donnés), d'une liste précise ou de toutes."""
    autoriser(True)
    s = magasin()
    calendriers = None
    if liste:
        import EventKit
        tous = s.calendarsForEntityType_(EventKit.EKEntityTypeReminder) or []
        calendriers = [c for c in tous if _texte(c.title()).lower() == liste.strip().lower()]
        if not calendriers:
            noms = ", ".join(_texte(c.title()) for c in tous)
            raise ErreurOutil(f"Liste de rappels « {liste} » introuvable. Listes : {noms or 'aucune'}.")
    predicat = s.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        vers_nsdate(debut) if debut else None, vers_nsdate(fin) if fin else None, calendriers)
    fini, trouves = threading.Event(), {}

    def retour(liste_rappels):
        trouves["r"] = list(liste_rappels or [])
        fini.set()

    s.fetchRemindersMatchingPredicate_completion_(predicat, retour)
    if not fini.wait(DELAI_LECTURE):
        raise ErreurOutil("Rappels : pas de réponse de macOS après 30 s.")
    sortie = []
    for r in trouves.get("r", []):
        echeance, avec_heure = _echeance(r.dueDateComponents())
        cal = r.calendar()
        sortie.append({"titre": _texte(r.title()) or "(sans titre)", "echeance": echeance,
                       "heure": avec_heure, "liste": _texte(cal.title()) if cal else ""})
    return sorted(sortie, key=lambda x: (x["echeance"] is None, x["echeance"] or datetime.max, x["titre"]))


def creer_evenement(titre: str, debut: datetime, fin: datetime, lieu: str = "", calendrier: str = "") -> str:
    """Crée un événement ; renvoie le nom du calendrier utilisé."""
    import EventKit
    autoriser(False)
    s = magasin()
    if calendrier:
        cals = [c for c in s.calendarsForEntityType_(EventKit.EKEntityTypeEvent) or []
                if _texte(c.title()).lower() == calendrier.strip().lower() and c.allowsContentModifications()]
        if not cals:
            raise ErreurOutil(f"Calendrier « {calendrier} » introuvable ou en lecture seule.")
        cal = cals[0]
    else:
        cal = s.defaultCalendarForNewEvents()
    if cal is None:
        raise ErreurOutil("Aucun calendrier modifiable.")
    e = EventKit.EKEvent.eventWithEventStore_(s)
    e.setTitle_(titre)
    e.setStartDate_(vers_nsdate(debut))
    e.setEndDate_(vers_nsdate(fin))
    if lieu:
        e.setLocation_(lieu)
    e.setCalendar_(cal)
    ok, erreur = s.saveEvent_span_commit_error_(e, EventKit.EKSpanThisEvent, True, None)
    if not ok:
        raise ErreurOutil(f"Événement non enregistré : {erreur.localizedDescription() if erreur else 'erreur inconnue'}")
    return _texte(cal.title())


def creer_rappel(titre: str, echeance: datetime | None = None, liste: str = "") -> str:
    """Crée un rappel (alarme à l'échéance) ; renvoie le nom de la liste utilisée."""
    import EventKit
    autoriser(True)
    s = magasin()
    if liste:
        cals = [c for c in s.calendarsForEntityType_(EventKit.EKEntityTypeReminder) or []
                if _texte(c.title()).lower() == liste.strip().lower()]
        if not cals:
            raise ErreurOutil(f"Liste de rappels « {liste} » introuvable.")
        cal = cals[0]
    else:
        cal = s.defaultCalendarForNewReminders()
    if cal is None:
        raise ErreurOutil("Aucune liste de rappels.")
    r = EventKit.EKReminder.reminderWithEventStore_(s)
    r.setTitle_(titre)
    r.setCalendar_(cal)
    if echeance:
        r.setDueDateComponents_(_composantes(echeance))
        r.addAlarm_(EventKit.EKAlarm.alarmWithAbsoluteDate_(vers_nsdate(echeance)))
    ok, erreur = s.saveReminder_commit_error_(r, True, None)
    if not ok:
        raise ErreurOutil(f"Rappel non enregistré : {erreur.localizedDescription() if erreur else 'erreur inconnue'}")
    return _texte(cal.title())
