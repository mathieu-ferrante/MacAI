"""Serveur local (stdlib) entre l'app Mac et le moteur : HTTP + flux d'événements (SSE).

Écoute uniquement sur 127.0.0.1, port choisi par le système, jeton aléatoire exigé à chaque requête.
Port et jeton sont écrits dans serveur.json (droits 0600) que l'app relit.
"""
from __future__ import annotations

import hmac
import json
import os
import queue
import secrets as sec
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .application import Application


def creer_gestionnaire(app: Application, jeton: str):
    class Gestionnaire(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silencieux
            pass

        # --- utilitaires -----------------------------------------------------------
        def _autorise(self) -> bool:
            recu = self.headers.get("X-MacAI-Jeton", "")
            if hmac.compare_digest(recu, jeton):
                return True
            self._json(401, {"erreur": "jeton invalide"})
            return False

        def _json(self, code: int, donnees) -> None:
            corps = json.dumps(donnees, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def _corps(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return {}

        # --- routes ------------------------------------------------------------------
        def do_GET(self):
            if not self._autorise():
                return
            if self.path == "/etat":
                return self._json(200, app.etat())
            if self.path == "/evenements":
                return self._flux()
            if self.path == "/souvenirs":
                m = app.ctx.service("memoire")
                return self._json(200, [{"id": f.id, "texte": f.texte, "source": f.source, "cree_le": f.cree_le}
                                        for f in (m.tous() if m else [])])
            if self.path == "/competences":
                b = app.ctx.service("competences")
                return self._json(200, [{"nom": c.nom, "description": c.description, "parametres": c.parametres,
                                         "utilisations": c.utilisations} for c in (b.competences.values() if b else [])])
            if self.path == "/journal":
                return self._json(200, app.journal.derniers(100))
            self._json(404, {"erreur": "inconnu"})

        def do_POST(self):
            if not self._autorise():
                return
            d = self._corps()
            if self.path == "/demande":
                texte = str(d.get("texte", "")).strip()
                if not texte:
                    return self._json(400, {"erreur": "texte vide"})
                if not app.traiter_en_fond(texte):
                    return self._json(409, {"erreur": "occupé"})
                return self._json(202, {"ok": True})
            if self.path == "/confirmation":
                ok = app.repondre_confirmation(str(d.get("id", "")), bool(d.get("accepter")))
                return self._json(200 if ok else 404, {"ok": ok})
            if self.path == "/arret":
                app.arreter()
                return self._json(200, {"ok": True})
            if self.path == "/competence":
                threading.Thread(target=app.creer_competence, daemon=True).start()
                return self._json(202, {"ok": True})
            if self.path == "/oublier":
                m = app.ctx.service("memoire")
                if m:
                    m.oublier_id(int(d.get("id", -1)))
                return self._json(200, {"ok": True})
            if self.path == "/reglages":
                if d.get("autonomie") in ("prudent", "equilibre", "autonome"):
                    app.cfg.agent["autonomie"] = d["autonomie"]
                return self._json(200, app.etat())
            if self.path == "/indexer":
                app._lancer_indexation(force=True)
                return self._json(202, {"ok": True})
            if self.path == "/diagnostic/arbre":
                from .mac import accessibilite
                try:
                    return self._json(200, accessibilite.inventaire(str(d.get("application", ""))))
                except Exception as e:  # noqa: BLE001 - diagnostic : on renvoie l'erreur telle quelle
                    return self._json(500, {"erreur": str(e)})
            if self.path == "/diagnostic/outil":
                # Essais et diagnostic : exécute un outil en LECTURE seule, avec les autorisations macOS de l'app
                # (le Terminal ne les a pas). Tout outil qui agit passe par /demande et ses confirmations.
                from .outils.base import Risque
                o = app.ctx.registre.get(str(d.get("nom", "")))
                args = d.get("arguments") or {}
                if o is None or not isinstance(args, dict):
                    return self._json(404, {"erreur": "outil inconnu"})
                if o.toujours_confirmer or o.risque_pour(args) != Risque.LECTURE:
                    return self._json(403, {"erreur": "réservé aux outils en lecture seule"})
                r = o.executer(app.ctx, args)
                return self._json(200, {"ok": r.ok, "texte": r.texte})
            self._json(404, {"erreur": "inconnu"})

        def _flux(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = app.abonner()
            try:
                self.wfile.write(b": connecte\n\n")
                self.wfile.flush()
                while True:
                    try:
                        evt = q.get(timeout=15)
                        ligne = "data: " + json.dumps(evt, ensure_ascii=False, default=str) + "\n\n"
                        self.wfile.write(ligne.encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                app.desabonner(q)

    return Gestionnaire


def ecrire_infos(fichier: Path, port: int, jeton: str) -> None:
    fichier.parent.mkdir(parents=True, exist_ok=True)
    tmp = fichier.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"port": port, "jeton": jeton, "pid": os.getpid()}, f)
    os.replace(tmp, fichier)


def servir(app: Application, port: int = 0) -> None:
    jeton = sec.token_urlsafe(32)
    serveur = ThreadingHTTPServer(("127.0.0.1", port), creer_gestionnaire(app, jeton))
    serveur.daemon_threads = True
    infos = app.cfg.chemin("serveur.json")
    ecrire_infos(infos, serveur.server_address[1], jeton)
    print(f"MacAI prêt sur 127.0.0.1:{serveur.server_address[1]}", flush=True)
    try:
        serveur.serve_forever(poll_interval=1.0)
    finally:
        infos.unlink(missing_ok=True)
        app.fermer()
