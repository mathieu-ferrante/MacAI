"""Indexation en arrière-plan : parcourt les dossiers, extrait, vectorise — seulement si le Mac est
sur secteur et inutilisé. Lancé dans un processus séparé avec `taskpolicy -b` : priorité basse,
cœurs basse consommation de la puce M2, entrées/sorties ralenties.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

from .. import extraction
from ..config import Config
from .index import Index

PAQUETS = {".app", ".photoslibrary", ".musiclibrary", ".tvlibrary", ".bundle", ".framework", ".xcodeproj",
           ".xcworkspace", ".pages", ".numbers", ".key", ".imovielibrary", ".fcpbundle", ".logicx", ".band"}
# Paquets iWork : indexés comme un fichier (aperçu intégré), pas parcourus.
PAQUETS_FICHIERS = {".pages", ".numbers", ".key"}


def genre_de(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in extraction.IMAGES:
        return "capture" if re.match(r"^(capture d.écran|screenshot|screen shot)", p.name, re.I) else "image"
    if ext == ".pdf":
        return "pdf"
    if ext in {".docx", ".doc", ".odt", ".rtf", ".pages", ".txt", ".md"}:
        return "document"
    if ext in {".xlsx", ".xlsm", ".csv", ".numbers"}:
        return "tableur"
    if ext in {".pptx", ".key"}:
        return "presentation"
    if ext in extraction.TEXTE:
        return "code"
    return "autre"


# Un dossier qui contient l'un de ces éléments est un projet logiciel : on y garde les documents, pas le code
# (des milliers de fichiers sans intérêt pour « retrouve ma facture », et une indexation bien plus longue).
MARQUEURS_PROJET = {".git", "package.json", "build.gradle", "build.gradle.kts", "settings.gradle", "Cargo.toml",
                    "pyproject.toml", "setup.py", "go.mod", "pom.xml", "Package.swift", "Gemfile", "composer.json"}
# Fichier iCloud non téléchargé (« dataless ») : le lire déclencherait son téléchargement.
SF_DATALESS = 0x40000000
# Explorés en premier : là où sont les fichiers personnels.
PRIORITAIRES = ["Desktop", "Documents", "Downloads", "Library/Mobile Documents/com~apple~CloudDocs"]


def parcourir(dossiers: list[str], ignorer: list[str], taille_max: int, images: bool = True) -> Iterator[tuple[Path, os.stat_result]]:
    ignores = set(ignorer)
    pile: list[tuple[Path, bool]] = []
    for d in reversed([Path(d).expanduser() for d in dossiers]):
        pile.append((d, False))
        # Dossier personnel : Bureau, Documents, Téléchargements d'abord (la pile sort le dernier ajouté).
        pile += [(d / p, False) for p in reversed(PRIORITAIRES) if d == Path.home() and (d / p).is_dir()]
    vus: set[Path] = set()
    while pile:
        d, projet = pile.pop()
        if d in vus:
            continue
        vus.add(d)
        try:
            entrees = list(os.scandir(d))
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            continue
        projet = projet or any(e.name in MARQUEURS_PROJET or e.name.endswith(".xcodeproj") for e in entrees)
        for e in entrees:
            nom = e.name
            if nom.startswith(".") or nom in ignores:
                continue
            p = Path(e.path)
            try:
                if e.is_dir(follow_symlinks=False):
                    ext = p.suffix.lower()
                    if ext in PAQUETS_FICHIERS:
                        st = e.stat()
                        if not getattr(st, "st_flags", 0) & SF_DATALESS:
                            yield p, st
                    elif ext not in PAQUETS:
                        pile.append((p, projet))
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                st = e.stat()
            except OSError:
                continue
            if st.st_size > taille_max or st.st_size == 0 or getattr(st, "st_flags", 0) & SF_DATALESS:
                continue
            if not images and p.suffix.lower() in extraction.IMAGES:
                continue
            if projet and genre_de(p) in ("code", "autre"):
                continue
            yield p, st


# --- Conditions (macOS) -----------------------------------------------------------

def sur_secteur() -> bool:
    if sys.platform != "darwin":
        return True
    try:
        return "AC Power" in subprocess.run(["pmset", "-g", "ps"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True


def inactivite_s() -> float:
    """Secondes depuis la dernière action clavier/souris."""
    if sys.platform != "darwin":
        return 1e9
    try:
        sortie = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r'"HIDIdleTime" = (\d+)', sortie)
        return int(m.group(1)) / 1e9 if m else 0
    except (OSError, subprocess.SubprocessError):
        return 0


class Indexeur:
    def __init__(self, cfg: Config, index: Index, sortie=print, sources: "SourcesApple | None" = None):
        self.cfg = cfg
        self.index = index
        self.sortie = sortie
        r = cfg.recherche
        self.dossiers = r["dossiers"]
        self.ignorer = r["ignorer"]
        self.taille_max = int(r["taille_max_mo"]) * 1024 * 1024
        self.images = bool(r["images"])
        # Mails et notes : seulement quand le dossier personnel entier est indexé (configuration réelle, pas
        # un dossier de test), sur Mac, et si les réglages ne les excluent pas.
        if sources is None and sys.platform == "darwin" and any(
                Path(d).expanduser() == Path.home() for d in self.dossiers):
            sources = SourcesApple(mails=bool(r.get("mails", True)), notes=bool(r.get("notes", True)),
                                   lancer_apps=bool(r.get("lancer_apps", False)))
        self.sources = sources

    def conditions_ok(self, force: bool = False) -> tuple[bool, str]:
        if force:
            return True, ""
        r = self.cfg.recherche
        if r.get("secteur_seulement", True) and not sur_secteur():
            return False, "sur batterie"
        if inactivite_s() < float(r.get("inactivite_minutes", 5)) * 60:
            return False, "Mac en cours d'utilisation"
        return True, ""

    def a_faire(self) -> tuple[list[tuple[Path, os.stat_result]], list[str]]:
        """Fichiers nouveaux ou modifiés (les plus récents d'abord) et fichiers disparus. Un fichier non vu
        (dossier illisible, disque débranché, fichier iCloud non téléchargé) n'est oublié que s'il n'existe plus."""
        connus = self.index.chemins()
        vus, nouveaux = set(), []
        for p, st in parcourir(self.dossiers, self.ignorer, self.taille_max, self.images):
            c = str(p)
            vus.add(c)
            ancien = connus.get(c)
            if ancien is None or abs((ancien[0] or 0) - st.st_mtime) > 1 or ancien[1] != st.st_size:
                nouveaux.append((p, st))
        nouveaux.sort(key=lambda x: -x[1].st_mtime)
        # Les mails et notes (« mail://… », « note://… ») ont leur propre suivi : jamais pris pour des fichiers disparus.
        disparus = [c for c in connus if c not in vus and "://" not in c and not os.path.lexists(c)]
        return nouveaux, disparus

    def traiter(self, p: Path, st: os.stat_result) -> None:
        texte = None
        if p.suffix.lower() in extraction.EXTRACTIBLES:
            try:
                texte = extraction.extraire(p, limite=60_000) or None
            except Exception as e:  # noqa: BLE001 - un fichier abîmé ne doit pas arrêter l'indexation
                self.sortie(f"  illisible : {p} ({e})")
        self.index.enregistrer(p, st.st_mtime, st.st_size, genre_de(p), texte)

    def executer(self, force: bool = False, limite: int | None = None, duree_max_s: float | None = None) -> dict:
        ok, raison = self.conditions_ok(force)
        if not ok:
            return {"faits": 0, "restants": None, "pause": raison}
        debut = time.monotonic()
        apple = {}
        if self.sources is not None:  # d'abord : borné (MAX_PAR_PASSAGE), alors que les fichiers peuvent durer
            try:
                apple = self.sources.indexer(self.index, self.sortie)
            except Exception as e:  # noqa: BLE001 - Mail/Notes indisponibles ne bloquent pas les fichiers
                self.sortie(f"  mails/notes non indexés : {e}")
        nouveaux, disparus = self.a_faire()
        if disparus:
            self.index.oublier(disparus)
        faits = 0
        for i, (p, st) in enumerate(nouveaux):
            if limite is not None and faits >= limite:
                break
            if duree_max_s is not None and time.monotonic() - debut > duree_max_s:
                break
            if i % 20 == 0 and i:
                ok, raison = self.conditions_ok(force)
                if not ok:
                    self.sortie(f"Pause : {raison}")
                    break
            self.traiter(p, st)
            faits += 1
        self.index.etat("dernier_passage", str(time.time()))
        restants = len(nouveaux) - faits
        self.sortie(f"Indexation : {faits} fichiers traités, {restants} restants, {len(disparus)} retirés.")
        r = {"faits": faits, "restants": restants, "retires": len(disparus)}
        if apple:
            r["apple"] = apple
        return r


# --- Mails et notes (AppleScript, sans accès complet au disque) ---------------------------------------------

US, RS = "\x1f", "\x1e"
US_AS, RS_AS = "(character id 31)", "(character id 30)"
MAILS_PAR_BOITE = 2000       # derniers messages suivis dans Réception et dans Envoyés
EXTRAIT_MAIL = 2000          # caractères du contenu gardés par mail
EXTRAIT_NOTE = 20000
MAX_PAR_PASSAGE = 300        # mails ou notes lus en détail par passage (le reste au passage suivant)
PAQUET = 25                  # messages lus par appel AppleScript


def _sans_chevrons(ident: str) -> str:
    return str(ident or "").strip().strip("<>").strip()


def adresse_mail(ident: str) -> str:
    return "mail://" + _sans_chevrons(ident)


def adresse_note(ident: str) -> str:
    return "note://" + str(ident or "").strip()


def _ouverte(app: str, lancer: bool) -> str:
    """Prélude AppleScript : ne lance pas l'app si elle est fermée (sauf réglage lancer_apps)."""
    return "" if lancer else f'if application "{app}" is not running then return "FERME"\n'


def script_lister_mails(lancer: bool = False, limite: int = MAILS_PAR_BOITE) -> str:
    """Identifiants et âges (secondes) des derniers messages de Réception et d'Envoyés, en lot (rapide)."""
    blocs = []
    for boite, cle, prop in (("inbox", "recus", "date received"), ("sent mailbox", "envoyes", "date sent")):
        blocs.append(f'''    try
        set b to {boite}
        set n to count of messages of b
        if n > {limite} then set n to {limite}
        if n > 0 then
            set ids to message id of messages 1 thru n of b
            set ds to {prop} of messages 1 thru n of b
            repeat with i from 1 to n
                set end of lignes to "{cle}" & {US_AS} & i & {US_AS} & (item i of ids) & {US_AS} & (maintenant - (item i of ds))
            end repeat
        end if
    end try''')
    return (_ouverte("Mail", lancer) + '''tell application "Mail"
    set maintenant to current date
    set lignes to {}
''' + "\n".join(blocs) + f'''
    set AppleScript's text item delimiters to {RS_AS}
    return lignes as text
end tell''')


def script_details_mails(demandes: list[tuple[str, int, str]], extrait: int = EXTRAIT_MAIL) -> str:
    """Détail de messages désignés par (boîte, rang, identifiant) ; si le rang a bougé, recherche par identifiant."""
    from ..mac.commun import chaine_as as S
    lignes = []
    for cle, rang, ident in demandes:
        boite = "inbox" if cle == "recus" else "sent mailbox"
        lignes.append(f'''    try
        set m to missing value
        try
            set m to message {int(rang)} of {boite}
            if (message id of m) is not {S(ident)} then set m to missing value
        end try
        if m is missing value then set m to first message of {boite} whose message id is {S(ident)}
        set c to ""
        try
            set c to content of m
            if (length of c) > {extrait} then set c to text 1 thru {extrait} of c
        end try
        set dest to ""
        try
            set dest to address of first to recipient of m
        end try
        set q to date received of m
        if "{cle}" is "envoyes" then set q to date sent of m
        set end of lignes to "{cle}" & {US_AS} & (message id of m) & {US_AS} & (my t(sender of m)) & {US_AS} & (my t(subject of m)) & {US_AS} & (maintenant - q) & {US_AS} & dest & {US_AS} & c
    end try''')
    return ('''on t(x)
    if x is missing value then return ""
    return x as text
end t
tell application "Mail"
    set maintenant to current date
    set lignes to {}
''' + "\n".join(lignes) + f'''
    set AppleScript's text item delimiters to {RS_AS}
    return lignes as text
end tell''')


def script_lister_notes(lancer: bool = False) -> str:
    return _ouverte("Notes", lancer) + f'''tell application "Notes"
    set maintenant to current date
    set ids to id of every note
    set ds to modification date of every note
    set noms to name of every note
    set lignes to {{}}
    repeat with i from 1 to count of ids
        set end of lignes to (item i of ids) & {US_AS} & (maintenant - (item i of ds)) & {US_AS} & (item i of noms)
    end repeat
    set AppleScript's text item delimiters to {RS_AS}
    return lignes as text
end tell'''


def script_details_notes(ids: list[str], extrait: int = EXTRAIT_NOTE) -> str:
    from ..mac.commun import chaine_as as S
    blocs = [f'''    try
        set n to note id {S(i)}
        -- Notes supprimées (dossier « Suppressions récentes ») : jamais indexées.
        if (name of container of n) is not in {{"Recently Deleted", "Suppressions récentes"}} then
            set c to plaintext of n
            if (length of c) > {extrait} then set c to text 1 thru {extrait} of c
            set end of lignes to (id of n) & {US_AS} & c
        end if
    end try''' for i in ids]
    return '''tell application "Notes"
    set lignes to {}
''' + "\n".join(blocs) + f'''
    set AppleScript's text item delimiters to {RS_AS}
    return lignes as text
end tell'''


def _champs(brut: str, n: int) -> list[list[str]]:
    return [(b.split(US) + [""] * n)[:n] for b in str(brut or "").split(RS) if b.strip()]


def _secondes(texte: str) -> float:
    try:
        return float(str(texte).strip().replace(",", "."))
    except ValueError:
        return 0.0


def _quand(ts: float) -> str:
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))


