"""Annuler la dernière action sur les fichiers, et tâches planifiées."""
import os
import shutil
import threading
from datetime import datetime

import pytest

from macai import annulation, planificateur as pl
from macai.agent.rapide import CommandesRapides
from macai.outils import fichiers, taches
from macai.outils.base import ErreurOutil


@pytest.fixture
def corbeille(tmp_path, monkeypatch):
    """Corbeille simulée : renvoie l'emplacement du fichier jeté, comme NSFileManager."""
    d = tmp_path / "Corbeille"
    d.mkdir()

    def jeter(p):
        dest = fichiers.sans_collision(d / p.name)
        shutil.move(str(p), str(dest))
        return dest
    monkeypatch.setattr(fichiers, "mettre_corbeille", jeter)
    return d


def _annuler(ctx):
    return taches.annuler_derniere_action(ctx)


# --- Annuler --------------------------------------------------------------------------------

def test_annuler_deplacement_et_dossier_cree(ctx, tmp_path, corbeille):
    (tmp_path / "facture.pdf").write_text("x")
    fichiers.deplacer(ctx, str(tmp_path / "facture.pdf"), str(tmp_path / "Factures"))
    e = annulation.derniere(ctx.config.chemin("annulations.json"))
    assert e["description"] == "Déplacement de facture.pdf vers Factures"
    assert oct(os.stat(ctx.config.chemin("annulations.json")).st_mode & 0o777) == "0o600"
    assert taches._annonce_annuler({}) == "Annuler : Déplacement de facture.pdf vers Factures"
    r = _annuler(ctx)
    assert r.ok and "facture.pdf" in r.texte and "Annulé" in r.texte
    assert (tmp_path / "facture.pdf").read_text() == "x"
    assert not (tmp_path / "Factures").exists()  # dossier créé par l'action, vide : retiré
    assert "Rien à annuler" in _annuler(ctx).texte


def test_annuler_renommage(ctx, tmp_path, corbeille):
    (tmp_path / "a.txt").write_text("a")
    fichiers.renommer(ctx, str(tmp_path / "a.txt"), "b.txt")
    assert _annuler(ctx).ok
    assert (tmp_path / "a.txt").exists() and not (tmp_path / "b.txt").exists()


def test_annuler_copie_met_la_copie_a_la_corbeille(ctx, tmp_path, corbeille):
    (tmp_path / "a.txt").write_text("a")
    fichiers.copier(ctx, str(tmp_path / "a.txt"), str(tmp_path / "copie.txt"))
    _annuler(ctx)
    assert not (tmp_path / "copie.txt").exists() and (corbeille / "copie.txt").exists()
    assert (tmp_path / "a.txt").exists()


def test_annuler_ecriture_nouvelle_et_remplacee(ctx, tmp_path, corbeille):
    f = tmp_path / "notes" / "n.md"
    fichiers.ecrire_fichier_texte(ctx, str(f), "v1")
    _annuler(ctx)
    assert not f.exists() and not (tmp_path / "notes").exists() and (corbeille / "n.md").exists()
    (corbeille / "n.md").unlink()
    f.parent.mkdir()
    f.write_text("v1")
    fichiers.ecrire_fichier_texte(ctx, str(f), "v2", ecraser=True)
    assert annulation.derniere(ctx.config.chemin("annulations.json"))["description"] == "Remplacement de n.md"
    r = _annuler(ctx)
    assert f.read_text() == "v1" and (corbeille / "n (2).md").read_text() == "v2", r.texte


def test_annuler_creer_dossier_seulement_si_vide(ctx, tmp_path, corbeille):
    fichiers.creer_dossier(ctx, str(tmp_path / "Projet"))
    (tmp_path / "Projet" / "garde.txt").write_text("x")
    r = _annuler(ctx)
    assert (tmp_path / "Projet" / "garde.txt").exists() and "pas vide" in r.texte
    fichiers.creer_dossier(ctx, str(tmp_path / "Projet"))  # existait déjà : rien à annuler
    assert "Rien à annuler" in _annuler(ctx).texte


