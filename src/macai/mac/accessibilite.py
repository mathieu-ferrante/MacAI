"""Accessibilité macOS (AXUIElement) : lire les éléments d'une fenêtre, cliquer, saisir ; clavier et souris.

Nécessite l'autorisation « Accessibilité » pour MacAI (Réglages Système > Confidentialité et sécurité).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..outils.base import ErreurOutil

ROLES = {
    "AXButton": "bouton", "AXCheckBox": "case", "AXRadioButton": "option", "AXTextField": "champ",
    "AXTextArea": "zone de texte", "AXSearchField": "recherche", "AXPopUpButton": "liste", "AXComboBox": "liste",
    "AXMenuButton": "menu", "AXLink": "lien", "AXSlider": "curseur", "AXTab": "onglet", "AXDisclosureTriangle": "dépliant",
    "AXIncrementor": "compteur", "AXCell": "cellule", "AXRow": "ligne", "AXMenuItem": "élément de menu",
    "AXStaticText": "texte", "AXImage": "image", "AXSecureTextField": "mot de passe",
}
INTERACTIFS = set(ROLES) - {"AXStaticText", "AXImage"}
PROFONDEUR_MAX = 12
ELEMENTS_MAX = 180


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


def pid_application(nom: str | None) -> tuple[int, str]:
    from AppKit import NSWorkspace
    ws = NSWorkspace.sharedWorkspace()
    if not nom:
        app = ws.frontmostApplication()
        return app.processIdentifier(), app.localizedName()
    from ..agent.routeur import normaliser
    cible = normaliser(nom)
    candidats = [a for a in ws.runningApplications() if a.localizedName()]
    for a in candidats:
        if normaliser(a.localizedName()) == cible:
            return a.processIdentifier(), a.localizedName()
    for a in candidats:
        if cible in normaliser(a.localizedName()):
            return a.processIdentifier(), a.localizedName()
    raise ErreurOutil(f"L'application « {nom} » n'est pas ouverte.")


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
    fenetre = attribut(app, "AXFocusedWindow") or (attribut(app, "AXWindows") or [None])[0]
    if fenetre is None:
        raise ErreurOutil(f"{nom} n'a pas de fenêtre ouverte.")
    titre = attribut(fenetre, "AXTitle") or nom
    elements: list[Element] = []

    def visiter(el, profondeur):
        if len(elements) >= ELEMENTS_MAX or profondeur > PROFONDEUR_MAX:
            return
        role = attribut(el, "AXRole") or ""
        if role in INTERACTIFS or (textes and role == "AXStaticText"):
            libelle = _libelle(el)
            valeur = attribut(el, "AXValue")
            valeur = "" if valeur is None or role == "AXSecureTextField" else str(valeur)[:120]
            if libelle or valeur or role in INTERACTIFS:
                if not (role == "AXStaticText" and not (valeur or libelle)):
                    elements.append(Element(el, role, libelle, valeur))
        for enfant in attribut(el, "AXChildren") or []:
            visiter(enfant, profondeur + 1)

    visiter(fenetre, 0)
    return f"{nom} — {titre}", elements


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
