"""Organisation : Calendrier, Rappels, Notes, Mail, Messages (tout reste dans les apps d'Apple).

Outils « tout-en-un » (D26) : un seul appel fait le travail complet, le petit modèle n'enchaîne pas de clics.
Lecture du Calendrier et des Rappels par EventKit (récurrences dépliées, sans lancer les apps), AppleScript
sinon ; Mail, Notes, Messages et Contacts par AppleScript.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, time, timedelta

from ..mac import commun
from .base import ErreurOutil, Resultat, Risque, interdire_donnees_bancaires, outil

S = commun.chaine_as
US, RS = "\x1f", "\x1e"  # séparateurs de champs et d'enregistrements renvoyés par AppleScript
US_AS, RS_AS = "(character id 31)", "(character id 30)"


MOMENTS = (("apres-midi", "14:00"), ("après-midi", "14:00"), ("apres midi", "14:00"), ("après midi", "14:00"),
           ("matin", "09:00"), ("midi", "12:00"), ("soir", "19:00"))
JOURS = (("apres-demain", 2), ("après-demain", 2), ("demain", 1), ("aujourd'hui", 0), ("ce", 0), ("cet", 0))


def _heure(texte: str):
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(texte, fmt).time()
        except ValueError:
            pass
    raise ValueError(texte)


def lire_date(texte: str) -> datetime:
    """« 2026-10-15 09:30 », « 2026-10-15T09:30 », « 2026-10-15 » (9 h), « 15/10/2026 14h », « demain 14:00 »,
    « demain à 14h », « demain matin », « ce soir ». Lève ErreurOutil si la date n'est pas comprise."""
    try:
        return _lire_date(texte)
    except (ValueError, OverflowError):
        raise ErreurOutil(f"Date non comprise : « {texte} ». Utilise le format AAAA-MM-JJ HH:MM "
                          "(ex. 2026-10-15 14:30), ou « demain 14:00 ».") from None


def _lire_date(texte: str) -> datetime:
    t = (texte or "").strip().lower().replace("’", "'")
    t = re.sub(r"(?<=\d)z$", "", t)  # « …T14:00Z » : heure donnée telle quelle
    t = re.sub(r"(\d{1,2})\s*h\s*(\d{2})?\b", lambda m: f"{m.group(1)}:{m.group(2) or '00'}", t)
    for mot, heure in MOMENTS:
        t = re.sub(rf"(?<![\w-]){re.escape(mot)}\b", heure, t)
    t = re.sub(r"\s+(?:à|a|vers)\s+", " ", f" {t} ").strip().rstrip(":")
    base = datetime.now()
    if not t:
        raise ValueError(texte)
    for mot, decalage in JOURS:
        if t == mot or t.startswith(mot + " ") or (decalage and t.startswith(mot)):
            reste = t[len(mot):].strip().rstrip(":") or "09:00"
            if reste.count(":") == 0:
                reste += ":00"
            return datetime.combine((base + timedelta(days=decalage)).date(), _heure(reste))
    if re.fullmatch(r"\d{1,2}:\d{2}", t):  # heure seule : aujourd'hui, ou demain si l'heure est passée
        h = datetime.combine(base.date(), _heure(t))
        return h if h > base else h + timedelta(days=1)
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}:\d{2}))?", t):  # 15/10/2026 14:00
        return datetime.combine(datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date(),
                                _heure(m.group(4) or "09:00"))
    d = datetime.fromisoformat(t)
    if d.tzinfo is not None:  # « Z » ou « +02:00 » : heure gardée telle quelle (les petits modèles l'ajoutent)
        d = d.replace(tzinfo=None)
    if len(t) <= 10:
        d = d.replace(hour=9)
    return d


def date_as(var: str, d: datetime) -> str:
    """Construit une date AppleScript indépendamment de la langue du système."""
    return (f"set {var} to current date\nset day of {var} to 1\nset year of {var} to {d.year}\n"
            f"set month of {var} to {d.month}\nset day of {var} to {d.day}\nset hours of {var} to {d.hour}\n"
            f"set minutes of {var} to {d.minute}\nset seconds of {var} to 0")


def _quand(d: datetime) -> str:
    return d.strftime("%d/%m/%Y à %H:%M")


JOURS_SEMAINE = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_ANNEE = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
              "octobre", "novembre", "décembre"]
