"""Boucle de l'agent : demande → (commande directe | modèle ⇄ outils) → réponse.

Événements émis via `ctx.emettre(type, **données)` pour l'interface :
  debut, routage, plan_propose, outil_debut, annonce, confirmation, outil_fin, texte, proposition_competence,
  fin, erreur

Mode plan (« montre-moi avant de faire », réglage agent.plan) : pour une demande en plusieurs étapes, le modèle
propose d'abord un plan numéroté (événement plan_propose) ; l'utilisateur l'accepte, le refuse ou le corrige via
`ctx.demander_plan(id, etapes) -> (decision, correction)`. Sans ce point d'accroche (CLI, banc, tests), pas de
plan : on agit directement (le plan serait accepté d'office, inutile de payer un appel au modèle).
"""
from __future__ import annotations

import inspect
import json
import re
import sys
import threading
import time
import uuid

from ..llm.ollama import ErreurOllama
from ..outils.base import Outil, Resultat, Risque
from . import consignes, routeur
from .contexte import Contexte

MOTS_REFLEXION = ("analyse", "compare", "planifie", "organise", "explique pourquoi", "reflechis",
                  "strategie", "plan de", "etape par etape")
HISTORIQUE_MAX = 12  # messages conservés d'une demande à l'autre
HISTORIQUE_CAR = 400  # chaque message gardé est raccourci : l'historique ne mange pas le contexte

# Outils qui ne font que regarder : jamais refusés (relire après une action est normal), mais la même
# observation répétée OBSERVATIONS_MAX fois sans aucune action entre deux = le modèle tourne en rond.
OBSERVATION = {"lire_fenetre", "lire_page", "voir_ecran", "attendre", "applications_ouvertes", "lister_menus",
               "etat_index"}
OBSERVATIONS_MAX = 6
LIMITE_DONNEES = {"lire_fenetre": 6000, "lire_page": 6000}  # listes d'éléments numérotés : plus de place
REFUS = "L'utilisateur a refusé cette action. Ne la refais pas."

# Budget de contexte (num_ctx 8192) : jetons estimés à 3,2 caractères, place gardée pour la réponse.
CAR_PAR_JETON = 3.2
RESERVE_REPONSE = 1800
OUTIL_EXPLOITE_CAR = 600  # résultat d'outil ancien, déjà exploité par le modèle

# Réponse qui annonce une suite au lieu de la faire (« je vais envoyer », « il me reste à valider »).
INACHEVE = re.compile(r"\b(je vais|il me reste a|je dois (encore|maintenant)|"
                      r"il reste a (valider|envoyer|cliquer|saisir|appuyer|taper))\b")
ACTION_AFFIRMEE = re.compile(r"\bj['’]ai\b")
# Demande d'explication, pas d'action : « comment faire… », « pourquoi… », « explique… », « c'est quoi… ».
SAVOIR = re.compile(r"^(comment (on |faire|faut|puis|je peux|est-ce|ca marche|fonctionne)|comment\b(?!.*\b(ouvre|lance|"
                    r"cree|mets|fais|range|envoie)\b)|pourquoi\b|explique|c'est quoi|qu'est-ce que c'est|a quoi sert|"
                    r"quelle est la difference|quel est l'interet)")
QUESTION = re.compile(r"^(comment|pourquoi|est-ce que|qu'est-ce|quels?|quelles?|quand|ou)\b")

# Mode plan
PLAN_ETAPES_MAX = 6
PLAN_ETAPES_MIN = 3     # en dessous, rien à valider : on agit directement
# Demande qui AGIT (pas une simple lecture ou question) : un verbe d'action quelque part.
PLAN_ACTION = re.compile(r"\b(envoi|envoy|ouvr|cree|crée|deplac|range|rang|renomm|ecri|ajout|supprim|mets|met |"
                         r"copi|clique|lance|ferm|telecharg|prepar|repond|planifi|programm|organis|rempli|"
                         r"enregistr|install|activ|desactiv|regl|change|modifi|effac|vide|archiv|tri|class|partag|"
                         r"imprim|convert|export|compress|deplace|colle|tape|saisi|inscri|reserv|commande|note )")
