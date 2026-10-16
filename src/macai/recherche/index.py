"""Index de recherche : SQLite FTS5 (mots) + vecteurs float16 (sens), fusion par rangs (RRF).

Les vecteurs ne sont chargés en mémoire qu'au moment d'une recherche et libérés après 5 minutes.
100 000 extraits × 256 dimensions × 2 octets ≈ 50 Mo.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DIMENSIONS = 256
TAILLE_EXTRAIT = 900
CHEVAUCHEMENT = 120
EXTRAITS_MAX_PAR_FICHIER = 40
INSTRUCTION_REQUETE = "Instruct: Retrouver le fichier personnel qui correspond à cette description\nQuery: "
LIBERER_APRES_S = 300

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS fichiers (
    id INTEGER PRIMARY KEY, chemin TEXT UNIQUE NOT NULL, mtime REAL, taille INTEGER,
    genre TEXT, indexe_le REAL, contenu INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS extraits (
    id INTEGER PRIMARY KEY, fichier_id INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    n INTEGER, texte TEXT, vecteur BLOB
);
CREATE INDEX IF NOT EXISTS idx_extraits_fichier ON extraits(fichier_id);
CREATE VIRTUAL TABLE IF NOT EXISTS extraits_fts USING fts5(
    texte, content='extraits', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS extraits_ai AFTER INSERT ON extraits BEGIN
    INSERT INTO extraits_fts(rowid, texte) VALUES (new.id, new.texte);
END;
CREATE TRIGGER IF NOT EXISTS extraits_ad AFTER DELETE ON extraits BEGIN
    INSERT INTO extraits_fts(extraits_fts, rowid, texte) VALUES ('delete', old.id, old.texte);
END;
CREATE TABLE IF NOT EXISTS etat (cle TEXT PRIMARY KEY, valeur TEXT);
"""


@dataclass
class Trouvaille:
    chemin: str
    extrait: str
    score: float
    genre: str
    mtime: float


def decouper(texte: str, taille: int = TAILLE_EXTRAIT, chevauchement: int = CHEVAUCHEMENT) -> list[str]:
    """Découpe en extraits, de préférence aux fins de paragraphe ou de phrase."""
    texte = re.sub(r"[ \t]+", " ", texte).strip()
    if len(texte) <= taille:
        return [texte] if texte else []
    extraits, i = [], 0
    while i < len(texte) and len(extraits) < EXTRAITS_MAX_PAR_FICHIER:
        fin = min(i + taille, len(texte))
        if fin < len(texte):
            coupe = max(texte.rfind("\n\n", i, fin), texte.rfind(". ", i, fin))
            if coupe > i + taille // 2:
                fin = coupe + 1
        extraits.append(texte[i:fin].strip())
        if fin >= len(texte):
            break
        i = max(fin - chevauchement, i + 1)
    return [e for e in extraits if e]


def _requete_fts(requete: str) -> str:
    """Transforme une phrase libre en requête FTS5 sûre : mots significatifs en OU, préfixes."""
    vides = {"le", "la", "les", "un", "une", "des", "de", "du", "d", "l", "et", "ou", "a", "au", "aux", "en",
             "mon", "ma", "mes", "ton", "ta", "tes", "sur", "dans", "avec", "pour", "par", "qui", "que", "quoi",
             "ou", "est", "sont", "j", "je", "moi", "trouve", "retrouve", "cherche", "fichier", "fichiers"}
    mots = [m for m in re.findall(r"\w+", requete.lower()) if m not in vides and len(m) > 1]
    return " OR ".join(f'"{m}"*' for m in mots[:12])