MOTS_AGENDA = ["agenda", "aujourd'hui", "demain", "planning", "emploi du temps", "rendez-vous", "rdv",
               "ma journee", "programme", "qu'est-ce que j'ai", "prevu"]


def _sans_accents(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", str(t or "").lower().replace("’", "'"))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()


def lire_jour(texte: str = "", maintenant: datetime | None = None) -> date:
    """« aujourd'hui » (défaut), « demain », « après-demain », « hier », « lundi » (le prochain, ou aujourd'hui
    si c'est lundi), « lundi prochain », « 20 octobre », « 20/10 », « 20/10/2026 », « 2026-10-20 »."""
    base = (maintenant or datetime.now()).date()
    t = re.sub(r"^(?:(?:le|la|ce|cette|pour|de|du)\s+|d')", "", _sans_accents(texte).strip(" .?!"))
    t = re.sub(r"^(journee de |journee d'|journee )", "", t)
    if t in ("", "aujourd'hui", "aujourdhui", "ce jour", "jour", "journee", "today"):
        return base
    decalages = {"demain": 1, "apres-demain": 2, "apres demain": 2, "hier": -1, "avant-hier": -2}
    if t in decalages:
        return base + timedelta(days=decalages[t])
    prochain = t.endswith(" prochain")
    nom = t.removesuffix(" prochain").strip()
    if nom in JOURS_SEMAINE:
        ecart = (JOURS_SEMAINE.index(nom) - base.weekday()) % 7
        return base + timedelta(days=ecart or (7 if prochain else 0))
    mois = [_sans_accents(m) for m in MOIS_ANNEE]
    try:
        if m := re.fullmatch(r"(?:\w+\s+)?(\d{1,2})(?:er)?\s+(" + "|".join(mois) + r")(?:\s+(\d{4}))?", t):
            return _sans_annee(base, int(m.group(1)), mois.index(m.group(2)) + 1, m.group(3))
        if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})", t):
            return _sans_annee(base, int(m.group(1)), int(m.group(2)), None)
        return lire_date(t).date()
    except (ErreurOutil, ValueError):
        raise ErreurOutil(f"Jour non compris : « {texte} ». Exemples : aujourd'hui, demain, lundi, 20 octobre, "
                          "2026-10-20.") from None


def _sans_annee(base: date, jour: int, mois: int, annee: str | None) -> date:
    """Date sans année : cette année, ou l'an prochain si elle est passée depuis plus d'un mois."""
    j = date(int(annee or base.year), mois, jour)
    return j if annee or j >= base - timedelta(days=31) else j.replace(year=j.year + 1)


def bornes_jour(j: date) -> tuple[datetime, datetime]:
    """[minuit, minuit du lendemain[ en heure locale."""
    debut = datetime.combine(j, time())
    return debut, debut + timedelta(days=1)


def nom_jour(j: date) -> str:
    return f"{JOURS_SEMAINE[j.weekday()]} {j.day} {MOIS_ANNEE[j.month - 1]} {j.year}"


def _hm(d: datetime | None) -> str:
    return d.strftime("%H:%M") if d else "?"


def ligne_evenement(e: dict, j: date | None = None) -> str:
    """« 09:00–10:00 Réunion (Toulon) [Travail] » ; journée entière ; débordement sur les jours voisins."""
    if e.get("journee"):
        quand = "toute la journée"
    else:
        d1, d2 = e.get("debut"), e.get("fin")
        avant = j is not None and d1 is not None and d1.date() < j
        apres = j is not None and d2 is not None and d2.date() > j and d2 != datetime.combine(d2.date(), time())
        if avant and apres:
            quand = "toute la journée (sur plusieurs jours)"
        elif avant:
            quand = f"jusqu'à {_hm(d2)}"
        elif apres:
            quand = f"{_hm(d1)} (jusqu'au {d2:%d/%m %H:%M})"
        else:
            quand = f"{_hm(d1)}–{_hm(d2)}"
        if j is None and d1 is not None:
            quand = f"{JOURS_SEMAINE[d1.weekday()]} {d1:%d/%m} {quand}"
    texte = f"{quand} {e.get('titre') or '(sans titre)'}"
    if e.get("lieu"):
        texte += f" ({' '.join(str(e['lieu']).split())})"
    if e.get("calendrier"):
        texte += f" [{e['calendrier']}]"
    return texte