PLAN_MOTS_MAX = 12      # au-delà : demande jugée en plusieurs étapes
PLAN_LIAISONS = re.compile(r"( et | puis |, |\bensuite\b|\bapres ca\b|\bpour finir\b)")
PLAN_REFUS = "D'accord, je ne fais rien."
CONSIGNE_PLAN = ("Tu prépares une tâche sur le Mac de l'utilisateur, sans rien faire pour l'instant. Écris "
                 "uniquement un plan numéroté de 1 à {n} étapes concrètes et courtes, en français (une action par "
                 "ligne : « 1. Ouvrir Mail », « 2. … »). Pas d'introduction, pas de conclusion.")
ETAPE_PLAN = re.compile(r"^\s*(?:\d+\s*[.)\-:]|[-*•])\s*(.+?)\s*$")

# Propositions de compétence : seulement pour ce qui se répète vraiment.
TRACES_MAX = 30
TRACES_RECENTES_S = 30 * 24 * 3600
MOTS_VIDES = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "a", "au", "aux", "en", "mon", "ma", "mes",
              "pour", "dans", "sur", "avec", "moi", "fais", "fait", "peux", "tu", "je", "me", "m", "l", "d", "ce",
              "cet", "cette", "ces", "puis", "ensuite", "stp", "merci", "s'il", "te", "plait", "plais", "qui",
              "que", "est", "son", "sa", "ses", "ton", "ta", "tes", "y", "il", "elle", "par"}


