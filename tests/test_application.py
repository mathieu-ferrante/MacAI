import json
import threading
import time
import urllib.request

from macai.application import Application
from macai.llm.ollama import Reponse
from macai.serveur import creer_gestionnaire

from .conftest import FauxOllama, appel


def faire_app(cfg, reponses):
    return Application(cfg, ollama=FauxOllama(reponses), avec_fond=False)


def test_outils_charges(cfg):
    app = faire_app(cfg, [])
    noms = set(app.registre.outils)
    for attendu in ["rechercher_fichiers", "lire_document", "creer_tableur", "ouvrir_application", "youtube_lire",
                    "lire_fenetre", "creer_rappel", "retenir", "creer_competence", "onshape_creer_piece"]:
        assert attendu in noms
    assert len(noms) > 50
    for o in app.registre.outils.values():   # schémas valides pour Ollama
        json.dumps(o.schema())
        assert o.description and len(o.nom) <= 64


def test_confirmation_par_l_interface(cfg, tmp_path):
    cible = tmp_path / "a_jeter.txt"
    cible.write_text("x")
    app = faire_app(cfg, [appel("mettre_a_la_corbeille", chemin=str(cible)), Reponse(texte="Jeté.")])
    q = app.abonner()
    t = threading.Thread(target=app.traiter, args=("jette a_jeter.txt",))
    t.start()
    while True:
        evt = q.get(timeout=5)
        if evt["type"] == "demande_confirmation":
            assert "Corbeille" in evt["phrase"]
            assert app.repondre_confirmation(evt["id"], True)
            break
    t.join(5)
    assert not cible.exists()


def test_serveur_http_et_flux(cfg):
    from http.server import ThreadingHTTPServer
    app = faire_app(cfg, [Reponse(texte="Bonjour !")])
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), creer_gestionnaire(app, "jeton-test"))
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{serveur.server_address[1]}"

    def req(chemin, corps=None, jeton="jeton-test"):
        r = urllib.request.Request(base + chemin, data=json.dumps(corps).encode() if corps is not None else None,
                                   headers={"X-MacAI-Jeton": jeton, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=5) as rep:
                return rep.status, json.loads(rep.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    assert req("/etat", jeton="mauvais")[0] == 401
    code, etat = req("/etat")
    assert code == 200 and etat["outils"] > 10

    evenements = []

    def ecouter():
        r = urllib.request.Request(base + "/evenements", headers={"X-MacAI-Jeton": "jeton-test"})
        with urllib.request.urlopen(r, timeout=10) as flux:
            for ligne in flux:
                if ligne.startswith(b"data: "):
                    evenements.append(json.loads(ligne[6:]))
                    if evenements[-1]["type"] == "fin":
                        return
    t = threading.Thread(target=ecouter, daemon=True)
    t.start()
    time.sleep(0.3)
    assert req("/demande", {"texte": "salut"})[0] == 202
    t.join(5)
    assert [e["type"] for e in evenements][0] == "debut"
    assert evenements[-1]["texte"] == "Bonjour !"
    assert req("/demande", {"texte": ""})[0] == 400
    serveur.shutdown()


def test_banc_embeddings_avec_faux_modele():
    from macai import banc
    from .conftest import FauxOllama
    r = banc.banc_embeddings(FauxOllama(), ["faux"])
    assert r[0]["modele"] == "faux" and "rappel_1" in r[0]