def ligne_rappel(r: dict, avec_jour: bool = False) -> str:
    d = r.get("echeance")
    if d is None:
        quand = "sans échéance"
    elif avec_jour:
        quand = f"{JOURS_SEMAINE[d.weekday()]} {d:%d/%m}" + (f" {_hm(d)}" if r.get("heure") else "")
    else:
        quand = _hm(d) if r.get("heure") else "dans la journée"
    return f"{quand} {r.get('titre') or '(sans titre)'}" + (f" [{r['liste']}]" if r.get("liste") else "")


def resume_jour(j: date, evenements: list[dict], rappels: list[dict], en_retard: list[dict] | None = None,
                aujourdhui: date | None = None) -> str:
    """Résumé lisible d'une journée : événements triés puis rappels du jour (et rappels en retard)."""
    ref = aujourdhui or date.today()
    titre = {0: "aujourd'hui", 1: "demain", -1: "hier"}.get((j - ref).days)
    lignes = [f"Agenda du {nom_jour(j)}" + (f" ({titre})" if titre else "") + " :"]
    evs = sorted(evenements, key=lambda e: (not e.get("journee"), e.get("debut") or datetime.min))
    if evs:
        lignes.append(f"Événements ({len(evs)}) :")
        lignes += [f"- {ligne_evenement(e, j)}" for e in evs]
    else:
        lignes.append("Aucun événement.")
    rps = sorted(rappels, key=lambda r: (not r.get("heure"), r.get("echeance") or datetime.max))
    if rps:
        lignes.append(f"Rappels du jour ({len(rps)}) :")
        lignes += [f"- {ligne_rappel(r)}" for r in rps]
    else:
        lignes.append("Aucun rappel prévu ce jour-là.")
    if en_retard:
        lignes.append(f"Rappels en retard ({len(en_retard)}) :")
        lignes += [f"- {ligne_rappel(r, avec_jour=True)}" for r in en_retard[:10]]
    return "\n".join(lignes)


def liste_evenements(evenements: list[dict], debut: date, jours: int) -> str:
    if not evenements:
        return "Aucun événement sur cette période."
    lignes, courant = [], None
    for e in evenements:
        j = max((e.get("debut") or datetime.combine(debut, time())).date(), debut)
        if j != courant:
            courant = j
            lignes.append(f"{nom_jour(j)} :")
        lignes.append(f"- {ligne_evenement(e, j)}")
    fin = debut + timedelta(days=jours - 1)
    entete = f"Événements du {debut:%d/%m} au {fin:%d/%m} :" if jours > 1 else "Événements :"
    return entete + "\n" + "\n".join(lignes)


def _agenda():
    """Module EventKit, ou None si pyobjc-framework-EventKit manque (repli AppleScript)."""
    from ..mac import agenda
    return agenda if agenda.disponible() else None


# --- Rappels -----------------------------------------------------------------------------------------------

@outil("creer_rappel", "Crée un rappel dans l'app Rappels, avec une échéance (notification à l'heure dite).",
       "organisation", {"titre": ("string", "texte du rappel"),
                        "echeance": ("string", "date et heure AAAA-MM-JJ HH:MM, facultatif"),
                        "liste": ("string", "liste de rappels, facultatif")}, requis=["titre"],
       risque=Risque.CREATION, annonce=lambda a: f"Rappel « {a['titre']} »" + (f" le {a['echeance']}" if a.get("echeance") else ""))
def creer_rappel(ctx, titre, echeance="", liste=""):
    # Création par AppleScript (validée sur le Mac) ; mac.agenda.creer_rappel est prêt pour EventKit.
    props = f"{{name:{S(titre)}" + (", remind me date:d, due date:d" if echeance else "") + "}"
    cible = f"list {S(liste)}" if liste else "default list"
    prelude = date_as("d", lire_date(echeance)) + "\n" if echeance else ""
    commun.osascript(f"{prelude}tell application \"Reminders\" to make new reminder at end of {cible} with properties {props}")
    return f"Rappel créé : « {titre} »" + (f" pour le {_quand(lire_date(echeance))}." if echeance else ".")


@outil("lister_rappels", "Liste les rappels non terminés (toutes les listes, ou une liste précise).", "organisation",
       {"liste": ("string", "liste précise, facultatif")}, requis=[], delai_max=100)