class Orchestrateur:
    def __init__(self, ctx: Contexte, rapide=None):
        self.ctx = ctx
        self.rapide = rapide
        self.historique: list[dict] = []
        self.derniere_trace: dict | None = None
        self.plan_valide = False  # plan accepté pour la demande en cours : plus que les confirmations sensibles
        ctx.services["orchestrateur"] = self

    # --- Décisions de sécurité ---------------------------------------------

    def faut_confirmer(self, o: Outil, args: dict, risque: Risque | None = None) -> bool:
        if o.toujours_confirmer:
            return True
        mode = self.ctx.config.agent.get("autonomie", "equilibre")
        if self.plan_valide and mode == "prudent":
            mode = "equilibre"  # l'utilisateur a validé le plan : on ne redemande que ce qui est sensible
        r = _risque(o, args) if risque is None else risque
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
        # Arguments corrigés UNE fois : le risque, la phrase, la confirmation et l'exécution portent sur les
        # mêmes valeurs (jamais un risque calculé sur des arguments bruts différents de ce qui tourne).
        brut = args
        args, erreur = preparer(o, args)
        phrase = o.phrase(args)
        ctx.emettre("outil_debut", outil=nom, arguments=args, phrase=phrase)
        if erreur:
            r = Resultat.echec(erreur)
            ctx.journal.ecrire("outil", outil=nom, arguments=_abreger(brut), ok=False, texte=erreur[:500], duree=0)
            ctx.emettre("outil_fin", outil=nom, ok=False, texte=r.texte)
            return r
        risque = _risque(o, args)
        if self.faut_confirmer(o, args, risque):
            ctx.emettre("confirmation", outil=nom, arguments=args, phrase=phrase)
            if not ctx.demander_confirmation(phrase, nom, args):
                ctx.journal.ecrire("refuse", outil=nom, arguments=_abreger(args))
                r = Resultat.echec(REFUS)
                ctx.emettre("outil_fin", outil=nom, ok=False, texte=r.texte)
                return r
        elif risque >= Risque.MODIFICATION:
            ctx.emettre("annonce", outil=nom, phrase=phrase)
        debut = time.monotonic()
        r = o.executer(ctx, args)
        ctx.journal.ecrire("outil", outil=nom, arguments=_abreger(args), ok=r.ok, texte=r.texte[:500],
                           duree=round(time.monotonic() - debut, 2))
        ctx.emettre("outil_fin", outil=nom, ok=r.ok, texte=r.texte[:500], donnees=_serialisable(r.donnees))
        return r

    # --- Traitement d'une demande --------------------------------------------

    def traiter(self, demande: str) -> str:
        ctx = self.ctx
        trace: list[dict] = []
        texte = ""
        try:  # quoi qu'il arrive, « fin » est émis : l'interface ne reste jamais « occupée »
            ctx.arret.clear()
            ctx.services["demande"] = demande  # certains garde-fous dépendent de ce que l'utilisateur a demandé
            self._oublier_fenetre()
            ctx.emettre("debut", demande=demande)
            ctx.journal.ecrire("demande", texte=demande)
            try:
                texte = self._commande_directe(demande, trace)
                if texte is None:
                    plan = self._plan(demande)
                    self.plan_valide = bool(plan)
                    texte = PLAN_REFUS if plan is False else self._boucle(demande, trace, plan or None)
            except InterruptedError:
                texte = "Arrêté."
            except ErreurOllama as e:
                texte = f"Le modèle local ne répond pas : {e}"
                ctx.emettre("erreur", texte=texte)
            except Exception as e:  # noqa: BLE001 - une erreur imprévue devient une réponse, jamais un blocage
                texte = f"Erreur interne ({type(e).__name__}) : {e}"
                ctx.emettre("erreur", texte=texte)
            self.historique += [{"role": "user", "content": _couper(demande, HISTORIQUE_CAR)},
                                {"role": "assistant", "content": _couper(texte, HISTORIQUE_CAR)}]
            self.historique = self.historique[-HISTORIQUE_MAX:]
            self._proposer_competence(demande, trace)
            ctx.journal.ecrire("reponse", texte=texte)
        except Exception as e:  # noqa: BLE001 - même une erreur de journal ne doit pas bloquer l'interface
            texte = texte or f"Erreur interne ({type(e).__name__}) : {e}"
            ctx.emettre("erreur", texte=f"Erreur interne ({type(e).__name__}) : {e}")
        finally:
            self.plan_valide = False
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

    def _oublier_fenetre(self) -> None:
        """Les numéros d'éléments lus pendant une demande précédente ne valent plus : on ne peut pas cliquer
        sur un « 12 » périmé."""
        for cle in ("ax_elements", "ax_application", "ax_pid"):
            self.ctx.services.pop(cle, None)
        fenetres = sys.modules.get("macai.outils.fenetres")  # seulement s'il est déjà chargé (pas d'import)
        derniere = getattr(fenetres, "_DERNIERE", None)
        if isinstance(derniere, dict):
            derniere.update(app="", pid=0, elements=[])

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
                # Refus de l'utilisateur : on s'arrête. Autre échec (nom d'appli mal compris…) : l'agent reprend.
                return r.texte if r.texte == REFUS else None
            textes.append(r.texte)
        return plan.reponse.format(*textes) if plan.reponse else (textes[-1] if textes else "C'est fait.")

    # --- Mode plan ------------------------------------------------------------------

    def plan_voulu(self, demande: str) -> bool:
        """Faut-il montrer un plan avant d'agir ? Jamais pour une tâche planifiée (personne devant l'écran), ni
        sans interface pour répondre, ni pour une question."""
        ctx = self.ctx
        mode = str(ctx.config.agent.get("plan", "complexe")).lower()
        if mode == "jamais" or ctx.services.get("tache_planifiee") or getattr(ctx, "demander_plan", None) is None:
            return False
        t = routeur.normaliser(demande).strip()
        if not _imperatif(demande) or SAVOIR.search(t) or not PLAN_ACTION.search(t + " "):
            return False  # question ou simple lecture : pas de plan
        return mode == "toujours" or demande_complexe(demande)

    def _plan(self, demande: str) -> list[str] | bool | None:
        """None : pas de plan (on agit directement). False : refusé. Liste : plan validé à suivre."""
        if not self.plan_voulu(demande):
            return None
        ctx = self.ctx
        etapes = self._proposer_plan(demande)
        if len(etapes) < PLAN_ETAPES_MIN:
            return None  # plan court : rien à valider, on agit
        for essai in range(2):
            ctx.verifier_arret()
            ident = uuid.uuid4().hex[:12]
            ctx.emettre("plan_propose", id=ident, demande=demande, etapes=etapes)
            ctx.journal.ecrire("plan_propose", id=ident, etapes=etapes)
            try:
                decision, correction = ctx.demander_plan(ident, etapes)
            except Exception:  # noqa: BLE001 - interface en défaut : on ne fait rien plutôt que d'agir à l'aveugle
                decision, correction = "refuser", ""
            decision = str(decision or "").lower()
            ctx.journal.ecrire("plan_decision", id=ident, decision=decision, correction=str(correction or "")[:300])
            ctx.verifier_arret()
            if decision.startswith("accept"):
                return etapes
            if decision.startswith("corrig") and str(correction or "").strip():
                if essai == 0:
                    nouvelles = self._proposer_plan(demande, etapes, str(correction).strip())
                    etapes = nouvelles or etapes
                    continue
                # Seconde correction : on suit le dernier plan en tenant compte de la remarque.
                return etapes + [f"(Remarque de l'utilisateur : {str(correction).strip()})"]
            return False
        return False

    def _proposer_plan(self, demande: str, precedent: list[str] | None = None, correction: str = "") -> list[str]:
        ctx = self.ctx
        contenu = demande
        if precedent:
            contenu += ("\n\nPlan précédent :\n" + "\n".join(f"{i}. {e}" for i, e in enumerate(precedent, 1))
                        + f"\n\nCorrection demandée par l'utilisateur : {correction}\nRefais le plan en en tenant compte.")
        messages = [{"role": "system", "content": CONSIGNE_PLAN.format(n=PLAN_ETAPES_MAX)},
                    {"role": "user", "content": contenu}]
        rep = ctx.ollama.discuter(ctx.config.modeles["agent"], messages, None, reflexion=False,
                                  options={"num_predict": 300, "temperature": 0})
        return lire_plan(rep.texte)

    def _boucle(self, demande: str, trace: list, plan: list[str] | None = None) -> str:
        ctx = self.ctx
        cfg = ctx.config
        noms = routeur.choisir(demande, ctx.registre, ctx.services.get("mots_routeur"))
        if SAVOIR.search(routeur.normaliser(demande).strip()):
            # « Comment envoyer un mail ? » : on explique, on n'agit pas (vu en essai : brouillons préparés et
            # mails lus pour une simple question). Seuls les outils de lecture restent.
            noms = [n for n in noms if (o := ctx.registre.get(n)) is not None and not o.toujours_confirmer
                    and _risque_fixe(o) == Risque.LECTURE and o.groupe not in ("organisation",)]
        ctx.emettre("routage", mode="agent", outils=noms)
        outils = ctx.registre.schemas(noms)

        memoire = ctx.service("memoire")
        souvenirs = memoire.pertinents(demande) if memoire else []
        valide = ""
        if plan:
            valide = ("\n\nPlan validé par l'utilisateur :\n" + "\n".join(f"{i}. {e}" for i, e in enumerate(plan, 1))
                      + "\nSuis-le.")
        messages = [{"role": "system", "content": consignes.construire()}, *self.historique,
                    {"role": "user", "content": f"{demande}{valide}\n\n{consignes.contexte(souvenirs, demande=demande)}"}]
        reflexion = any(m in routeur.normaliser(demande) for m in MOTS_REFLEXION) or len(demande.split()) > 40
        imperatif = _imperatif(demande)
        modele = cfg.modeles["agent"]
        nb_hist = len(self.historique)
        version = 0                    # augmente à chaque action réussie qui change l'état
        deja_vus: dict[str, int] = {}  # appel identique dans le même état
        observations: dict[str, int] = {}  # même observation sans action entre deux
        appels_faits = 0
        relance = vide_relance = False

        for _etape in range(int(cfg.agent.get("etapes_max", 10))):
            ctx.verifier_arret()
            if ((deja_vus and max(deja_vus.values()) > 3)
                    or (observations and max(observations.values()) >= OBSERVATIONS_MAX)):
                break  # le modèle tourne en rond : bilan immédiat
            nb_hist = self._tailler(messages, nb_hist, outils)
            rep = ctx.ollama.discuter(modele, messages, outils, reflexion=reflexion,
                                      sur_texte=lambda t: ctx.emettre("texte", morceau=t))
            if not rep.appels:
                texte = rep.texte.strip()
                if not texte:
                    # Réponse vide (souvent tout parti en réflexion) : une seconde chance, sans réflexion.
                    if not vide_relance:
                        vide_relance, reflexion = True, False
                        continue
                    return "C'est fait." if _action_reussie(trace) else "Je n'ai pas pu produire de réponse."
                # Un petit modèle s'arrête souvent en décrivant ce qu'il reste à faire : on le relance une fois.
                norme = routeur.normaliser(texte)
                if (not relance and imperatif and INACHEVE.search(norme)
                        and (appels_faits or ACTION_AFFIRMEE.search(norme))):
                    relance = True
                    messages += [{"role": "assistant", "content": rep.texte},
                                 {"role": "user", "content": "Fais-le maintenant avec les outils, jusqu'au bout "
                                                             "(par exemple appuyer sur Entrée pour envoyer)."}]
                    continue
                # Garde-fou d'honnêteté : « J'ai ouvert TextEdit et écrit… » alors qu'aucun outil n'a réussi
                # (vu en essai réel). On ne laisse pas passer une action inventée.
                if ACTION_AFFIRMEE.search(norme) and not any(t["ok"] for t in trace):
                    echecs = [t["outil"] for t in trace if not t["ok"]]
                    return ("Je n'ai pas réussi à le faire" + (f" ({', '.join(dict.fromkeys(echecs))} a échoué)"
                                                              if echecs else "") + ". Reformule ou précise la demande.")
                return texte
            messages.append({"role": "assistant", "content": rep.texte,
                             "tool_calls": [{"function": {"name": a.nom, "arguments": a.arguments}}
                                            for a in rep.appels]})
            for appel in rep.appels:
                ctx.verifier_arret()
                appels_faits += 1
                cle = appel.nom + json.dumps(appel.arguments, sort_keys=True, ensure_ascii=False, default=str)
                if appel.nom in OBSERVATION:
                    observations[cle] = observations.get(cle, 0) + 1
                    r = self.executer_outil(appel.nom, appel.arguments)
                else:
                    cle = f"{version}|{cle}"
                    deja_vus[cle] = deja_vus.get(cle, 0) + 1
                    if deja_vus[cle] > 2:
                        r = Resultat.echec("Appel identique déjà fait deux fois. Change d'approche ou conclus.")
                        ctx.emettre("outil_debut", outil=appel.nom, arguments=appel.arguments, phrase=appel.nom)
                        ctx.emettre("outil_fin", outil=appel.nom, ok=False, texte=r.texte)
                    else:
                        r = self.executer_outil(appel.nom, appel.arguments)
                        observations.clear()  # une action a eu lieu : relire redevient normal
                        if r.ok and self._modifie(appel.nom, appel.arguments):
                            version += 1  # l'état a changé : refaire un appel déjà vu redevient légitime
                trace.append({"outil": appel.nom, "arguments": appel.arguments, "ok": r.ok,
                              "cles": sorted(r.donnees) if isinstance(r.donnees, dict) else []})
                if not r.ok and "AUTORISATION MANQUANTE" in r.texte:
                    # Rien à tenter de plus : c'est à l'utilisateur d'accorder l'autorisation (vu en essai : le modèle
                    # ouvrait les Réglages en boucle, ou conseillait de désactiver l'autorisation).
                    return ("Je ne peux pas le faire pour l'instant : " +
                            r.texte.split(":", 1)[1].strip() + " Ensuite, redemande-moi.")
                statut = "SUCCÈS" if r.ok else "ÉCHEC"
                limite = LIMITE_DONNEES.get(appel.nom, 4000)
                messages.append({"role": "tool", "tool_name": appel.nom,
                                 "content": f"{statut}\n{consignes.donnees(r.texte, limite=limite)}"})

        # Trop d'étapes : on demande un bilan honnête, sans outils.
        messages.append({"role": "user", "content": "Arrête-toi ici et dis brièvement ce qui a été fait "
                                                    "et ce qui reste à faire."})
        self._tailler(messages, nb_hist, None)
        rep = ctx.ollama.discuter(modele, messages, None, sur_texte=lambda t: ctx.emettre("texte", morceau=t))
        return rep.texte.strip() or "Je n'ai pas réussi à terminer cette demande."

    def _modifie(self, nom: str, args: dict) -> bool:
        o = self.ctx.registre.get(nom)
        return o is not None and _risque(o, preparer(o, args)[0]) >= Risque.MODIFICATION

    # --- Budget de contexte -----------------------------------------------------

    def _tailler(self, messages: list[dict], nb_hist: int, outils: list | None) -> int:
        """Fait tenir la conversation dans le contexte du modèle (num_ctx). Dans l'ordre : résultats d'outils
        déjà exploités raccourcis (les plus anciens d'abord), puis historique ancien retiré, puis tout résultat
        d'outil raccourci. Jamais les consignes ni la demande en cours. Renvoie le nombre de messages
        d'historique restants (ils suivent les consignes, en tête de liste)."""
        contexte = getattr(self.ctx.ollama, "contexte", 0) or 8192
        budget = contexte - RESERVE_REPONSE - _jetons(json.dumps(outils or [], ensure_ascii=False))

        def trop() -> bool:
            return sum(_jetons_message(m) for m in messages) > budget

        if not trop():
            return nb_hist
        dernier_assistant = max((i for i, m in enumerate(messages) if m["role"] == "assistant"), default=-1)
        for i, m in enumerate(messages):
            if m["role"] == "tool" and i < dernier_assistant:
                m["content"] = _raccourcir(m["content"], OUTIL_EXPLOITE_CAR)
                if not trop():
                    return nb_hist
        while nb_hist > 0 and trop():  # échanges précédents, par paires, les plus anciens d'abord
            n = min(2, nb_hist)
            del messages[1:1 + n]
            nb_hist -= n
        for m in messages:
            if not trop():
                break
            if m["role"] == "tool":
                m["content"] = _raccourcir(m["content"], OUTIL_EXPLOITE_CAR)
        return nb_hist

    # --- Compétences ----------------------------------------------------------

    def _proposer_competence(self, demande: str, trace: list) -> None:
        """Garde la dernière tâche réussie (pour « crée une compétence ») mais ne PROPOSE une compétence que si elle
        vaut la peine : même genre de tâche réussi au moins deux fois récemment, au moins N actions (hors simples
        observations), et aucune compétence existante qui fait déjà la même suite d'outils."""
        ctx = self.ctx
        seuil = int(ctx.config.agent.get("competence_apres_actions", 3))
        utiles = [t for t in trace if not t.get("direct")]
        reussie = (utiles and all(t["ok"] for t in utiles)
                   and not any(t["outil"].startswith("competence_") or t["outil"] == "creer_competence"
                               for t in utiles))
        actions = [t for t in utiles if t["outil"] not in OBSERVATION]
        if reussie and len(utiles) >= seuil:
            self.derniere_trace = {"demande": demande, "actions": utiles}
            ctx.services["derniere_trace"] = self.derniere_trace
        elif any(t["outil"] != "creer_competence" for t in trace):
            self.derniere_trace = None
            ctx.services["derniere_trace"] = None
        if not reussie or not actions or ctx.services.get("tache_planifiee"):
            return
        signature = signature_trace(demande, utiles)
        fois = 1 + sum(1 for t in self._traces_reussies() if traces_similaires(signature, t))
        self._retenir_trace(demande, signature)
        if len(actions) < seuil or fois < 2 or self._competence_similaire(signature["outils"]):
            return
        ctx.emettre("proposition_competence", demande=demande, nb_actions=len(utiles),
                    raison=f"Tu as fait cette tâche {fois} fois")

    def proposer_depuis_demonstration(self, etapes, demande: str = "") -> bool:
        """Fin d'une démonstration (« regarde comment je fais ») : propose d'en faire une compétence.
        `etapes` : [{"outil": nom, "arguments": {...}}, …] (comme une trace de l'agent), ou directement la recette
        de demonstration.recette() ({"etapes": [...], "description": ...}). Les phrases (str) sont ignorées.
        Renvoie True si proposé."""
        if isinstance(etapes, dict):
            demande = demande or str(etapes.get("description") or "")
            etapes = etapes.get("etapes") or []
        actions = [{"outil": str(e["outil"]), "arguments": dict(e.get("arguments") or {}), "ok": True,
                    "cles": list(e.get("cles") or [])}
                   for e in etapes or [] if isinstance(e, dict) and e.get("outil")]
        if not actions:
            return False
        demande = demande or "tâche montrée par l'utilisateur"
        self.derniere_trace = {"demande": demande, "actions": actions}
        self.ctx.services["derniere_trace"] = self.derniere_trace
        if self._competence_similaire(signature_trace(demande, actions)["outils"]):
            return False
        self.ctx.emettre("proposition_competence", demande=demande, nb_actions=len(actions),
                         raison="Tu viens de me montrer comment faire")
        return True

    def _fichier_traces(self):
        return self.ctx.config.chemin("traces_reussies.json")

    def _traces_reussies(self) -> list[dict]:
        try:
            d = json.loads(self._fichier_traces().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        limite = time.time() - TRACES_RECENTES_S
        return [t for t in d if isinstance(t, dict) and t.get("quand", 0) >= limite] if isinstance(d, list) else []

    def _retenir_trace(self, demande: str, signature: dict) -> None:
        traces = self._traces_reussies() + [{**signature, "demande": _couper(demande, 200), "quand": time.time()}]
        try:
            f = self._fichier_traces()
            f.parent.mkdir(parents=True, exist_ok=True)
            temp = f.with_name(f.name + ".tmp")
            temp.write_text(json.dumps(traces[-TRACES_MAX:], ensure_ascii=False), encoding="utf-8")
            temp.replace(f)
        except OSError:
            pass

    def _competence_similaire(self, outils: list[str]) -> bool:
        biblio = self.ctx.service("competences")
        for c in (getattr(biblio, "competences", None) or {}).values():
            etapes = [e.get("outil", "") for e in getattr(c, "etapes", []) if isinstance(e, dict)]
            if suite_outils(etapes) == outils:
                return True
        return False


def demande_complexe(demande: str) -> bool:
    """Plusieurs étapes probables : liaison (« et », « puis », virgule, « ensuite »…) ou plus de 12 mots."""
    t = " " + routeur.normaliser(demande).strip() + " "
    return bool(PLAN_LIAISONS.search(t)) or len(demande.split()) > PLAN_MOTS_MAX


def lire_plan(texte: str) -> list[str]:
    """Étapes d'un plan numéroté (au plus 6) ; lignes sans numéro ignorées dès qu'il y a une liste."""
    texte = re.sub(r"<think>.*?</think>", "", texte or "", flags=re.S)
    etapes = []
    for ligne in texte.splitlines():
        m = ETAPE_PLAN.match(ligne)
        if m and (e := m.group(1).strip(" *_`")):
            etapes.append(e[:200])
    return etapes[:PLAN_ETAPES_MAX]


def suite_outils(noms: list[str]) -> list[str]:
    """Suite des outils qui agissent (observations retirées, répétitions consécutives fusionnées)."""
    sortie: list[str] = []
    for n in noms:
        if n not in OBSERVATION and (not sortie or sortie[-1] != n):
            sortie.append(n)
    return sortie


def mots_demande(demande: str) -> list[str]:
    mots = re.findall(r"[a-z0-9']+", routeur.normaliser(demande))
    return sorted({m for m in mots if m not in MOTS_VIDES and len(m) > 2 and not m.isdigit()})


def signature_trace(demande: str, actions: list[dict]) -> dict:
    return {"outils": suite_outils([a["outil"] for a in actions]), "mots": mots_demande(demande)}


def traces_similaires(a: dict, b: dict) -> bool:
    """Même genre de tâche : même suite d'outils, et des mots de la demande en commun."""
    if not a.get("outils") or a.get("outils") != b.get("outils"):
        return False
    ma, mb = set(a.get("mots") or []), set(b.get("mots") or [])
    if not ma or not mb:
        return True
    commun = ma & mb
    return len(commun) >= 2 or len(commun) / len(ma | mb) >= 0.25


def preparer(o: Outil, args) -> tuple[dict, str]:
    """Arguments tels qu'ils seront exécutés (inventés écartés, types corrigés) et erreur éventuelle."""
    if not isinstance(args, dict):
        args = {}
    if hasattr(o, "preparer"):
        return o.preparer(args)
    try:
        signature = inspect.signature(o.fonction)
        tout = any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values())
        args = {k: v for k, v in args.items() if tout or k in signature.parameters}
    except (TypeError, ValueError):
        pass
    propres, invalides = o._corriger(args)
    return propres, ("Valeur invalide : " + " ; ".join(invalides)) if invalides else ""


