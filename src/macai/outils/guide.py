"""Assistant de logiciel : trouver où se trouve une commande (menus, boutons) et la montrer à l'écran, cliquer
sur un bouton par son libellé (étapes des démonstrations), et recettes toutes faites (ArtCraft…)."""
from __future__ import annotations

import re
import time

from .base import ErreurOutil, Resultat, Risque, interdire_achat, outil

# Équivalents anglais des mots d'un objectif (applis en anglais, ou menus mal traduits). Complète
# routeur.ANGLAIS, pensé pour les outils MCP.
FR_EN: dict[str, list[str]] = {
    "exporter": ["export"], "exporte": ["export"], "export": ["exporter"], "enregistrer": ["save"],
    "enregistre": ["save"], "sauvegarder": ["save"], "ouvrir": ["open"], "ouvre": ["open"], "imprimer": ["print"],
    "imprime": ["print"], "fermer": ["close"], "nouveau": ["new"], "nouvelle": ["new"], "creer": ["new", "create"],
    "copier": ["copy"], "coller": ["paste"], "couper": ["cut"], "annuler": ["undo"], "retablir": ["redo"],
    "rechercher": ["find", "search"], "chercher": ["find", "search"], "trouver": ["find"], "remplacer": ["replace"],
    "inserer": ["insert"], "ajouter": ["add", "insert"], "supprimer": ["delete", "remove"], "effacer": ["delete"],
    "dupliquer": ["duplicate"], "renommer": ["rename"], "partager": ["share"], "envoyer": ["send"],
    "affichage": ["view"], "afficher": ["show", "view"], "masquer": ["hide"], "zoom": ["zoom"],
    "agrandir": ["zoom", "enlarge"], "reglages": ["settings", "preferences"], "preferences": ["settings"],
    "parametres": ["settings", "preferences"], "police": ["font"], "taille": ["size"], "couleur": ["color"],
    "image": ["image", "picture"], "photo": ["photo", "image"], "tableau": ["table"], "lien": ["link"],
    "page": ["page"], "fenetre": ["window"], "onglet": ["tab"], "format": ["format"], "texte": ["text"],
    "selectionner": ["select"], "tout": ["all"], "aide": ["help"], "redimensionner": ["resize", "size"],
    "recadrer": ["crop"], "pivoter": ["rotate"], "tourner": ["rotate"], "convertir": ["convert", "export"],
    "importer": ["import"], "calque": ["layer"], "filtre": ["filter"], "pdf": ["pdf"], "fichier": ["file"],
    "edition": ["edit"], "modifier": ["edit"], "outils": ["tools"], "orthographe": ["spelling"],
    "signet": ["bookmark"], "favori": ["bookmark", "favorite"], "historique": ["history"],
    "telecharger": ["download"], "plein": ["full"], "ecran": ["screen"], "commentaire": ["comment"],
}
VIDES = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "a", "au", "aux", "en", "mon", "ma", "mes",
         "ce", "cette", "pour", "dans", "sur", "avec", "moi", "me", "il", "elle", "est", "comment", "faire", "fait",
         "fais", "on", "je", "tu", "peux", "veux", "voudrais", "montre", "montre-moi", "explique", "aide", "aide-moi",
         "se", "trouve", "trouver", "quoi", "quel", "quelle", "the", "to", "how", "do", "i", "of", "in", "an"}
MOTS_GUIDE = ["comment faire", "comment on fait", "ou est", "ou se trouve", "montre-moi", "guide",
              "explique comment", "aide-moi a", "comment je fais", "ou trouver"]
MENUS_MAX = 600   # commandes de menu lues au plus (une grosse appli en a quelques centaines)
PROFONDEUR_MENU = 3

# Roles qu'on peut montrer / cliquer par leur libellé (pas les textes ni les images).
CLIQUABLES = {"AXButton", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXLink", "AXTab",
              "AXDisclosureTriangle", "AXComboBox", "AXCell", "AXRow", "AXMenuItem", "AXTextField", "AXTextArea",
              "AXSearchField", "AXSlider", "AXIncrementor"}


