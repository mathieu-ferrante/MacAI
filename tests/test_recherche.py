import os
import time

from macai.outils import recherche_outils
from macai.recherche.index import Index, _requete_fts, decouper
from macai.recherche.indexeur import Indexeur, genre_de

from .conftest import FauxOllama


def test_decouper():
    assert decouper("") == []
    assert decouper("court") == ["court"]
    texte = ("Phrase numéro %d. " * 400) % tuple(range(400))
    morceaux = decouper(texte)
    assert all(len(m) <= 900 for m in morceaux)
    assert morceaux[0].endswith(".")          # coupe en fin de phrase
    assert len(morceaux) <= 40


def test_requete_fts_sure():
    assert _requete_fts('trouve la facture "EDF" de mars') == '"facture"* OR "edf"* OR "mars"*'
    assert _requete_fts("le la les") == ""


def remplir(tmp_path, ollama=None):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "facture_edf_mars.txt").write_text("Facture EDF électricité mars 2025 montant 84,20 euros", encoding="utf-8")
    (docs / "cours_reseaux.md").write_text("Cours réseaux : le protocole TCP, la poignée de main en trois temps.",
                                           encoding="utf-8")
    (docs / "recette.txt").write_text("Recette des crêpes : farine, oeufs, lait.", encoding="utf-8")
    (docs / "installeur.dmg").write_bytes(b"binaire")
    (docs / "node_modules").mkdir()
    (docs / "node_modules" / "x.js").write_text("ignoré")
    (docs / ".cache").mkdir()
    (docs / ".cache" / "y.txt").write_text("ignoré")
    return docs


def indexeur(cfg, index, docs):
    cfg.recherche["dossiers"] = [str(docs)]
    return Indexeur(cfg, index, sortie=lambda *a: None)


def test_indexation_et_recherche_hybride(cfg, tmp_path):
    docs = remplir(tmp_path)
    index = Index(tmp_path / "index.db", FauxOllama())
    ix = indexeur(cfg, index, docs)
    r = ix.executer(force=True)
    assert r["faits"] == 4                    # node_modules et dossiers cachés ignorés
    assert index.stats()["fichiers"] == 4 and index.stats()["avec_contenu"] == 3

    res = index.rechercher("facture électricité EDF")
    assert res[0].chemin.endswith("facture_edf_mars.txt")
    assert "84,20" in res[0].extrait
    assert index.rechercher("poignée de main TCP")[0].chemin.endswith("cours_reseaux.md")
    # Fichier non lisible : retrouvé par son nom.
    assert index.rechercher("installeur")[0].chemin.endswith("installeur.dmg")
    # Accents ignorés côté mots-clés.
    assert index.rechercher("electricite")[0].chemin.endswith("facture_edf_mars.txt")


def test_incremental_modification_et_suppression(cfg, tmp_path):
    docs = remplir(tmp_path)
    index = Index(tmp_path / "index.db", FauxOllama())
    ix = indexeur(cfg, index, docs)
    ix.executer(force=True)
    assert ix.executer(force=True)["faits"] == 0          # rien n'a changé
    f = docs / "recette.txt"
    f.write_text("Recette du gâteau au chocolat", encoding="utf-8")
    os.utime(f, (time.time() + 10, time.time() + 10))
    (docs / "cours_reseaux.md").unlink()
    r = ix.executer(force=True)
    assert r["faits"] == 1 and r["retires"] == 1
    assert index.rechercher("chocolat")[0].chemin.endswith("recette.txt")
    assert index.stats()["fichiers"] == 3
    # Plus d'extraits orphelins dans la table plein texte.
    assert not index.conn.execute("SELECT 1 FROM extraits_fts WHERE extraits_fts MATCH 'poignee'").fetchall()


def test_filtres(cfg, tmp_path):
    docs = remplir(tmp_path)
    index = Index(tmp_path / "index.db", FauxOllama())
    indexeur(cfg, index, docs).executer(force=True)
    assert index.rechercher("facture", genres=["pdf"]) == []
    assert index.rechercher("facture", apres=time.time() + 1000) == []
    assert index.rechercher("facture", dossier=str(docs))


def test_index_sans_modele_mots_seulement(cfg, tmp_path):
    docs = remplir(tmp_path)
    index = Index(tmp_path / "index.db", None)
    indexeur(cfg, index, docs).executer(force=True)
    assert index.rechercher("crêpes")[0].chemin.endswith("recette.txt")


def test_outil_recherche(ctx, tmp_path):
    docs = remplir(tmp_path)
    index = Index(tmp_path / "index.db", FauxOllama())
    indexeur(ctx.config, index, docs).executer(force=True)
    ctx.services["index"] = index
    r = recherche_outils.rechercher_fichiers(ctx, "facture EDF", periode="cette semaine")
    assert "facture_edf_mars.txt" in r.texte and r.donnees["resultats"]
    assert "fichiers indexés" in recherche_outils.etat_index(ctx)
    vide = Index(tmp_path / "vide.db", None)
    ctx.services["index"] = vide
    assert "encore vide" in recherche_outils.rechercher_fichiers(ctx, "rien").texte


def test_genres():
    from pathlib import Path
    assert genre_de(Path("Capture d’écran 2026-01-01.png")) == "capture"
    assert genre_de(Path("Capture d'écran 2026.png")) == "capture"
    assert genre_de(Path("IMG_001.HEIC")) == "image"
    assert genre_de(Path("a.pdf")) == "pdf"
    assert recherche_outils._date_min("3 mois") < time.time() - 80 * 86400


def test_parcours_ignore_le_code_des_projets(tmp_path):
    from macai.recherche.indexeur import parcourir
    projet = tmp_path / "MonAppli"
    (projet / "src").mkdir(parents=True)
    (projet / "package.json").write_text("{}")
    (projet / "src" / "main.js").write_text("console.log(1)")
    (projet / "cahier des charges.docx").write_text("x")
    (tmp_path / "script.py").write_text("print(1)")
    noms = {p.name for p, _ in parcourir([str(tmp_path)], [], 10**6)}
    assert noms == {"cahier des charges.docx", "script.py"}
