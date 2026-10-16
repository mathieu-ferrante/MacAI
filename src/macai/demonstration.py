"""Démonstration : l'utilisateur montre une tâche (clics, saisie, raccourcis), MacAI la note puis propose d'en
faire une compétence rejouable.

Écoute passive (CGEventTap « listen only ») : rien n'est bloqué ni modifié. Aucune frappe brute n'est gardée :
chaque clic est décrit par l'élément visé (rôle, libellé, application, chemin de menu), la saisie est regroupée
en textes, et un champ de mot de passe, un numéro de carte, un IBAN ou un texte qui ressemble à un mot de passe
sont remplacés par « [masqué] » (jamais rejoués).
"""
from __future__ import annotations

import re
import threading
import time

from .outils.base import ErreurOutil, interdire_donnees_bancaires

DUREE_MAX_S = 600          # arrêt automatique après 10 minutes
EVENEMENTS_MAX = 3000
MASQUE = "[masqué]"
APPS_IGNOREES = {"macai", "loginwindow", "systemuiserver", "controlcenter", "centre de controle",
                 "notificationcenter"}
ROLES_SAISIE = {"AXTextField", "AXTextArea", "AXSearchField", "AXComboBox"}
ROLES_SANS_ETAPE = {"AXMenuBarItem", "AXMenuBar", "AXMenu", "AXScrollBar", "AXSplitter", "AXWindow",
                    "AXApplication"}
TOUCHES_SPECIALES = {36: "entree", 76: "entree", 48: "tab", 51: "effacer", 53: "echap"}
# Masques de modificateurs Quartz (kCGEventFlagMask…).
F_MAJ, F_CTRL, F_ALT, F_CMD = 1 << 17, 1 << 18, 1 << 19, 1 << 20
AUTORISATION = ("AUTORISATION MANQUANTE (à accorder par l'utilisateur) : pour apprendre en regardant, MacAI doit "
                "voir les clics et les touches. Réglages Système > Confidentialité et sécurité > Surveillance de "
                "l'entrée > active MacAI (et Accessibilité), puis relance MacAI.")


# --- Masquage --------------------------------------------------------------------------