def _ax():
    from ..mac import accessibilite as ax
    return ax


def _racine(mot: str) -> str:
    return mot.rstrip("s")[:5]


def mots_objectif(objectif: str) -> set[str]:
    """Racines des mots utiles de l'objectif, avec leurs équivalents anglais."""
    from ..agent.routeur import ANGLAIS, normaliser
    mots = [m for m in re.findall(r"[a-z0-9]+", normaliser(objectif).replace("'", " ")) if m not in VIDES]
    racines = set()
    for m in mots:
        if len(m) < 2:
            continue
        racines.add(_racine(m))
        for en in FR_EN.get(m, []) + ANGLAIS.get(m, []):
            racines.add(_racine(en))
        # « exporte » / « exportez » / « exportation » : même racine que « exporter ».
        for cle, ens in FR_EN.items():
            if len(m) >= 5 and _racine(cle) == _racine(m):
                racines.update(_racine(e) for e in ens)
    return racines


def score(texte: str, racines: set[str], poids_fin: str = "") -> float:
    """Nombre de racines de l'objectif retrouvées dans le texte ; la dernière partie (la commande elle-même)
    compte double."""
    from ..agent.routeur import normaliser
    def racines_de(t):
        return {_racine(m) for m in re.findall(r"[a-z0-9]+", normaliser(t)) if len(m) >= 2}
    tout = racines_de(texte)
    s = float(len(racines & tout))
    if poids_fin:
        s += len(racines & racines_de(poids_fin))
    return s


def classer(objectif: str, candidats: list[dict], cle: str = "chemin", n: int = 5) -> list[dict]:
    """Candidats ({chemin, …}) les plus proches de l'objectif, meilleurs d'abord (score > 0 seulement)."""
    racines = mots_objectif(objectif)
    if not racines:
        return []
    notes = []
    for i, c in enumerate(candidats):
        texte = str(c.get(cle, ""))
        fin = texte.rsplit(">", 1)[-1]
        s = score(texte, racines, fin)
        if s > 0:
            notes.append((-s, len(texte), i, c))
    notes.sort(key=lambda x: x[:3])
    return [c for *_, c in notes[:n]]


# --- Lecture des menus ------------------------------------------------------------------

MODIFS = [(1, "⇧"), (2, "⌥"), (4, "⌃")]


def _raccourci(item) -> str:
    ax = _ax()
    car = ax.attribut(item, "AXMenuItemCmdChar")
    if not car or str(car).strip() == "":
        return ""
    mods = ax.attribut(item, "AXMenuItemCmdModifiers") or 0
    try:
        mods = int(mods)
    except (TypeError, ValueError):
        mods = 0
    texte = "".join(s for bit, s in MODIFS if mods & bit)
    if not mods & 8:  # bit 8 : pas de ⌘
        texte += "⌘"
    return texte + str(car).upper()


def chemins_menus(barre, profondeur_max: int = PROFONDEUR_MENU) -> list[dict]:
    """Toutes les commandes de la barre des menus : [{chemin: « Fichier > Exporter > PDF… », raccourci,
    actif}], sous-menus compris (le menu Pomme est ignoré)."""
    ax = _ax()
    sortie: list[dict] = []

    def visiter(menu_el, parents: list[str], profondeur: int):
        for sous in ax.attribut(menu_el, "AXChildren") or []:  # le AXMenu
            for item in ax.attribut(sous, "AXChildren") or []:
                if len(sortie) >= MENUS_MAX:
                    return
                titre = str(ax.attribut(item, "AXTitle") or "").strip()
                if not titre:
                    continue  # séparateur
                chemin = parents + [titre]
                enfants = ax.attribut(item, "AXChildren") or []
                if enfants and profondeur < profondeur_max:
                    visiter(item, chemin, profondeur + 1)
                else:
                    sortie.append({"chemin": " > ".join(chemin), "raccourci": _raccourci(item),
                                   "actif": ax.attribut(item, "AXEnabled") is not False})

    for titre_el in (ax.attribut(barre, "AXChildren") or [])[1:]:
        titre = str(ax.attribut(titre_el, "AXTitle") or "").strip()
        if titre:
            visiter(titre_el, [titre], 1)
    return sortie


