"""Pilotage de n'importe quel logiciel : éléments de fenêtre (Accessibilité), menus, clavier, et vision
de l'écran en dernier recours."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from ..mac import accessibilite as ax
from ..mac import commun
from .base import (APPS_EXECUTION, APPS_MESSAGERIE, ENVOI, ErreurOutil, Resultat, Risque, interdire_achat,
                   interdire_donnees_bancaires, nom_appli, outil)


def _pas_dans_claude_code(ctx, application: str = "") -> None:
    """Écrire dans Claude en mode Code = donner des ordres à Claude Code, qui agit sur le Mac : seulement si
    l'utilisateur parle de Claude Code dans sa demande."""
    from ..agent.routeur import normaliser
    demande = normaliser(ctx.services.get("demande", ""))
    if re.search(r"\bclaude code\b|\bmode code\b", demande):
        return
    try:
        pid, nom = ax.pid_application(application) if application else ax.application_au_premier_plan()
    except ErreurOutil:
        return
    if normaliser(nom) != "claude":
        return
    if ax.option_cochee(pid, "Code"):
        raise ErreurOutil("Claude est en mode Code : clique d'abord sur l'option « Chat et Cowork », relis la "
                          "fenêtre pour vérifier, puis écris.")


# Dernière fenêtre lue (pour les niveaux de risque, qui ne voient que les arguments).
_DERNIERE = {"app": "", "pid": 0, "elements": []}
TOUCHES_ENVOI = {"entree", "return", "enter", "cmd+entree", "cmd+return", "cmd+enter", "cmd+maj+d", "cmd+shift+d"}


def _appli_devant() -> str:
    try:
        return ax.application_au_premier_plan()[1]
    except Exception:  # noqa: BLE001 - hors Mac ou lsappinfo indisponible : pas d'appli connue
        return ""


def _risque_selon(app: str, envoi: bool, libelle: str = "") -> Risque:
    """Taper ou valider dans un Terminal = exécuter du code ; valider dans une messagerie = écrire à quelqu'un ;
    cliquer sur Envoyer / Supprimer / Publier : confirmation dans tous ces cas."""
    a = nom_appli(app)
    if a in APPS_EXECUTION:
        return Risque.SENSIBLE
    if envoi and a in APPS_MESSAGERIE:
        return Risque.SENSIBLE
    if libelle and ENVOI.search(libelle):
        return Risque.SENSIBLE
    return Risque.MODIFICATION


def _risque_cliquer(args: dict) -> Risque:
    try:
        n = int(args.get("numero", 0))
        e = _DERNIERE["elements"][n - 1] if n >= 1 else None
        libelle = f"{e.libelle} {e.valeur}" if e else ""
    except (IndexError, ValueError, TypeError):
        libelle = ""
    return _risque_selon(_DERNIERE["app"], True, libelle)


def _risque_saisir(args: dict) -> Risque:
    return _risque_selon(_DERNIERE["app"], bool(args.get("valider")))


def _risque_taper(args: dict) -> Risque:
    return _risque_selon(str(args.get("application") or _appli_devant()), bool(args.get("valider")))


def _risque_raccourci(args: dict) -> Risque:
    touches = str(args.get("touches", "")).lower().replace(" ", "")
    return _risque_selon(_appli_devant(), touches in TOUCHES_ENVOI)


def _risque_menu(args: dict) -> Risque:
    return _risque_selon(str(args.get("application", "")), False, str(args.get("chemin", "")))


def _mettre_devant(ctx, pid: int, nom: str) -> None:
    """Amène l'application au premier plan et vérifie qu'elle y est : les frappes vont à l'appli de devant."""
    commun.osascript(f'tell application "System Events" to set frontmost of (first process whose unix id is '
                     f'{int(pid)}) to true')
    time.sleep(0.3)
    pid_devant, devant = ax.application_au_premier_plan()
    if pid_devant != pid:
        raise ErreurOutil(f"{nom} n'est pas au premier plan ({devant} l'est) : je ne tape pas à l'aveugle.")