def lister_rappels(ctx, liste=""):
    ek = _agenda()
    if ek is None:
        return _lister_rappels_as(liste)
    rps = ek.rappels(liste=liste)
    if not rps:
        return "Aucun rappel en cours."
    lignes = [f"- {ligne_rappel(r, avec_jour=True)}" for r in rps[:60]]
    reste = f"\n… et {len(rps) - 60} autres." if len(rps) > 60 else ""
    return f"Rappels en cours ({len(rps)}) :\n" + "\n".join(lignes) + reste


def _lister_rappels_as(liste=""):
    cible = f"list {S(liste)}" if liste else "default list"
    brut = commun.osascript(f'''tell application "Reminders"
    set res to ""
    repeat with r in (reminders of {cible} whose completed is false)
        set ligne to name of r
        try
            set ligne to ligne & " (échéance : " & ((due date of r) as string) & ")"
        end try
        set res to res & ligne & linefeed
    end repeat
    return res
end tell''', delai=60)
    return brut or "Aucun rappel en cours."


# --- Calendrier --------------------------------------------------------------------------------------------

@outil("creer_evenement", "Crée un événement dans le Calendrier.", "organisation",
       {"titre": ("string", "titre"), "debut": ("string", "AAAA-MM-JJ HH:MM"),
        "fin": ("string", "AAAA-MM-JJ HH:MM, facultatif (1 h par défaut)"), "lieu": ("string", "facultatif"),
        "calendrier": ("string", "nom du calendrier, facultatif")}, requis=["titre", "debut"],
       risque=Risque.CREATION, annonce=lambda a: f"Événement « {a['titre']} » le {a['debut']}")
def creer_evenement(ctx, titre, debut, fin="", lieu="", calendrier=""):
    d1 = lire_date(debut)
    d2 = lire_date(fin) if fin else d1 + timedelta(hours=1)
    if d2 <= d1:
        raise ErreurOutil("La fin doit être après le début.")
    # Création par AppleScript (validée sur le Mac) ; mac.agenda.creer_evenement est prêt pour EventKit.
    cal = f"calendar {S(calendrier)}" if calendrier else "first calendar whose writable is true"
    props = f"{{summary:{S(titre)}, start date:d1, end date:d2" + (f", location:{S(lieu)}" if lieu else "") + "}"
    commun.osascript(f'''{date_as("d1", d1)}
{date_as("d2", d2)}
tell application "Calendar"
    tell ({cal}) to make new event with properties {props}
end tell''', delai=60)
    return f"Événement « {titre} » ajouté le {_quand(d1)}."


@outil("lister_evenements", "Liste les événements du Calendrier sur les prochains jours (récurrents compris).",
       "organisation", {"jours": ("integer", "nombre de jours à partir d'aujourd'hui (1 = aujourd'hui)")},
       requis=[], delai_max=100)
def lister_evenements(ctx, jours=1):
    jours = min(max(1, int(jours or 1)), 62)
    debut = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    fin = debut + timedelta(days=jours)
    ek = _agenda()
    if ek is None:
        return _lister_evenements_as(debut, fin)
    return liste_evenements(ek.evenements(debut, fin), debut.date(), jours)


def _lister_evenements_as(debut: datetime, fin: datetime) -> str:
    brut = commun.osascript(f'''{date_as("d1", debut)}
{date_as("d2", fin)}
tell application "Calendar"
    set res to ""
    repeat with c in calendars
        repeat with e in (every event of c whose start date ≥ d1 and start date < d2)
            set res to res & ((start date of e) as string) & " | " & (summary of e) & linefeed
        end repeat
    end repeat
    return res
end tell''', delai=90)
    return brut or "Aucun événement sur cette période."


@outil("mon_agenda", "Résumé d'une journée : rendez-vous du Calendrier (heures, lieux, récurrents compris) et "
       "rappels prévus ce jour-là. Un seul appel suffit.", "organisation",
       {"jour": ("string", "aujourd'hui (défaut), demain, un jour de la semaine (lundi…) ou une date (2026-10-20)")},
       requis=[], mots_cles=MOTS_AGENDA, delai_max=150)
def mon_agenda(ctx, jour="aujourd'hui"):
    j = lire_jour(jour)
    debut, fin = bornes_jour(j)
    ek = _agenda()
    if ek is None:
        return f"Agenda du {nom_jour(j)} :\n" + _lister_evenements_as(debut, fin)
    evenements = ek.evenements(debut, fin)
    try:
        rappels = ek.rappels(debut, fin)
        en_retard = ek.rappels(None, datetime.now().replace(second=0, microsecond=0)) if j == date.today() else []
        en_retard = [r for r in en_retard if r.get("echeance") and r["echeance"] < debut]
    except ErreurOutil as e:  # accès aux Rappels refusé : le calendrier reste utile
        texte = resume_jour(j, evenements, [])
        return f"{texte}\n(Rappels non lus : {e})"
    return resume_jour(j, evenements, rappels, en_retard)