def test_annuler_rangement_en_une_fois(ctx, tmp_path, corbeille):
    d = tmp_path / "telechargements"
    d.mkdir()
    for nom in ["facture.pdf", "photo.jpg", "notes.txt"]:
        (d / nom).write_text(nom)
    fichiers.ranger_dossier(ctx, str(d))
    assert (d / "PDF" / "facture.pdf").exists()
    r = _annuler(ctx)
    assert r.ok
    assert sorted(p.name for p in d.iterdir()) == ["facture.pdf", "notes.txt", "photo.jpg"]


def test_annuler_mise_a_la_corbeille(ctx, tmp_path, corbeille):
    d = tmp_path / "a" / "b"
    d.mkdir(parents=True)
    (d / "rapport.pdf").write_text("r")
    fichiers.mettre_a_la_corbeille(ctx, str(d / "rapport.pdf"))
    assert not (d / "rapport.pdf").exists()
    r = _annuler(ctx)
    assert (d / "rapport.pdf").read_text() == "r" and "Corbeille" in r.texte


def test_annuler_n_ecrase_jamais(ctx, tmp_path, corbeille):
    (tmp_path / "a.txt").write_text("original")
    fichiers.renommer(ctx, str(tmp_path / "a.txt"), "b.txt")
    (tmp_path / "a.txt").write_text("nouveau venu")
    r = _annuler(ctx)
    assert (tmp_path / "a.txt").read_text() == "nouveau venu"
    assert (tmp_path / "a (2).txt").read_text() == "original"
    assert "existait déjà" in r.texte and "a (2).txt" in r.texte


def test_annuler_element_disparu_et_historique(ctx, tmp_path, corbeille):
    for n in ("x.txt", "y.txt"):
        (tmp_path / n).write_text(n)
    fichiers.renommer(ctx, str(tmp_path / "x.txt"), "x2.txt")
    fichiers.renommer(ctx, str(tmp_path / "y.txt"), "y2.txt")
    h = taches.historique_actions(ctx, 5)
    assert "Renommage de y.txt en y2.txt" in h.texte.splitlines()[1]
    (tmp_path / "y2.txt").unlink()
    r = _annuler(ctx)
    assert r.ok and "rien pu restaurer" in r.texte and "introuvable" in r.texte
    _annuler(ctx)  # l'entrée ratée a été retirée : on passe à la précédente
    assert (tmp_path / "x.txt").exists()


def test_pile_limitee_a_50(ctx, tmp_path):
    f = ctx.config.chemin("annulations.json")
    for i in range(60):
        annulation.ajouter(f, f"action {i}", [{"type": "corbeille", "chemin": str(tmp_path / f"{i}")}])
    entrees = annulation.charger(f)
    assert len(entrees) == 50 and entrees[-1]["description"] == "action 59"


def test_ancien_faux_mettre_corbeille_toujours_accepte(ctx, tmp_path, monkeypatch):
    # Une corbeille qui ne renvoie pas d'emplacement : l'écriture marche, l'ancienne version n'est juste pas restaurable.
    monkeypatch.setattr(fichiers, "mettre_corbeille", lambda p: p.unlink())
    (tmp_path / "n.md").write_text("v1")
    assert fichiers.ecrire_fichier_texte(ctx, str(tmp_path / "n.md"), "v2", ecraser=True).ok


# --- Commandes directes ------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", ["annule", "Annule ça", "annuler", "annule la dernière action",
                                    "reviens en arrière", "ctrl z", "Ctrl+Z", "annule ça !"])
def test_commande_directe_annuler(phrase):
    plan = CommandesRapides().reconnaitre(phrase)
    assert plan is not None and plan.actions == [("annuler_derniere_action", {})]


@pytest.mark.parametrize("phrase", ["annule mon rendez-vous de demain", "annule la réunion de lundi",
                                    "annule l'envoi du mail"])
