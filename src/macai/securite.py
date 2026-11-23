"""Règles de sécurité communes à tous les outils.

Principe (relecture de sécurité de novembre 2026) : le niveau de risque doit porter sur ce que macOS va RÉELLEMENT
faire, pas sur la chaîne écrite par le modèle. « Messages.app », « maj+cmd+d », « ~/library/LaunchAgents » ou
« /System/Volumes/Data/Users/… » désignent la même chose que leur forme habituelle : ils doivent avoir le même
risque. D'où une seule normalisation, ici, utilisée par le calcul du risque ET par l'exécution.

Deuxième principe : le modèle est entièrement manipulable par un contenu piégé (page web, mail, fichier, écran).
Dès qu'un contenu extérieur a été lu pendant une demande, toute donnée qui sortirait du Mac (adresse web,
question à une IA, saisie dans un navigateur ou une messagerie) ou qui s'installerait durablement (mémoire,
compétence) sans venir de la demande de l'utilisateur demande sa confirmation.
"""
from __future__ import annotations

import os
import re
import unicodedata
import urllib.parse
from pathlib import Path

# --- Texte -----------------------------------------------------------------------------------------------------


def texte_normal(t) -> str:
    """Forme canonique (NFKC : ＜ → <, ﬁ → fi, accents composés) sans caractères invisibles (Cf : zéro largeur,
    contrôle de sens d'écriture…) qui permettent d'écrire « Ach​eter » pour tromper un filtre."""
    t = unicodedata.normalize("NFKC", str(t or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Cf")


def simple(t) -> str:
    """Minuscules sans accents, après texte_normal : pour comparer des mots."""
    t = unicodedata.normalize("NFD", texte_normal(t).casefold())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").replace("’", "'")


# --- Applications ------------------------------------------------------------------------------------------------

# Catégories par mots du nom (sous-chaîne à frontière de mot) : « Microsoft Outlook », « Spark Desktop »,
# « WhatsApp Beta » sont reconnus, sans liste exacte à tenir à jour.
APPLIS = {
    "ia": ("claude", "chatgpt", "le chat", "mistral", "perplexity", "gemini", "copilot"),
    "execution": ("terminal", "iterm", "iterm2", "warp", "ghostty", "alacritty", "kitty", "wezterm", "hyper",
                  "editeur de script", "script editor", "automator", "raccourcis", "shortcuts", "trousseau",
                  "keychain", "utilitaire de disque", "disk utility", "visual studio code", "vscode", "cursor",
                  "xcode", "windsurf", "zed", "sublime text", "textmate", "bbedit", "nova", "pycharm", "intellij",
                  "android studio", "docker", "utm", "parallels"),
    "messagerie": ("mail", "messages", "message", "whatsapp", "slack", "discord", "telegram", "signal", "teams",
                   "outlook", "messenger", "spark", "thunderbird", "facetime", "skype", "zoom", "mimestream",
                   "beeper", "wechat", "viber", "element", "mattermost", "linkedin", "airmail", "canary",
                   "superhuman", "gmail", "google chat", "kakaotalk", "threema", "wire", "webex", "rocket chat",
                   "line", "twitter", "tweetbot", "ivory", "mastodon", "bluesky", "instagram", "facebook"),
    "navigateur": ("chrome", "google chrome", "safari", "firefox", "arc", "edge", "microsoft edge", "brave",
                   "opera", "vivaldi", "orion", "chromium", "duckduckgo", "zen", "sigmaos", "dia"),
}
# Applis dont le nom exact (seul) suffit : « Code » est VS Code, mais « Claude Code » est Claude.
EXACTES = {"code": "execution"}


def appli_canonique(nom) -> str:
    """Nom réel de l'application que macOS ouvrira pour ce nom (« Messages.app », « le Terminal », « chrome »),
    simplifié. Même résolution que les outils (trouver_application), sinon le nom nettoyé."""
    brut = re.sub(r"\.app$", "", simple(nom).strip().strip("\"'« »").strip(), flags=re.I).strip()
    brut = re.sub(r"^(l'|le |la |les |l'application |l'appli |application |appli |app )", "", brut).strip()
    try:
        from .outils.applications import trouver_application
        app = trouver_application(brut) if brut else None
    except Exception:  # noqa: BLE001 - hors Mac, ou applications illisibles : on garde le nom donné
        app = None
    return simple(app.stem) if app is not None else brut


def categorie_appli(nom, deja_canonique: bool = False) -> str:
    """« execution », « messagerie », « navigateur », « ia » ou « autre » (l'IA d'abord : « ChatGPT » contient
    « chat » mais n'engage personne)."""
    a = nom if deja_canonique else appli_canonique(nom)
    a = re.sub(r"[^a-z0-9' ]+", " ", simple(a)).strip()
    if not a:
        return "autre"
    if a in EXACTES:
        return EXACTES[a]
    for cat, mots in APPLIS.items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", a) for m in mots):
            return cat
    return "autre"


# --- Clavier -----------------------------------------------------------------------------------------------------

MODIFICATEURS = {"cmd": "cmd", "command": "cmd", "commande": "cmd", "⌘": "cmd", "meta": "cmd", "super": "cmd",
                 "maj": "maj", "shift": "maj", "⇧": "maj", "majuscule": "maj",
                 "alt": "alt", "option": "alt", "opt": "alt", "⌥": "alt",
                 "ctrl": "ctrl", "control": "ctrl", "controle": "ctrl", "⌃": "ctrl"}
TOUCHES = {"entree": "entree", "enter": "entree", "return": "entree", "retour": "entree", "↩": "entree",
           "⏎": "entree", "valider": "entree", "effacer": "effacer", "delete": "effacer", "backspace": "effacer",
           "⌫": "effacer", "retour arriere": "effacer", "suppr": "suppr", "supprimer": "suppr", "⌦": "suppr",
           "forwarddelete": "suppr", "del": "suppr", "echap": "echap", "escape": "echap", "esc": "echap",
           "espace": "espace", "space": "espace", "tabulation": "tab"}


def touches_normalisees(touches) -> tuple[list[str], str]:
    """(modificateurs canoniques triés, touche canonique), exactement comme le raccourci sera envoyé.
    « maj+cmd+d », « Command + Shift + D », « +entree », « cmd-entrée » donnent la même chose."""
    t = simple(touches).replace("\t", " ").strip()
    morceaux = [m.strip() for m in re.split(r"\s*[+]\s*|(?<=[a-z⌘⇧⌥⌃])-(?=[a-z⌘⇧⌥⌃↩⌫])", t) if m.strip()]
    if len(morceaux) == 1 and " " in morceaux[0] and morceaux[0] not in TOUCHES:
        morceaux = morceaux[0].split()  # « cmd entree »
    mods = sorted({MODIFICATEURS[m] for m in morceaux if m in MODIFICATEURS})
    autres = [TOUCHES.get(m, m.replace(" ", "")) for m in morceaux if m not in MODIFICATEURS]
    return mods, (autres[-1] if autres else "")


def raccourci_sensible(mods: list[str], touche: str, categorie: str, contenu_lu: bool = False) -> bool:
    """Raccourcis qui envoient, exécutent ou suppriment."""
    m = set(mods)
    if touche == "entree" and (categorie in ("execution", "messagerie", "navigateur") or "cmd" in m
                               or (categorie == "ia" and contenu_lu)):
        return True  # envoyer, exécuter, valider un formulaire web ; ⌘↩ envoie presque partout
    if touche in ("effacer", "suppr") and m & {"cmd", "alt"}:
        return True  # ⌘⌫ Corbeille, ⌘⌥⇧⌫ vide la Corbeille sans dialogue
    if touche == "d" and {"cmd", "maj"} <= m:
        return True  # Mail : envoyer
    if touche == "v" and "cmd" in m and (categorie == "execution" or (categorie in ("ia", "messagerie")
                                                                      and contenu_lu)):
        return True  # coller dans un Terminal exécute la ligne ; le presse-papiers contourne les autres filtres
    return False


def contient_retour(texte) -> bool:
    """Un retour à la ligne tapé dans une messagerie ou un Terminal vaut Entrée."""
    return bool(re.search(r"[\r\n\x03  ]", str(texte or "")))


# --- Chemins -----------------------------------------------------------------------------------------------------

LIEN_SYSTEME = "/system/volumes/data/"  # « firmlink » : même fichier que /Users/… vu par un autre chemin


def cle_chemin(p) -> str:
    """Clé de comparaison d'un chemin : liens résolus, firmlink /System/Volumes/Data retiré, sans casse ni forme
    Unicode (APFS confond « Library » et « library », « é » composé et décomposé)."""
    try:
        r = os.path.realpath(os.path.expanduser(str(p)))
    except (OSError, ValueError):
        r = str(p)
    r = unicodedata.normalize("NFD", r).casefold()
    if r.startswith(LIEN_SYSTEME):
        r = "/" + r[len(LIEN_SYSTEME):]
    return r.rstrip("/") or "/"


def sous(cle: str, racine: str) -> bool:
    return cle == racine or cle.startswith(racine.rstrip("/") + "/")


# --- Contenu extérieur lu pendant la demande ------------------------------------------------------------------

# Outils dont le résultat est écrit par MacAI ou macOS lui-même (pas de contenu d'un tiers).
NON_CONTAMINANTS = {"regler_volume", "controle_media", "etat_memoire", "infos_systeme", "notifier",
                    "capture_ecran", "ouvrir_application", "quitter_application", "applications_ouvertes",
                    "attendre", "ouvrir_reglage", "etat_index", "indexer_maintenant", "creer_dossier",
                    "ecrire_fichier_texte", "creer_document_word", "creer_tableur", "creer_csv",
                    "creer_presentation", "creer_rappel", "creer_evenement", "creer_note", "retenir", "oublier",
                    "lister_taches", "supprimer_tache", "annuler_derniere_action", "ouvrir_url", "chrome_rechercher",
                    "naviguer_page"}
LUS_MAX = 400_000


def debut_demande(ctx) -> None:
    ctx.services["contenu_lu"] = False
    ctx.services["textes_lus"] = []


def marquer_lu(ctx, nom: str, texte: str) -> None:
    if nom in NON_CONTAMINANTS:
        return
    ctx.services["contenu_lu"] = True
    lus = ctx.services.setdefault("textes_lus", [])
    if sum(len(x) for x in lus) < LUS_MAX:
        lus.append(simple(urllib.parse.unquote(str(texte or "")))[:100_000])


def contenu_lu(ctx) -> bool:
    return bool(ctx.services.get("contenu_lu"))


MOT = re.compile(r"[a-z0-9]+")


def donnees_nouvelles(texte, demande) -> list[str]:
    """Mots du texte absents de la demande de l'utilisateur, s'ils forment assez de données pour qu'il s'agisse
    d'informations lues ailleurs (un secret, un mail, un résumé) et non d'une reformulation. Liste vide sinon."""
    connus = set(MOT.findall(simple(demande)))
    nouveaux = [w for w in MOT.findall(simple(urllib.parse.unquote(str(texte or "")))) if w not in connus]
    longs = [w for w in nouveaux if len(w) >= 3]
    if (sum(len(w) for w in longs) > 30 or any(len(w) >= 16 for w in nouveaux)
            or any(sum(c.isdigit() for c in w) >= 6 for w in nouveaux)
            or any(len(w) >= 5 and re.search(r"[a-z]", w) and re.search(r"\d", w) for w in nouveaux)):
        return nouveaux  # beaucoup de texte nouveau, ou un mot qui ressemble à un code (« azerty12 », « sk9f8e… »)
    return []


def url_vue(ctx, url: str) -> bool:
    """Adresse donnée par l'utilisateur ou présente telle quelle dans ce qui a été lu (suivre un lien)."""
    u = simple(urllib.parse.unquote(str(url or ""))).strip().rstrip("/")
    u_sans = re.sub(r"^https?://(www\.)?", "", u)
    if len(u_sans) < 4:
        return True
    demande = simple(urllib.parse.unquote(ctx.services.get("demande", "")))
    return u_sans in demande or any(u_sans in t for t in ctx.services.get("textes_lus", []))


def adresse_locale(url: str) -> bool:
    """Le Mac lui-même, la box, le réseau local : une page ne doit pas pouvoir les faire interroger."""
    import ipaddress
    import socket
    if not re.match(r"^[a-z][a-z0-9+.-]*://", str(url), re.I):
        url = "https://" + str(url)
    hote = (urllib.parse.urlparse(url).hostname or "").strip("[]").lower()
    if not hote or hote == "localhost" or hote.endswith((".local", ".localhost", ".internal", ".lan", ".home")):
        return True
    try:
        adresses = {i[4][0] for i in socket.getaddrinfo(hote, None)}
    except (OSError, UnicodeError):
        return False  # inconnue : le navigateur échouera aussi
    for a in adresses:
        try:
            ip = ipaddress.ip_address(a.split("%")[0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast \
                or ip.is_unspecified:
            return True
    return False


# Outils qui font sortir un texte du Mac (vers le web, une IA, une page, une messagerie) ou l'installent
# durablement : paramètre qui porte ce texte.
SORTIES_TEXTE = {"chrome_rechercher": "requete", "youtube_lire": "requete", "recherche_web": "requete",
                 "rechercher_et_lire": "question", "demander_a_claude": "question", "ecrire_et_envoyer": "texte",
                 "remplir_page": "texte", "taper_texte": "texte", "saisir_element": "texte",
                 "retenir": "fait", "creer_competence": "description", "creer_evenement": "titre"}
SORTIES_URL = {"ouvrir_url": "url", "lire_page_web": "url"}
# Taper ou saisir n'est une sortie que dans ces applis (dans TextEdit ou Pages, c'est un document local).
APPLIS_SORTIE = {"navigateur", "ia", "messagerie", "execution"}


def sortie_a_confirmer(ctx, nom: str, args: dict, categorie: str = "") -> str:
    """Raison de confirmer (texte pour l'utilisateur), ou "" si rien ne sort sans son accord."""
    if not contenu_lu(ctx):
        return ""
    demande = ctx.services.get("demande", "")
    if nom in SORTIES_URL:
        url = str(args.get(SORTIES_URL[nom]) or "")
        if url_vue(ctx, url):
            return ""
        # Adresse construite par le modèle : chaque mot du chemin et des paramètres doit venir de la demande (un
        # secret court, « ?p=azerty12 », suffit à fuir), et le domaine doit être connu (demande ou contenu lu) :
        # sinon un sous-domaine « azerty12.evil.example » transporterait les données.
        partie = urllib.parse.urlparse(url if "://" in url else "https://" + url)
        connus = set(MOT.findall(simple(demande)))
        reste = simple(urllib.parse.unquote(f"{partie.path} {partie.query} {partie.fragment}"))
        nouveaux = [w for w in MOT.findall(reste) if w not in connus and w not in ("www", "html", "htm", "php")]
        hote = simple(partie.hostname or "")
        hote_connu = not hote or hote in simple(demande) or any(hote in t for t in ctx.services.get("textes_lus", []))
        if nouveaux or not hote_connu:
            return "cette adresse contient des informations qui ne viennent pas de ta demande"
        return ""
    if nom in SORTIES_TEXTE:
        if nom in ("taper_texte", "saisir_element") and categorie not in APPLIS_SORTIE:
            return ""
        if nom == "creer_evenement" and not str(args.get("calendrier") or "").strip():
            return ""  # agenda par défaut : personnel ; un calendrier nommé peut être partagé avec d'autres
        if donnees_nouvelles(args.get(SORTIES_TEXTE[nom]) or "", demande):
            return "ce texte contient des informations qui ne viennent pas de ta demande"
    return ""


def confirmer_pendant(ctx, phrase: str, nom: str, args: dict) -> None:
    """Confirmation demandée par l'outil lui-même quand ce qu'il va vraiment toucher n'est connu qu'au moment
    d'agir (libellé réel du bouton trouvé, page qui a changé). Rien si l'action a déjà été confirmée."""
    from .outils.base import ErreurOutil
    if ctx is None or ctx.services.get("outil_confirme"):
        return
    demander = getattr(ctx, "demander_confirmation", None)
    if demander is not None:
        ctx.emettre("confirmation", outil=nom, arguments=args, phrase=phrase)
        if demander(phrase, nom, args):
            ctx.services["outil_confirme"] = True
            return
    raise ErreurOutil("L'utilisateur a refusé cette action. Ne la refais pas.")
