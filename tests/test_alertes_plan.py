"""Alertes (décisions pures, anti-répétition), briefing du matin, mode plan, propositions de compétence."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from macai import planificateur as pl
from macai import surveillance as sv
from macai.agent.orchestrateur import PLAN_REFUS, Orchestrateur, demande_complexe, lire_plan
from macai.llm.ollama import AppelOutil, Reponse
from tests.conftest import FauxOllama, appel
from tests.test_agent import registre_test

# --- Alertes : décisions pures -----------------------------------------------------------------

PMSET_BATTERIE = ("Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1234)\t18%; discharging; "
                  "0:40 remaining present: true")
PMSET_SECTEUR = ("Now drawing from 'AC Power'\n -InternalBattery-0 (id=1234)\t18%; charging; "
                 "1:10 remaining present: true")


def test_lire_pmset():
    assert sv.lire_pmset(PMSET_BATTERIE) == (18, False)
    assert sv.lire_pmset(PMSET_SECTEUR) == (18, True)
    assert sv.lire_pmset("Now drawing from 'AC Power'") is None  # Mac de bureau


def test_decider_batterie_une_fois_par_decharge():
    assert sv.decider_batterie(50, False, False) == (False, False)
    assert sv.decider_batterie(19, False, False) == (True, True)
    assert sv.decider_batterie(12, False, True) == (False, True)     # déjà signalé pendant cette décharge
    assert sv.decider_batterie(12, True, True) == (False, False)     # rebranché : réarmé
    assert sv.decider_batterie(15, False, False) == (True, True)     # nouvelle décharge
    assert sv.decider_batterie(None, False, False) == (False, False)


def test_decider_memoire_et_disque():
    assert not sv.decider_memoire([4])
    assert not sv.decider_memoire([2, 4])
    assert sv.decider_memoire([1, 4, 4])
    assert sv.decider_disque(9 * 1024 ** 3) and not sv.decider_disque(11 * 1024 ** 3)
    assert not sv.decider_disque(None)


def test_rendez_vous_a_signaler():
    m = datetime(2026, 10, 16, 14, 0)
    evts = [{"titre": "Réunion", "debut": m + timedelta(minutes=12), "lieu": "Salle B", "journee": False},
            {"titre": "Plus tard", "debut": m + timedelta(minutes=40), "journee": False},
            {"titre": "Férié", "debut": m + timedelta(minutes=5), "journee": True},
            {"titre": "Passé", "debut": m - timedelta(minutes=5), "journee": False}]
    a = sv.rendez_vous_a_signaler(evts, m, set())
    assert [e["titre"] for e in a] == ["Réunion"]
    assert sv.rendez_vous_a_signaler(evts, m, {sv.id_evenement(evts[0])}) == []
    titre, texte = sv.texte_rendez_vous(evts[0], m)
    assert titre == "Rendez-vous dans 12 min" and "14:12" in texte and "Salle B" in texte


def test_telechargements_finis():
    debut = 1000.0
    prec = {"a.pdf": (10, 1500.0), "b.zip.crdownload": (5, 1500.0), "vieux.txt": (3, 10.0), "c.dmg": (5, 1500.0)}
    act = {"a.pdf": (10, 1500.0), "b.zip.crdownload": (5, 1500.0), "vieux.txt": (3, 10.0), "c.dmg": (9, 1600.0),
           "d.png": (4, 1700.0)}
    assert sv.telechargements_finis(act, prec, debut, set()) == ["a.pdf"]  # c grossit encore, d vient d'arriver
    assert sv.telechargements_finis(act, prec, debut, {"a.pdf"}) == []


def test_anti_repetition():
    a = sv.AntiRepetition(3600)
    assert a.autoriser("disque", 0) and not a.autoriser("disque", 1800) and a.autoriser("memoire", 1800)
    assert a.autoriser("disque", 3700)


def _surveillance(cfg, tmp_path, **reglages):
    evts = []
    temps = {"t": 10_000.0}
    cfg.alertes.update(reglages)
    s = sv.Surveillance(cfg, lambda t, **d: evts.append((t, d)), horloge=lambda: temps["t"])
    s.lire_batterie = lambda: None
    s.lire_pression = lambda: None
    s.lire_disque_libre = lambda: None
    s.lire_agenda = lambda d, f: None
    s.dossier = tmp_path / "dl"
    s.dossier.mkdir()
    return s, evts, temps


def test_surveillance_passages(cfg, tmp_path):
    s, evts, temps = _surveillance(cfg, tmp_path)
    assert set(sv.TYPES) <= set(cfg.alertes)  # section [alertes] dans la configuration par défaut
    s.lire_batterie = lambda: (15, False)
    s.lire_pression = lambda: 4
    s.application_gourmande = lambda: ("Google Chrome", 3 * 1024 ** 3)
    s.lire_disque_libre = lambda: 5 * 1024 ** 3
    s.verifier()
    types = [d["type"] for _, d in evts]
    assert types == ["batterie", "disque"]          # mémoire : une seule mesure critique, pas encore
    s.verifier()
    types = [d["type"] for _, d in evts]
    assert types == ["batterie", "disque", "memoire"]  # batterie et disque pas répétés
    assert "Google Chrome" in evts[-1][1]["texte"] and evts[-1][0] == "alerte"
    temps["t"] += 3700
    s.verifier()
    assert [d["type"] for _, d in evts].count("disque") == 2  # une heure après : à nouveau
    assert [d["type"] for _, d in evts].count("batterie") == 1


def test_surveillance_desactivee_et_telechargement(cfg, tmp_path):
    s, evts, temps = _surveillance(cfg, tmp_path, disque=False)
    s.lire_disque_libre = lambda: 1
    (s.dossier / "ancien.pdf").write_bytes(b"x")
    import os
    os.utime(s.dossier / "ancien.pdf", (1, 1))      # plus vieux que le démarrage du moteur
    s.debut = 5_000.0
    s.verifier()                                     # premier passage : état initial
    nouveau = s.dossier / "rapport.pdf"
    nouveau.write_bytes(b"abc")
    os.utime(nouveau, (9_000, 9_000))
    (s.dossier / "film.mp4.crdownload").write_bytes(b"abc")
    s.verifier()                                     # vu une fois : taille pas encore stable
    assert evts == []
    s.verifier()
    assert [(d["type"], d["texte"]) for _, d in evts] == [("telechargements", "rapport.pdf : dans Téléchargements.")]
    s.verifier()
    assert len(evts) == 1


def test_surveillance_rendez_vous_une_fois(cfg, tmp_path):
    s, evts, temps = _surveillance(cfg, tmp_path)
    m = datetime(2026, 10, 16, 9, 50)
    s.lire_agenda = lambda d, f: [{"titre": "Point équipe", "debut": datetime(2026, 10, 16, 10, 0), "lieu": "",
                                   "journee": False}]
    s.verifier(m)
    s.verifier(m + timedelta(minutes=1))
    assert [d["type"] for _, d in evts] == ["rendez_vous"]
    s.lire_agenda = lambda d, f: (_ for _ in ()).throw(RuntimeError("pas d'autorisation"))
    temps["t"] += 600
    s.verifier(m + timedelta(minutes=2))             # erreur d'agenda : silence, pas de plantage
    assert len(evts) == 1


# --- Briefing du matin --------------------------------------------------------------------------

def test_briefing_creation_mise_a_jour_suppression(cfg):
    assert pl.briefing_etat(cfg) == {"actif": False, "heure": "08:00"}
    assert pl.regler_briefing(cfg, True, "7h30") == {"actif": True, "heure": "07:30"}
    taches = pl.charger(cfg.chemin("taches.json"))
    assert len(taches) == 1 and taches[0]["etiquette"] == "briefing" and taches[0]["frequence"] == "quotidien"
    assert taches[0]["demande"] == pl.BRIEFING_DEMANDE
    pl.regler_briefing(SimpleNamespace(cfg=cfg), True, "06:45")   # une Application convient aussi
    taches = pl.charger(cfg.chemin("taches.json"))
    assert len(taches) == 1 and taches[0]["heure"] == "06:45" and "06:45" in taches[0]["description"]
    assert pl.briefing_etat(cfg) == {"actif": True, "heure": "06:45"}
    pl.ajouter(cfg.chemin("taches.json"), pl.creer("liste mes rappels", "quotidien", "12:00"))
    assert pl.regler_briefing(cfg, False)["actif"] is False
    restantes = pl.charger(cfg.chemin("taches.json"))
    assert [t["demande"] for t in restantes] == ["liste mes rappels"]  # les autres tâches ne bougent pas
    assert pl.briefing_etat(cfg)["actif"] is False


def test_briefing_heure_invalide(cfg):
    import pytest
    with pytest.raises(ValueError):
        pl.regler_briefing(cfg, True, "25h")


# --- Mode plan ------------------------------------------------------------------------------------

DEMANDE_LONGUE = "lis le fichier a puis déplace-le vers b"


def _orch_plan(ctx, reponses, decisions):
    ctx.registre, faits = registre_test()
    ctx.ollama = FauxOllama(reponses)
    vus = []

    def demander_plan(ident, etapes):
        vus.append(list(etapes))
        return decisions.pop(0)
    ctx.demander_plan = demander_plan
    return Orchestrateur(ctx), faits, vus


def test_demande_complexe_et_lecture_du_plan():
    assert demande_complexe("ouvre Mail et écris à Paul")
    assert demande_complexe("range le bureau, puis vide la corbeille")
    assert not demande_complexe("ouvre Safari")
    assert lire_plan("Voici :\n1. Ouvrir Mail\n2) Écrire à Paul\n- Envoyer\n" + "\n".join(
        f"{i}. x" for i in range(4, 10))) == ["Ouvrir Mail", "Écrire à Paul", "Envoyer", "x", "x", "x"]


def test_plan_accepte(ctx):
    o, faits, vus = _orch_plan(ctx, [Reponse(texte="1. Lire a\n2. Déplacer a vers b\n3. Vérifier b"),
                                     appel("deplacer", src="a", dest="b"), Reponse(texte="fini")],
                               [("accepter", "")])
    assert o.traiter(DEMANDE_LONGUE) == "fini"
    assert vus == [["Lire a", "Déplacer a vers b", "Vérifier b"]] and faits == [("deplacer", "a", "b")]
    plan = [d for t, d in ctx.evenements if t == "plan_propose"]
    assert plan and plan[0]["etapes"] == ["Lire a", "Déplacer a vers b", "Vérifier b"] and plan[0]["id"]
    assert plan[0]["demande"] == DEMANDE_LONGUE
    assert ctx.ollama.recus[0]["outils"] is None and ctx.ollama.recus[0]["reflexion"] is False
    user = [m["content"] for m in ctx.ollama.recus[1]["messages"] if m["role"] == "user"][-1]
    assert "Plan validé par l'utilisateur" in user and "1. Lire a" in user and "Suis-le." in user


def test_plan_refuse(ctx):
    o, faits, vus = _orch_plan(ctx, [Reponse(texte="1. Lire a\n2. Déplacer a\n3. Fin")], [("refuser", "")])
    assert o.traiter(DEMANDE_LONGUE) == PLAN_REFUS
    assert faits == [] and len(ctx.ollama.recus) == 1
    assert any(t == "fin" for t, _ in ctx.evenements)


def test_plan_corrige_puis_accepte(ctx):
    o, faits, vus = _orch_plan(ctx, [Reponse(texte="1. Lire a\n2. Déplacer a vers c\n3. Fin"),
                                     Reponse(texte="1. Lire a\n2. Déplacer a vers b\n3. Fin"),
                                     appel("deplacer", src="a", dest="b"), Reponse(texte="fini")],
                               [("corriger", "vers b, pas c"), ("accepter", "")])
    assert o.traiter(DEMANDE_LONGUE) == "fini"
    assert vus == [["Lire a", "Déplacer a vers c", "Fin"], ["Lire a", "Déplacer a vers b", "Fin"]]
    replan = ctx.ollama.recus[1]["messages"][-1]["content"]
    assert "vers b, pas c" in replan and "Déplacer a vers c" in replan
    assert len([t for t, _ in ctx.evenements if t == "plan_propose"]) == 2


def test_plan_pas_pour_simple_question_tache_ou_sans_interface(ctx):
    o, faits, vus = _orch_plan(ctx, [Reponse(texte="ok")], [])
    o.traiter("lis le fichier a")                     # simple : pas de plan
    assert vus == []
    ctx.ollama = FauxOllama([Reponse(texte="parce que")])
    o.traiter("pourquoi le fichier a et le fichier b sont-ils différents ?")
    assert vus == []
    ctx.services["tache_planifiee"] = "x"
    ctx.ollama = FauxOllama([Reponse(texte="ok")])
    o.traiter(DEMANDE_LONGUE)
    assert vus == []
    del ctx.services["tache_planifiee"]
    ctx.config.agent["plan"] = "jamais"
    ctx.ollama = FauxOllama([Reponse(texte="ok")])
    o.traiter(DEMANDE_LONGUE)
    assert vus == []
    ctx.config.agent["plan"] = "complexe"
    ctx.ollama = FauxOllama([Reponse(texte="1. Lire a\n2. Lire b\n3. Comparer"), Reponse(texte="ok")])
    o.traiter("lis le fichier a puis le fichier b et compare-les")   # simple lecture : jamais de plan
    assert vus == [] and len(ctx.ollama.recus) == 1
    ctx.ollama = FauxOllama([Reponse(texte="1. Lire a\n2. Déplacer a"), Reponse(texte="ok")])
    o.traiter(DEMANDE_LONGUE)                          # plan de 2 étapes : pas montré, on agit
    assert vus == [] and len(ctx.ollama.recus) == 2
    ctx.config.agent["plan"] = "toujours"
    ctx.ollama = FauxOllama([Reponse(texte="1. Ouvrir a\n2. Déplacer\n3. Fin"), Reponse(texte="ok")])
    ctx.demander_plan = lambda i, e: vus.append(e) or ("accepter", "")
    o.traiter("déplace le fichier a")
    assert len(vus) == 1
    del ctx.demander_plan                              # pas d'interface (CLI, banc) : on agit directement
    ctx.ollama = FauxOllama([Reponse(texte="ok")])
    assert o.traiter(DEMANDE_LONGUE) == "ok" and len(ctx.ollama.recus) == 1


def test_plan_valide_ne_redemande_que_le_sensible(ctx):
    ctx.config.agent["autonomie"] = "prudent"
    o, faits, vus = _orch_plan(ctx, [Reponse(texte="1. Lire a\n2. Déplacer a\n3. Corbeille"),
                                     appel("deplacer", src="a", dest="b"), appel("corbeille", chemin="b"),
                                     Reponse(texte="fini")], [("accepter", "")])
    demandes = []
    ctx.demander_confirmation = lambda phrase, nom, args: demandes.append(nom) or True
    o.traiter(DEMANDE_LONGUE)
    assert demandes == ["corbeille"] and o.plan_valide is False   # déplacer : plus redemandé en « prudent »


# --- Propositions de compétence -------------------------------------------------------------------

def _tache_rangement(ctx, o, demande):
    ctx.ollama = FauxOllama([appel("lire", chemin="a"), appel("deplacer", src="a", dest="b"),
                             Reponse(appels=[AppelOutil("ouvrir_application", {"nom": "Finder"})]), Reponse(texte="fini")])
    ctx.evenements.clear()
    o.traiter(demande)
    return [d for t, d in ctx.evenements if t == "proposition_competence"]


def test_competence_proposee_seulement_a_la_repetition(ctx):
    ctx.registre, _ = registre_test()
    o = Orchestrateur(ctx)
    assert _tache_rangement(ctx, o, "range le fichier rapport dans archives") == []
    assert o.derniere_trace is not None               # « crée une compétence » reste possible
    props = _tache_rangement(ctx, o, "range le fichier facture dans archives")
    assert len(props) == 1 and props[0]["raison"] == "Tu as fait cette tâche 2 fois"
    assert cfg_traces(ctx) == 2
    # Tâche différente (autres outils) : pas de proposition
    ctx.ollama = FauxOllama([appel("lire", chemin="a"), appel("lire", chemin="b"), appel("lire", chemin="c"),
                             Reponse(texte="fini")])
    ctx.evenements.clear()
    o.traiter("range le fichier devis dans archives")
    assert not any(t == "proposition_competence" for t, _ in ctx.evenements)


def cfg_traces(ctx):
    import json
    return len(json.loads(ctx.config.chemin("traces_reussies.json").read_text(encoding="utf-8")))


def test_competence_pas_proposee_si_deja_existante(ctx):
    ctx.registre, _ = registre_test()
    competence = SimpleNamespace(etapes=[{"outil": "lire"}, {"outil": "deplacer"}, {"outil": "ouvrir_application"}])
    ctx.services["competences"] = SimpleNamespace(competences={"ranger": competence})
    o = Orchestrateur(ctx)
    _tache_rangement(ctx, o, "range le fichier rapport dans archives")
    assert _tache_rangement(ctx, o, "range le fichier facture dans archives") == []


def test_proposition_depuis_demonstration(ctx):
    o = Orchestrateur(ctx)
    etapes = [{"outil": "ouvrir_application", "arguments": {"nom": "Mail"}},
              {"outil": "cliquer", "arguments": {"numero": 3}}]
    assert o.proposer_depuis_demonstration(etapes, "trier mes mails")
    props = [d for t, d in ctx.evenements if t == "proposition_competence"]
    assert props[0]["raison"] == "Tu viens de me montrer comment faire" and props[0]["nb_actions"] == 2
    assert ctx.services["derniere_trace"]["actions"][0]["outil"] == "ouvrir_application"
    assert not o.proposer_depuis_demonstration([])
    assert o.proposer_depuis_demonstration({"description": "trier", "etapes": etapes})