def test_annuler_autre_chose_part_vers_l_agent(phrase):
    assert CommandesRapides().reconnaitre(phrase) is None


def test_commande_directe_resume_chaque_matin():
    plan = CommandesRapides().reconnaitre("Fais-moi un résumé chaque matin")
    assert plan.actions == [("planifier_tache", {"demande": "résume mes mails non lus et mon agenda du jour",
                                                 "frequence": "quotidien", "heure": "08:00"})]
    plan = CommandesRapides().reconnaitre("fais moi un résumé tous les matins à 7h30")
    assert plan.actions[0][1]["heure"] == "07:30"


# --- Horaires --------------------------------------------------------------------------------------

def T(**k):
    base = {"id": "t", "demande": "résume", "frequence": "quotidien", "heure": "08:00", "jour": "", "date": "",
            "derniere_execution": None, "active": True, "cree": "2026-10-01T12:00:00"}
    return {**base, **k}


D = datetime


def test_quotidien():
    t = T(derniere_execution="2026-10-15T08:00:05")
    assert pl.prochaine_execution(t, D(2026, 10, 15, 20, 0)) == D(2026, 10, 16, 8, 0)
    assert pl.est_due(t, D(2026, 10, 16, 8, 0, 10))
    assert not pl.est_due(t, D(2026, 10, 16, 7, 59))


def test_creee_apres_l_heure_ne_tourne_pas_tout_de_suite():
    t = T(cree="2026-10-16T09:00:00")
    assert pl.prochaine_execution(t, D(2026, 10, 16, 9, 0, 30)) == D(2026, 10, 17, 8, 0)


def test_jours_ouvres_saute_le_week_end():
    t = T(frequence="jours_ouvres", derniere_execution="2026-10-16T08:00:00")  # vendredi
    assert pl.prochaine_execution(t, D(2026, 10, 16, 12, 0)) == D(2026, 10, 19, 8, 0)  # lundi


def test_hebdomadaire():
    t = T(frequence="hebdomadaire", jour="mercredi", heure="18:30", derniere_execution="2026-10-14T18:30:00")
    assert pl.prochaine_execution(t, D(2026, 10, 16, 12, 0)) == D(2026, 10, 21, 18, 30)


def test_horaire():
    t = T(frequence="horaire", heure="00:15", derniere_execution="2026-10-16T10:15:02")
    assert pl.prochaine_execution(t, D(2026, 10, 16, 10, 40)) == D(2026, 10, 16, 11, 15)


def test_une_fois():
    t = T(frequence="une_fois", date="2026-10-20", heure="09:00")
    assert pl.prochaine_execution(t, D(2026, 10, 16, 12, 0)) == D(2026, 10, 20, 9, 0)
    assert pl.prochaine_execution({**t, "derniere_execution": "2026-10-20T09:00:00"}, D(2026, 10, 20, 9, 1)) is None
    assert pl.prochaine_execution(t, D(2026, 10, 21, 22, 0)) is None  # manquée de plus de 12 h : abandonnée


def test_heure_locale_au_changement_d_heure():
    # Passage à l'heure d'hiver le 25/10/2026 et d'été le 29/03/2026 : 08:00 reste 08:00 (heure locale naïve).
    t = T(derniere_execution="2026-10-24T08:00:00")
    assert pl.prochaine_execution(t, D(2026, 10, 24, 9, 0)) == D(2026, 10, 25, 8, 0)
    t = T(derniere_execution="2026-03-28T08:00:00")
    assert pl.prochaine_execution(t, D(2026, 3, 28, 9, 0)) == D(2026, 3, 29, 8, 0)


