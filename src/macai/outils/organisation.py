"""Organisation : Rappels, Calendrier, Notes, Mail (AppleScript ; tout reste dans les apps d'Apple)."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

from ..mac import commun
from .base import ErreurOutil, Resultat, Risque, outil

S = commun.chaine_as


def lire_date(texte: str) -> datetime:
    """« 2026-10-15 09:30 », « 2026-10-15T09:30 », « 2026-10-15 » (9 h), « demain 14:00 »."""
    t = re.sub(r"(\d{1,2})\s*h\s*(\d{2})?", lambda m: f"{m.group(1)}:{m.group(2) or '00'}",
               (texte or "").strip().lower())
    base = datetime.now()
    for mot, decalage in (("apres-demain", 2), ("après-demain", 2), ("demain", 1), ("aujourd'hui", 0), ("aujourd’hui", 0)):
        if t.startswith(mot):
            reste = t[len(mot):].strip().rstrip(":") or "09:00"
            if reste.count(":") == 0:
                reste += ":00"
            heure = datetime.strptime(reste, "%H:%M").time()
            return datetime.combine((base + timedelta(days=decalage)).date(), heure)
    t = t.rstrip(":")
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        raise ErreurOutil(f"Date non comprise : « {texte} ». Utilise le format AAAA-MM-JJ HH:MM.") from None
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


@outil("creer_rappel", "Crée un rappel dans l'app Rappels, avec une échéance (notification à l'heure dite).",
       "organisation", {"titre": ("string", "texte du rappel"),
                        "echeance": ("string", "date et heure AAAA-MM-JJ HH:MM, facultatif"),
                        "liste": ("string", "liste de rappels, facultatif")}, requis=["titre"],
       risque=Risque.CREATION, annonce=lambda a: f"Rappel « {a['titre']} »" + (f" le {a['echeance']}" if a.get("echeance") else ""))
def creer_rappel(ctx, titre, echeance="", liste=""):
    props = f"{{name:{S(titre)}" + (", remind me date:d, due date:d" if echeance else "") + "}"
    cible = f"list {S(liste)}" if liste else "default list"
    prelude = date_as("d", lire_date(echeance)) + "\n" if echeance else ""
    commun.osascript(f"{prelude}tell application \"Reminders\" to make new reminder at end of {cible} with properties {props}")
    return f"Rappel créé : « {titre} »" + (f" pour le {_quand(lire_date(echeance))}." if echeance else ".")


@outil("lister_rappels", "Liste les rappels non terminés.", "organisation",
       {"liste": ("string", "liste précise, facultatif")}, requis=[])
def lister_rappels(ctx, liste=""):
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
    cal = f"calendar {S(calendrier)}" if calendrier else "first calendar whose writable is true"
    props = f"{{summary:{S(titre)}, start date:d1, end date:d2" + (f", location:{S(lieu)}" if lieu else "") + "}"
    commun.osascript(f'''{date_as("d1", d1)}
{date_as("d2", d2)}
tell application "Calendar"
    tell ({cal}) to make new event with properties {props}
end tell''', delai=60)
    return f"Événement « {titre} » ajouté le {_quand(d1)}."


@outil("lister_evenements", "Liste les événements du Calendrier sur les prochains jours.", "organisation",
       {"jours": ("integer", "nombre de jours à partir d'aujourd'hui (1 = aujourd'hui)")}, requis=[])
def lister_evenements(ctx, jours=1):
    debut = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    fin = debut + timedelta(days=max(1, int(jours or 1)))
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


@outil("creer_note", "Crée une note dans l'app Notes.", "organisation",
       {"titre": ("string", "titre"), "contenu": ("string", "texte de la note")}, risque=Risque.CREATION)
def creer_note(ctx, titre, contenu):
    corps = f"<h1>{html.escape(titre)}</h1>" + "".join(f"<div>{html.escape(l) or '<br>'}</div>" for l in contenu.splitlines())
    commun.osascript(f'tell application "Notes" to make new note with properties {{body:{S(corps)}}}')
    return f"Note « {titre} » créée."


@outil("chercher_notes", "Cherche dans les notes de l'app Notes (titre et contenu).", "organisation",
       {"requete": ("string", "mot ou expression")})
def chercher_notes(ctx, requete):
    brut = commun.osascript(f'''on extrait(t)
    if (length of t) > 600 then return text 1 thru 600 of t
    return t
end extrait
tell application "Notes"
    set res to ""
    repeat with n in (notes whose name contains {S(requete)} or plaintext contains {S(requete)})
        set res to res & "### " & (name of n) & linefeed & (my extrait(plaintext of n)) & linefeed
    end repeat
    return res
end tell''', delai=60)
    return brut or f"Aucune note ne contient « {requete} »."


@outil("lire_mails", "Liste les derniers mails reçus (expéditeur, sujet, date) dans l'app Mail.", "organisation",
       {"nombre": ("integer", "combien (10 par défaut)"), "non_lus": ("boolean", "seulement les non lus")}, requis=[])
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


@outil("preparer_mail", "Prépare un mail dans l'app Mail et l'affiche, SANS l'envoyer (l'utilisateur relit).",
       "organisation", {"destinataire": ("string", "adresse e-mail"), "sujet": ("string", "sujet"),
                        "corps": ("string", "texte du mail")}, risque=Risque.CREATION,
       annonce=lambda a: f"Préparer un mail à {a['destinataire']}")
def preparer_mail(ctx, destinataire, sujet, corps):
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
    commun.osascript(f'''tell application "Mail"
    set m to make new outgoing message with properties {{subject:{S(sujet)}, content:{S(corps)}, visible:false}}
    tell m to make new to recipient at end of to recipients with properties {{address:{S(destinataire)}}}
    send m
end tell''')
    return f"Mail envoyé à {destinataire}."