def _elements(ctx) -> list:
    els = ctx.services.get("ax_elements")
    if not els:
        raise ErreurOutil("Lis d'abord la fenêtre avec lire_fenetre pour connaître les numéros.")
    return els


def _element(ctx, numero):
    els = _elements(ctx)
    n = int(numero)
    if not 1 <= n <= len(els):
        raise ErreurOutil(f"Numéro {n} invalide (1 à {len(els)}). Relis la fenêtre avec lire_fenetre.")
    return els[n - 1]


@outil("lire_fenetre", "Liste les éléments de la fenêtre active d'une application (boutons, champs, cases, "
       "textes…) avec un numéro, pour cliquer_element et saisir_element. Fonctionne avec la plupart des logiciels.",
       "fenetres", {"application": ("string", "nom de l'application, facultatif (sinon celle au premier plan)")},
       requis=[])
def lire_fenetre(ctx, application=""):
    nom = None
    if application:
        from .applications import trouver_application
        app = trouver_application(application)
        if app is None:
            raise ErreurOutil(f"Application « {application} » introuvable. Vérifie avec applications_ouvertes.")
        commun.executer(["open", "-a", str(app)])
        time.sleep(0.6)
        nom = app.stem
    if nom is None and nom_appli(_appli_devant()) in ("macai", "loginwindow"):
        raise ErreurOutil("Précise l'application à lire (paramètre application) : au premier plan, il n'y a que "
                          "le panneau MacAI.")
    titre, elements = ax.explorer_fenetre(nom)
    appli = titre.split(" — ", 1)[0]
    ctx.services["ax_elements"] = elements
    ctx.services["ax_application"] = appli
    try:
        ctx.services["ax_pid"] = ax.pid_application(appli)[0]
    except ErreurOutil:
        ctx.services["ax_pid"] = 0
    _DERNIERE.update(app=appli, pid=ctx.services["ax_pid"], elements=elements)
    if not elements:
        return Resultat(True, f"{titre} : aucun élément lisible. Essaie voir_ecran (vision).")
    return Resultat(True, f"Fenêtre : {titre}\n{ax.decrire(elements)}", {"nb": len(elements)})


@outil("cliquer_element", "Clique sur un élément de fenêtre par son numéro (donné par lire_fenetre).", "fenetres",
       {"numero": ("integer", "numéro de l'élément")}, risque=_risque_cliquer,
       annonce=lambda a: f"Cliquer sur l'élément {a['numero']}")
def cliquer_element(ctx, numero):
    e = _element(ctx, numero)
    interdire_achat(e.libelle, bouton=True)
    interdire_achat(e.valeur)
    if e.role in ("AXStaticText", "AXImage"):
        raise ErreurOutil(f"L'élément {numero} est un {ax.ROLES.get(e.role)}, pas un bouton : choisis un [bouton], "
                          "[option], [case], [lien] ou [onglet] proche.")
    ax.appuyer(e.ref)
    time.sleep(0.4)
    return f"Clic sur « {e.libelle or e.valeur or ax.ROLES.get(e.role, e.role)} »."


@outil("saisir_element", "Écrit un texte dans un champ de fenêtre par son numéro (donné par lire_fenetre).",
       "fenetres", {"numero": ("integer", "numéro du champ"), "texte": ("string", "texte à écrire"),
                    "valider": ("boolean", "appuyer sur Entrée ensuite"),
                    "remplacer": ("boolean", "effacer le texte déjà présent (seulement si l'utilisateur le demande)")},
       requis=["numero", "texte"],
       risque=_risque_saisir, annonce=lambda a: f"Écrire « {a['texte']} » dans le champ {a['numero']}"
                                                + (" puis valider (Entrée)" if a.get("valider") else ""))