def test_executions_manquees_pendant_la_veille():
    t = T(derniere_execution="2026-10-12T08:00:00")  # Mac en veille depuis 4 jours
    # Réveil à 9 h : l'exécution de 8 h (1 h de retard) est rattrapée UNE fois.
    assert pl.prochaine_execution(t, D(2026, 10, 16, 9, 0)) == D(2026, 10, 16, 8, 0)
    # Réveil à 21 h : 13 h de retard, on attend demain 8 h.
    assert pl.prochaine_execution(t, D(2026, 10, 16, 21, 0)) == D(2026, 10, 17, 8, 0)
    h = T(frequence="horaire", heure="00:00", derniere_execution="2026-10-10T10:00:00")
    assert pl.prochaine_execution(h, D(2026, 10, 16, 10, 20)) == D(2026, 10, 16, 10, 0)


def test_tache_inactive():
    assert pl.prochaine_execution(T(active=False), D(2026, 10, 16, 9)) is None


# --- Création et validation ---------------------------------------------------------------------

def test_lire_frequence():
    assert pl.lire_frequence("tous les jours") == ("quotidien", "", "")
    assert pl.lire_frequence("en semaine") == ("jours_ouvres", "", "")
    assert pl.lire_frequence("du lundi au vendredi") == ("jours_ouvres", "", "")
    assert pl.lire_frequence("chaque lundi") == ("hebdomadaire", "lundi", "")
    assert pl.lire_frequence("hebdomadaire", jour="Vendredi") == ("hebdomadaire", "vendredi", "")
    assert pl.lire_frequence("toutes les heures") == ("horaire", "", "")
    assert pl.lire_frequence("demain") == ("une_fois", "", "demain")
    with pytest.raises(ValueError):
        pl.lire_frequence("hebdomadaire")
    with pytest.raises(ValueError):
        pl.lire_frequence("de temps en temps")


def test_creer_tache_et_refus():
    m = D(2026, 10, 16, 10, 0)
    t = pl.creer("résume mes mails", "chaque lundi", "7h30", maintenant=m)
    assert (t["frequence"], t["jour"], t["heure"]) == ("hebdomadaire", "lundi", "07:30")
    t = pl.creer("rappelle-moi de sortir", "demain", "9h", maintenant=m)
    assert t["date"] == "2026-10-17"
    assert pl.creer("un résumé", "quotidien", maintenant=m)["demande"] == \
        "résume mes mails non lus et mon agenda du jour"
    for demande in ("envoie un mail à Paul", "supprime les vieux fichiers", "efface mes téléchargements",
                    "achète du pain", "paie la facture", "publie un message", "poste une photo"):
        with pytest.raises(ValueError, match="sans toi"):
            pl.creer(demande, "quotidien", maintenant=m)
    with pytest.raises(ValueError, match="passé"):
        pl.creer("résume", "une_fois", "08:00", date_="2026-10-15", maintenant=m)
    with pytest.raises(ValueError, match="Heure"):
        pl.creer("résume mes mails", "quotidien", "27h", maintenant=m)


def test_outils_planifier_lister_supprimer(ctx):
    r = taches.planifier_tache(ctx, "résume mes mails non lus", "tous les jours", "08:00")
    assert r.ok and "programmé" in r.texte
    assert "existe déjà" in taches.planifier_tache(ctx, "résume mes mails non lus", "quotidien", "8h").texte
    taches.planifier_tache(ctx, "liste mes rendez-vous", "chaque vendredi", "17:00")
    assert oct(os.stat(ctx.config.chemin("taches.json")).st_mode & 0o777) == "0o600"
    assert taches.lister_taches(ctx).texte.count("[") == 2
    with pytest.raises(ErreurOutil, match="sans toi"):
        taches.planifier_tache(ctx, "envoie le rapport à Paul", "quotidien")
    taches.supprimer_tache(ctx, "rendez-vous")
    assert "rendez-vous" not in taches.lister_taches(ctx).texte
    with pytest.raises(ErreurOutil):
        taches.supprimer_tache(ctx, "inexistante")


# --- Exécution sans témoin -------------------------------------------------------------------------

