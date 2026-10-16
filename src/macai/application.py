"""Assemblage du moteur : configuration, modèle, outils, services, agent, tâches de fond."""
from __future__ import annotations

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
        self._occupe = threading.Lock()
        self._arret_avant_debut = False   # arrêt demandé entre l'envoi de la demande et son démarrage
        self.ctx = Contexte(config=self.cfg, ollama=self.ollama, registre=self.registre, journal=self.journal,
                            emettre=self.emettre, demander_confirmation=self._demander_confirmation)
        self._services()
        self.orchestrateur = Orchestrateur(self.ctx, CommandesRapides())
        self._indexeur = None
        annulation.definir_fichier(self.cfg.chemin("annulations.json"))
        self.planificateur = planificateur.Planificateur(self.cfg.chemin("taches.json"), self._occupe,
                                                         self.executer_tache, self.journal)
        if avec_fond:
            threading.Thread(target=self._fond, daemon=True, name="taches-de-fond").start()
            self.planificateur.demarrer()

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
        mcp = self.ctx.service("mcp")
        if mcp:
            mcp.fermer()
        if self._indexeur is not None and self._indexeur.poll() is None:
            self._indexeur.terminate()
