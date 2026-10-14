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


def parcourir(dossiers: list[str], ignorer: list[str], taille_max: int, images: bool = True) -> Iterator[tuple[Path, os.stat_result]]:
    ignores = set(ignorer)
    pile = [Path(d).expanduser() for d in dossiers]
    while pile:
        d = pile.pop()
        try:
            entrees = list(os.scandir(d))
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            continue
        for e in entrees:
            nom = e.name
            if nom.startswith(".") or nom in ignores:
                continue
            p = Path(e.path)
            try:
                if e.is_dir(follow_symlinks=False):
                    ext = p.suffix.lower()
                    if ext in PAQUETS_FICHIERS:
                        yield p, e.stat()
                    elif ext not in PAQUETS:
                        pile.append(p)
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                st = e.stat()
            except OSError:
                continue
            if st.st_size > taille_max or st.st_size == 0:
                continue
            if not images and p.suffix.lower() in extraction.IMAGES:
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
    def __init__(self, cfg: Config, index: Index, sortie=print):
        self.cfg = cfg
        self.index = index
        self.sortie = sortie
        r = cfg.recherche
        self.dossiers = r["dossiers"]
        self.ignorer = r["ignorer"]
        self.taille_max = int(r["taille_max_mo"]) * 1024 * 1024
        self.images = bool(r["images"])

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
        """Fichiers nouveaux ou modifiés (les plus récents d'abord) et fichiers disparus."""
        connus = self.index.chemins()
        vus, nouveaux = set(), []
        for p, st in parcourir(self.dossiers, self.ignorer, self.taille_max, self.images):
            c = str(p)
            vus.add(c)
            ancien = connus.get(c)
            if ancien is None or abs((ancien[0] or 0) - st.st_mtime) > 1 or ancien[1] != st.st_size:
                nouveaux.append((p, st))
        nouveaux.sort(key=lambda x: -x[1].st_mtime)
        disparus = [c for c in connus if c not in vus]
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
        nouveaux, disparus = self.a_faire()
        if disparus:
            self.index.oublier(disparus)
        debut, faits = time.monotonic(), 0
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
        return {"faits": faits, "restants": restants, "retires": len(disparus)}


def lancer_en_arriere_plan(force: bool = False) -> subprocess.Popen | None:
    """Démarre `python -m macai indexer` en priorité basse (cœurs E sur Apple Silicon)."""
    cmd = [sys.executable, "-m", "macai", "indexer"] + (["--force"] if force else [])
    if sys.platform == "darwin":
        cmd = ["/usr/sbin/taskpolicy", "-b"] + cmd
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
