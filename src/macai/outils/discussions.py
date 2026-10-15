"""Écrire dans une application de discussion (Claude, ChatGPT, Messages…) et lire la réponse.

Un petit modèle local enchaîne mal six clics dans une interface web (choisir le mode, nouvelle conversation,
trouver la zone de saisie, taper, envoyer, attendre, relire) : ces outils font toute la séquence eux-mêmes,
en vérifiant chaque étape. Le modèle n'a qu'un appel à faire.
"""
from __future__ import annotations

import time

from ..mac import accessibilite as ax
from ..mac import commun
from .base import ErreurOutil, Resultat, Risque, outil

ATTENTE_REPONSE_MAX_S = 120
STABLE_S = 4.0  # la réponse est finie quand plus rien ne change pendant ce temps
# Applis d'IA : y envoyer une question n'engage personne. Ailleurs (Messages, WhatsApp, Slack…) c'est un
# message envoyé à quelqu'un : confirmation obligatoire.
DISCUSSIONS_IA = {"claude", "chatgpt", "le chat", "mistral", "perplexity", "gemini", "copilot"}


def _parcourir(pid: int, noeuds_max: int = 5000):
    app = ax._ax().AXUIElementCreateApplication(pid)
    fenetre = ax.fenetre_principale(app)
    if fenetre is None:
        raise ErreurOutil("Pas de fenêtre visible : affiche l'application (pas réduite, pas en plein écran ailleurs).")
    pile, vus = [(fenetre, 0)], 0
    while pile and vus < noeuds_max:
        el, p = pile.pop()
        vus += 1
        yield el
        if p < ax.PROFONDEUR_MAX:
            pile += [(e, p + 1) for e in reversed(ax.attribut(el, "AXChildren") or [])]


def _textes(pid: int) -> list[str]:
    sortie = []
    for el in _parcourir(pid):
        if ax.attribut(el, "AXRole") == "AXStaticText":
            v = ax.attribut(el, "AXValue") or ax.attribut(el, "AXTitle")
            if v and str(v).strip():
                sortie.append(str(v).strip())
    return sortie


def _zone_de_saisie(pid: int):
    """La zone de texte vide où écrire : celle qui a le focus si elle est vide, sinon la dernière vide."""
    vides = []
    for el in _parcourir(pid):
        if ax.attribut(el, "AXRole") in ("AXTextArea", "AXTextField"):
            if not str(ax.attribut(el, "AXValue") or "").strip():
                if ax.attribut(el, "AXFocused"):
                    return el
                vides.append(el)
    return vides[-1] if vides else None


def _radio(pid: int, libelle: str):
    for el in _parcourir(pid):
        if ax.attribut(el, "AXRole") == "AXRadioButton" and ax._libelle(el) == libelle:
            return el
    return None


def _activer(application: str) -> tuple[int, str]:
    from .applications import trouver_application
    app = trouver_application(application)
    if app is None:
        raise ErreurOutil(f"Application « {application} » introuvable.")
    commun.executer(["open", "-a", str(app)])
    time.sleep(1.0)
    pid, nom = ax.pid_application(app.stem)
    ax.activer_contenu_web(ax._ax().AXUIElementCreateApplication(pid), pid)
    time.sleep(0.8)
    return pid, nom


def _envoyer(ctx, pid: int, nom: str, texte: str) -> list[str]:
    """Tape le texte dans la zone de saisie vide et l'envoie. Renvoie les textes visibles avant l'envoi."""
    zone = _zone_de_saisie(pid)
    if zone is None:
        raise ErreurOutil(f"Pas de zone de saisie vide dans {nom} (un brouillon est peut-être en cours : je n'y "
                          "touche pas).")
    avant = _textes(pid)
    ax.definir_valeur(zone, texte)
    time.sleep(0.3)
    if texte[:15] not in str(ax.attribut(zone, "AXValue") or ""):
        raise ErreurOutil(f"Le texte n'a pas été pris par {nom}.")
    pid_devant, devant = ax.application_au_premier_plan()
    if pid_devant != pid:
        raise ErreurOutil(f"{nom} n'est plus au premier plan ({devant}) : envoi annulé.")
    ax.raccourci([], "entree")
    time.sleep(1.0)
    if texte[:15] in str(ax.attribut(zone, "AXValue") or ""):
        raise ErreurOutil(f"Le message est écrit dans {nom} mais n'est pas parti (Entrée sans effet).")
    return avant


