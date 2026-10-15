"""Accessibilité macOS (AXUIElement) : lire les éléments d'une fenêtre, cliquer, saisir ; clavier et souris.

Nécessite l'autorisation « Accessibilité » pour MacAI (Réglages Système > Confidentialité et sécurité).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from ..outils.base import ErreurOutil

ROLES = {
    "AXButton": "bouton", "AXCheckBox": "case", "AXRadioButton": "option", "AXTextField": "champ",
    "AXTextArea": "zone de texte", "AXSearchField": "recherche", "AXPopUpButton": "liste", "AXComboBox": "liste",
    "AXMenuButton": "menu", "AXLink": "lien", "AXSlider": "curseur", "AXTab": "onglet", "AXDisclosureTriangle": "dépliant",
    "AXIncrementor": "compteur", "AXCell": "cellule", "AXRow": "ligne", "AXMenuItem": "élément de menu",
    "AXStaticText": "texte", "AXImage": "image", "AXSecureTextField": "mot de passe",
}
INTERACTIFS = set(ROLES) - {"AXStaticText", "AXImage"}
PROFONDEUR_MAX = 30   # les pages web (Chrome, applis Electron comme Claude) sont profondes
ELEMENTS_MAX = 180
ELEMENTS_LUS = 600    # on lit plus large, puis on garde d'abord boutons et champs (la saisie est souvent en bas)
DUREE_MAX_S = 4.0     # une fenêtre énorme ne bloque pas l'agent : on rend ce qu'on a lu


def _ax():
    try:
        import ApplicationServices as AS
    except ImportError as e:
        raise ErreurOutil("Accessibilité indisponible (macOS uniquement).") from e
    if not AS.AXIsProcessTrusted():
        raise ErreurOutil("macOS bloque le contrôle des fenêtres : Réglages Système > Confidentialité et "
                          "sécurité > Accessibilité > active MacAI.")
    return AS


def attribut(el, nom):
    AS = _ax()
    err, val = AS.AXUIElementCopyAttributeValue(el, nom, None)
    return val if err == 0 else None


BLOC_LSAPPINFO = re.compile(r'^\s*\d+\) "(?P<nom>[^"]*)" ASN:[^\n]*\n(?P<corps>(?:(?!^\s*\d+\) ").*\n?)*)', re.M)


def applis_ouvertes() -> list[dict]:
    """Applications au premier plan possible (« Foreground »), lues à chaque appel avec lsappinfo.

    NSWorkspace.runningApplications ne se met à jour que dans une boucle d'événements : dans le moteur (sans
    boucle), la liste restait figée à son premier appel et les applis ouvertes ensuite étaient introuvables."""
    import subprocess
    sortie = subprocess.run(["lsappinfo", "list"], capture_output=True, text=True, timeout=10).stdout
    applis = []
    for m in BLOC_LSAPPINFO.finditer(sortie):
        corps = m.group("corps")
        if 'type="Foreground"' not in corps:
            continue
        pid = re.search(r"\bpid = (\d+)", corps)
        chemin = re.search(r'bundle path="([^"]+)"', corps)
        ident = re.search(r'bundleID="([^"]+)"', corps)
        if pid:
            applis.append({"nom": m.group("nom"), "pid": int(pid.group(1)),
                           "paquet": Path(chemin.group(1)).stem if chemin else "",
                           "id": ident.group(1) if ident else ""})
    return applis


def application_au_premier_plan() -> tuple[int, str]:
    import subprocess
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=5).stdout.strip()
    info = subprocess.run(["lsappinfo", "info", "-only", "pid", "-only", "name", asn],
                          capture_output=True, text=True, timeout=5).stdout
    pid, nom = re.search(r'"pid"=(\d+)|pid = (\d+)', info), re.search(r'"LSDisplayName"="([^"]+)"|^"([^"]+)"', info.strip())
    if not pid:
        raise ErreurOutil("Impossible de savoir quelle application est au premier plan.")
    return int(pid.group(1) or pid.group(2)), (nom.group(1) or nom.group(2)) if nom else "application"


def pid_application(nom: str | None) -> tuple[int, str]:
    if not nom:
        return application_au_premier_plan()
    from ..agent.routeur import normaliser
    cible = normaliser(nom).removesuffix(".app")
    candidats = applis_ouvertes()

    def noms(a) -> list[str]:
        # Nom affiché (« Réglages Système »), nom du paquet (« System Settings ») et identifiant :
        # le modèle emploie l'un ou l'autre, en français ou en anglais.
        return [normaliser(a["nom"]), normaliser(a["paquet"]), normaliser(a["id"].rsplit(".", 1)[-1])]

    for a in candidats:
        if cible in noms(a):
            return a["pid"], a["nom"]
    for a in candidats:
        if any(cible in n for n in noms(a)[:2] if n):
            return a["pid"], a["nom"]
    raise ErreurOutil(f"L'application « {nom} » n'est pas ouverte.")


_actives: set[int] = set()


def activer_contenu_web(app_el, pid: int) -> bool:
    """Chrome et les applis Electron (Claude, VS Code, Slack, Discord…) ne publient le contenu de leurs pages
    qu'à un lecteur d'écran qui le demande : sans cela, lire_fenetre ne voit que les boutons de la fenêtre.
    Renvoie True à la première activation (l'appli met ~1 s à construire son arbre)."""
    if pid in _actives:
        return False
    AS = _ax()
    _actives.add(pid)
    for attr in ("AXManualAccessibility", "AXEnhancedUserInterface"):
        AS.AXUIElementSetAttributeValue(app_el, attr, True)
    return True


@dataclass
class Element:
    ref: object
    role: str
    libelle: str
    valeur: str


def _libelle(el) -> str:
    for a in ("AXTitle", "AXDescription", "AXLabel", "AXHelp", "AXPlaceholderValue"):
        v = attribut(el, a)
        if v:
            return str(v).strip()
    titre = attribut(el, "AXTitleUIElement")
    if titre is not None:
        v = attribut(titre, "AXValue")
        if v:
            return str(v).strip()
    return ""


def explorer_fenetre(nom_app: str | None = None, textes: bool = True) -> tuple[str, list[Element]]:
    """Parcourt la fenêtre active de l'application ; renvoie (titre, éléments numérotés)."""
    AS = _ax()
    pid, nom = pid_application(nom_app)
    app = AS.AXUIElementCreateApplication(pid)
    nouvelle = activer_contenu_web(app, pid)
    for essai in range(6):
        titre, elements = _lire(app, nom, textes)
        # Juste après l'activation, une appli web n'expose encore que ses boutons de fenêtre : on attend.
        if not nouvelle or len(elements) > 8:
            break
        time.sleep(0.5)
    return f"{nom} — {titre}", elements


def _lire(app, nom: str, textes: bool) -> tuple[str, list[Element]]:
    fenetre = attribut(app, "AXFocusedWindow") or (attribut(app, "AXWindows") or [None])[0]
    if fenetre is None:
        raise ErreurOutil(f"{nom} n'a pas de fenêtre ouverte.")
    titre = attribut(fenetre, "AXTitle") or nom
    elements: list[Element] = []

    fin = time.monotonic() + DUREE_MAX_S

    def visiter(el, profondeur):
        if len(elements) >= ELEMENTS_LUS or profondeur > PROFONDEUR_MAX or time.monotonic() > fin:
            return
        role = attribut(el, "AXRole") or ""
        if role in INTERACTIFS or (textes and role == "AXStaticText"):
            libelle = _libelle(el)
            valeur = attribut(el, "AXValue")
            valeur = "" if valeur is None or role == "AXSecureTextField" else str(valeur)[:120]
            # Lignes et cellules sans texte (listes, barres latérales) : seuls leurs textes enfants comptent.
            if role in ("AXRow", "AXCell") and not (libelle or valeur):
                pass
            elif libelle or valeur or role in INTERACTIFS:
                if not (role == "AXStaticText" and not (valeur or libelle)):
                    elements.append(Element(el, role, libelle, valeur))
        for enfant in attribut(el, "AXChildren") or []:
            visiter(enfant, profondeur + 1)

    visiter(fenetre, 0)
    if len(elements) > ELEMENTS_MAX:
        # Tous les éléments interactifs, puis les textes dans l'ordre jusqu'à la limite (ordre d'origine gardé).
        interactifs = sum(1 for e in elements if e.role in INTERACTIFS)
        place_textes = max(0, ELEMENTS_MAX - interactifs)
        gardes, textes_vus = [], 0
        for e in elements:
            if e.role in INTERACTIFS:
                gardes.append(e)
            elif textes_vus < place_textes:
                gardes.append(e)
                textes_vus += 1
        elements = gardes[:ELEMENTS_MAX * 2]
    return titre, elements


def decrire(elements: list[Element]) -> str:
    lignes = []
    for i, e in enumerate(elements, 1):
        genre = ROLES.get(e.role, e.role)
        texte = e.libelle
        if e.valeur and e.valeur != e.libelle:
            texte += f" = « {e.valeur} »" if texte else f"« {e.valeur} »"
        lignes.append(f"{i} [{genre}] {texte}".rstrip())
    return "\n".join(lignes)


def centre(el) -> tuple[float, float] | None:
    AS = _ax()
    pos, taille = attribut(el, "AXPosition"), attribut(el, "AXSize")
    if pos is None or taille is None:
        return None
    ok_p, p = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
    ok_t, t = AS.AXValueGetValue(taille, AS.kAXValueCGSizeType, None)
    if not (ok_p and ok_t):
        return None
    return p.x + t.width / 2, p.y + t.height / 2


def appuyer(el) -> None:
    AS = _ax()
    actions = AS.AXUIElementCopyActionNames(el, None)
    noms = actions[1] if isinstance(actions, tuple) else actions
    if noms and "AXPress" in noms and AS.AXUIElementPerformAction(el, "AXPress") == 0:
        return
    c = centre(el)
    if c is None:
        raise ErreurOutil("Impossible de cliquer sur cet élément.")
    cliquer(*c)


def definir_valeur(el, texte: str) -> None:
    AS = _ax()
    AS.AXUIElementSetAttributeValue(el, "AXFocused", True)
    if AS.AXUIElementSetAttributeValue(el, "AXValue", texte) != 0:
        appuyer(el)
        time.sleep(0.1)
        raccourci(["cmd"], "a")
        taper(texte)


# --- Souris et clavier (Quartz) ----------------------------------------------------

def cliquer(x: float, y: float, double: bool = False) -> None:
    import Quartz
    pt = (x, y)
    for _ in range(2 if double else 1):
        for genre in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
            ev = Quartz.CGEventCreateMouseEvent(None, genre, pt, Quartz.kCGMouseButtonLeft)
            if double:
                Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, 2)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
            time.sleep(0.03)