def entete_mail(cle: str, de: str, sujet: str, destinataire: str, ts: float) -> str:
    sujet = sujet or "(sans sujet)"
    if cle == "envoyes":
        return f"Mail envoyé à {destinataire or '?'} — « {sujet} » — le {_quand(ts)}"
    return f"Mail « {sujet} » — de {de or '?'} — reçu le {_quand(ts)}"


class SourcesApple:
    """Mails (Réception + Envoyés, derniers MAILS_PAR_BOITE) et notes, indexés comme des fichiers. Incrémental :
    un mail ne change pas (identifiant), une note change avec sa date de modification. Ce qui ne figure plus dans
    la fenêtre suivie (mail supprimé ou trop ancien, note effacée) est retiré de l'index."""

    def __init__(self, mails: bool = True, notes: bool = True, lancer_apps: bool = False, osascript=None):
        self.mails, self.notes, self.lancer = mails, notes, lancer_apps
        self._osascript = osascript

    def _as(self, script: str, delai: float = 120) -> str:
        if self._osascript is not None:
            return self._osascript(script, delai=delai)
        from ..mac import commun
        return commun.osascript(script, delai=delai)

    def indexer(self, index: Index, sortie=print, maintenant: float | None = None) -> dict:
        maintenant = maintenant or time.time()
        bilan = {}
        if self.mails:
            bilan["mails"] = self._mails(index, maintenant)
        if self.notes:
            bilan["notes"] = self._notes(index, maintenant)
        for genre, (faits, retires) in bilan.items():
            if faits or retires:
                sortie(f"  {genre} : {faits} indexés, {retires} retirés")
        return bilan

    def _mails(self, index: Index, maintenant: float) -> tuple[int, int]:
        brut = self._as(script_lister_mails(self.lancer), delai=180)
        if brut.strip() == "FERME":
            return 0, 0
        listes = _champs(brut, 4)
        connus = index.chemins("mail://")
        presents = {adresse_mail(c[2]) for c in listes if c[2].strip()}
        retires = [c for c in connus if c not in presents]
        if listes and retires:  # liste vide = Mail injoignable : on ne retire rien
            index.oublier(retires)
        a_lire = [(c[0], int(_secondes(c[1])), c[2].strip()) for c in listes
                  if c[2].strip() and adresse_mail(c[2]) not in connus][:MAX_PAR_PASSAGE]
        faits = 0
        for i in range(0, len(a_lire), PAQUET):
            for cle, ident, de, sujet, age, dest, contenu in _champs(
                    self._as(script_details_mails(a_lire[i:i + PAQUET]), delai=180), 7):
                if not ident.strip():
                    continue
                ts = maintenant - _secondes(age)
                index.enregistrer_entree(adresse_mail(ident), ts, len(contenu), "mail",
                                         entete_mail(cle, de.strip(), sujet.strip(), dest.strip(), ts),
                                         contenu.strip() or None)
                faits += 1
        return faits, len(retires) if listes else 0

    def _notes(self, index: Index, maintenant: float) -> tuple[int, int]:
        brut = self._as(script_lister_notes(self.lancer), delai=120)
        if brut.strip() == "FERME":
            return 0, 0
        listes = _champs(brut, 3)
        connus = index.chemins("note://")
        vues = {}
        for ident, age, nom in listes:
            if ident.strip():
                vues[adresse_note(ident)] = (ident.strip(), maintenant - _secondes(age), nom.strip())
        retires = [c for c in connus if c not in vues]
        if listes and retires:
            index.oublier(retires)
        a_lire = [v for a, v in vues.items() if a not in connus or abs((connus[a][0] or 0) - v[1]) > 5]
        a_lire = a_lire[:MAX_PAR_PASSAGE]
        faits = 0
        for i in range(0, len(a_lire), PAQUET):
            paquet = {v[0]: v for v in a_lire[i:i + PAQUET]}
            for ident, contenu in _champs(self._as(script_details_notes(list(paquet)), delai=120), 2):
                v = paquet.get(ident.strip())
                if v is None:
                    continue
                corps = contenu.strip()
                if corps.startswith(v[2]):  # le titre est répété en tête du texte
                    corps = corps[len(v[2]):].strip()
                index.enregistrer_entree(adresse_note(v[0]), v[1], len(contenu), "note",
                                         f"Note « {v[2] or '(sans titre)'} » — modifiée le {_quand(v[1])}",
                                         corps or None)
                faits += 1
        return faits, len(retires) if listes else 0


def lancer_en_arriere_plan(force: bool = False) -> subprocess.Popen | None:
    """Démarre `python -m macai indexer` en priorité basse (cœurs E sur Apple Silicon)."""
    cmd = [sys.executable, "-m", "macai", "indexer"] + (["--force"] if force else [])
    if sys.platform == "darwin":
        cmd = ["/usr/sbin/taskpolicy", "-b"] + cmd
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