# --- Notes -------------------------------------------------------------------------------------------------

def _html_lignes(texte: str) -> str:
    return "".join(f"<div>{html.escape(l) or '<br>'}</div>" for l in str(texte).splitlines() or [""])


@outil("creer_note", "Crée une note dans l'app Notes.", "organisation",
       {"titre": ("string", "titre"), "contenu": ("string", "texte de la note")}, risque=Risque.CREATION)
def creer_note(ctx, titre, contenu):
    corps = f"<h1>{html.escape(titre)}</h1>" + _html_lignes(contenu)
    commun.osascript(f'tell application "Notes" to make new note with properties {{body:{S(corps)}}}')
    return f"Note « {titre} » créée."


def script_ajouter_note(titre: str, texte: str) -> str:
    ajout = _html_lignes(texte)
    nouvelle = f"<h1>{html.escape(titre)}</h1>" + ajout
    return f'''tell application "Notes"
    set trouvees to (notes whose name is {S(titre)})
    if (count of trouvees) > 0 then
        set n to item 1 of trouvees
        set body of n to (body of n) & {S(ajout)}
        return "ajout"
    end if
    make new note with properties {{body:{S(nouvelle)}}}
    return "creation"
end tell'''


@outil("ajouter_a_note", "Ajoute du texte à la fin d'une note de l'app Notes (la crée si elle n'existe pas) : "
       "liste de courses, journal, idées…", "organisation",
       {"titre": ("string", "titre exact de la note"), "texte": ("string", "texte à ajouter")},
       risque=Risque.CREATION, annonce=lambda a: f"Ajouter à la note « {a['titre']} » : {a['texte']}")
def ajouter_a_note(ctx, titre, texte):
    if not str(texte).strip():
        raise ErreurOutil("Rien à ajouter : donne le texte.")
    interdire_donnees_bancaires(texte)
    r = commun.osascript(script_ajouter_note(titre, texte), delai=60)
    if r.strip() == "creation":
        return f"Note « {titre} » introuvable : créée avec ce texte."
    return f"Texte ajouté à la note « {titre} »."


def formater_notes(brut: str, requete: str, lignes_max: int = 4) -> str:
    """Titre puis premières lignes non vides de chaque note (le titre répété en tête est sauté)."""
    notes = [n.split(US) for n in brut.split(RS) if n.strip()]
    if not notes:
        return f"Aucune note ne contient « {requete} »."
    sortie = []
    for champs in notes[:10]:
        nom = champs[0].strip()
        corps = [l.strip() for l in (champs[1] if len(champs) > 1 else "").splitlines() if l.strip()]
        if corps and corps[0] == nom:
            corps = corps[1:]
        sortie.append(f"### {nom}\n" + ("\n".join(l[:200] for l in corps[:lignes_max]) or "(vide)"))
    reste = f"\n… et {len(notes) - 10} autres notes." if len(notes) > 10 else ""
    return "\n".join(sortie) + reste


@outil("chercher_notes", "Cherche dans les notes de l'app Notes (titre et contenu) et montre leurs premières "
       "lignes.", "organisation", {"requete": ("string", "mot ou expression")}, delai_max=100)
def chercher_notes(ctx, requete):
    brut = commun.osascript(f'''on extrait(t)
    if (length of t) > 800 then return text 1 thru 800 of t
    return t
end extrait
tell application "Notes"
    set res to ""
    set i to 0
    repeat with n in (notes whose name contains {S(requete)} or plaintext contains {S(requete)})
        set i to i + 1
        if i > 11 then exit repeat
        set res to res & (name of n) & {US_AS} & (my extrait(plaintext of n)) & {RS_AS}
    end repeat
    return res
end tell''', delai=90)
    return formater_notes(brut, requete)


# --- Mail --------------------------------------------------------------------------------------------------

def _champs_mail_as(var: str, extrait: int) -> str:
    """AppleScript qui ajoute à `res` : expéditeur, sujet, âge en secondes, lu, début du contenu."""
    return f'''set c to ""
        try
            set c to content of {var}
            if (length of c) > {extrait} then set c to text 1 thru {extrait} of c
        end try
        set res to res & (sender of {var}) & {US_AS} & (subject of {var}) & {US_AS} & ((current date) - (date received of {var})) & {US_AS} & (read status of {var}) & {US_AS} & c & {RS_AS}'''