def _attendre_reponse(ctx, pid: int, avant: list[str], question: str) -> str:
    """Attend que de nouveaux textes apparaissent puis ne bougent plus ; renvoie ces nouveaux textes."""
    deja = set(avant) | {question.strip()}
    fin = time.monotonic() + ATTENTE_REPONSE_MAX_S
    precedent, stable_depuis = None, None
    while time.monotonic() < fin:
        if ctx.arret.wait(2.0):
            raise ErreurOutil("Arrêt demandé.")
        nouveaux = [t for t in _textes(pid) if t not in deja]
        if nouveaux and nouveaux == precedent:
            stable_depuis = stable_depuis or time.monotonic()
            if time.monotonic() - stable_depuis >= STABLE_S:
                return "\n".join(nouveaux)
        else:
            stable_depuis = None
        precedent = nouveaux
    return "\n".join(precedent or [])


@outil("demander_a_claude", "Pose une question à l'application Claude (mode chat, nouvelle conversation), "
       "attend sa réponse et la renvoie. À utiliser dès que l'utilisateur veut demander quelque chose à Claude.",
       "fenetres", {"question": ("string", "la question ou le message à envoyer à Claude"),
                    "nouvelle_conversation": ("boolean", "ouvrir une nouvelle conversation (oui par défaut)")},
       requis=["question"], risque=Risque.MODIFICATION, mots_cles=["claude"],
       annonce=lambda a: f"Demander à Claude : « {a['question'][:80]} »")
def demander_a_claude(ctx, question, nouvelle_conversation=True):
    question = str(question).strip()
    if not question:
        raise ErreurOutil("Question vide.")
    pid, nom = _activer("Claude")
    # 1. Mode chat (« Chat et Cowork ») : en mode Code, on parlerait à Claude Code, qui agit sur le Mac.
    chat = _radio(pid, "Chat et Cowork")
    if chat is not None and str(ax.attribut(chat, "AXValue")) not in ("1", "True", "true"):
        ax.appuyer(chat)
        time.sleep(1.5)
    if ax.option_cochee(pid, "Code"):
        raise ErreurOutil("Impossible de passer Claude en mode chat (l'option « Chat et Cowork » ne répond pas).")
    # 2. Nouvelle conversation.
    if nouvelle_conversation:
        ax.raccourci(["cmd"], "n")
        time.sleep(1.5)
    # 3. Écrire, envoyer, 4. attendre la réponse.
    avant = _envoyer(ctx, pid, nom, question)
    ctx.emettre("info", texte="Question envoyée à Claude, j'attends sa réponse…")
    reponse = _attendre_reponse(ctx, pid, avant, question)
    if not reponse:
        return Resultat(True, "Question envoyée à Claude, mais sa réponse n'est pas encore lisible : elle "
                              "s'affiche dans l'application.")
    return Resultat(True, f"Réponse de Claude :\n{reponse[:4000]}")


def _risque_ecrire(args: dict) -> Risque:
    from ..agent.routeur import normaliser
    if not args.get("envoyer", True):
        return Risque.MODIFICATION
    return Risque.MODIFICATION if normaliser(str(args.get("application", ""))) in DISCUSSIONS_IA else Risque.SENSIBLE


@outil("ecrire_et_envoyer", "Écrit un message dans la zone de saisie d'une application (ChatGPT, Messages, "
       "Slack, une barre de recherche…) et l'envoie avec Entrée. Pour Claude, préfère demander_a_claude.",
       "fenetres", {"application": ("string", "nom de l'application"), "texte": ("string", "texte à écrire"),
                    "envoyer": ("boolean", "appuyer sur Entrée (oui par défaut)")},
       requis=["application", "texte"], risque=_risque_ecrire,
       annonce=lambda a: f"Écrire « {a['texte'][:60]} » dans {a['application']}"
                         + (" et l'envoyer" if a.get("envoyer", True) else ""))
def ecrire_et_envoyer(ctx, application, texte, envoyer=True):
    pid, nom = _activer(application)
    from ..agent.routeur import normaliser
    if normaliser(nom) == "claude" and ax.option_cochee(pid, "Code"):
        raise ErreurOutil("Claude est en mode Code : utilise demander_a_claude.")
    if not envoyer:
        zone = _zone_de_saisie(pid)
        if zone is None:
            raise ErreurOutil(f"Pas de zone de saisie vide dans {nom}.")
        ax.definir_valeur(zone, str(texte))
        return f"Texte écrit dans {nom} (pas envoyé)."
    _envoyer(ctx, pid, nom, str(texte))
    return f"Message envoyé dans {nom}. Relis la fenêtre (lire_fenetre) pour voir la suite."
