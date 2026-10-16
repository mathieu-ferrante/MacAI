"""Organisation : agenda, mails, notes, messages — fonctions pures et AppleScript simulé (rien sur le vrai Mac)."""
import re
from datetime import date, datetime

import pytest

from macai.mac import commun
from macai.outils import organisation as org
from macai.outils.base import REGISTRE, ErreurOutil, Risque

VENDREDI = datetime(2026, 10, 16, 10, 0)


@pytest.fixture
def scripts(monkeypatch):
    journal = {"as": [], "reponses": []}

    def faux_osascript(script, javascript=False, delai=30):
        journal["as"].append(script)
        return journal["reponses"].pop(0) if journal["reponses"] else ""

    monkeypatch.setattr(commun, "osascript", faux_osascript)
    return journal


class FauxAgenda:
    """Remplace mac.agenda : aucun accès à EventKit."""

    def __init__(self, evenements=(), rappels=(), refus_rappels=False):
        self.evs, self.rps, self.refus, self.appels = list(evenements), list(rappels), refus_rappels, []

    def evenements(self, debut, fin):
        self.appels.append(("evenements", debut, fin))
        return self.evs

    def rappels(self, debut=None, fin=None, liste=""):
        self.appels.append(("rappels", debut, fin, liste))
        if self.refus:
            raise ErreurOutil("AUTORISATION MANQUANTE (à accorder par l'utilisateur) : Rappels.")
        return [r for r in self.rps if debut is None or (r["echeance"] and debut <= r["echeance"] < fin)]


@pytest.mark.parametrize("texte, attendu", [
    ("", date(2026, 10, 16)), ("aujourd'hui", date(2026, 10, 16)), ("Demain", date(2026, 10, 17)),
    ("après-demain", date(2026, 10, 18)), ("pour demain", date(2026, 10, 17)), ("lundi", date(2026, 10, 19)),
    ("vendredi", date(2026, 10, 16)), ("vendredi prochain", date(2026, 10, 23)),
    ("le 20 octobre", date(2026, 10, 20)), ("mardi 20 octobre", date(2026, 10, 20)),
    ("1er janvier", date(2027, 1, 1)), ("20/10", date(2026, 10, 20)), ("2026-11-03", date(2026, 11, 3)),
    ("03/11/2026", date(2026, 11, 3)),
])
def test_lire_jour(texte, attendu):
    assert org.lire_jour(texte, VENDREDI) == attendu


def test_lire_jour_refuse_l_incomprehensible():
    for t in ("la semaine des quatre jeudis", "31/02"):
        with pytest.raises(ErreurOutil, match="Jour non compris"):
            org.lire_jour(t, VENDREDI)


def test_bornes_jour():
    assert org.bornes_jour(date(2026, 10, 25)) == (datetime(2026, 10, 25), datetime(2026, 10, 26))


def test_resume_jour_trie_et_formate():
    j = date(2026, 10, 16)
    evs = [{"titre": "Réunion", "debut": datetime(2026, 10, 16, 14), "fin": datetime(2026, 10, 16, 15),
            "lieu": "Toulon", "calendrier": "Travail"},
           {"titre": "Dentiste", "debut": datetime(2026, 10, 16, 9), "fin": datetime(2026, 10, 16, 9, 30)},
           {"titre": "Anniversaire de Paul", "debut": datetime(2026, 10, 16), "fin": datetime(2026, 10, 17),
            "journee": True},
           {"titre": "Salon", "debut": datetime(2026, 10, 15, 9), "fin": datetime(2026, 10, 17, 18)}]
    rps = [{"titre": "Pain", "echeance": datetime(2026, 10, 16), "heure": False, "liste": "Courses"},
           {"titre": "Appeler la banque", "echeance": datetime(2026, 10, 16, 11), "heure": True}]
    retard = [{"titre": "Impôts", "echeance": datetime(2026, 10, 14, 9), "heure": True}]
    t = org.resume_jour(j, evs, rps, retard, aujourdhui=j)
    lignes = t.splitlines()
    assert lignes[0] == "Agenda du vendredi 16 octobre 2026 (aujourd'hui) :"
    assert lignes[2] == "- toute la journée Anniversaire de Paul"
    assert lignes.index("- 09:00–09:30 Dentiste") < lignes.index("- 14:00–15:00 Réunion (Toulon) [Travail]")
    assert "- toute la journée (sur plusieurs jours) Salon" in lignes
    assert lignes.index("- 11:00 Appeler la banque") < lignes.index("- dans la journée Pain [Courses]")
    assert "Rappels en retard (1) :" in lignes and "- mercredi 14/10 09:00 Impôts" in lignes


def test_resume_jour_vide():
    t = org.resume_jour(date(2026, 10, 17), [], [], aujourdhui=date(2026, 10, 16))
    assert "(demain)" in t and "Aucun événement." in t and "Aucun rappel" in t