def script_resumer_mails(nombre: int, non_lus: bool, extrait: int = 400) -> str:
    filtre = " whose read status is false" if non_lus else ""
    n = max(1, min(int(nombre or 10), 30))
    return f'''tell application "Mail"
    set res to ""
    set msgs to (messages of inbox{filtre})
    set n to count of msgs
    if n > {n} then set n to {n}
    repeat with i from 1 to n
        set m to item i of msgs
        {_champs_mail_as("m", extrait)}
    end repeat
    return res
end tell'''


def _age(secondes: str, maintenant: datetime) -> str:
    try:
        d = maintenant - timedelta(seconds=float(secondes.replace(",", ".")))
    except ValueError:
        return "date inconnue"
    return d.strftime("%H:%M") if d.date() == maintenant.date() else d.strftime("%d/%m %H:%M")


def lire_mails_bruts(brut: str, maintenant: datetime | None = None) -> list[dict]:
    m = maintenant or datetime.now()
    mails = []
    for bloc in brut.split(RS):
        if not bloc.strip():
            continue
        c = (bloc.split(US) + [""] * 5)[:5]
        mails.append({"de": c[0].strip(), "sujet": c[1].strip() or "(sans sujet)", "date": _age(c[2].strip(), m),
                      "lu": c[3].strip().lower() == "true", "extrait": " ".join(c[4].split())})
    return mails


def formater_mails(mails: list[dict], non_lus: bool) -> str:
    if not mails:
        return "Aucun mail non lu." if non_lus else "Aucun mail."
    entete = f"{len(mails)} mail(s) {'non lu(s) ' if non_lus else ''}les plus récents :"
    blocs = []
    for i, x in enumerate(mails, 1):
        etat = "" if non_lus or x["lu"] else " (non lu)"
        blocs.append(f"{i}. De : {x['de']} — {x['date']}{etat}\n   Sujet : {x['sujet']}\n"
                     f"   Début : {x['extrait'] or '(vide)'}")
    return entete + "\n" + "\n".join(blocs)


@outil("lire_mails", "Liste les derniers mails reçus (expéditeur, sujet, date) dans l'app Mail.", "organisation",
       {"nombre": ("integer", "combien (10 par défaut)"), "non_lus": ("boolean", "seulement les non lus")},
       requis=[], delai_max=120)
def lire_mails(ctx, nombre=10, non_lus=False):
    filtre = " whose read status is false" if non_lus else ""
    brut = commun.osascript(f'''tell application "Mail"
    set res to ""
    set msgs to (messages of inbox{filtre})
    set n to count of msgs
    if n > {int(nombre)} then set n to {int(nombre)}
    repeat with i from 1 to n
        set m to item i of msgs
        set res to res & ((date received of m) as string) & " | " & (sender of m) & " | " & (subject of m) & linefeed
    end repeat
    return res
end tell''', delai=90)
    return Resultat(True, brut or "Aucun mail.")


@outil("resumer_mails", "Lit les derniers mails (expéditeur, sujet, date et début du texte) pour les résumer en "
       "un seul appel. Résume ensuite toi-même.", "organisation",
       {"nombre": ("integer", "combien (10 par défaut, 30 au plus)"),
        "non_lus": ("boolean", "seulement les non lus (oui par défaut)")}, requis=[],
       mots_cles=["resume mes mails", "resumer mes mails", "mails non lus", "nouveaux mails", "boite mail",
                  "courrier", "mes mails"], delai_max=180)
def resumer_mails(ctx, nombre=10, non_lus=True):
    brut = commun.osascript(script_resumer_mails(nombre, non_lus), delai=150)
    return formater_mails(lire_mails_bruts(brut), bool(non_lus))


def script_repondre(recherche: str, texte: str = "", extrait: int = 1500) -> str:
    """Mail le plus récent dont l'expéditeur ou le sujet contient `recherche` ; brouillon de réponse si `texte`."""
    R = S(recherche)
    reponse = ""
    if texte:
        reponse = f'''
    set r to reply m with opening window
    try
        set content of r to {S(texte)} & return & return & (content of r)
    on error
        set content of r to {S(texte)}
    end try
    activate'''
    return f'''tell application "Mail"
    set trouves to (messages of inbox whose sender contains {R} or subject contains {R})
    set k to count of trouves
    if k = 0 then return ""
    if k > 50 then set k to 50
    set m to item 1 of trouves
    repeat with i from 2 to k
        set x to item i of trouves
        if (date received of x) > (date received of m) then set m to x
    end repeat
    set res to ""
    {_champs_mail_as("m", extrait)}{reponse}
    return res
end tell'''