def _risque(o: Outil, args: dict) -> Risque:
    try:
        return o.risque_pour(args)
    except Exception:  # noqa: BLE001 - risque incalculable : on le traite comme sensible
        return Risque.SENSIBLE


def _imperatif(demande: str) -> bool:
    """« Envoie… », « ouvre… » : oui. « Comment… ? », « quel… » : non (une réponse suffit)."""
    t = routeur.normaliser(demande).strip()
    return "?" not in t and not QUESTION.match(t)


def _risque_fixe(o: Outil) -> Risque:
    """Risque d'un outil hors arguments (une fonction de risque est comptée comme une action possible)."""
    return o.risque if isinstance(o.risque, Risque) else Risque.MODIFICATION


def _action_reussie(trace: list) -> bool:
    return any(t["ok"] and t["outil"] not in OBSERVATION for t in trace)


def _couper(texte: str, n: int) -> str:
    texte = texte or ""
    return texte if len(texte) <= n else texte[:n] + " […]"


def _abreger(args: dict, n: int = 200) -> dict:
    """Pour le journal : les longs textes (contenu, corps…) raccourcis."""
    return {k: (v[:n] + "…" if isinstance(v, str) and len(v) > n else v) for k, v in args.items()}


def _jetons(texte: str) -> int:
    return int(len(texte) / CAR_PAR_JETON) + 1


def _jetons_message(m: dict) -> int:
    n = _jetons(str(m.get("content") or "")) + 4
    if m.get("tool_calls"):
        n += _jetons(json.dumps(m["tool_calls"], ensure_ascii=False, default=str))
    return n


def _raccourcir(contenu: str, n: int) -> str:
    """Raccourcit un résultat d'outil en gardant son cadre <donnees> intact."""
    m = re.match(r"(.*?)<donnees>\n(.*)\n</donnees>\s*$", contenu, re.S)
    if not m:
        return _couper(contenu, n)
    interieur = m.group(2)
    if len(interieur) <= n:
        return contenu
    return m.group(1) + consignes.donnees(interieur[:n] + "\n[… raccourci : résultat déjà exploité]", limite=n + 60)


def _serialisable(d):
    try:
        json.dumps(d)
        return d
    except (TypeError, ValueError):
        return None