def _barre_menus(application: str):
    ax = _ax()
    AS = ax._ax()
    pid, nom = ax.pid_application(application)
    barre = ax.attribut(AS.AXUIElementCreateApplication(pid), "AXMenuBar")
    if barre is None:
        raise ErreurOutil(f"{nom} n'a pas de barre des menus lisible.")
    return pid, nom, barre


def rectangle(el) -> tuple[float, float, float, float] | None:
    """(x, y, largeur, hauteur) en points d'écran, origine en haut à gauche (repère de l'Accessibilité)."""
    ax = _ax()
    AS = ax._ax()
    pos, taille = ax.attribut(el, "AXPosition"), ax.attribut(el, "AXSize")
    if pos is None or taille is None:
        return None
    ok_p, p = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
    ok_t, t = AS.AXValueGetValue(taille, AS.kAXValueCGSizeType, None)
    if not (ok_p and ok_t) or t.width <= 0 or t.height <= 0:
        return None
    return float(p.x), float(p.y), float(t.width), float(t.height)


def _surligner(ctx, rect, texte: str) -> None:
    x, y, l, h = rect
    ctx.emettre("surligner", x=round(x, 1), y=round(y, 1), largeur=round(l, 1), hauteur=round(h, 1), texte=texte)


def _memoriser_fenetre(ctx, titre: str, elements: list) -> None:
    """Même mémoire que lire_fenetre : les numéros servent ensuite à montrer_element et cliquer_element."""
    ax = _ax()
    appli = titre.split(" — ", 1)[0]
    ctx.services["ax_elements"] = elements
    ctx.services["ax_application"] = appli
    try:
        ctx.services["ax_pid"] = ax.pid_application(appli)[0]
    except ErreurOutil:
        ctx.services["ax_pid"] = 0
    try:
        from . import fenetres
        fenetres._DERNIERE.update(app=appli, pid=ctx.services["ax_pid"], elements=elements)
    except ImportError:
        pass


# --- Outils du guide ---------------------------------------------------------------------

@outil("guider", "Explique comment faire quelque chose dans un logiciel : trouve les commandes de menu et les "
       "boutons qui correspondent à l'objectif (ex. « exporter en PDF » dans Pages). Ne clique rien.", "fenetres",
       {"application": ("string", "nom de l'application (ouverte)"),
        "objectif": ("string", "ce que l'utilisateur veut faire, ex. « exporter en PDF »")},
       mots_cles=MOTS_GUIDE)
def guider(ctx, application, objectif):
    from ..agent.routeur import normaliser
    ax = _ax()
    if normaliser(str(application)).strip() in ("macai", ""):
        raise ErreurOutil("Précise le logiciel concerné (paramètre application).")
    try:
        _pid, nom, barre = _barre_menus(application)
    except ErreurOutil as e:
        if "n'est pas ouverte" in str(e):
            raise ErreurOutil(f"{e} Ouvre-la d'abord avec ouvrir_application, puis relance guider.") from e
        raise
    commandes = chemins_menus(barre)
    menus_trouves = classer(objectif, commandes)
    boutons, titre = [], nom
    try:
        titre, elements = ax.explorer_fenetre(nom, textes=False)
        _memoriser_fenetre(ctx, titre, elements)
        candidats = [{"chemin": e.libelle or e.valeur, "numero": i, "role": e.role}
                     for i, e in enumerate(elements, 1) if e.role in CLIQUABLES and (e.libelle or e.valeur)]
        boutons = classer(objectif, candidats, n=5)
    except ErreurOutil:
        elements = []  # pas de fenêtre visible : les menus suffisent
    lignes = [f"Logiciel : {nom} — objectif : {objectif}"]
    if menus_trouves:
        lignes.append("Commandes de menu possibles (la meilleure d'abord) :")
        for c in menus_trouves:
            extra = f" (raccourci {c['raccourci']})" if c["raccourci"] else ""
            extra += "" if c["actif"] else " [grisée pour l'instant]"
            lignes.append(f"- {c['chemin']}{extra}")
    if boutons:
        lignes.append("Boutons visibles dans la fenêtre :")
        for b in boutons:
            lignes.append(f"- n° {b['numero']} [{ax.ROLES.get(b['role'], b['role'])}] {b['chemin']}")
    if not menus_trouves and not boutons:
        titres = sorted({c["chemin"].split(" > ", 1)[0] for c in commandes}, key=lambda t: t)
        lignes.append("Rien ne correspond directement. Menus de l'application : " + ", ".join(titres))
        lignes.append("Consigne : propose à l'utilisateur de regarder ces menus, ou utilise voir_ecran.")
    else:
        lignes.append("Consigne : explique les étapes en une ou deux phrases (« Ouvre le menu Fichier, puis "
                      "Exporter… »). Pour les montrer à l'écran : montrer_menu (chemin de menu) ou montrer_element "
                      "(numéro de bouton). Ne clique pas à la place de l'utilisateur sauf s'il le demande.")
    return Resultat(True, "\n".join(lignes), {"menus": [c["chemin"] for c in menus_trouves],
                                              "boutons": [b["numero"] for b in boutons]})


