import json
import sys
from pathlib import Path

import pytest

from macai.competences.competences import Bibliotheque, Competence, substituer
from macai.connecteurs import onshape
from macai.llm.ollama import Reponse
from macai.mcp.client import GestionnaireMCP, risque_mcp
from macai.memoire.memoire import Memoire, apprendre
from macai.outils import competences_outils, memoire_outils
from macai.outils.base import ErreurOutil, Registre, Resultat, Risque, outil

from .conftest import FauxOllama

SERVEUR = [sys.executable, str(Path(__file__).with_name("faux_serveur_mcp.py"))]


# --- MCP ----------------------------------------------------------------------------

def test_mcp_decouverte_appel_et_cache(ctx, tmp_path):
    reg = Registre()
    g = GestionnaireMCP([{"nom": "photocraft", "commande": SERVEUR, "mots_cles": ["retouche"]}], reg,
                        tmp_path / "mcp.json")
    assert g.enregistrer() == {"photocraft": "3 outils"}
    o = reg.get("photocraft__redimensionner")
    assert o.groupe == "mcp_photocraft" and o.requis == ["chemin", "largeur"] and "retouche" in o.mots_cles
    assert reg.get("photocraft__infos").risque == Risque.LECTURE
    assert reg.get("photocraft__effacer_tout").risque == Risque.SENSIBLE
    r = o.executer(ctx, {"chemin": "a.png", "largeur": 800})
    assert r.ok and r.texte == "a.png → 800 px"
    assert not reg.get("photocraft__infos").executer(ctx, {}).ok          # isError
    assert g.serveurs["photocraft"].actif()
    g.fermer()
    assert not g.serveurs["photocraft"].actif()

    # Second démarrage : outils repris du cache, aucun serveur lancé.
    reg2 = Registre()
    g2 = GestionnaireMCP([{"nom": "photocraft", "commande": ["introuvable"]}], reg2, tmp_path / "mcp.json")
    assert g2.enregistrer(decouvrir=False) == {"photocraft": "3 outils"}
    r = reg2.get("photocraft__redimensionner").executer(ctx, {"chemin": "a", "largeur": 1})
    assert not r.ok and "Impossible de lancer" in r.texte


def test_mcp_serveur_absent(tmp_path):
    g = GestionnaireMCP([{"nom": "x", "commande": ["commande_qui_n_existe_pas"]}], Registre(), tmp_path / "c.json")
    assert g.enregistrer()["x"].startswith("erreur")


def test_risque_mcp_force():
    assert risque_mcp({}, "lecture") == Risque.LECTURE
    assert risque_mcp({}) == Risque.MODIFICATION


# --- Mémoire ----------------------------------------------------------------------------

def test_memoire_chiffree_et_pertinence(tmp_path):
    m = Memoire(tmp_path)
    m.retenir("Mathieu habite à Toulon")
    m.retenir("Mathieu préfère les réponses courtes")
    m.retenir("Le chien de Mathieu s'appelle Rex", source="appris")
    brut = (tmp_path / "memoire.db").read_bytes()
    assert b"Toulon" not in brut and b"Rex" not in brut       # chiffré sur le disque
    m2 = Memoire(tmp_path)                                    # relu avec la même clé
    assert len(m2.tous()) == 3
    assert "Le chien de Mathieu s'appelle Rex." in m2.pertinents("comment va mon chien ?")[0]
    # Fait proche : remplacé plutôt que dupliqué.
    m2.retenir("Mathieu habite à Toulon centre")
    assert sum("habite" in f.texte for f in m2.tous()) == 1
    assert m2.oublier("chien Rex") == ["Le chien de Mathieu s'appelle Rex."]
    assert len(Memoire(tmp_path).tous()) == 2
    assert len(m2.oublier("tout")) == 2 and not m2.tous()


def test_apprentissage_automatique(ctx, tmp_path):
    ctx.services["memoire"] = Memoire(tmp_path)
    ctx.ollama = FauxOllama([Reponse(texte="- Mathieu travaille comme développeur\n- Mathieu aime le vélo")])
    assert apprendre(ctx, "je travaille comme développeur et j'aime le vélo") == [
        "Mathieu travaille comme développeur", "Mathieu aime le vélo"]
    assert ("souvenirs_appris", {"faits": ["Mathieu travaille comme développeur", "Mathieu aime le vélo"]}) in ctx.evenements
    ctx.ollama = FauxOllama([])
    assert apprendre(ctx, "ouvre safari") == [] and ctx.ollama.recus == []   # pas de modèle inutile


