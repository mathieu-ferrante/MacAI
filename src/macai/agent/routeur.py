"""Choisit les outils à montrer au modèle pour une demande.

Un petit modèle (4 milliards de paramètres) se trompe davantage quand on lui présente 80 outils :
on ne lui donne que les groupes pertinents (≈ 10 à 20 outils), choisis par mots-clés.
"""
from __future__ import annotations

import re
import unicodedata

from ..outils.base import APPS_MESSAGERIE, Registre

MOTS_GROUPES: dict[str, list[str]] = {
    "systeme": ["volume", "son", "muet", "musique", "pause", "lecture", "suivant", "precedent",
                "presse-papier", "copie", "colle", "capture", "screenshot", "memoire", "ram", "lent",
                "rame", "ralenti", "batterie", "notification", "terminal", "commande", "shell",
                "heure", "date", "disque", "stockage", "espace", "wifi", "luminosite", "veille"],
    "applications": ["ouvre", "ouvrir", "lance", "lancer", "ferme", "fermer", "quitte", "quitter",
                     "appli", "application", "logiciel", "app", "programme", "bascule", "demarre"],
    "fichiers": ["fichier", "dossier", "document", "pdf", "word", "docx", "excel", "xlsx", "tableur",
                 "tableau", "csv", "powerpoint", "pptx", "presentation", "texte", "markdown", "cree",
                 "creer", "ecris", "ecrire", "redige", "range", "ranger", "deplace", "renomme",
                 "supprime", "efface", "corbeille", "bureau", "telechargement", "lis", "lire", "resume",
                 "resumer", "analyse", "convertis", "contenu", "image", "photo"],
    "recherche": ["trouve", "trouver", "cherche", "chercher", "retrouve", "ou est", "ou sont", "photo",
                  "image", "facture", "capture", "scan", "fichier", "indexe", "indexation"],
    "web": ["chrome", "youtube", "google", "site", "page", "video", "internet", "web", "navigateur",
            "onglet", "url", "http", "www", "recherche sur", "regarde", "musique", "wikipedia", "lien"],
    "fenetres": ["clique", "cliquer", "bouton", "menu", "fenetre", "tape", "taper", "ecran", "champ",
                 "formulaire", "selectionne", "coche", "fais defiler", "dans l'appli", "dans le logiciel"],
    "organisation": ["rappel", "rappelle-moi", "calendrier", "agenda", "rendez-vous", "rdv", "reunion",
                     "evenement", "note", "notes", "mail", "mails", "e-mail", "email", "courriel", "message",
                     "planning", "emploi du temps", "imessage", "sms", "texto", "reponds", "aujourd'hui", "demain",
                     "j'ai quoi", "dentiste", "medecin"],
    "memoire": ["souviens", "souvenir", "retiens", "retenir", "oublie", "oublier", "rappelle-toi",
                "sais-tu", "prefere", "preference", "je m'appelle", "mon nom", "qui suis-je", "j'aime"],
    "competences": ["competence", "skill", "recette", "automatise", "comme la derniere fois"],
    "onshape": ["onshape", "cao", "3d", "cube", "piece", "cylindre", "pave", "modelise", "extrusion",
                "esquisse", "cad"],
}

GROUPES_DEFAUT = ["applications", "fichiers", "recherche", "web", "systeme"]
TOUJOURS = ["memoire"]
MAX_OUTILS = 14
MAX_DESIGNES = 9
# Outils de haut niveau d'abord (s'ils existent) : ils doivent survivre à la limite du nombre d'outils.
PILOTAGE = ["demander_a_claude", "ecrire_et_envoyer", "ouvrir_application", "lire_fenetre", "cliquer_element", "saisir_element", "taper_texte",
            "raccourci_clavier", "attendre"]
# Une deuxième action après l'ouverture d'une appli : il faudra lire sa fenêtre, cliquer, écrire.
ACTION_DANS_APPLI = re.compile(r"\b(et|puis|ensuite|va|passe|demande|ecris|tape|envoie|mets|active|desactive|"
                               r"choisis|selectionne|clique|appuie|remplis|pose|dis-lui|demande-lui|"
                               r"ecris-lui)\b|,")
# « Écris à Claude », « demande à ChatGPT », « envoie-le sur WhatsApp » : agir dans une appli connue,
# même sans « ouvre ».
APPS_CONNUES = sorted({"claude", "chatgpt", "gemini", "le chat", "mistral", "perplexity", "copilot", "notes",
                       "reglages", "reglages systeme", *APPS_MESSAGERIE}, key=len, reverse=True)
VERS_APPLI = re.compile(r"\b(ecris|ecrire|ecris-lui|demande|demander|demande-lui|pose|poser|dis(?!-moi)|dire|envoie|"
                        r"envoyer|envoie-lui|reponds|repondre)\b.*?\b(a|au|sur|dans|via|avec)\s+"
                        r"(?:l'(?:appli(?:cation)?\s+)?)?(" + "|".join(map(re.escape, APPS_CONNUES)) + r")\b")