def saisir_element(ctx, numero, texte, valider=False, remplacer=False):
    e = _element(ctx, numero)
    interdire_achat(e.libelle, texte)
    interdire_donnees_bancaires(texte)
    _pas_dans_claude_code(ctx, ctx.services.get("ax_application", ""))
    deja = (ax.attribut(e.ref, "AXValue") or "").strip() if e.role in ("AXTextArea", "AXTextField", "AXComboBox",
                                                                     "AXSearchField") else ""
    if deja and not remplacer:
        # Probablement un texte que l'utilisateur est en train d'écrire : on n'y touche pas.
        raise ErreurOutil(f"Le champ « {e.libelle or numero} » contient déjà "
                          f"du texte (« {deja[:60]} ») : ce n'est sans doute pas le bon champ. Relis la fenêtre.")
    if e.role == "AXSecureTextField":
        raise ErreurOutil("C'est un champ de mot de passe : je ne le remplis pas, c'est à toi de le faire.")
    if ctx.services.get("ax_pid"):  # les frappes vont à l'appli au premier plan : on la vérifie
        _mettre_devant(ctx, ctx.services["ax_pid"], ctx.services.get("ax_application", "l'application"))
    ax.definir_valeur(e.ref, str(texte), remplacer=bool(remplacer))
    if valider:
        time.sleep(0.2)
        ax.raccourci([], "entree")
        time.sleep(0.5)
        return f"Texte écrit dans « {e.libelle or 'le champ'} » et envoyé (Entrée)."
    return f"Texte écrit dans « {e.libelle or 'le champ'} » (pas encore envoyé : valider=true ou « entree »)."


@outil("choisir_menu", "Choisit une commande dans la barre des menus d'une application, ex. "
       "« Fichier > Exporter > PDF… » (noms tels qu'affichés, en français).", "fenetres",
       {"application": ("string", "nom de l'application"),
        "chemin": ("string", "menus séparés par >, ex. « Fichier > Enregistrer sous… »")},
       risque=_risque_menu, annonce=lambda a: f"Menu {a['chemin']} dans {a['application']}")
def choisir_menu(ctx, application, chemin):
    from .applications import trouver_application
    app = trouver_application(application)
    nom = app.stem if app else application
    interdire_achat(chemin)
    parties = [p.strip() for p in re.split(r"\s*>\s*", chemin) if p.strip()]
    if len(parties) < 2:
        raise ErreurOutil("Donne au moins un menu et une commande : « Fichier > Enregistrer ».")
    cible = f"menu item {commun.chaine_as(parties[-1])}"
    for p in reversed(parties[1:-1]):
        cible += f" of menu 1 of menu item {commun.chaine_as(p)}"
    cible += f" of menu 1 of menu bar item {commun.chaine_as(parties[0])} of menu bar 1"
    commun.osascript(f'''tell application {commun.chaine_as(nom)} to activate
delay 0.3
tell application "System Events" to tell process {commun.chaine_as(nom)} to click {cible}''')
    return f"Menu « {chemin} » choisi dans {nom}."


@outil("lister_menus", "Liste les menus et commandes disponibles d'une application (pour trouver la bonne "
       "commande avant choisir_menu).", "fenetres",
       {"application": ("string", "nom de l'application"),
        "menu": ("string", "un menu précis, ex. « Fichier », facultatif")}, requis=["application"])
def lister_menus(ctx, application, menu=""):
    from .applications import trouver_application
    app = trouver_application(application)
    if app is not None:
        commun.executer(["open", "-a", str(app)])  # l'appli doit tourner pour avoir des menus
        time.sleep(0.5)
    nom, texte = ax.menus(app.stem if app else application, menu)
    return f"Menus de {nom} (commande à passer à choisir_menu, ex. « Fichier > Exporter… ») :\n{texte}"