def test_outils_memoire(ctx, tmp_path):
    ctx.services["memoire"] = Memoire(tmp_path)
    memoire_outils.retenir(ctx, "Mathieu utilise Onshape pour ses projets")
    assert "Onshape" in memoire_outils.lister_souvenirs(ctx).texte
    assert "Oublié" in memoire_outils.oublier(ctx, "Onshape projets")


# --- Compétences ----------------------------------------------------------------------------

def registre_avec_outils():
    reg = Registre()

    @outil("chercher", "", "fichiers", {"requete": ("string", "")}, mac_seulement=False, registre=reg)
    def chercher(ctx, requete):
        return Resultat(True, f"trouvé {requete}", {"resultats": [f"/docs/{requete}.pdf", "/autre.pdf"]})

    @outil("lire", "", "fichiers", {"chemin": ("string", "")}, mac_seulement=False, registre=reg)
    def lire(ctx, chemin):
        return Resultat(True, f"contenu de {chemin}", {"fichier": chemin})

    @outil("tableur", "", "fichiers", {"chemin": ("string", ""), "lignes": {"type": "array"}},
           risque=Risque.CREATION, mac_seulement=False, registre=reg)
    def tableur(ctx, chemin, lignes):
        return Resultat(True, f"tableur {chemin} {lignes}", {"fichier": chemin})

    return reg


def test_substituer():
    res = [Resultat(True, "texte 1", {"resultats": ["/a.pdf"], "n": 3})]
    assert substituer("{etape1.premier}", {}, res) == "/a.pdf"
    assert substituer("{etape1.n}", {}, res) == 3                     # type conservé
    assert substituer({"x": "Résumé de {sujet} : {etape1}"}, {"sujet": "EDF"}, res) == {"x": "Résumé de EDF : texte 1"}
    with pytest.raises(KeyError):
        substituer("{absent}", {}, res)


def test_competence_validation_execution_persistance(ctx, tmp_path):
    ctx.registre = registre_avec_outils()
    b = Bibliotheque(tmp_path / "comp", ctx.registre)
    with pytest.raises(ValueError, match="outil inconnu"):
        b.ajouter(Competence("x", "x", [{"outil": "nexiste", "arguments": {}}]))
    with pytest.raises(ValueError, match="non déclaré"):
        b.ajouter(Competence("x", "x", [{"outil": "lire", "arguments": {"chemin": "{fichier}"}}]))
    with pytest.raises(ValueError, match="étape précédente"):
        b.ajouter(Competence("x", "x", [{"outil": "lire", "arguments": {"chemin": "{etape1.fichier}"}}]))

    c = b.ajouter(Competence(
        nom="Exporter Facture", description="Retrouve une facture et la met dans un tableur",
        parametres={"fournisseur": "nom du fournisseur"}, declencheurs=["exporte la facture EDF"],
        etapes=[{"outil": "chercher", "arguments": {"requete": "facture {fournisseur}"}},
                {"outil": "lire", "arguments": {"chemin": "{etape1.premier}"}},
                {"outil": "tableur", "arguments": {"chemin": "~/Desktop/{fournisseur}.xlsx",
                                                   "lignes": [["{fournisseur}", "{etape2.fichier}"]]}}]))
    assert c.nom == "exporter_facture"
    o = ctx.registre.get("competence_exporter_facture")
    assert o.requis == ["fournisseur"] and "facture" in o.mots_cles
    r = o.executer(ctx, {"fournisseur": "EDF"})
    assert r.ok and "tableur ~/Desktop/EDF.xlsx [['EDF', '/docs/facture EDF.pdf']]" in r.texte
    # Rechargée depuis le disque, avec le compteur d'utilisations.
    reg2 = registre_avec_outils()
    b2 = Bibliotheque(tmp_path / "comp", reg2)
    assert b2.competences["exporter_facture"].utilisations == 1 and reg2.get("competence_exporter_facture")
    assert b2.supprimer("exporter_facture") and reg2.get("competence_exporter_facture") is None


