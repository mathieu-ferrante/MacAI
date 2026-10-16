import json
import threading
import urllib.error
import urllib.request

from macai.application import Application
from macai.serveur import creer_gestionnaire

from .conftest import FauxOllama


def _serveur(cfg):
    from http.server import ThreadingHTTPServer
    app = Application(cfg, ollama=FauxOllama(), avec_fond=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), creer_gestionnaire(app, "jeton"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def req(chemin, corps=None):
        r = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{chemin}",
                                   data=json.dumps(corps).encode() if corps is not None else None,
                                   headers={"X-MacAI-Jeton": "jeton", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=5) as rep:
                return rep.status, json.loads(rep.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    return app, srv, req


def test_reglages_plan_et_briefing_par_http(cfg):
    app, srv, req = _serveur(cfg)
    try:
        code, r = req("/reglages")
        assert code == 200 and r["plan"] == "complexe" and r["alertes"]["batterie"] is True
        code, r = req("/reglages", {"alertes": {"batterie": False}, "plan": "jamais", "classement": True,
                                    "briefing": {"actif": True, "heure": "7h30"}})
        assert code == 200 and r["alertes"]["batterie"] is False and r["plan"] == "jamais"
        assert r["classement"] is True and r["briefing"] == {"actif": True, "heure": "07:30"}
        assert any(t["description"] for t in app.taches())
        # Réglages gardés au redémarrage (sauf le briefing, qui est une tâche planifiée).
        app2 = Application(cfg, ollama=FauxOllama(), avec_fond=False)
        assert app2.cfg.agent["plan"] == "jamais" and app2.classement_actif is True
        assert req("/reglages", {"briefing": {"actif": True, "heure": "n'importe quand"}})[0] == 400
        # Plan : la réponse débloque l'attente.
        resultat = {}
        fil = threading.Thread(target=lambda: resultat.update(d=app._demander_plan("p1", ["a", "b", "c"])))
        fil.start()
        while "p1" not in app._plans:
            pass
        assert req("/plan", {"id": "p1", "accepter": False, "correction": "sans l'étape b"})[1]["ok"]
        fil.join(5)
        assert resultat["d"] == ("corriger", "sans l'étape b")
        assert req("/plan", {"id": "inconnu", "accepter": True})[0] == 404
    finally:
        srv.shutdown()


def test_ouvrir_fichier_redirige_les_mails(ctx, monkeypatch):
    from macai.outils import applications, recherche_outils
    vus = []
    monkeypatch.setattr(recherche_outils, "ouvrir_mail", lambda ctx, chemin: vus.append(chemin) or "ouvert")
    assert applications.ouvrir_fichier(ctx, "mail://abc@exemple") == "ouvert" and vus == ["mail://abc@exemple"]
