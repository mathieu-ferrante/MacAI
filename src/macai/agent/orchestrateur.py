"""Boucle de l'agent : demande → (commande directe | modèle ⇄ outils) → réponse.

Événements émis via `ctx.emettre(type, **données)` pour l'interface :
  debut, routage, outil_debut, annonce, confirmation, outil_fin, texte, proposition_competence, fin, erreur
"""
from __future__ import annotations

import json
import threading
import time

from ..llm.ollama import ErreurOllama
from ..outils.base import Outil, Resultat, Risque
from . import consignes, routeur
from .contexte import Contexte

MOTS_REFLEXION = ("analyse", "compare", "planifie", "organise", "explique pourquoi", "reflechis",
                  "strategie", "plan de", "etape par etape")
HISTORIQUE_MAX = 12  # messages conservés d'une demande à l'autre


class Orchestrateur:
    def __init__(self, ctx: Contexte, rapide=None):
        self.ctx = ctx
        self.rapide = rapide
        self.historique: list[dict] = []
        self.derniere_trace: dict | None = None
        ctx.services["orchestrateur"] = self

    # --- Décisions de sécurité ---------------------------------------------

    def faut_confirmer(self, o: Outil, args: dict) -> bool:
        if o.toujours_confirmer:
            return True
        mode = self.ctx.config.agent.get("autonomie", "equilibre")
        r = o.risque_pour(args)
        if mode == "autonome":
            return False
        if mode == "prudent":
            return r >= Risque.MODIFICATION
        return r >= Risque.SENSIBLE

    def executer_outil(self, nom: str, args: dict) -> Resultat:
        ctx = self.ctx
        o = ctx.registre.get(nom)
        if o is None:
            return Resultat.echec(f"Outil inconnu : {nom}. Utilise uniquement les outils fournis.")
        phrase = o.phrase(args)
        ctx.emettre("outil_debut", outil=nom, arguments=args, phrase=phrase)
        if self.faut_confirmer(o, args):
            ctx.emettre("confirmation", outil=nom, arguments=args, phrase=phrase)
            if not ctx.demander_confirmation(phrase, nom, args):
                ctx.journal.ecrire("refuse", outil=nom, arguments=args)
                r = Resultat.echec("L'utilisateur a refusé cette action. Ne la refais pas.")
                ctx.emettre("outil_fin", outil=nom, ok=False, texte=r.texte)
                return r
        elif o.risque_pour(args) >= Risque.MODIFICATION:
            ctx.emettre("annonce", outil=nom, phrase=phrase)
        debut = time.monotonic()
        r = o.executer(ctx, args)
        ctx.journal.ecrire("outil", outil=nom, arguments=args, ok=r.ok, texte=r.texte[:500],
                           duree=round(time.monotonic() - debut, 2))
        ctx.emettre("outil_fin", outil=nom, ok=r.ok, texte=r.texte[:500], donnees=_serialisable(r.donnees))
        return r

    # --- Traitement d'une demande --------------------------------------------

    def traiter(self, demande: str) -> str:
        ctx = self.ctx
        ctx.arret.clear()
        ctx.emettre("debut", demande=demande)
        ctx.journal.ecrire("demande", texte=demande)
        trace: list[dict] = []
        try:
            texte = self._commande_directe(demande, trace)
            if texte is None:
                texte = self._boucle(demande, trace)
        except InterruptedError:
            texte = "Arrêté."
        except ErreurOllama as e:
            texte = f"Le modèle local ne répond pas : {e}"
            ctx.emettre("erreur", texte=texte)
        self.historique += [{"role": "user", "content": demande}, {"role": "assistant", "content": texte}]
        self.historique = self.historique[-HISTORIQUE_MAX:]
        self._proposer_competence(demande, trace)
        ctx.journal.ecrire("reponse", texte=texte)
        ctx.emettre("fin", texte=texte, actions=trace)
        # Apprentissage hors du verrou de la demande : l'utilisateur peut enchaîner tout de suite.
        threading.Thread(target=self._apprendre, args=(demande,), daemon=True, name="apprentissage").start()
        return texte

    def _apprendre(self, demande: str) -> None:
        """Après la réponse : retient ce que l'utilisateur dit de lui (modèle encore chargé)."""
        from ..memoire.memoire import apprendre
        try:
            apprendre(self.ctx, demande)
        except Exception as e:  # noqa: BLE001 - l'apprentissage ne doit jamais casser une réponse
            self.ctx.journal.ecrire("erreur_apprentissage", texte=str(e))

    def _commande_directe(self, demande: str, trace: list) -> str | None:
        if not self.rapide:
            return None
        plan = self.rapide.reconnaitre(demande, self.ctx.registre)
        if plan is None:
            return None
        self.ctx.emettre("routage", mode="direct")
        textes = []
        for nom, args in plan.actions:
            r = self.executer_outil(nom, args)
            trace.append({"outil": nom, "arguments": args, "ok": r.ok, "direct": True})
            if not r.ok:
                return r.texte
            textes.append(r.texte)
        return plan.reponse.format(*textes) if plan.reponse else (textes[-1] if textes else "C'est fait.")

    def _boucle(self, demande: str, trace: list) -> str:
        ctx = self.ctx
        cfg = ctx.config
        noms = routeur.choisir(demande, ctx.registre, ctx.services.get("mots_routeur"))
        ctx.emettre("routage", mode="agent", outils=noms)
        outils = ctx.registre.schemas(noms)

        memoire = ctx.service("memoire")
        souvenirs = memoire.pertinents(demande) if memoire else []
        messages = [{"role": "system", "content": consignes.construire()}, *self.historique,
                    {"role": "user", "content": f"{demande}\n\n{consignes.contexte(souvenirs, demande=demande)}"}]
        reflexion = any(m in routeur.normaliser(demande) for m in MOTS_REFLEXION) or len(demande.split()) > 40
        modele = cfg.modeles["agent"]
        deja_vus: dict[str, int] = {}

        for _etape in range(int(cfg.agent.get("etapes_max", 10))):
            ctx.verifier_arret()
            if deja_vus and max(deja_vus.values()) > 3:
                break  # le modèle tourne en rond : bilan immédiat
            rep = ctx.ollama.discuter(modele, messages, outils, reflexion=reflexion,
                                      sur_texte=lambda t: ctx.emettre("texte", morceau=t))
            if not rep.appels:
                return rep.texte.strip() or "C'est fait."
            messages.append({"role": "assistant", "content": rep.texte,
                             "tool_calls": [{"function": {"name": a.nom, "arguments": a.arguments}}
                                            for a in rep.appels]})
            for appel in rep.appels:
                ctx.verifier_arret()
                cle = appel.nom + json.dumps(appel.arguments, sort_keys=True, ensure_ascii=False)
                deja_vus[cle] = deja_vus.get(cle, 0) + 1
                if deja_vus[cle] > 2:
                    r = Resultat.echec("Appel identique déjà fait deux fois. Change d'approche ou conclus.")
                else:
                    r = self.executer_outil(appel.nom, appel.arguments)
                trace.append({"outil": appel.nom, "arguments": appel.arguments, "ok": r.ok,
                              "cles": sorted(r.donnees) if isinstance(r.donnees, dict) else []})
                statut = "SUCCÈS" if r.ok else "ÉCHEC"
                messages.append({"role": "tool", "tool_name": appel.nom,
                                 "content": f"{statut}\n{consignes.donnees(r.texte)}"})

        # Trop d'étapes : on demande un bilan honnête, sans outils.
        messages.append({"role": "user", "content": "Arrête-toi ici et dis brièvement ce qui a été fait "
                                                    "et ce qui reste à faire."})
        rep = ctx.ollama.discuter(modele, messages, None, sur_texte=lambda t: ctx.emettre("texte", morceau=t))
        return rep.texte.strip() or "Je n'ai pas réussi à terminer cette demande."

    # --- Compétences ----------------------------------------------------------

    def _proposer_competence(self, demande: str, trace: list) -> None:
        seuil = int(self.ctx.config.agent.get("competence_apres_actions", 3))
        utiles = [t for t in trace if not t.get("direct")]
        if (len(utiles) >= seuil and all(t["ok"] for t in utiles)
                and not any(t["outil"].startswith("competence_") for t in utiles)):
            self.derniere_trace = {"demande": demande, "actions": utiles}
            self.ctx.services["derniere_trace"] = self.derniere_trace
            self.ctx.emettre("proposition_competence", demande=demande, nb_actions=len(utiles))
        elif any(t["outil"] != "creer_competence" for t in trace):
            self.derniere_trace = None
            self.ctx.services["derniere_trace"] = None


def _serialisable(d):
    try:
        json.dumps(d)
        return d
    except (TypeError, ValueError):
        return None
