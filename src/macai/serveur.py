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
import signal
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .application import Application

CORPS_MAX = 1_000_000
# Jamais par le diagnostic, même « en lecture » : exécution de code et recettes à plusieurs étapes.
INTERDITS_DIAGNOSTIC = {"executer_commande"}


def diagnostic_actif(cfg) -> bool:
    """Points d'entrée /diagnostic/* : fermés sauf `[diagnostic] actif = true` dans macai.toml."""
    # Relu à chaque appel : le désactiver dans macai.toml prend effet sans redémarrer le moteur.
    try:
        section = tomllib.loads(cfg.fichier.read_text(encoding="utf-8")).get("diagnostic", {})
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return isinstance(section, dict) and section.get("actif") is True


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

        def _corps(self) -> dict | None:
            """Corps JSON ; None si trop gros (réponse 413 déjà envoyée, connexion fermée)."""
            try:
                n = max(0, int(self.headers.get("Content-Length") or 0))
            except ValueError:
                n = 0
            if n > CORPS_MAX:
                # Corps non lu : la connexion ne peut pas resservir (la requête suivante serait décalée).
                self.close_connection = True
                corps = json.dumps({"erreur": "corps trop gros"}).encode()
                self.send_response(413)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(corps)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(corps)
                return None
            try:
                d = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return {}
            return d if isinstance(d, dict) else {}

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
            if self.path == "/reglages":
                return self._json(200, app.reglages())
            if self.path == "/taches":
                return self._json(200, app.taches() if hasattr(app, "taches") else [])
            if self.path == "/journal":
                return self._json(200, app.journal.derniers(100))
            self._json(404, {"erreur": "inconnu"})

        def do_POST(self):
            if not self._autorise():
                return
            d = self._corps()
            if d is None:
                return
            if self.path.startswith("/diagnostic/"):
                return self._diagnostic(d)
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
                try:
                    ident = int(d.get("id", -1))
                except (TypeError, ValueError):
                    return self._json(400, {"erreur": "id invalide"})
                if m:
                    m.oublier_id(ident)
                return self._json(200, {"ok": True})
            if self.path == "/reglages":
                try:
                    return self._json(200, app.changer_reglages(d))
                except ValueError as e:  # heure de briefing illisible…
                    return self._json(400, {"erreur": str(e)})
            if self.path == "/plan":
                ok = app.repondre_plan(str(d.get("id", "")), bool(d.get("accepter")), str(d.get("correction", "")))
                return self._json(200 if ok else 404, {"ok": ok})
            if self.path in ("/demonstration/debut", "/demonstration/fin"):
                r = app.demonstration(self.path.endswith("debut"), str(d.get("nom", "")))
                return self._json(200, r)
            if self.path == "/indexer":
                app._lancer_indexation(force=True)
                return self._json(202, {"ok": True})
            if self.path in ("/texte", "/image"):
                from . import texte
                from .outils.base import ErreurOutil
                try:
                    if self.path == "/texte":
                        r = texte.demande_texte(app, str(d.get("action", "")), str(d.get("consigne", "")),
                                                str(d.get("sortie", "")))
                    else:
                        r = texte.demande_image(app, str(d.get("chemin", "")), str(d.get("action", "")),
                                                str(d.get("question", "")))
                except ErreurOutil as e:
                    return self._json(409 if str(e) == "occupé" else 400, {"erreur": str(e)})
                return self._json(202, r)
            if self.path == "/annuler":
                if app.occupe():
                    return self._json(409, {"erreur": "occupé"})
                return self._json(200, app.annuler() if hasattr(app, "annuler") else
                                  {"ok": False, "texte": "Annulation indisponible."})
            if self.path == "/taches/supprimer":
                ok = app.supprimer_tache(str(d.get("id", ""))) if hasattr(app, "supprimer_tache") else False
                return self._json(200 if ok else 404, {"ok": ok})
            self._json(404, {"erreur": "inconnu"})

        def _diagnostic(self, d: dict):
            """Essais et diagnostic, avec les autorisations macOS de l'app (le Terminal ne les a pas). Fermé par
            défaut ; jamais pendant une demande ; outils en LECTURE seule, hors commandes et compétences."""
            if not diagnostic_actif(app.cfg):
                return self._json(403, {"erreur": "diagnostic désactivé ([diagnostic] actif = true dans macai.toml)"})
            if self.path not in ("/diagnostic/arbre", "/diagnostic/outil"):
                return self._json(404, {"erreur": "inconnu"})
            if not app._occupe.acquire(blocking=False):
                return self._json(409, {"erreur": "occupé"})
            try:
                if self.path == "/diagnostic/arbre":
                    from .mac import accessibilite
                    try:
                        return self._json(200, accessibilite.inventaire(str(d.get("application", ""))))
                    except Exception as e:  # noqa: BLE001 - diagnostic : on renvoie l'erreur telle quelle
                        return self._json(500, {"erreur": str(e)})
                from .outils.base import Risque
                nom = str(d.get("nom", ""))
                o = app.ctx.registre.get(nom)
                args = d.get("arguments") or {}
                if o is None or not isinstance(args, dict):
                    return self._json(404, {"erreur": "outil inconnu"})
                if nom in INTERDITS_DIAGNOSTIC or nom.startswith("competence_") or o.toujours_confirmer \
                        or o.risque_pour(args) != Risque.LECTURE:
                    return self._json(403, {"erreur": "réservé aux outils en lecture seule"})
                r = o.executer(app.ctx, args)
                return self._json(200, {"ok": r.ok, "texte": r.texte})
            finally:
                app._occupe.release()

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


def surveiller_parent(arreter, intervalle: float = 5.0) -> None:
    """L'app Mac a disparu (plantage, arrêt forcé) : le moteur ne reste pas orphelin."""
    if os.getppid() == 1:  # lancé directement par launchd : pas de parent à surveiller
        return

    def boucle():
        while os.getppid() != 1:
            time.sleep(intervalle)
        arreter()
        time.sleep(5)      # laisse le nettoyage se faire, puis sortie quoi qu'il arrive
        os._exit(0)
    threading.Thread(target=boucle, daemon=True, name="surveillance-parent").start()


def servir(app: Application, port: int = 0) -> None:
    jeton = sec.token_urlsafe(32)
    serveur = ThreadingHTTPServer(("127.0.0.1", port), creer_gestionnaire(app, jeton))
    serveur.daemon_threads = True
    infos = app.cfg.chemin("serveur.json")
    ecrire_infos(infos, serveur.server_address[1], jeton)

    def arreter(*_):
        # shutdown() attend la fin de serve_forever : appelé depuis un autre fil, jamais celui du serveur.
        threading.Thread(target=serveur.shutdown, daemon=True).start()
    try:
        signal.signal(signal.SIGTERM, arreter)
    except ValueError:
        pass  # pas dans le fil principal (tests) : pas de signal
    surveiller_parent(arreter)
    print(f"MacAI prêt sur 127.0.0.1:{serveur.server_address[1]}", flush=True)
    try:
        serveur.serve_forever(poll_interval=1.0)
    finally:
        infos.unlink(missing_ok=True)
        app.fermer()
        serveur.server_close()