@outil("repondre_mail", "Retrouve le mail le plus récent d'un expéditeur ou sur un sujet et renvoie son texte. "
       "Avec « texte » : ouvre en plus une réponse pré-remplie dans Mail, SANS l'envoyer (l'utilisateur relit). "
       "Lis d'abord le mail (sans texte), rédige la réponse, puis rappelle l'outil avec texte.", "organisation",
       {"recherche": ("string", "nom, adresse de l'expéditeur ou mot du sujet"),
        "texte": ("string", "texte de la réponse, facultatif")}, requis=["recherche"],
       risque=lambda a: Risque.CREATION if str(a.get("texte") or "").strip() else Risque.LECTURE,
       annonce=lambda a: (f"Préparer une réponse (non envoyée) au mail « {a['recherche']} » : {a['texte']}"
                          if str(a.get("texte") or "").strip() else f"Lire le mail « {a['recherche']} »"),
       mots_cles=["reponds", "repondre", "reponse au mail", "repondre au mail"], delai_max=180)
def repondre_mail(ctx, recherche, texte=""):
    texte = str(texte or "").strip()
    if not str(recherche).strip():
        raise ErreurOutil("Indique l'expéditeur ou le sujet du mail.")
    if texte:
        interdire_donnees_bancaires(texte)
    brut = commun.osascript(script_repondre(recherche, texte), delai=150)
    mails = lire_mails_bruts(brut)
    if not mails:
        raise ErreurOutil(f"Aucun mail de la boîte de réception ne correspond à « {recherche} ».")
    x = mails[0]
    contenu = f"De : {x['de']} — {x['date']}\nSujet : {x['sujet']}\nTexte : {x['extrait'] or '(vide)'}"
    if texte:
        return f"Réponse prête dans Mail (NON envoyée, l'utilisateur relit et envoie).\nMail d'origine :\n{contenu}"
    return (f"Mail trouvé (aucun brouillon ouvert : rédige la réponse puis rappelle repondre_mail avec "
            f"texte).\n{contenu}")


@outil("preparer_mail", "Prépare un mail dans l'app Mail et l'affiche, SANS l'envoyer (l'utilisateur relit).",
       "organisation", {"destinataire": ("string", "adresse e-mail"), "sujet": ("string", "sujet"),
                        "corps": ("string", "texte du mail")}, risque=Risque.CREATION,
       annonce=lambda a: f"Préparer un mail à {a['destinataire']}")
def preparer_mail(ctx, destinataire, sujet, corps):
    interdire_donnees_bancaires(f"{sujet}\n{corps}")
    commun.osascript(f'''tell application "Mail"
    set m to make new outgoing message with properties {{subject:{S(sujet)}, content:{S(corps)}, visible:true}}
    tell m to make new to recipient at end of to recipients with properties {{address:{S(destinataire)}}}
    activate
end tell''')
    return f"Mail à {destinataire} prêt dans Mail (non envoyé)."


@outil("envoyer_mail", "Envoie un mail immédiatement depuis l'app Mail.", "organisation",
       {"destinataire": ("string", "adresse e-mail"), "sujet": ("string", "sujet"), "corps": ("string", "texte")},
       risque=Risque.SENSIBLE, toujours_confirmer=True,
       annonce=lambda a: f"ENVOYER un mail à {a['destinataire']} — sujet : {a['sujet']}")
def envoyer_mail(ctx, destinataire, sujet, corps):
    interdire_donnees_bancaires(f"{sujet}\n{corps}")
    commun.osascript(f'''tell application "Mail"
    set m to make new outgoing message with properties {{subject:{S(sujet)}, content:{S(corps)}, visible:false}}
    tell m to make new to recipient at end of to recipients with properties {{address:{S(destinataire)}}}
    send m
end tell''')
    return f"Mail envoyé à {destinataire}."


# --- Messages (iMessage / SMS) ----------------------------------------------------------------------------