@outil("raccourci_clavier", "Appuie sur un raccourci clavier dans l'application au premier plan, ex. "
       "« cmd+s », « cmd+maj+n », « entree », « echap », « tab ».", "fenetres",
       {"touches": ("string", "raccourci, ex. cmd+c")}, risque=_risque_raccourci,
       annonce=lambda a: f"Raccourci {a['touches']} dans {_appli_devant() or 'l’application au premier plan'}")
def raccourci_clavier(ctx, touches):
    parties = [p.strip() for p in touches.lower().replace(" ", "").split("+") if p.strip()]
    if not parties:
        raise ErreurOutil("Raccourci vide.")
    if parties[-1] == "q" and any(m in parties[:-1] for m in ("cmd", "command", "commande")):
        raise ErreurOutil("Pour quitter une application, utilise quitter_application.")
    if nom_appli(_appli_devant()) in ("macai", "loginwindow", ""):
        raise ErreurOutil("Aucune application cible au premier plan (le panneau MacAI l'est) : ouvre d'abord "
                          "l'application avec ouvrir_application, puis refais le raccourci.")
    ax.raccourci(parties[:-1], parties[-1])
    return f"Raccourci {touches} envoyé."


@outil("taper_texte", "Tape un texte au clavier à l'endroit du curseur, dans l'application indiquée. Préfère "
       "saisir_element (champ précis) quand lire_fenetre montre le champ.",
       "fenetres", {"texte": ("string", "texte à taper"),
                    "application": ("string", "application où taper (elle doit être au premier plan)"),
                    "valider": ("boolean", "appuyer sur Entrée ensuite (envoyer un message, lancer une recherche)")},
       requis=["texte", "application"], risque=_risque_taper,
       annonce=lambda a: f"Taper « {a['texte'][:300]} » dans {a.get('application', '?')}"
                         + (" puis valider (Entrée)" if a.get("valider") else ""))
def taper_texte(ctx, texte, application, valider=False):
    # Garde-fou : le texte part dans le champ qui a le focus. On vérifie que c'est bien l'appli voulue,
    # sinon il atterrirait n'importe où (vu en essai : dans la saisie de l'utilisateur).
    from .applications import trouver_application
    interdire_achat(texte)
    interdire_donnees_bancaires(texte)
    app = trouver_application(application)
    if app is None:
        raise ErreurOutil(f"Application « {application} » introuvable.")
    commun.executer(["open", "-a", str(app)])
    time.sleep(0.4)
    pid_voulu, nom_voulu = ax.pid_application(app.stem)
    _mettre_devant(ctx, pid_voulu, nom_voulu)
    if ax.role_actif(pid_voulu) == "AXSecureTextField":
        raise ErreurOutil("Le curseur est dans un champ de mot de passe : je n'y tape rien.")
    _pas_dans_claude_code(ctx, nom_voulu)
    focus = ax.champ_actif(pid_voulu)
    if focus and focus.strip():
        raise ErreurOutil(f"Le champ actif de {nom_voulu} contient déjà du texte (« {focus.strip()[:60]} ») : "
                          "c'est peut-être ce que l'utilisateur écrit. Utilise lire_fenetre puis saisir_element.")
    ax.taper(str(texte))
    if valider:
        time.sleep(0.2)
        ax.raccourci([], "entree")
        return f"Texte tapé dans {nom_voulu} et envoyé (Entrée)."
    return f"Texte tapé dans {nom_voulu}, pas encore envoyé (valider=true ou raccourci « entree »)."


@outil("attendre", "Attend quelques secondes (qu'une page charge, qu'une appli réponde), puis relis la fenêtre.",
       "fenetres", {"secondes": ("integer", "durée, 1 à 60")}, mac_seulement=False)
def attendre(ctx, secondes=5):
    s = max(1, min(int(secondes or 5), 60))
    if ctx.arret.wait(s):
        raise ErreurOutil("Arrêt demandé.")
    return f"{s} s écoulées."


# --- Vision : dernier recours -----------------------------------------------------------

