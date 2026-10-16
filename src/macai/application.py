"""Assemblage du moteur : configuration, modèle, outils, services, agent, tâches de fond."""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid

from . import annulation
from . import config as config_mod
from . import planificateur
from .agent.contexte import Contexte
from .agent.orchestrateur import Orchestrateur
from .agent.rapide import CommandesRapides
from .journal import Journal
from .llm.ollama import Ollama
from .outils.base import charger_tous

DELAI_CONFIRMATION_S = 120
INDEXATION_TOUTES_S = 30 * 60
ECHECS = ("Erreur interne", "Le modèle local ne répond pas", "Arrêté.", "Je n'ai pas réussi",
          "Je n'ai pas pu", "Je ne peux pas")


def _refus_sans_temoin(phrase: str, outil: str, args: dict) -> bool:
    """Tâche planifiée : personne n'est là pour accepter, toute confirmation est refusée."""
    return False


class Application:
    def __init__(self, cfg: config_mod.Config | None = None, ollama=None, avec_fond: bool = True):
        self.cfg = cfg or config_mod.charger()
        m = self.cfg.modeles
        self.ollama = ollama or Ollama(garder=m["garder_en_memoire"], contexte=int(m["contexte"]))
        self.registre = charger_tous()
        self.journal = Journal(self.cfg.chemin("journal.jsonl"))
        self._abonnes: list[queue.Queue] = []
        self._verrou_abonnes = threading.Lock()
        self._confirmations: dict[str, dict] = {}
        self._plans: dict[str, dict] = {}
        self._appliquer_reglages()
        self._occupe = threading.Lock()
        self._arret_avant_debut = False   # arrêt demandé entre l'envoi de la demande et son démarrage
        self.ctx = Contexte(config=self.cfg, ollama=self.ollama, registre=self.registre, journal=self.journal,
                            emettre=self.emettre, demander_confirmation=self._demander_confirmation)
        self.ctx.demander_plan = self._demander_plan
        self._services()
        self.orchestrateur = Orchestrateur(self.ctx, CommandesRapides())
        self._indexeur = None
        annulation.definir_fichier(self.cfg.chemin("annulations.json"))
        self.planificateur = planificateur.Planificateur(self.cfg.chemin("taches.json"), self._occupe,
                                                         self.executer_tache, self.journal)
        self.surveillance = None
        if avec_fond:
            threading.Thread(target=self._fond, daemon=True, name="taches-de-fond").start()
            self.planificateur.demarrer()
            from .surveillance import Surveillance
            self.surveillance = Surveillance(self.cfg, self.emettre, self.ctx)
            self.surveillance.demarrer()

    def _services(self) -> None:
        s, cfg = self.ctx.services, self.cfg
        try:
            from .memoire.memoire import Memoire
            s["memoire"] = Memoire(cfg.donnees)
        except Exception as e:  # noqa: BLE001 - l'assistant reste utilisable sans mémoire
            self.journal.ecrire("erreur_service", service="memoire", texte=str(e))
        try:
            from .recherche.index import Index
            s["index"] = Index(cfg.chemin("index.db"), self.ollama, cfg.modeles["embeddings"])
        except Exception as e:  # noqa: BLE001
            self.journal.ecrire("erreur_service", service="index", texte=str(e))
        from .competences.competences import Bibliotheque
        s["competences"] = Bibliotheque(cfg.chemin("competences"), self.registre)
        if cfg.mcp:
            from .mcp.client import GestionnaireMCP
            g = GestionnaireMCP(cfg.mcp, self.registre, cfg.chemin("mcp_cache.json"))
            # Les outils découverts en fond remplacent le dictionnaire du registre d'un bloc (voir
            # GestionnaireMCP.enregistrer) : l'agent qui le parcourt au même moment n'est pas perturbé.
            g.enregistrer(decouvrir=False)
            s["mcp"] = g
            s["mots_routeur"] = g.mots_routeur
            g.surveiller()
            # Serveurs jamais interrogés : découverte en arrière-plan, sans bloquer le démarrage.
            threading.Thread(target=g.enregistrer, daemon=True, name="mcp-decouverte").start()

    # --- Événements (diffusés à l'interface) -------------------------------------------

    def emettre(self, type_: str, **donnees) -> None:
        evt = {"type": type_, "ts": time.time(), **donnees}
        with self._verrou_abonnes:
            for q in list(self._abonnes):
                try:
                    q.put_nowait(evt)
                except queue.Full:
                    pass

    def abonner(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._verrou_abonnes:
            self._abonnes.append(q)
        return q

    def desabonner(self, q: queue.Queue) -> None:
        with self._verrou_abonnes:
            if q in self._abonnes:
                self._abonnes.remove(q)

    # --- Confirmations -----------------------------------------------------------------

    def _demander_confirmation(self, phrase: str, outil: str, args: dict) -> bool:
        ident = uuid.uuid4().hex[:12]
        attente = {"evenement": threading.Event(), "reponse": False}
        self._confirmations[ident] = attente
        self.emettre("demande_confirmation", id=ident, phrase=phrase, outil=outil, arguments=args)
        repondu = attente["evenement"].wait(DELAI_CONFIRMATION_S)
        self._confirmations.pop(ident, None)
        if not repondu:
            self.emettre("confirmation_expiree", id=ident)
        return repondu and attente["reponse"]

    def repondre_confirmation(self, ident: str, accepter: bool) -> bool:
        attente = self._confirmations.get(ident)
        if attente is None:
            return False
        attente["reponse"] = bool(accepter)
        attente["evenement"].set()
        return True

    # --- Plan proposé avant d'agir ---------------------------------------------------------

    def _demander_plan(self, ident: str, etapes: list) -> tuple[str, str]:
        """Attend la décision de l'utilisateur sur un plan (événement plan_propose déjà émis)."""
        attente = {"evenement": threading.Event(), "decision": ("refuser", "")}
        self._plans[ident] = attente
        repondu = attente["evenement"].wait(DELAI_CONFIRMATION_S)
        self._plans.pop(ident, None)
        return attente["decision"] if repondu else ("refuser", "")

    def repondre_plan(self, ident: str, accepter: bool, correction: str = "") -> bool:
        attente = self._plans.get(ident)
        if attente is None:
            return False
        attente["decision"] = ("corriger", correction.strip()) if correction.strip() else \
            ("accepter" if accepter else "refuser", "")
        attente["evenement"].set()
        return True

    # --- Réglages modifiables depuis le menu (gardés dans reglages.json) -------------------

    def _appliquer_reglages(self) -> None:
        try:
            r = json.loads(self.cfg.chemin("reglages.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(r.get("alertes"), dict):
            self.cfg.alertes.update({k: bool(v) for k, v in r["alertes"].items() if k in self.cfg.alertes})
        if r.get("plan") in ("complexe", "toujours", "jamais"):
            self.cfg.agent["plan"] = r["plan"]
        if r.get("autonomie") in ("prudent", "equilibre", "autonome"):
            self.cfg.agent["autonomie"] = r["autonomie"]
        self.classement_actif = bool(r.get("classement", False))

    def reglages(self) -> dict:
        from . import planificateur as pl
        return {"autonomie": self.cfg.agent.get("autonomie", "equilibre"), "alertes": dict(self.cfg.alertes),
                "plan": self.cfg.agent.get("plan", "complexe"), "briefing": pl.briefing_etat(self),
                "classement": getattr(self, "classement_actif", False)}

    def changer_reglages(self, d: dict) -> dict:
        """Applique et enregistre les réglages reçus (sous-ensemble de reglages())."""
        from . import planificateur as pl
        if isinstance(d.get("alertes"), dict):
            self.cfg.alertes.update({k: bool(v) for k, v in d["alertes"].items() if k in self.cfg.alertes})
        if d.get("plan") in ("complexe", "toujours", "jamais"):
            self.cfg.agent["plan"] = d["plan"]
        if d.get("autonomie") in ("prudent", "equilibre", "autonome"):
            self.cfg.agent["autonomie"] = d["autonomie"]
        if "classement" in d:
            self.classement_actif = bool(d["classement"])
        if isinstance(d.get("briefing"), dict):
            b = d["briefing"]
            pl.regler_briefing(self, bool(b.get("actif")), str(b.get("heure") or "08:00"))
        r = self.reglages()
        fichier = self.cfg.chemin("reglages.json")
        fichier.write_text(json.dumps({k: v for k, v in r.items() if k != "briefing"}, ensure_ascii=False),
                           encoding="utf-8")
        os.chmod(fichier, 0o600)
        return r

    # --- Démonstration (enregistrer une tâche faite à la main) ------------------------------

    def demonstration(self, debut: bool, nom: str = "") -> dict:
        from . import demonstration as demo
        from .outils.base import ErreurOutil
        enregistreur = demo.obtenir(self.ctx)
        try:
            if debut:
                return enregistreur.demarrer()
            r = enregistreur.arreter(nom)
        except ErreurOutil as e:
            return {"ok": False, "texte": str(e), "etapes": []}
        if r.get("competence"):
            # Proposée, jamais enregistrée d'office : l'utilisateur ne veut pas de compétences inutiles.
            self.orchestrateur.proposer_depuis_demonstration(r["competence"], nom)
        return {k: v for k, v in r.items() if k != "competence"}

    # --- Demandes ----------------------------------------------------------------------

    def occupe(self) -> bool:
        return self._occupe.locked()

    def traiter(self, texte: str) -> str:
        with self._occupe:
            return self.orchestrateur.traiter(texte)

    def traiter_en_fond(self, texte: str) -> bool:
        # Verrou pris ici (et non dans le fil) : deux demandes simultanées ne peuvent pas partir toutes les deux.
        if not self._occupe.acquire(blocking=False):
            return False
        self._arret_avant_debut = False
        try:
            threading.Thread(target=self._traiter_verrouille, args=(texte,), daemon=True, name="demande").start()
        except RuntimeError:
            self._occupe.release()
            raise
        return True

    def _traiter_verrouille(self, texte: str) -> str:
        try:
            if self._arret_avant_debut:  # « Stop » cliqué avant le démarrage : l'orchestrateur l'aurait effacé
                self.emettre("fin", texte="Arrêté.", actions=[])
                return "Arrêté."
            return self.orchestrateur.traiter(texte)
        finally:
            self._arret_avant_debut = False
            self._occupe.release()

    def arreter(self) -> None:
        self._arret_avant_debut = True
        self.ctx.arret.set()
        for attente in list(self._confirmations.values()):
            attente["evenement"].set()

    def creer_competence(self) -> str:
        with self._occupe:
            r = self.orchestrateur.executer_outil("creer_competence", {})
            self.emettre("fin", texte=r.texte, actions=[])
            return r.texte

    def annuler(self) -> dict:
        """Annule la dernière action sur les fichiers (bouton « Annuler » de l'interface)."""
        if not self._occupe.acquire(blocking=False):
            return {"ok": False, "texte": "Une demande est en cours : réessaie quand elle sera finie."}
        try:
            r = self.orchestrateur.executer_outil("annuler_derniere_action", {})
            donnees = r.donnees if isinstance(r.donnees, dict) else {}
            ok = r.ok and not (donnees.get("echecs") and not donnees.get("restaures"))
            self.emettre("fin", texte=r.texte, actions=[])
            return {"ok": ok, "texte": r.texte}
        finally:
            self._occupe.release()

    # --- Tâches planifiées ---------------------------------------------------------------

    def taches(self) -> list[dict]:
        fichier = self.cfg.chemin("taches.json")
        return [planificateur.resume(t) for t in planificateur.charger(fichier) if t.get("active", True)]

    def supprimer_tache(self, ident: str) -> bool:
        return planificateur.supprimer(self.cfg.chemin("taches.json"), str(ident))

    def executer_tache(self, tache: dict) -> tuple[bool, str]:
        """Joue une tâche planifiée. Appelée verrou du moteur PRIS (par le planificateur). Personne devant
        l'écran : confirmations refusées d'office, au moins le mode « equilibre », pas de proposition de
        compétence, et la conversation de l'utilisateur n'est pas polluée."""
        ctx, agent = self.ctx, self.cfg.agent
        sauve = (ctx.demander_confirmation, dict(agent), list(self.orchestrateur.historique))
        ctx.demander_confirmation = _refus_sans_temoin
        if agent.get("autonomie") not in ("prudent", "equilibre"):
            agent["autonomie"] = "equilibre"
        agent["competence_apres_actions"] = 10 ** 6
        ctx.services["tache_planifiee"] = tache.get("id") or True
        self._arret_avant_debut = False
        try:
            self.journal.ecrire("tache_planifiee", id=tache.get("id"), demande=tache.get("demande"))
            texte = self.orchestrateur.traiter(tache["demande"]) or ""
            ok = not texte.startswith(ECHECS)
        except Exception as e:  # noqa: BLE001 - une tâche ratée devient une notification, jamais un blocage
            texte, ok = f"Erreur interne ({type(e).__name__}) : {e}", False
        finally:
            ctx.demander_confirmation = sauve[0]
            agent.clear()
            agent.update(sauve[1])
            self.orchestrateur.historique = sauve[2]
            ctx.services.pop("tache_planifiee", None)
        description = tache.get("description") or tache.get("demande", "")
        self.emettre("tache_terminee", description=description, texte=texte[:planificateur.RESULTAT_MAX], ok=ok)
        return ok, texte

    # --- Tâches de fond ------------------------------------------------------------------

    def _fond(self) -> None:
        dernier_index = 0.0
        while True:
            time.sleep(60)
            index = self.ctx.service("index")
            if index is not None:
                index.liberer_si_inactif()
            if time.time() - dernier_index > INDEXATION_TOUTES_S and not self.occupe():
                dernier_index = time.time()
                self._lancer_indexation()
            if getattr(self, "classement_actif", False) and not self.occupe():
                self._classer_telechargements()

    def _classer_telechargements(self) -> None:
        """Range les nouveaux documents des Téléchargements (factures, impôts…) quand c'est sûr ; annulable."""
        try:
            from . import classement
        except ImportError:
            return
        if not self._occupe.acquire(blocking=False):
            return
        try:
            self._deja_vus = getattr(self, "_deja_vus", set())
            for texte in classement.verifier_telechargements(self.ctx, self._deja_vus) or []:
                self.emettre("alerte", titre="Document rangé", texte=texte, type="classement")
        except Exception as e:  # noqa: BLE001 - le fond ne doit jamais s'arrêter
            self.journal.ecrire("erreur_classement", texte=str(e)[:300])
        finally:
            self._occupe.release()

    def _lancer_indexation(self, force: bool = False) -> None:
        from .recherche.indexeur import Indexeur, lancer_en_arriere_plan
        if self._indexeur is not None and self._indexeur.poll() is None:
            return  # déjà en cours
        if not force and self.ctx.service("index") is not None:
            ok, _ = Indexeur(self.cfg, self.ctx.service("index")).conditions_ok()
            if not ok:
                return
        self._indexeur = lancer_en_arriere_plan(force)

    def etat(self) -> dict:
        index = self.ctx.service("index")
        return {
            "pret": True,
            "occupe": self.occupe(),
            "ollama": self.ollama.disponible() if hasattr(self.ollama, "disponible") else True,
            "modele": self.cfg.modeles["agent"],
            "outils": len(self.registre.disponibles()),
            "competences": len(self.ctx.service("competences").competences) if self.ctx.service("competences") else 0,
            "index": index.stats() if index else None,
            "autonomie": self.cfg.agent.get("autonomie"),
        }

    def fermer(self) -> None:
        self.planificateur.arreter()
        if self.surveillance is not None:
            self.surveillance.arreter()
        mcp = self.ctx.service("mcp")
        if mcp:
            mcp.fermer()
        if self._indexeur is not None and self._indexeur.poll() is None:
            self._indexeur.terminate()