@outil("montrer_element", "Surligne à l'écran un élément de fenêtre par son numéro (donné par lire_fenetre ou "
       "guider), pour montrer à l'utilisateur où cliquer. Ne clique pas.", "fenetres",
       {"numero": ("integer", "numéro de l'élément")})
def montrer_element(ctx, numero):
    ax = _ax()
    els = ctx.services.get("ax_elements")
    if not els:
        raise ErreurOutil("Lis d'abord la fenêtre avec lire_fenetre (ou guider) pour connaître les numéros.")
    n = int(numero)
    if not 1 <= n <= len(els):
        raise ErreurOutil(f"Numéro {n} invalide (1 à {len(els)}).")
    e = els[n - 1]
    rect = rectangle(e.ref)
    if rect is None:
        raise ErreurOutil("Position de cet élément inconnue (hors écran ou masqué).")
    libelle = e.libelle or e.valeur or ax.ROLES.get(e.role, e.role)
    _surligner(ctx, rect, libelle)
    return Resultat(True, f"« {libelle} » est surligné à l'écran.", {"rect": list(rect)})


@outil("montrer_menu", "Surligne à l'écran le menu à ouvrir dans la barre des menus et rappelle le chemin à "
       "suivre (ex. « Fichier > Exporter > PDF… »). N'ouvre ni ne choisit rien.", "fenetres",
       {"application": ("string", "nom de l'application"),
        "chemin": ("string", "chemin de menu, ex. « Fichier > Exporter > PDF… »")})
def montrer_menu(ctx, application, chemin):
    from ..agent.routeur import normaliser
    ax = _ax()
    parties = [p.strip() for p in re.split(r"\s*>\s*", str(chemin)) if p.strip()]
    if not parties:
        raise ErreurOutil("Donne un chemin de menu, ex. « Fichier > Exporter… ».")
    _pid, nom, barre = _barre_menus(application)
    titre_el = None
    for el in (ax.attribut(barre, "AXChildren") or [])[1:]:
        if normaliser(str(ax.attribut(el, "AXTitle") or "")).strip() == normaliser(parties[0]):
            titre_el = el
            break
    if titre_el is None:
        titres = [str(ax.attribut(el, "AXTitle") or "") for el in (ax.attribut(barre, "AXChildren") or [])[1:]]
        raise ErreurOutil(f"Pas de menu « {parties[0]} » dans {nom}. Menus : {', '.join(t for t in titres if t)}.")
    etapes = f"clique sur « {parties[0]} » dans la barre des menus en haut de l'écran"
    if len(parties) > 1:
        etapes += ", puis " + " > ".join(f"« {p} »" for p in parties[1:])
    rect = rectangle(titre_el)
    if rect is not None:
        _surligner(ctx, rect, parties[0])
    return Resultat(True, f"Dans {nom}, {etapes}." + ("" if rect else " (position du menu inconnue)"),
                    {"chemin": " > ".join(parties)})