class Index:
    def __init__(self, fichier: Path, ollama=None, modele: str = "qwen3-embedding:0.6b"):
        self.fichier = Path(fichier)
        self.ollama = ollama
        self.modele = modele
        self._verrou = threading.RLock()
        self._matrice = None          # (ids, numpy float16 [n, D]) chargés à la demande
        self._version = None          # PRAGMA data_version au chargement de la matrice
        self._derniere_utilisation = 0.0
        self.conn = self._connecter()

    def _connecter(self) -> sqlite3.Connection:
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.fichier), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        return conn

    # --- Écriture -----------------------------------------------------------

    def connu(self, chemin: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM fichiers WHERE chemin = ?", (chemin,)).fetchone()

    def enregistrer(self, chemin: Path, mtime: float, taille: int, genre: str, texte: str | None) -> int:
        """Remplace l'entrée d'un fichier. `texte` None = nom seulement (format non lisible)."""
        entete = f"{chemin.name} — dossier {chemin.parent.name} ({chemin.parent})"
        return self.enregistrer_entree(str(chemin), mtime, taille, genre, entete, texte)

    def enregistrer_entree(self, chemin: str, mtime: float, taille: int, genre: str, entete: str,
                           texte: str | None) -> int:
        """Entrée quelconque : fichier, ou mail / note sous une pseudo-adresse (« mail://… », « note://… »).
        `entete` (nom, expéditeur, date…) précède le premier extrait : il est cherchable et affiché."""
        import numpy as np
        extraits = decouper(texte) if texte else []
        textes = [entete + ("\n" + extraits[0] if extraits else "")] + extraits[1:]
        vecs = None
        if self.ollama is not None:
            vecs = []
            for i in range(0, len(textes), 16):
                vecs += self.ollama.vecteurs(self.modele, textes[i:i + 16], DIMENSIONS)
            vecs = np.asarray(vecs, dtype=np.float32)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
            vecs = vecs.astype(np.float16)
        with self._verrou, self.conn:
            self.conn.execute("DELETE FROM fichiers WHERE chemin = ?", (chemin,))
            cur = self.conn.execute(
                "INSERT INTO fichiers (chemin, mtime, taille, genre, indexe_le, contenu) VALUES (?,?,?,?,?,?)",
                (chemin, mtime, taille, genre, time.time(), int(bool(extraits))))
            fid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO extraits (fichier_id, n, texte, vecteur) VALUES (?,?,?,?)",
                [(fid, n, t, vecs[n].tobytes() if vecs is not None else None) for n, t in enumerate(textes)])
            self._matrice = None
        return fid

    def oublier(self, chemins: list[str]) -> None:
        with self._verrou, self.conn:
            self.conn.executemany("DELETE FROM fichiers WHERE chemin = ?", [(c,) for c in chemins])
            self._matrice = None

    def chemins(self, prefixe: str | None = None) -> dict[str, tuple[float, int]]:
        if prefixe:
            lignes = self.conn.execute("SELECT chemin, mtime, taille FROM fichiers WHERE substr(chemin, 1, ?) = ?",
                                       (len(prefixe), prefixe))
        else:
            lignes = self.conn.execute("SELECT chemin, mtime, taille FROM fichiers")
        return {r["chemin"]: (r["mtime"], r["taille"]) for r in lignes}

    def documents(self, requete: str, genres: list[str] | None = None, apres: float | None = None,
                  limite: int = 400) -> list[dict]:
        """Entrées dont le texte contient l'un des mots de `requete` (syntaxe FTS5), avec leur texte complet
        reconstitué : {chemin, genre, mtime, entete, texte}. Sert aux relevés (factures, tickets…)."""
        sql = ("SELECT DISTINCT f.id, f.chemin, f.genre, f.mtime FROM extraits_fts "
               "JOIN extraits e ON e.id = extraits_fts.rowid JOIN fichiers f ON f.id = e.fichier_id "
               "WHERE extraits_fts MATCH ?")
        params: list = [requete]
        if genres:
            sql += f" AND f.genre IN ({','.join('?' * len(genres))})"
            params += list(genres)
        if apres:
            sql += " AND f.mtime >= ?"
            params.append(apres)
        sql += " ORDER BY f.mtime DESC LIMIT ?"
        params.append(int(limite))
        sortie = []
        for f in self.conn.execute(sql, params).fetchall():
            morceaux = [r["texte"] for r in self.conn.execute(
                "SELECT texte FROM extraits WHERE fichier_id = ? ORDER BY n", (f["id"],))]
            premier = morceaux[0] if morceaux else ""
            entete, _, debut = premier.partition("\n")
            sortie.append({"chemin": f["chemin"], "genre": f["genre"], "mtime": f["mtime"], "entete": entete,
                           "texte": "\n".join([debut] + morceaux[1:])})
        return sortie

    def stats(self) -> dict:
        r = self.conn.execute("SELECT COUNT(*) n, SUM(contenu) c FROM fichiers").fetchone()
        e = self.conn.execute("SELECT COUNT(*) FROM extraits").fetchone()[0]
        return {"fichiers": r["n"] or 0, "avec_contenu": r["c"] or 0, "extraits": e,
                "taille_mo": round(self.fichier.stat().st_size / 1e6, 1) if self.fichier.exists() else 0}

    def etat(self, cle: str, valeur: str | None = None) -> str | None:
        if valeur is not None:
            with self.conn:
                self.conn.execute("INSERT OR REPLACE INTO etat VALUES (?,?)", (cle, valeur))
            return valeur
        r = self.conn.execute("SELECT valeur FROM etat WHERE cle = ?", (cle,)).fetchone()
        return r["valeur"] if r else None

    # --- Recherche ----------------------------------------------------------

    def _version_base(self) -> int:
        """Change quand une AUTRE connexion (l'indexeur, processus séparé) a modifié la base."""
        return self.conn.execute("PRAGMA data_version").fetchone()[0]

    def _vecteurs(self):
        import numpy as np
        with self._verrou:
            version = self._version_base()
            if self._matrice is not None and version != self._version:
                self._matrice = None  # l'indexeur a écrit depuis : matrice périmée, rechargée
            if self._matrice is None:
                lignes = self.conn.execute("SELECT id, vecteur FROM extraits WHERE vecteur IS NOT NULL").fetchall()
                if not lignes:
                    return None
                ids = np.fromiter((l["id"] for l in lignes), dtype=np.int64, count=len(lignes))
                mat = np.frombuffer(b"".join(l["vecteur"] for l in lignes), dtype=np.float16).reshape(len(lignes), -1)
                self._matrice = (ids, mat)
                self._version = version
            self._derniere_utilisation = time.monotonic()
            return self._matrice

    def liberer_si_inactif(self) -> None:
        if self._matrice is not None and time.monotonic() - self._derniere_utilisation > LIBERER_APRES_S:
            self._matrice = None

    def rechercher(self, requete: str, nombre: int = 8, genres: list[str] | None = None,
                   dossier: str | None = None, apres: float | None = None,
                   exclure: list[str] | None = None) -> list[Trouvaille]:
        import numpy as np
        rangs: dict[int, list[int]] = {}
        # Avec un filtre (genre, dossier, date), plus de candidats : les mails ne doivent pas évincer les fichiers.
        candidats = 150 if (genres or exclure or dossier or apres) else 60

        # 1. Mots-clés (BM25).
        fts = _requete_fts(requete)
        if fts:
            for rang, r in enumerate(self.conn.execute(
                    "SELECT rowid FROM extraits_fts WHERE extraits_fts MATCH ? ORDER BY rank LIMIT ?", (fts, candidats))):
                rangs.setdefault(r["rowid"], []).append(rang)

        # 2. Sens (cosinus).
        donnees = self._vecteurs() if self.ollama is not None else None
        if donnees is not None:
            ids, mat = donnees
            q = np.asarray(self.ollama.vecteurs(self.modele, [INSTRUCTION_REQUETE + requete], DIMENSIONS)[0],
                           dtype=np.float32)
            q /= np.linalg.norm(q) + 1e-9
            scores = mat.astype(np.float32) @ q if len(ids) < 50_000 else (mat @ q.astype(np.float16)).astype(np.float32)
            meilleurs = np.argsort(-scores)[:candidats]
            for rang, i in enumerate(meilleurs):
                if scores[i] > 0.2:
                    rangs.setdefault(int(ids[i]), []).append(rang)

        if not rangs:
            return []
        # Fusion RRF, puis meilleur extrait par fichier.
        score_extrait = {eid: sum(1 / (60 + r) for r in rs) for eid, rs in rangs.items()}
        marques = ",".join("?" * len(score_extrait))
        lignes = self.conn.execute(
            f"SELECT e.id, e.texte, f.chemin, f.genre, f.mtime FROM extraits e JOIN fichiers f ON f.id = e.fichier_id "
            f"WHERE e.id IN ({marques})", list(score_extrait)).fetchall()
        par_fichier: dict[str, Trouvaille] = {}
        for l in lignes:
            if genres and l["genre"] not in genres:
                continue
            if exclure and l["genre"] in exclure:
                continue
            if dossier and not l["chemin"].startswith(dossier):
                continue
            if apres and (l["mtime"] or 0) < apres:
                continue
            s = score_extrait[l["id"]]
            t = par_fichier.get(l["chemin"])
            if t is None or s > t.score:
                par_fichier[l["chemin"]] = Trouvaille(l["chemin"], l["texte"], s, l["genre"], l["mtime"])
        return sorted(par_fichier.values(), key=lambda t: -t.score)[:nombre]