def taper(texte: str) -> None:
    """Tape un texte Unicode, indépendamment de la disposition du clavier (AZERTY…)."""
    import Quartz
    for morceau in (texte[i:i + 18] for i in range(0, len(texte), 18)):
        for appui in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, 0, appui)
            Quartz.CGEventKeyboardSetUnicodeString(ev, len(morceau), morceau)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.02)


CODES = {"entree": 36, "return": 36, "enter": 36, "tab": 48, "espace": 49, "space": 49, "effacer": 51,
         "delete": 51, "backspace": 51, "echap": 53, "escape": 53, "esc": 53, "gauche": 123, "left": 123,
         "droite": 124, "right": 124, "bas": 125, "down": 125, "haut": 126, "up": 126, "suppr": 117,
         "debut": 115, "home": 115, "fin": 119, "end": 119, "pageup": 116, "pagedown": 121,
         **{f"f{i}": c for i, c in zip(range(1, 13), [122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111])}}
MODIFICATEURS = {"cmd": "command", "command": "command", "commande": "command", "maj": "shift",
                 "shift": "shift", "alt": "option", "option": "option", "ctrl": "control", "control": "control"}


def raccourci(modificateurs: list[str], touche: str) -> None:
    """Raccourci clavier via System Events : les lettres suivent la disposition active (AZERTY compris)."""
    from .commun import chaine_as, osascript
    mods = []
    for m in modificateurs:
        if m.lower() not in MODIFICATEURS:
            raise ErreurOutil(f"Modificateur inconnu : {m}")
        mods.append(f"{MODIFICATEURS[m.lower()]} down")
    using = f" using {{{', '.join(mods)}}}" if mods else ""
    t = touche.lower()
    if t in CODES:
        action = f"key code {CODES[t]}{using}"
    elif len(touche) == 1:
        action = f"keystroke {chaine_as(t)}{using}"
    else:
        raise ErreurOutil(f"Touche inconnue : {touche}")
    osascript(f'tell application "System Events" to {action}')