def normaliser_numero(texte: str) -> str | None:
    """Numéro de téléphone (06…, +33…, 0033…) mis au format international, sinon None."""
    t = re.sub(r"[\s.\-()]", "", str(texte or ""))
    if not re.fullmatch(r"\+?\d{6,15}", t):
        return None
    if t.startswith("00"):
        return "+" + t[2:]
    if re.fullmatch(r"0[1-9]\d{8}", t):  # numéro français
        return "+33" + t[1:]
    return t


def est_adresse(texte: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(texte or "").strip()))


def script_contacts(nom: str) -> str:
    return f'''tell application "Contacts"
    set res to ""
    repeat with p in (people whose name contains {S(nom)})
        set res to res & (name of p) & {US_AS}
        repeat with t in phones of p
            set res to res & (label of t) & "=" & (value of t) & linefeed
        end repeat
        set res to res & {US_AS}
        repeat with e in emails of p
            set res to res & (value of e) & linefeed
        end repeat
        set res to res & {RS_AS}
    end repeat
    return res
end tell'''


def choisir_contact(brut: str, nom: str) -> tuple[str, str]:
    """(nom complet, numéro ou adresse) : le portable de préférence ; erreur si aucun ou plusieurs contacts."""
    gens = []
    for bloc in brut.split(RS):
        if not bloc.strip():
            continue
        c = (bloc.split(US) + ["", ""])[:3]
        tels = [l.partition("=") for l in c[1].splitlines() if "=" in l]
        mails = [l.strip() for l in c[2].splitlines() if l.strip()]
        gens.append((c[0].strip(), tels, mails))
    if not gens:
        raise ErreurOutil(f"Aucun contact « {nom} » dans Contacts. Donne son numéro ou son adresse iMessage.")
    exacts = [g for g in gens if _sans_accents(g[0]) == _sans_accents(nom)]
    if len(exacts) == 1:
        gens = exacts
    elif len({g[0] for g in gens}) > 1:
        noms = ", ".join(sorted({g[0] for g in gens})[:8])
        raise ErreurOutil(f"Plusieurs contacts correspondent à « {nom} » : {noms}. Précise lequel.")
    complet, tels, mails = gens[0]
    portables = [v for lab, _, v in tels if re.search(r"mobile|iphone|portable|cell", lab, re.I)]
    for v in portables + [v for _, _, v in tels]:
        if numero := normaliser_numero(v):
            return complet, numero
    if mails:
        return complet, mails[0]
    raise ErreurOutil(f"Le contact « {complet} » n'a ni numéro ni adresse.")


def script_message(identifiant: str, texte: str) -> str:
    """Envoi par iMessage, puis par SMS (iPhone relié) si iMessage échoue."""
    return f'''tell application "Messages"
    try
        set s to 1st account whose service type = iMessage
        send {S(texte)} to participant {S(identifiant)} of s
        return "iMessage"
    on error e1
        try
            set s to 1st account whose service type = SMS
            send {S(texte)} to participant {S(identifiant)} of s
            return "SMS"
        on error e2
            error e1
        end try
    end try
end tell'''


@outil("envoyer_message", "Envoie un iMessage (ou un SMS) avec l'app Messages, à un numéro, une adresse ou un nom "
       "de Contacts. L'historique des Messages n'est pas lisible.", "organisation",
       {"destinataire": ("string", "nom d'un contact, numéro de téléphone ou adresse iMessage"),
        "texte": ("string", "texte du message")},
       risque=Risque.SENSIBLE, toujours_confirmer=True,
       annonce=lambda a: f"ENVOYER un message à {a['destinataire']} : « {a['texte']} »",
       mots_cles=["imessage", "sms", "texto", "envoie un message", "envoyer un message"], delai_max=120)
def envoyer_message(ctx, destinataire, texte):
    texte = str(texte or "").strip()
    if not texte:
        raise ErreurOutil("Message vide : donne le texte à envoyer.")
    interdire_donnees_bancaires(texte)
    dest = str(destinataire or "").strip()
    if est_adresse(dest):
        nom, ident = dest, dest
    elif numero := normaliser_numero(dest):
        nom, ident = dest, numero
    else:
        nom, ident = choisir_contact(commun.osascript(script_contacts(dest), delai=60), dest)
    service = commun.osascript(script_message(ident, texte), delai=60).strip() or "iMessage"
    qui = nom if nom == ident else f"{nom} ({ident})"
    return f"Message envoyé à {qui} par {service}."