def ressemble_mot_de_passe(texte: str) -> bool:
    """Un seul « mot » de 8 caractères ou plus mêlant au moins trois sortes de caractères (minuscules,
    majuscules, chiffres, symboles) : sans doute un mot de passe ou une clé."""
    t = texte.strip()
    if len(t) < 8 or " " in t:
        return False
    sortes = sum(bool(re.search(p, t)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
    return sortes >= 3 or (len(t) >= 20 and re.fullmatch(r"[A-Za-z0-9_\-]+", t) is not None
                           and re.search(r"\d", t) is not None)


def masquer(texte: str) -> str:
    try:
        interdire_donnees_bancaires(texte)
    except ErreurOutil:
        return MASQUE
    return MASQUE if any(ressemble_mot_de_passe(m) for m in texte.split()) else texte


# --- Conversion : événements → étapes lisibles + recette -------------------------------------

def _nom_app(ev) -> str:
    return str(ev.get("application") or "").strip()


def _ignoree(app: str) -> bool:
    from .agent.routeur import normaliser
    return normaliser(app) in APPS_IGNOREES


def regrouper(evenements: list[dict]) -> list[dict]:
    """Actions de haut niveau : {genre: ouvrir|menu|clic|texte|raccourci|touche|inutilisable, …}.

    Événements bruts attendus :
    - {"type": "clic", "role", "libelle", "application", "menu": [titres] (élément de menu), "barre": bool}
    - {"type": "touche", "caractere" | "special", "application", "secret": bool}
    - {"type": "raccourci", "touches": "cmd+s", "application"}
    """
    actions: list[dict] = []
    texte: dict | None = None
    app_courante = ""

    def fermer_texte():
        nonlocal texte
        if texte is not None and texte["texte"]:
            brut = texte.pop("brut")
            texte["texte"] = MASQUE if texte.get("secret") else masquer(brut)
            actions.append(texte)
        texte = None

    def changer_app(app: str):
        nonlocal app_courante
        if app and app != app_courante and not _ignoree(app):
            actions.append({"genre": "ouvrir", "application": app})
            app_courante = app

    for ev in evenements[:EVENEMENTS_MAX]:
        app = _nom_app(ev)
        typ = ev.get("type")
        if app and _ignoree(app):
            continue
        if typ == "touche":
            if ev.get("special"):
                sp = ev["special"]
                if sp == "effacer" and texte is not None:
                    texte["brut"] = texte["brut"][:-1]
                    texte["texte"] = texte["brut"]
                    continue
                fermer_texte()
                if sp in ("entree", "tab", "echap"):
                    changer_app(app)
                    actions.append({"genre": "touche", "touches": sp, "application": app or app_courante})
                continue
            car = str(ev.get("caractere") or "")
            if not car:
                continue
            if texte is None or texte["application"] != (app or app_courante) or bool(ev.get("secret")) != \
                    bool(texte.get("secret")):
                fermer_texte()
                changer_app(app)
                texte = {"genre": "texte", "application": app or app_courante, "brut": "", "texte": "",
                         "secret": bool(ev.get("secret"))}
            texte["brut"] += car
            texte["texte"] = texte["brut"]
            continue
        fermer_texte()
        if typ == "raccourci":
            changer_app(app)
            actions.append({"genre": "raccourci", "touches": str(ev.get("touches", "")),
                            "application": app or app_courante})
        elif typ == "clic":
            role, libelle = str(ev.get("role") or ""), str(ev.get("libelle") or "").strip()
            if app.lower() == "dock" or role == "AXDockItem":
                if libelle:
                    actions.append({"genre": "ouvrir", "application": libelle})
                    app_courante = libelle
                continue
            changer_app(app)
            menu = [str(m) for m in ev.get("menu") or [] if str(m).strip()]
            if role == "AXMenuItem" and menu:
                if ev.get("barre", True) and len(menu) >= 2:
                    action = {"genre": "menu", "chemin": " > ".join(menu), "application": app}
                else:
                    action = {"genre": "inutilisable", "description": f"menu contextuel « {menu[-1]} »",
                              "application": app}
            elif role in ROLES_SANS_ETAPE:
                continue
            elif libelle:
                action = {"genre": "clic", "libelle": libelle, "role": role, "application": app}
            else:
                from .mac.accessibilite import ROLES
                genre = ROLES.get(role, role.removeprefix("AX").lower() or "zone")
                action = {"genre": "inutilisable", "description": f"clic sur un(e) {genre} sans libellé",
                          "application": app}
            # Double-clic ou clic répété au même endroit : une seule étape.
            if actions and actions[-1] == action:
                continue
            actions.append(action)
    fermer_texte()
    return actions


def _phrase(a: dict) -> str:
    dans = f" dans {a['application']}" if a.get("application") else ""
    if a["genre"] == "ouvrir":
        return f"ouvrir {a['application']}"
    if a["genre"] == "menu":
        return f"menu {a['chemin']}{dans}"
    if a["genre"] == "clic":
        from .mac.accessibilite import ROLES
        return f"cliquer « {a['libelle']} » ({ROLES.get(a['role'], 'élément')}){dans}"
    if a["genre"] == "texte":
        return f"taper « {a['texte']} »{dans}"
    if a["genre"] == "raccourci":
        return f"raccourci {a['touches']}{dans}"
    if a["genre"] == "touche":
        return f"touche {a['touches']}{dans}"
    return f"{a.get('description', 'action')}{dans} (non rejouable)"


def recette(actions: list[dict], nom: str = "") -> dict | None:
    """Recette au format des compétences (dict), ou None s'il n'y a pas au moins deux étapes rejouables.
    Les textes tapés deviennent des paramètres {texte}, {texte2}…"""
    from .competences.competences import nom_valide
    etapes, parametres, apps = [], {}, []
    for a in actions:
        g, app = a["genre"], a.get("application", "")
        if app and app not in apps and g != "ouvrir":
            apps.append(app)
        if g == "ouvrir":
            if not etapes or etapes[-1] != {"outil": "ouvrir_application", "arguments": {"nom": app}}:
                etapes.append({"outil": "ouvrir_application", "arguments": {"nom": app}})
            if app not in apps:
                apps.append(app)
        elif g == "menu":
            etapes.append({"outil": "choisir_menu", "arguments": {"application": app, "chemin": a["chemin"]}})
        elif g == "clic":
            etapes.append({"outil": "cliquer_libelle", "arguments": {"application": app, "libelle": a["libelle"]}})
        elif g == "texte":
            if a["texte"] == MASQUE:
                continue  # jamais rejoué : à taper par l'utilisateur
            cle = "texte" if not parametres else f"texte{len(parametres) + 1}"
            parametres[cle] = f"texte à taper dans {app} (démonstration : « {a['texte'][:60]} »)"
            etapes.append({"outil": "taper_texte", "arguments": {"application": app, "texte": f"{{{cle}}}"}})
        elif g in ("raccourci", "touche"):
            touches = a["touches"]
            if re.fullmatch(r"(cmd|commande)\+q", touches):
                etapes.append({"outil": "quitter_application", "arguments": {"nom": app}})
            else:
                etapes.append({"outil": "raccourci_clavier", "arguments": {"touches": touches}})
    utiles = [e for e in etapes if e["outil"] != "ouvrir_application"]
    if len(etapes) < 2 or not utiles:
        return None
    base = nom or (("demonstration_" + "_".join(apps[:2])) if apps else "demonstration")
    description = "Rejoue la démonstration : " + ", ".join(_phrase(a) for a in actions
                                                            if a["genre"] != "inutilisable")[:220]
    return {"nom": nom_valide(base), "description": description, "etapes": etapes, "parametres": parametres,
            "declencheurs": [nom] if nom else [], "source": "demonstration"}


def apercu(rec) -> list[str]:
    """Étapes d'une recette (dict ou Competence) en phrases courtes, pour l'affichage."""
    etapes = rec.get("etapes", []) if isinstance(rec, dict) else getattr(rec, "etapes", [])
    lignes = []
    for i, e in enumerate(etapes, 1):
        a, o = e.get("arguments", {}), e.get("outil", "")
        if o == "ouvrir_application":
            t = f"ouvrir {a.get('nom', '?')}"
        elif o == "choisir_menu":
            t = f"menu {a.get('chemin', '?')} dans {a.get('application', '?')}"
        elif o == "cliquer_libelle":
            t = f"cliquer « {a.get('libelle', '?')} » dans {a.get('application', '?')}"
        elif o == "taper_texte":
            t = f"taper {a.get('texte', '')} dans {a.get('application', '?')}"
        elif o == "raccourci_clavier":
            t = f"raccourci {a.get('touches', '?')}"
        elif o == "quitter_application":
            t = f"quitter {a.get('nom', '?')}"
        else:
            details = ", ".join(f"{k}={v}" for k, v in a.items())
            t = f"{o}({details})"
        lignes.append(f"{i}. {t}")
    return lignes


# --- Capture (macOS) ------------------------------------------------------------------------

def _decrire_element(AS, ax, el) -> dict:
    """Rôle, libellé et chemin de menu de l'élément cliqué (parents parcourus pour les menus)."""
    role = str(ax.attribut(el, "AXRole") or "")
    libelle = ax._libelle(el)
    if not libelle and role not in ROLES_SAISIE and role != "AXSecureTextField":
        v = ax.attribut(el, "AXValue")
        libelle = str(v)[:80] if isinstance(v, str) else ""
    info = {"role": role, "libelle": libelle}
    if role == "AXMenuItem":
        chemin, barre, courant = [], False, el
        for _ in range(8):
            if courant is None:
                break
            r = ax.attribut(courant, "AXRole")
            if r in ("AXMenuItem", "AXMenuBarItem"):
                t = str(ax.attribut(courant, "AXTitle") or "").strip()
                if t:
                    chemin.append(t)
                if r == "AXMenuBarItem":
                    barre = True
                    break
            elif r in ("AXMenuBar", "AXApplication"):
                break
            courant = ax.attribut(courant, "AXParent")
        info.update(menu=list(reversed(chemin)), barre=barre)
    return info


class Enregistreur:
    """Enregistre une démonstration. demarrer() puis arreter(nom) → {ok, texte, etapes, competence}."""

    def __init__(self, ctx, duree_max: float = DUREE_MAX_S):
        self.ctx = ctx
        self.duree_max = duree_max
        self.evenements: list[dict] = []
        self.actif = False
        self.debut = 0.0
        self._verrou = threading.Lock()
        self._fil: threading.Thread | None = None
        self._boucle = None
        self._tap = None
        self._minuterie: threading.Timer | None = None
        self._applis: dict[int, str] = {}
        self._resultat_auto: dict | None = None

    # --- Cycle ---------------------------------------------------------------------

    def demarrer(self) -> dict:
        if self.actif:
            return {"ok": True, "texte": "Enregistrement déjà en cours."}
        self.evenements = []
        self._resultat_auto = None
        self._lancer_ecoute()
        self.actif = True
        self.debut = time.monotonic()
        self._minuterie = threading.Timer(self.duree_max, self._arret_automatique)
        self._minuterie.daemon = True
        self._minuterie.start()
        self.ctx.emettre("demonstration", etat="debut", duree_max=int(self.duree_max))
        return {"ok": True, "texte": "Je regarde : fais la tâche normalement, puis arrête l'enregistrement "
                                     f"(arrêt automatique après {int(self.duree_max // 60)} min)."}

    def arreter(self, nom: str = "") -> dict:
        if not self.actif:
            if self._resultat_auto is not None:  # arrêté par la minuterie : résultat gardé
                r, self._resultat_auto = self._resultat_auto, None
                return r if not nom else self._conclure(nom)
            return {"ok": False, "texte": "Aucun enregistrement en cours.", "etapes": [], "competence": None}
        self._couper_ecoute()
        return self._conclure(nom)

    def _arret_automatique(self) -> None:
        if not self.actif:
            return
        self._couper_ecoute()
        self._resultat_auto = self._conclure("")
        self._resultat_auto["texte"] = "Enregistrement arrêté au bout de 10 minutes. " + self._resultat_auto["texte"]
        self.ctx.emettre("demonstration", etat="arret_automatique", texte=self._resultat_auto["texte"])

    def _conclure(self, nom: str) -> dict:
        with self._verrou:
            evenements = list(self.evenements)
        actions = regrouper(evenements)
        etapes = [_phrase(a) for a in actions]
        rec = recette(actions, nom)
        non_rejouables = sum(a["genre"] == "inutilisable" for a in actions)
        masques = sum(a["genre"] == "texte" and a["texte"] == MASQUE for a in actions)
        if not etapes:
            texte = "Je n'ai vu aucune action exploitable."
        else:
            texte = f"J'ai noté {len(etapes)} étape(s)."
            if rec:
                texte += " Je peux en faire une compétence rejouable."
            if non_rejouables:
                texte += f" {non_rejouables} clic(s) sans libellé ne seront pas rejoués."
            if masques:
                texte += " Les saisies masquées (mot de passe, données bancaires) ne sont jamais rejouées."
        self.ctx.emettre("demonstration", etat="fin")
        return {"ok": True, "texte": texte, "etapes": etapes, "competence": rec}

    # --- Écoute Quartz ----------------------------------------------------------------

    def _lancer_ecoute(self) -> None:
        try:
            import Quartz
            from .mac import accessibilite as ax
            ax._ax()  # Accessibilité nécessaire pour décrire les éléments cliqués
        except ImportError as e:
            raise ErreurOutil("Démonstration indisponible (macOS uniquement).") from e
        if hasattr(Quartz, "CGPreflightListenEventAccess") and not Quartz.CGPreflightListenEventAccess():
            if hasattr(Quartz, "CGRequestListenEventAccess"):
                Quartz.CGRequestListenEventAccess()  # inscrit MacAI dans la liste des Réglages
            raise ErreurOutil(AUTORISATION)
        masque = (Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown))
        pret, erreur = threading.Event(), {}

        def boucle():
            tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGTailAppendEventTap,
                                          Quartz.kCGEventTapOptionListenOnly, masque, self._rappel, None)
            if tap is None:
                erreur["e"] = AUTORISATION
                pret.set()
                return
            source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            self._boucle = Quartz.CFRunLoopGetCurrent()
            Quartz.CFRunLoopAddSource(self._boucle, source, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(tap, True)
            self._tap = tap
            pret.set()
            Quartz.CFRunLoopRun()
            Quartz.CGEventTapEnable(tap, False)

        self._fil = threading.Thread(target=boucle, daemon=True, name="demonstration")
        self._fil.start()
        pret.wait(5)
        if "e" in erreur:
            raise ErreurOutil(erreur["e"])

    def _couper_ecoute(self) -> None:
        self.actif = False
        if self._minuterie:
            self._minuterie.cancel()
        if self._boucle is not None:
            try:
                import Quartz
                Quartz.CFRunLoopStop(self._boucle)
            except ImportError:
                pass
        self._boucle = self._tap = None

    def ajouter(self, ev: dict) -> None:
        with self._verrou:
            if len(self.evenements) < EVENEMENTS_MAX:
                self.evenements.append({**ev, "t": round(time.monotonic() - self.debut, 2)})

    def _nom_pid(self, pid: int) -> str:
        if pid not in self._applis:
            from .mac import accessibilite as ax
            try:
                self._applis.update({a["pid"]: a["nom"] for a in ax.applis_ouvertes()})
            except Exception:  # noqa: BLE001 - lsappinfo indisponible : appli inconnue
                pass
        return self._applis.get(pid, "")

    def _rappel(self, proxy, genre, ev, refcon):
        """Appelé pour chaque événement (écoute passive : l'événement passe de toute façon)."""
        try:
            import Quartz
            if genre in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                if self._tap is not None:
                    Quartz.CGEventTapEnable(self._tap, True)
                return ev
            if not self.actif:
                return ev
            if genre == Quartz.kCGEventLeftMouseDown:
                self._clic(Quartz.CGEventGetLocation(ev))
            elif genre == Quartz.kCGEventKeyDown:
                self._touche(Quartz, ev)
        except Exception:  # noqa: BLE001 - un événement mal lu ne doit jamais casser l'écoute
            pass
        return ev

    def _clic(self, point) -> None:
        from .mac import accessibilite as ax
        AS = ax._ax()
        systeme = AS.AXUIElementCreateSystemWide()
        err, el = AS.AXUIElementCopyElementAtPosition(systeme, float(point.x), float(point.y), None)
        if err != 0 or el is None:
            return
        err, pid = AS.AXUIElementGetPid(el, None)
        app = self._nom_pid(int(pid)) if err == 0 else ""
        self.ajouter({"type": "clic", "application": app, **_decrire_element(AS, ax, el)})

    def _touche(self, Quartz, ev) -> None:
        from .mac import accessibilite as ax
        AS = ax._ax()
        drapeaux = Quartz.CGEventGetFlags(ev)
        code = Quartz.CGEventGetIntegerValueField(ev, Quartz.kCGKeyboardEventKeycode)
        focus = ax.attribut(AS.AXUIElementCreateSystemWide(), "AXFocusedUIElement")
        role = str(ax.attribut(focus, "AXRole") or "") if focus is not None else ""
        app = ""
        if focus is not None:
            err, pid = AS.AXUIElementGetPid(focus, None)
            app = self._nom_pid(int(pid)) if err == 0 else ""
        secret = role == "AXSecureTextField"
        if drapeaux & (F_CMD | F_CTRL) and not secret:
            _n, car = Quartz.CGEventKeyboardGetUnicodeString(ev, 4, None, None)
            touche = TOUCHES_SPECIALES.get(code) or str(car or "").lower()
            if not touche or not touche.isprintable():
                return
            mods = [m for f, m in ((F_CMD, "cmd"), (F_CTRL, "ctrl"), (F_ALT, "alt"), (F_MAJ, "maj")) if drapeaux & f]
            self.ajouter({"type": "raccourci", "touches": "+".join(mods + [touche]), "application": app})
            return
        if code in TOUCHES_SPECIALES:
            self.ajouter({"type": "touche", "special": TOUCHES_SPECIALES[code], "application": app})
            return
        if secret:  # aucune frappe d'un champ de mot de passe n'est gardée
            self.ajouter({"type": "touche", "caractere": "•", "application": app, "secret": True})
            return
        _n, car = Quartz.CGEventKeyboardGetUnicodeString(ev, 4, None, None)
        car = str(car or "")
        if car and car.isprintable():
            self.ajouter({"type": "touche", "caractere": car, "application": app})


def obtenir(ctx) -> Enregistreur:
    """Enregistreur unique de la session (gardé dans ctx.services["demonstration"])."""
    e = ctx.services.get("demonstration")
    if e is None:
        e = ctx.services["demonstration"] = Enregistreur(ctx)
    return e