# Les outils des logiciels tiers (MCP) sont décrits en anglais : verbes et noms français courants traduits.
ANGLAIS: dict[str, list[str]] = {
    "ouvre": ["open"], "ouvrir": ["open"], "convertis": ["export", "convert", "open"],
    "convertir": ["export", "convert", "open"], "exporte": ["export"], "exporter": ["export"],
    "enregistre": ["save", "export"], "enregistrer": ["save", "export"], "sauvegarde": ["save"],
    "cree": ["new", "create"], "creer": ["new", "create"], "nouveau": ["new"], "nouvelle": ["new"],
    "ferme": ["close"], "fermer": ["close"], "ajoute": ["add", "import"], "ajouter": ["add", "import"],
    "importe": ["import"], "importer": ["import"], "applique": ["run", "apply", "command"],
    "filtre": ["filter", "command"], "flou": ["blur", "command"], "recadre": ["crop", "command"],
    "redimensionne": ["resize", "size", "command"], "dessine": ["draw", "shape"], "forme": ["shape"],
    "texte": ["text"], "calque": ["layer"], "calques": ["layer"], "image": ["image", "document"],
    "photo": ["photo", "image"], "photos": ["photo", "query"], "video": ["video", "media"],
    "montage": ["timeline", "clip"], "liste": ["list"], "cherche": ["query", "search", "find"],
    "selectionne": ["select"], "note": ["rating", "rate"], "etoiles": ["rating"], "rendu": ["render"],
    "apercu": ["preview", "render"], "capture": ["screenshot"], "annule": ["undo"], "efface": ["delete"],
    "supprime": ["delete", "remove"], "commandes": ["command", "list"], "effet": ["effect"],
    "anime": ["keyframe", "animation"], "animation": ["keyframe", "animation"],
}
VIDES = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "a", "au", "en", "mon", "ma", "mes",
         "ce", "cette", "pour", "dans", "sur", "avec", "moi", "me", "il", "elle", "est", "dis", "fais", "peux"}


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _contient(texte: str, mot: str) -> bool:
    # Mots courts (« son », « ram », « lis ») : mot entier, pluriel admis (« sont » ne doit pas valoir « son »).
    fin = r"(?:s|x)?(?![a-z0-9])" if len(mot) <= 4 else ""
    return re.search(rf"(?<![a-z0-9]){re.escape(mot)}{fin}", texte) is not None


def choisir(demande: str, registre: Registre, mots_extra: dict[str, list[str]] | None = None) -> list[str]:
    """Renvoie les noms d'outils à proposer au modèle, les plus pertinents d'abord."""
    t = normaliser(demande)
    mots = {**MOTS_GROUPES, **(mots_extra or {})}
    groupes = registre.groupes()

    scores = {g: sum(_contient(t, normaliser(m)) for m in ms) for g, ms in mots.items() if g in groupes}
    choisis = [g for g, s in sorted(scores.items(), key=lambda x: -x[1]) if s > 0]
    # « Ouvre Claude et demande-lui… », « ouvre Réglages, va dans Wi-Fi » : agir DANS l'appli ouverte.
    dans_appli = "fenetres" in groupes and (("applications" in choisis and bool(ACTION_DANS_APPLI.search(t)))
                                            or bool(VERS_APPLI.search(t)))
    if not choisis:
        choisis = [g for g in GROUPES_DEFAUT if g in groupes]

    mots = {_racine(m) for m in re.findall(r"[a-z0-9']+", t) if m not in VIDES and len(m) > 2}
    mots |= {_racine(a) for m in re.findall(r"[a-z0-9']+", t) for a in ANGLAIS.get(m, [])}

    def proximite(o) -> int:
        texte = normaliser(o.nom.replace("_", " ") + " " + o.description)
        return len(mots & {_racine(m) for m in re.findall(r"[a-z0-9']+", texte)})

    # Outils désignés par leurs mots-clés (compétences, connecteurs MCP) : les plus proches de la demande
    # d'abord, et pas plus de MAX_DESIGNES (une appli peut en exposer des dizaines).
    designes = [o for o in registre.disponibles()
                if o.mots_cles and any(_contient(t, normaliser(m)) for m in o.mots_cles)]
    designes.sort(key=lambda o: -proximite(o))
    noms: list[str] = [o.nom for o in designes[:MAX_DESIGNES]]
    if dans_appli:  # de quoi ouvrir l'appli, lire sa fenêtre, cliquer, écrire, valider
        noms += [n for n in PILOTAGE if registre.get(n) is not None and n not in noms]
    # Dans les groupes retenus, les outils dont le nom et la description ressemblent le plus à la demande.
    candidats = []
    for rang, g in enumerate(choisis):
        for o in groupes[g]:
            if o.nom in noms:
                continue
            candidats.append((-proximite(o), rang, o.nom))
    noms += [n for _, _, n in sorted(candidats)]
    noms = noms[:MAX_OUTILS - 3]
    for g in TOUJOURS:  # toujours disponibles, en fin de liste
        noms += [o.nom for o in groupes.get(g, []) if o.nom not in noms]
    return noms[:MAX_OUTILS]


SYNONYMES = {
    "lis": "lire", "lit": "lire", "lecture": "lire", "ouvre": "ouvrir", "lance": "ouvrir", "demarre": "ouvrir",
    "trouve": "chercher", "retrouve": "chercher", "cherche": "chercher", "recherche": "chercher",
    "retrouver": "chercher", "trouver": "chercher", "ou": "chercher", "cree": "creer", "fais": "creer",
    "ecris": "ecrire", "redige": "ecrire", "ferme": "quitter", "quitte": "quitter", "supprime": "corbeille",
    "efface": "corbeille", "jette": "corbeille", "resume": "lire", "analyse": "lire", "dis-moi": "lire",
    "clique": "cliquer", "appuie": "cliquer", "tape": "taper", "saisis": "saisir", "remplis": "remplir",
    "range": "ranger", "classe": "ranger", "deplace": "deplacer", "renomme": "renommer",
}


def _racine(mot: str) -> str:
    """Racine grossière : synonymes ramenés au même verbe, puis 5 premières lettres sans « s » final."""
    mot = SYNONYMES.get(mot, mot)
    return mot.rstrip("s")[:5]