def taille_ecran() -> tuple[float, float]:
    import Quartz
    b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return b.size.width, b.size.height


def menus(nom_app: str, menu: str = "", max_par_menu: int = 25) -> tuple[str, str]:
    """Menus de l'application et leurs commandes (un seul appel suffit au modèle pour trouver la bonne)."""
    from ..agent.routeur import normaliser
    AS = _ax()
    pid, nom = pid_application(nom_app)
    barre = attribut(AS.AXUIElementCreateApplication(pid), "AXMenuBar")
    if barre is None:
        raise ErreurOutil(f"{nom} n'a pas de barre des menus lisible.")
    lignes = []
    for titre_el in (attribut(barre, "AXChildren") or [])[1:]:  # le premier est le menu Pomme
        titre = str(attribut(titre_el, "AXTitle") or "")
        if not titre or (menu and normaliser(menu) not in normaliser(titre)):
            continue
        commandes = []
        for sous in attribut(titre_el, "AXChildren") or []:
            for item in attribut(sous, "AXChildren") or []:
                t = attribut(item, "AXTitle")
                if t and attribut(item, "AXEnabled") is not False:
                    commandes.append(str(t))
        if not menu:
            commandes = commandes[:max_par_menu]
        lignes.append(f"{titre} : " + ", ".join(commandes))
    if menu and not lignes:
        raise ErreurOutil(f"Pas de menu « {menu} » dans {nom}.")
    return nom, "\n".join(lignes)