def test_mon_agenda_par_eventkit(ctx, monkeypatch):
    j = date.today()
    faux = FauxAgenda(
        [{"titre": "Yoga", "debut": datetime.combine(j, datetime.min.time()).replace(hour=18),
          "fin": datetime.combine(j, datetime.min.time()).replace(hour=19)}],
        [{"titre": "Courses", "echeance": datetime.combine(j, datetime.min.time()).replace(hour=10),
          "heure": True}])
    monkeypatch.setattr(org, "_agenda", lambda: faux)
    t = org.mon_agenda(ctx, "aujourd'hui")
    assert "18:00–19:00 Yoga" in t and "10:00 Courses" in t
    assert faux.appels[0][1:] == org.bornes_jour(j)


def test_mon_agenda_sans_acces_aux_rappels(ctx, monkeypatch):
    monkeypatch.setattr(org, "_agenda", lambda: FauxAgenda(refus_rappels=True))
    t = org.mon_agenda(ctx, "demain")
    assert "Aucun événement." in t and "AUTORISATION MANQUANTE" in t


def test_mon_agenda_inscrit():
    o = REGISTRE.get("mon_agenda")
    assert o.risque == Risque.LECTURE and "emploi du temps" in o.mots_cles and o.requis == []


def test_lister_evenements_groupe_par_jour(ctx, monkeypatch):
    j = date.today()
    d = datetime.combine(j, datetime.min.time())
    faux = FauxAgenda([{"titre": "A", "debut": d.replace(hour=8), "fin": d.replace(hour=9)}])
    monkeypatch.setattr(org, "_agenda", lambda: faux)
    t = org.lister_evenements(ctx, 3)
    assert t.startswith("Événements du ") and f"{org.nom_jour(j)} :" in t and "- 08:00–09:00 A" in t
    assert (faux.appels[0][2] - faux.appels[0][1]).days == 3


def test_lister_rappels_par_eventkit(ctx, monkeypatch):
    faux = FauxAgenda(rappels=[{"titre": "Pain", "echeance": None, "heure": False, "liste": "Courses"}])
    monkeypatch.setattr(org, "_agenda", lambda: faux)
    assert "- sans échéance Pain [Courses]" in org.lister_rappels(ctx, "Courses")
    assert faux.appels[-1][3] == "Courses"


def test_repli_applescript_sans_eventkit(ctx, scripts, monkeypatch):
    monkeypatch.setattr(org, "_agenda", lambda: None)
    scripts["reponses"] = ["vendredi 16 octobre 2026 à 09:00:00 | Réunion"]
    assert "Réunion" in org.lister_evenements(ctx, 1)
    assert "tell application \"Calendar\"" in scripts["as"][-1]


def test_message_refus_eventkit():
    from macai.mac import agenda
    m = agenda.message_refus(True)
    assert m.startswith("AUTORISATION MANQUANTE (à accorder par l'utilisateur) : ")
    assert "Confidentialité et sécurité > Rappels" in m and "relance MacAI" in m
    assert "> Calendriers" in agenda.message_refus(False)


# --- Mail --------------------------------------------------------------------------------------------------

def _mail(de, sujet, age, lu, texte):
    return org.US.join([de, sujet, str(age), lu, texte]) + org.RS


def test_resumer_mails(ctx, scripts):
    scripts["reponses"] = [_mail("Paul <p@x.fr>", "Devis", 120, "false", "Bonjour,\n\n  voici le devis") +
                           _mail("Anne <a@y.fr>", "", 3 * 86400, "false", "")]
    t = org.resumer_mails(ctx, 5)
    s = scripts["as"][-1]
    assert "whose read status is false" in s and "if n > 5 then set n to 5" in s and "text 1 thru 400" in s
    assert t.startswith("2 mail(s) non lu(s)")
    assert "1. De : Paul <p@x.fr>" in t and "Sujet : Devis" in t and "Début : Bonjour, voici le devis" in t
    assert "Sujet : (sans sujet)" in t and "Début : (vide)" in t


def test_resumer_mails_borne_et_vide(ctx, scripts):
    assert org.resumer_mails(ctx, 500, False) == "Aucun mail."
    assert "if n > 30 then set n to 30" in scripts["as"][-1] and "whose" not in scripts["as"][-1]


def test_age_des_mails():
    m = datetime(2026, 10, 16, 12, 0)
    assert org._age("3600", m) == "11:00" and org._age("90000", m) == "15/10 11:00"
    assert org._age("n'importe", m) == "date inconnue"


def test_repondre_mail_lit_puis_prepare(ctx, scripts):
    scripts["reponses"] = [_mail("Paul", "Devis", 60, "true", "Peux-tu confirmer ?")]
    t = org.repondre_mail(ctx, "Paul")
    assert "aucun brouillon" in t and "Peux-tu confirmer ?" in t and "reply" not in scripts["as"][-1]
    scripts["reponses"] = [_mail("Paul", "Devis", 60, "true", "Peux-tu confirmer ?")]
    t = org.repondre_mail(ctx, 'Pa"ul', "C'est confirmé.")
    s = scripts["as"][-1]
    assert 'sender contains "Pa\\"ul" or subject contains "Pa\\"ul"' in s
    assert "reply m with opening window" in s and '"C\'est confirmé."' in s and not re.search(r"\bsend\b", s)
    assert "NON envoyée" in t


