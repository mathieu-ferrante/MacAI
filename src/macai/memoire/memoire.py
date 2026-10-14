"""Mémoire de l'utilisateur : faits chiffrés au repos (AES-GCM, clé dans le Trousseau macOS).

Les faits sont déchiffrés en mémoire au démarrage (quelques Ko) ; la recherche des faits pertinents se
fait par mots-clés, sans modèle : aucun coût en RAM ni en temps à chaque demande.
"""
from __future__ import annotations

import base64
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..agent.routeur import normaliser

SERVICE_TROUSSEAU = "MacAI-memoire"
MOTS_VIDES = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "a", "au", "en", "est", "je", "tu",
              "il", "elle", "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses", "que", "qui", "pour",
              "dans", "sur", "avec", "pas", "ne", "ce", "cette", "ces", "moi", "toi", "fais", "fait", "peux"}
# Phrases où l'utilisateur parle de lui : déclenchent l'apprentissage automatique.
PARLE_DE_LUI = re.compile(r"\b(je suis|je m'appelle|appelle[- ]moi|j'aime|je n'aime pas|je deteste|je prefere|"
                          r"j'habite|je vis|je travaille|mon (?:nom|metier|travail|anniversaire|projet|ecole)|"
                          r"ma (?:femme|copine|mere|soeur|ville)|mon (?:frere|pere|copain|chien|chat)|"
                          r"retiens|souviens-toi|n'oublie pas)\b")


def _cle(dossier: Path) -> bytes:
    """Clé AES 256 bits : Trousseau sur macOS, fichier 0600 ailleurs (poste de développement)."""
    if sys.platform == "darwin":
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE_TROUSSEAU, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return base64.b64decode(r.stdout.strip())
        cle = os.urandom(32)
        # Passée par l'entrée standard (`security -i`) pour ne jamais apparaître dans la liste des processus.
        commande = f"add-generic-password -a macai -s {SERVICE_TROUSSEAU} -w {base64.b64encode(cle).decode()} -U\n"
        subprocess.run(["security", "-i"], input=commande, text=True, check=True, capture_output=True)
        return cle
    f = dossier / "cle_memoire"
    if not f.exists():
        f.write_bytes(os.urandom(32))
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return f.read_bytes()


@dataclass
class Fait:
    id: int
    texte: str
    source: str        # "dit" (demandé par l'utilisateur) ou "appris"
    cree_le: float
    mots: frozenset


def _mots(texte: str) -> frozenset:
    return frozenset(m for m in re.findall(r"\w+", normaliser(texte)) if len(m) > 2 and m not in MOTS_VIDES)


class Memoire:
    def __init__(self, dossier: Path):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self._aes = AESGCM(_cle(self.dossier))
        self._verrou = threading.Lock()
        self.conn = sqlite3.connect(str(self.dossier / "memoire.db"), check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS faits (id INTEGER PRIMARY KEY, chiffre BLOB, source TEXT, cree_le REAL)")
        self.faits: list[Fait] = []
        for i, chiffre, source, cree in self.conn.execute("SELECT id, chiffre, source, cree_le FROM faits"):
            try:
                texte = self._dechiffrer(chiffre)
            except Exception:  # noqa: BLE001 - fait illisible (clé changée) : ignoré
                continue
            self.faits.append(Fait(i, texte, source, cree, _mots(texte)))

    def _chiffrer(self, texte: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aes.encrypt(nonce, texte.encode(), None)

    def _dechiffrer(self, blob: bytes) -> str:
        return self._aes.decrypt(blob[:12], blob[12:], None).decode()

    def retenir(self, texte: str, source: str = "dit") -> Fait:
        texte = texte.strip().rstrip(".") + "."
        mots = _mots(texte)
        with self._verrou:
            # Un fait très proche existe déjà : on le remplace (ex. nouvelle adresse).
            for f in self.faits:
                if mots and len(mots & f.mots) / max(len(mots | f.mots), 1) > 0.7:
                    self.oublier_id(f.id)
                    break
            cur = self.conn.execute("INSERT INTO faits (chiffre, source, cree_le) VALUES (?,?,?)",
                                    (self._chiffrer(texte), source, time.time()))
            self.conn.commit()
            f = Fait(cur.lastrowid, texte, source, time.time(), mots)
            self.faits.append(f)
            return f

    def oublier_id(self, ident: int) -> None:
        self.conn.execute("DELETE FROM faits WHERE id = ?", (ident,))
        self.conn.commit()
        self.faits = [f for f in self.faits if f.id != ident]

    def oublier(self, requete: str) -> list[str]:
        """Oublie les faits qui correspondent ; « tout » efface toute la mémoire."""
        with self._verrou:
            if normaliser(requete).strip() in ("tout", "toute la memoire", "tout ce que tu sais"):
                cibles = list(self.faits)
            else:
                q = _mots(requete)
                cibles = [f for f in self.faits if q and len(q & f.mots) >= max(1, len(q) // 2)]
            for f in cibles:
                self.oublier_id(f.id)
            return [f.texte for f in cibles]

    def pertinents(self, demande: str, nombre: int = 6) -> list[str]:
        """Faits liés à la demande + les plus récents « dits » (profil de base), sans doublon."""
        q = _mots(demande)
        notes = sorted(((len(q & f.mots), f.cree_le, f) for f in self.faits if q & f.mots), key=lambda x: (-x[0], -x[1]))
        choisis = [f for _, _, f in notes[:nombre]]
        for f in sorted((f for f in self.faits if f.source == "dit"), key=lambda f: -f.cree_le):
            if len(choisis) >= nombre:
                break
            if f not in choisis:
                choisis.append(f)
        return [f.texte for f in choisis]

    def tous(self) -> list[Fait]:
        return sorted(self.faits, key=lambda f: f.cree_le)


EXTRACTION = """Voici un message de l'utilisateur. Extrais UNIQUEMENT les faits durables sur lui (identité, goûts,
habitudes, proches, travail, projets), formulés à la 3e personne, une ligne chacun, commençant par « - ».
Rien d'éphémère (demandes du moment). Si aucun, réponds exactement : AUCUN.

Message : {message}"""


def apprendre(ctx, message: str) -> list[str]:
    """Si l'utilisateur parle de lui, extrait des faits avec le modèle (déjà chargé) et les retient."""
    memoire = ctx.service("memoire")
    if memoire is None or not PARLE_DE_LUI.search(normaliser(message)):
        return []
    rep = ctx.ollama.discuter(ctx.config.modeles["agent"],
                              [{"role": "user", "content": EXTRACTION.format(message=message)}])
    faits = [l.strip("-• ").strip() for l in rep.texte.splitlines() if l.strip().startswith(("-", "•"))]
    retenus = []
    for f in faits[:5]:
        if 8 < len(f) < 200:
            memoire.retenir(f, source="appris")
            retenus.append(f)
    if retenus:
        ctx.emettre("souvenirs_appris", faits=retenus)
    return retenus