def _risque_cliquer_libelle(args: dict) -> Risque:
    from .fenetres import _risque_selon
    return _risque_selon(str(args.get("application", "")), True, str(args.get("libelle", "")))


def trouver_par_libelle(elements: list, libelle: str):
    """Élément cliquable au libellé exact (sans casse ni accents), sinon le seul qui le contient."""
    from ..agent.routeur import normaliser
    cible = normaliser(str(libelle)).strip().rstrip(".…").strip()
    if not cible:
        return None
    candidats = [e for e in elements if e.role in CLIQUABLES]

    def propre(e):
        return normaliser(e.libelle or e.valeur or "").strip().rstrip(".…").strip()

    exacts = [e for e in candidats if propre(e) == cible]
    if exacts:
        return exacts[0]
    proches = [e for e in candidats if cible in propre(e)]
    return proches[0] if len(proches) == 1 else None


@outil("cliquer_libelle", "Clique sur un bouton (ou onglet, case, lien) d'une application désigné par son "
       "libellé exact, ex. « Exporter ». Sert surtout aux compétences apprises par démonstration.", "fenetres",
       {"application": ("string", "nom de l'application"), "libelle": ("string", "libellé du bouton")},
       risque=_risque_cliquer_libelle, annonce=lambda a: f"Cliquer sur « {a['libelle']} » dans {a['application']}")
def cliquer_libelle(ctx, application, libelle):
    ax = _ax()
    interdire_achat(libelle, bouton=True)
    titre, elements = ax.explorer_fenetre(application, textes=False)
    _memoriser_fenetre(ctx, titre, elements)
    e = trouver_par_libelle(elements, libelle)
    if e is None:
        raise ErreurOutil(f"Pas de bouton « {libelle} » dans {titre}. Relis la fenêtre avec lire_fenetre.")
    interdire_achat(e.libelle, e.valeur, bouton=True)
    ax.appuyer(e.ref)
    time.sleep(0.4)
    return f"Clic sur « {e.libelle or e.valeur} » dans {titre.split(' — ', 1)[0]}."


# --- Recettes toutes faites ----------------------------------------------------------------

def _biblio(ctx):
    b = ctx.service("competences")
    if b is None:
        raise ErreurOutil("Compétences indisponibles.")
    return b


@outil("competences_proposees", "Liste les compétences toutes faites (recettes prêtes, ex. pour PhotoCraft, "
       "VectorCraft, LightCraft) qu'on peut installer.", "competences", {}, mac_seulement=False,
       mots_cles=["competences proposees", "competences toutes faites", "recettes toutes faites",
                  "modeles de competences", "competences disponibles"])
def competences_proposees(ctx):
    from ..competences.modeles import modeles_disponibles
    dispo = modeles_disponibles(ctx.registre)
    biblio = ctx.service("competences")
    installees = set(biblio.competences) if biblio else set()
    if not dispo:
        return "Aucune compétence toute faite disponible (les logiciels concernés ne sont pas connectés)."
    lignes = [f"- {m['nom']} : {m['description']} (paramètres : {', '.join(m.get('parametres') or {}) or 'aucun'})"
              + (" [déjà installée]" if m["nom"] in installees else "") for m in dispo]
    return Resultat(True, "Compétences toutes faites (installer_competence_modele pour en ajouter une) :\n"
                    + "\n".join(lignes), {"modeles": [m["nom"] for m in dispo]})


@outil("installer_competence_modele", "Installe une compétence toute faite (nom donné par "
       "competences_proposees).", "competences", {"nom": ("string", "nom de la compétence toute faite")},
       risque=Risque.CREATION, mac_seulement=False, annonce=lambda a: f"Installer la compétence {a['nom']}")
def installer_competence_modele(ctx, nom):
    from ..competences.modeles import installer_modele
    try:
        c = installer_modele(_biblio(ctx), nom)
    except (KeyError, ValueError) as e:
        raise ErreurOutil(str(e.args[0] if e.args else e)) from e
    params = ", ".join(c.parametres) or "aucun"
    return Resultat(True, f"Compétence « {c.nom} » installée : {c.description} (paramètres : {params}).",
                    {"competence": c.nom})