def _verifier_capture_autorisee() -> None:
    """Sans « Enregistrement de l'écran », macOS renvoie une capture noire : le modèle décrirait un écran noir."""
    try:
        import Quartz
        if not Quartz.CGPreflightScreenCaptureAccess():
            raise ErreurOutil("AUTORISATION MANQUANTE (à accorder par l'utilisateur) : Enregistrement de l'écran. "
                              "Réglages Système > Confidentialité et sécurité > Enregistrement de l'écran > active "
                              "MacAI, puis relance MacAI.")
    except (ImportError, AttributeError):
        pass


def capture_reduite() -> bytes:
    _verifier_capture_autorisee()
    with tempfile.TemporaryDirectory() as d:
        brut, petit = Path(d) / "ecran.png", Path(d) / "ecran.jpg"
        commun.executer(["screencapture", "-x", "-m", "-t", "png", str(brut)])
        r = subprocess.run(["sips", "-Z", "1280", "-s", "format", "jpeg", str(brut), "--out", str(petit)],
                           capture_output=True, timeout=30)
        return (petit if r.returncode == 0 else brut).read_bytes()


@outil("voir_ecran", "Regarde l'écran (capture analysée par le modèle de vision local) et décrit ce qui "
       "s'y trouve ou répond à une question. Plus lent : à utiliser quand lire_fenetre ne suffit pas.",
       "fenetres", {"question": ("string", "ce qu'on veut savoir, facultatif")}, requis=[])
def voir_ecran(ctx, question=""):
    from .documents import demander_vision
    rep = demander_vision(ctx, capture_reduite(),
                          question or "Décris ce qui est affiché à l'écran : application, contenu, boutons visibles.")
    return rep


def extraire_coordonnees(texte: str) -> tuple[float, float]:
    """Accepte {"x": 512, "y": 300}, [512, 300] ou « (512, 300) » ; valeurs sur 0-1000."""
    try:
        d = json.loads(re.search(r"\{.*?\}", texte, re.S).group(0))
        return float(d["x"]), float(d["y"])
    except (AttributeError, ValueError, KeyError, TypeError):
        pass
    m = re.search(r"(\d+(?:\.\d+)?)\s*[,;]\s*(\d+(?:\.\d+)?)", texte)
    if not m:
        raise ErreurOutil(f"Le modèle de vision n'a pas donné de position exploitable : {texte[:120]}")
    return float(m.group(1)), float(m.group(2))


@outil("cliquer_ecran", "Trouve à l'écran l'élément décrit (vision) et clique dessus. Dernier recours, moins "
       "fiable que cliquer_element.", "fenetres",
       {"description": ("string", "ce sur quoi cliquer, ex. « le bouton bleu Partager en haut à droite »"),
        "double": ("boolean", "double-clic")}, requis=["description"], risque=Risque.MODIFICATION,
       annonce=lambda a: f"Cliquer à l'écran sur : {a['description']}")
def cliquer_ecran(ctx, description, double=False):
    from .documents import demander_vision
    interdire_achat(description)
    rep = demander_vision(ctx, capture_reduite(),
                          f"Trouve sur cette capture d'écran : {description}. Réponds UNIQUEMENT en JSON "
                          '{"x": <0-1000>, "y": <0-1000>} : position du centre de l\'élément, en millièmes de la '
                          'largeur (x) et de la hauteur (y). Si absent, réponds {"absent": true}.')
    if "absent" in rep:
        raise ErreurOutil(f"Élément introuvable à l'écran : {description}")
    x, y = extraire_coordonnees(rep)
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        raise ErreurOutil(f"Position hors de l'écran : {x}, {y}")
    largeur, hauteur = ax.taille_ecran()
    ax.cliquer(x / 1000 * largeur, y / 1000 * hauteur, double=bool(double))
    return f"Clic effectué sur « {description} » (vision, à vérifier)."