def test_repondre_mail_introuvable_et_risque(ctx, scripts):
    with pytest.raises(ErreurOutil, match="Aucun mail"):
        org.repondre_mail(ctx, "personne")
    o = REGISTRE.get("repondre_mail")
    assert o.risque_pour({"recherche": "x"}) == Risque.LECTURE
    assert o.risque_pour({"recherche": "x", "texte": "ok"}) == Risque.CREATION


def test_textes_sortants_sans_donnees_bancaires(ctx, scripts):
    carte = "ma carte 4111 1111 1111 1111"
    for appel in (lambda: org.repondre_mail(ctx, "Paul", carte), lambda: org.preparer_mail(ctx, "a@b.fr", "x", carte),
                  lambda: org.envoyer_mail(ctx, "a@b.fr", "x", carte),
                  lambda: org.envoyer_message(ctx, "0612345678", carte),
                  lambda: org.ajouter_a_note(ctx, "Banque", "FR76 3000 6000 0112 3456 7890 189")):
        with pytest.raises(ErreurOutil, match="bancaires"):
            appel()
    assert scripts["as"] == []


# --- Messages ----------------------------------------------------------------------------------------------

def test_normaliser_numero():
    assert org.normaliser_numero("06 12 34 56 78") == "+33612345678"
    assert org.normaliser_numero("0033 6.12.34.56.78") == "+33612345678"
    assert org.normaliser_numero("+1 (415) 555-0100") == "+14155550100"
    assert org.normaliser_numero("Maman") is None
    assert org.est_adresse("a@b.fr") and not org.est_adresse("Maman")


def _contact(nom, tels=(), mails=()):
    return org.US.join([nom, "".join(f"{l}={v}\n" for l, v in tels), "".join(f"{m}\n" for m in mails)]) + org.RS


def test_choisir_contact():
    brut = _contact("Marie Dupont", [("_$!<Home>!$_", "04 94 00 00 00"), ("_$!<Mobile>!$_", "06 11 22 33 44")])
    assert org.choisir_contact(brut, "marie") == ("Marie Dupont", "+33611223344")
    assert org.choisir_contact(_contact("Léa", mails=["lea@icloud.com"]), "lea") == ("Léa", "lea@icloud.com")
    deux = _contact("Marie Dupont", [("m", "0611223344")]) + _contact("Marie Curie", [("m", "0699887766")])
    with pytest.raises(ErreurOutil, match="Plusieurs contacts.*Marie Curie"):
        org.choisir_contact(deux, "Marie")
    assert org.choisir_contact(deux, "marie curie")[1] == "+33699887766"
    with pytest.raises(ErreurOutil, match="Aucun contact"):
        org.choisir_contact("", "Zorro")


def test_envoyer_message(ctx, scripts):
    scripts["reponses"] = [_contact("Maman", [("_$!<Mobile>!$_", "06 12 34 56 78")]), "iMessage"]
    t = org.envoyer_message(ctx, "Maman", 'J\'arrive "bientôt"')
    assert 'people whose name contains "Maman"' in scripts["as"][0]
    s = scripts["as"][1]
    assert 'send "J\'arrive \\"bientôt\\"" to participant "+33612345678" of s' in s and "SMS" in s
    assert t == "Message envoyé à Maman (+33612345678) par iMessage."
    o = REGISTRE.get("envoyer_message")
    assert o.toujours_confirmer and o.risque == Risque.SENSIBLE
    assert o.phrase({"destinataire": "Maman", "texte": "J'arrive"}) == "ENVOYER un message à Maman : « J'arrive »"


def test_envoyer_message_direct_et_vide(ctx, scripts):
    org.envoyer_message(ctx, "a@b.fr", "Salut")
    assert len(scripts["as"]) == 1 and 'participant "a@b.fr"' in scripts["as"][0]
    with pytest.raises(ErreurOutil, match="vide"):
        org.envoyer_message(ctx, "a@b.fr", "  ")


# --- Notes -------------------------------------------------------------------------------------------------

def test_ajouter_a_note(ctx, scripts):
    scripts["reponses"] = ["ajout"]
    assert org.ajouter_a_note(ctx, "Courses", "lait\n<œufs>") == "Texte ajouté à la note « Courses »."
    s = scripts["as"][-1]
    assert 'notes whose name is "Courses"' in s and "<div>lait</div><div>&lt;œufs&gt;</div>" in s
    scripts["reponses"] = ["creation"]
    assert "créée" in org.ajouter_a_note(ctx, "Idées", "x")
    assert REGISTRE.get("ajouter_a_note").risque == Risque.CREATION


def test_chercher_notes_premieres_lignes(ctx, scripts):
    corps = "Courses\n\nlait\ncafé\npain\nbeurre\nconfiture\n"
    scripts["reponses"] = [org.US.join(["Courses", corps]) + org.RS + org.US.join(["Vide", ""]) + org.RS]
    t = org.chercher_notes(ctx, "lait")
    assert t == "### Courses\nlait\ncafé\npain\nbeurre\n### Vide\n(vide)"
    assert org.chercher_notes(ctx, "rien") == "Aucune note ne contient « rien »."
