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
from .base import ErreurOutil, Resultat, Risque, interdire_achat, outil


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
    if application:
        from .applications import trouver_application
        app = trouver_application(application)
        commun.executer(["open", "-a", str(app) if app else application])
        time.sleep(0.6)
    titre, elements = ax.explorer_fenetre(application or None)
    ctx.services["ax_elements"] = elements
    if not elements:
        return Resultat(True, f"{titre} : aucun élément lisible. Essaie voir_ecran (vision).")
    return Resultat(True, f"Fenêtre : {titre}\n{ax.decrire(elements)}", {"nb": len(elements)})


@outil("cliquer_element", "Clique sur un élément de fenêtre par son numéro (donné par lire_fenetre).", "fenetres",
       {"numero": ("integer", "numéro de l'élément")}, risque=Risque.MODIFICATION,
       annonce=lambda a: f"Cliquer sur l'élément {a['numero']}")
def cliquer_element(ctx, numero):
    e = _element(ctx, numero)
    interdire_achat(e.libelle, e.valeur)
    if e.role in ("AXStaticText", "AXImage"):
        raise ErreurOutil(f"L'élément {numero} est un {ax.ROLES.get(e.role)}, pas un bouton : choisis un [bouton], "
                          "[option], [case], [lien] ou [onglet] proche.")
    ax.appuyer(e.ref)
    time.sleep(0.4)
    return f"Clic sur « {e.libelle or e.valeur or ax.ROLES.get(e.role, e.role)} »."


@outil("saisir_element", "Écrit un texte dans un champ de fenêtre par son numéro (donné par lire_fenetre).",
       "fenetres", {"numero": ("integer", "numéro du champ"), "texte": ("string", "texte à écrire"),
                    "valider": ("boolean", "appuyer sur Entrée ensuite")}, requis=["numero", "texte"],
       risque=Risque.MODIFICATION, annonce=lambda a: f"Écrire « {a['texte']} » dans le champ {a['numero']}")
def saisir_element(ctx, numero, texte, valider=False):
    e = _element(ctx, numero)
    interdire_achat(e.libelle)
    if e.role == "AXSecureTextField":
        raise ErreurOutil("C'est un champ de mot de passe : je ne le remplis pas, c'est à toi de le faire.")
    ax.definir_valeur(e.ref, str(texte))
    if valider:
        ax.raccourci([], "entree")
    return f"Texte écrit dans « {e.libelle or 'le champ'} »."


@outil("choisir_menu", "Choisit une commande dans la barre des menus d'une application, ex. "
       "« Fichier > Exporter > PDF… » (noms tels qu'affichés, en français).", "fenetres",
       {"application": ("string", "nom de l'application"),
        "chemin": ("string", "menus séparés par >, ex. « Fichier > Enregistrer sous… »")},
       risque=Risque.MODIFICATION, annonce=lambda a: f"Menu {a['chemin']} dans {a['application']}")
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
       {"touches": ("string", "raccourci, ex. cmd+c")}, risque=Risque.MODIFICATION,
       annonce=lambda a: f"Raccourci {a['touches']}")
def raccourci_clavier(ctx, touches):
    parties = [p.strip() for p in touches.lower().replace(" ", "").split("+") if p.strip()]
    if not parties:
        raise ErreurOutil("Raccourci vide.")
    if parties[-1] == "q" and any(m in parties[:-1] for m in ("cmd", "command", "commande")):
        raise ErreurOutil("Pour quitter une application, utilise quitter_application.")
    ax.raccourci(parties[:-1], parties[-1])
    return f"Raccourci {touches} envoyé."


@outil("taper_texte", "Tape un texte au clavier à l'endroit du curseur, dans l'application indiquée. Préfère "
       "saisir_element (champ précis) quand lire_fenetre montre le champ.",
       "fenetres", {"texte": ("string", "texte à taper"),
                    "application": ("string", "application où taper (elle doit être au premier plan)")},
       requis=["texte", "application"], risque=Risque.MODIFICATION,
       annonce=lambda a: f"Taper « {a['texte'][:60]} » dans {a.get('application', '?')}")
def taper_texte(ctx, texte, application):
    # Garde-fou : le texte part dans le champ qui a le focus. On vérifie que c'est bien l'appli voulue,
    # sinon il atterrirait n'importe où (vu en essai : dans la saisie de l'utilisateur).
    from .applications import trouver_application
    app = trouver_application(application)
    if app is not None:
        commun.executer(["open", "-a", str(app)])
        time.sleep(0.4)
    pid_voulu, nom_voulu = ax.pid_application(app.stem if app else application)
    pid_devant, devant = ax.application_au_premier_plan()
    if pid_devant != pid_voulu:
        raise ErreurOutil(f"{nom_voulu} n'est pas au premier plan ({devant} l'est) : je ne tape pas à l'aveugle.")
    ax.taper(str(texte))
    return f"Texte tapé dans {nom_voulu} (vérifie avec lire_fenetre qu'il est au bon endroit)."


@outil("attendre", "Attend quelques secondes (qu'une page charge, qu'une appli réponde), puis relis la fenêtre.",
       "fenetres", {"secondes": ("integer", "durée, 1 à 60")}, mac_seulement=False)
def attendre(ctx, secondes=5):
    s = max(1, min(int(secondes or 5), 60))
    if ctx.arret.wait(s):
        raise ErreurOutil("Arrêt demandé.")
    return f"{s} s écoulées."


# --- Vision : dernier recours -----------------------------------------------------------

def capture_reduite() -> bytes:
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