def test_planificateur_lance_les_taches_dues_une_a_la_fois(cfg):
    f = cfg.chemin("taches.json")
    pl.ajouter(f, T(id="a", cree="2026-10-15T09:00:00"))
    pl.ajouter(f, T(id="b", frequence="une_fois", date="2026-10-16", heure="08:30", cree="2026-10-15T09:00:00"))
    verrou, faites = threading.Lock(), []

    def executer(t):
        assert verrou.locked()  # jamais hors du verrou du moteur
        faites.append(t["id"])
        return True, "ok " + t["id"]
    p = pl.Planificateur(f, verrou, executer)
    verrou.acquire()  # moteur occupé : rien ne part
    assert p.verifier(D(2026, 10, 16, 9, 0)) == []
    verrou.release()
    assert p.verifier(D(2026, 10, 16, 9, 0)) == ["a", "b"]
    assert p.verifier(D(2026, 10, 16, 9, 1)) == []  # déjà faites
    etat = {t["id"]: t for t in pl.charger(f)}
    assert etat["a"]["dernier_resultat"] == "ok a" and etat["b"]["active"] is False


def test_tache_sans_temoin_refuse_les_confirmations(cfg):
    from .conftest import FauxOllama, appel
    from macai.application import Application
    from macai.outils.base import Risque, outil
    cfg.agent["autonomie"] = "autonome"
    faits = []

    app = Application(cfg, ollama=FauxOllama([appel("test_envoi_sensible", texte="salut"),
                                               appel("test_lecture"), appel("test_lecture"),
                                               appel("test_lecture")]), avec_fond=False)

    @outil("test_envoi_sensible", "Envoie (test).", "test", {"texte": ("string", "texte")},
           risque=Risque.SENSIBLE, toujours_confirmer=True, mac_seulement=False, registre=app.registre,
           mots_cles=["resume"])
    def test_envoi_sensible(ctx, texte):
        faits.append(texte)
        return "envoyé"

    @outil("test_lecture", "Lit (test).", "test", {}, mac_seulement=False, registre=app.registre,
           mots_cles=["resume"])
    def test_lecture(ctx):
        return "lu"
    try:
        evenements = app.abonner()
        avant = app.ctx.demander_confirmation
        app.orchestrateur.historique = [{"role": "user", "content": "bonjour"}]
        with app._occupe:
            ok, texte = app.executer_tache({"id": "x", "demande": "resume tout", "description": "Résumé"})
        assert faits == []  # la confirmation a été refusée d'office
        assert app.ctx.demander_confirmation is avant
        assert cfg.agent["autonomie"] == "autonome" and cfg.agent["competence_apres_actions"] == 3
        assert app.orchestrateur.historique == [{"role": "user", "content": "bonjour"}]
        types = []
        while not evenements.empty():
            types.append(evenements.get_nowait())
        assert any(e["type"] == "confirmation" for e in types)  # demandée… et refusée
        assert not any(e["type"] == "proposition_competence" for e in types)
        fin = [e for e in types if e["type"] == "tache_terminee"]
        assert fin and fin[0]["description"] == "Résumé" and "texte" in fin[0]
    finally:
        app.registre.retirer("test_envoi_sensible")
        app.registre.retirer("test_lecture")
        app.fermer()


def test_application_annuler_et_taches(cfg, tmp_path, corbeille):
    from .conftest import FauxOllama
    from macai.application import Application
    app = Application(cfg, ollama=FauxOllama(), avec_fond=False)
    try:
        (tmp_path / "a.txt").write_text("a")
        fichiers.renommer(app.ctx, str(tmp_path / "a.txt"), "b.txt")
        r = app.annuler()
        assert r["ok"] and (tmp_path / "a.txt").exists()
        assert app.annuler()["texte"].startswith("Rien à annuler")
        taches.planifier_tache(app.ctx, "résume mes mails non lus", "quotidien", "08:00")
        liste = app.taches()
        assert set(liste[0]) == {"id", "description", "frequence", "prochaine"}
        assert app.supprimer_tache(liste[0]["id"]) and app.taches() == []
        assert not app.supprimer_tache("absente")
    finally:
        app.fermer()