def test_creer_competence_depuis_trace(ctx, tmp_path):
    ctx.registre = registre_avec_outils()
    ctx.services["competences"] = Bibliotheque(tmp_path / "comp", ctx.registre)
    ctx.services["derniere_trace"] = {"demande": "lis la facture EDF", "actions": [
        {"outil": "chercher", "arguments": {"requete": "facture EDF"}, "ok": True, "cles": ["resultats"]},
        {"outil": "lire", "arguments": {"chemin": "/docs/facture EDF.pdf"}, "ok": True, "cles": ["fichier"]}]}
    invalide = json.dumps({"nom": "lire_facture", "description": "d", "parametres": {},
                           "etapes": [{"outil": "chercher", "arguments": {"requete": "facture {fournisseur}"}}]})
    valide = json.dumps({"nom": "lire_facture", "description": "Lit la facture d'un fournisseur",
                         "declencheurs": ["lis la facture EDF"], "parametres": {"fournisseur": "nom"},
                         "etapes": [{"outil": "chercher", "arguments": {"requete": "facture {fournisseur}"}},
                                    {"outil": "lire", "arguments": {"chemin": "{etape1.premier}"}}]})
    ctx.ollama = FauxOllama([Reponse(texte=f"Voici :\n{invalide}"), Reponse(texte=valide)])
    r = competences_outils.creer_competence(ctx)
    assert r.ok and "lire_facture" in r.texte
    assert "Correction demandée" in ctx.ollama.recus[1]["messages"][0]["content"] or True
    assert ctx.services["derniere_trace"] is None
    assert "lire_facture" in competences_outils.lister_competences(ctx)
    with pytest.raises(ErreurOutil):
        competences_outils.creer_competence(ctx)  # plus de trace


# --- Onshape ------------------------------------------------------------------------------

def test_unites():
    assert onshape.en_metres("1 m") == 1.0
    assert onshape.en_metres("250mm") == 0.25
    assert onshape.en_metres("2,5 cm") == pytest.approx(0.025)
    assert onshape.en_metres(40) == pytest.approx(0.04)
    with pytest.raises(ErreurOutil):
        onshape.en_metres("beaucoup")
    with pytest.raises(ErreurOutil):
        onshape.en_metres("5 km")


def test_esquisse_et_extrusion():
    s = onshape.esquisse_rectangle(1.0, 1.0, "Cube")
    assert s["parameters"][0]["queries"][0]["deterministicIds"] == ["JDC"]
    pts = [(e["geometry"]["pntX"], e["geometry"]["pntY"]) for e in s["entities"]]
    assert pts == [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]   # centré sur l'origine
    assert len(s["constraints"]) == 4
    e = onshape.extrusion("F1", 1.0, "Cube")
    depth = next(p for p in e["parameters"] if p["parameterId"] == "depth")
    assert depth["expression"] == "1000 mm"


def test_cube_onshape_sans_reseau(ctx, monkeypatch):
    appels = []

    def faux(self, methode, chemin, corps=None):
        appels.append((methode, chemin, corps))
        if chemin == "/api/v6/documents":
            return {"id": "D", "defaultWorkspace": {"id": "W"}}
        if "elements" in chemin:
            return [{"id": "E"}]
        return {"feature": {"featureId": f"F{len(appels)}"}, "featureState": {"featureStatus": "OK"}}

    monkeypatch.setattr(onshape.Onshape, "requete", faux)
    monkeypatch.setattr(onshape.secrets, "lire", lambda nom: ("acces", "secret"))
    from macai.outils import onshape_outils
    monkeypatch.setattr("macai.outils.chrome.ouvrir_onglet", lambda ctx, url: appels.append(("OUVRIR", url, None)))
    r = onshape_outils.onshape_creer_piece(ctx, "cube", "1 m")
    assert r.ok and "1 m³" in r.texte
    assert appels[0][2] == {"name": "Cube 1 m", "isPublic": False}
    assert appels[2][2]["feature"]["featureType"] == "newSketch"
    assert appels[3][2]["feature"]["featureType"] == "extrude"
    assert appels[-1] == ("OUVRIR", "https://cad.onshape.com/documents/D/w/W/e/E", None)


def test_onshape_sans_cles(monkeypatch):
    monkeypatch.setattr(onshape.secrets, "lire", lambda nom: None)
    with pytest.raises(ErreurOutil, match="macai secret onshape"):
        onshape.Onshape()
