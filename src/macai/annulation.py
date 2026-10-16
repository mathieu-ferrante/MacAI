"""Annuler : pile persistante des opérations inverses enregistrées par les outils de fichiers.

Chaque entrée décrit UNE action de l'utilisateur (un déplacement, un rangement complet…) et la liste des
opérations qui la défont. L'annulation les applique dans l'ordre inverse, n'écrase jamais rien (chemin
d'origine occupé → « nom (2) ») et dit précisément ce qui a été restauré.

Opérations (enregistrées dans l'ordre où les actions ont été faites) :
  {"type": "deplacer", "de": chemin actuel, "vers": chemin d'origine}
  {"type": "corbeille", "chemin": élément créé par l'action, à mettre à la Corbeille}
  {"type": "restaurer", "depuis": emplacement dans la Corbeille, "vers": chemin d'origine}
  {"type": "supprimer_dossier_vide", "chemin": dossier créé par l'action}
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

MAX_ENTREES = 50
_VERROU = threading.Lock()
_FICHIER_COURANT: Path | None = None  # dernier fichier utilisé (pour les annonces, qui n'ont pas le contexte)


def fichier_pour(ctx) -> Path | None:
    global _FICHIER_COURANT
    config = getattr(ctx, "config", None)
    if config is None:
        return None
    _FICHIER_COURANT = Path(config.chemin("annulations.json"))
    return _FICHIER_COURANT


def fichier_courant() -> Path:
    if _FICHIER_COURANT is not None:
        return _FICHIER_COURANT
    from .config import dossier_donnees
    return Path(dossier_donnees()) / "annulations.json"


def definir_fichier(fichier: Path) -> None:
    global _FICHIER_COURANT
    _FICHIER_COURANT = Path(fichier)


# --- Stockage ---------------------------------------------------------------------------

def charger(fichier: Path) -> list[dict]:
    try:
        donnees = json.loads(Path(fichier).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in donnees if isinstance(e, dict) and isinstance(e.get("operations"), list)] \
        if isinstance(donnees, list) else []


def _sauver(fichier: Path, entrees: list[dict]) -> None:
    fichier = Path(fichier)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    temp = fichier.with_name(fichier.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entrees[-MAX_ENTREES:], f, ensure_ascii=False, indent=1)
    os.chmod(temp, 0o600)
    os.replace(temp, fichier)


def ajouter(fichier: Path, description: str, operations: list[dict]) -> dict | None:
    if not operations:
        return None
    entree = {"id": uuid.uuid4().hex[:10], "quand": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "description": description, "operations": operations}
    with _VERROU:
        entrees = charger(fichier)
        entrees.append(entree)
        _sauver(fichier, entrees)
    return entree


def enregistrer(ctx, description: str, operations: list[dict]) -> None:
    """Appelé par les outils après une action réussie. Ne fait jamais échouer l'action elle-même."""
    try:
        fichier = fichier_pour(ctx)
        if fichier is not None:
            ajouter(fichier, description, operations)
    except Exception as e:  # noqa: BLE001 - l'annulation est un plus : l'action a déjà eu lieu
        journal = getattr(ctx, "journal", None)
        if journal is not None:
            journal.ecrire("erreur_annulation", texte=str(e))


def derniere(fichier: Path) -> dict | None:
    entrees = charger(fichier)
    return entrees[-1] if entrees else None


def historique(fichier: Path, nombre: int = 5) -> list[dict]:
    return list(reversed(charger(fichier)))[:max(1, nombre)]


def _retirer(fichier: Path, ident: str) -> None:
    with _VERROU:
        _sauver(fichier, [e for e in charger(fichier) if e.get("id") != ident])


# --- Annulation -------------------------------------------------------------------------

def _libre(p: Path) -> tuple[Path, str]:
    """Chemin d'arrivée sans écrasement, et la remarque à faire si le nom d'origine était pris."""
    from .outils.fichiers import sans_collision
    if not p.exists() and not p.is_symlink():
        return p, ""
    autre = sans_collision(p)
    return autre, f" ({p.name} existait déjà : restauré sous {autre.name})"


def _verifier(p: Path) -> None:
    from .outils.fichiers import verifier_chemin
    verifier_chemin(p, ecriture=True)


def _appliquer(op: dict) -> tuple[bool, str]:
    from .outils import fichiers
    genre = op.get("type")
    if genre in ("deplacer", "restaurer"):
        de = Path(op.get("de") or op.get("depuis") or "")
        vers = Path(op.get("vers") or "")
        if not str(de) or not str(vers):
            return False, "opération incomplète"
        if not de.exists() and not de.is_symlink():
            ou = "dans la Corbeille" if genre == "restaurer" else "à " + str(de)
            return False, f"{de.name} introuvable {ou} (déplacé ou supprimé depuis ?)"
        _verifier(vers)
        dest, remarque = _libre(vers)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(de), str(dest))
        verbe = "sorti de la Corbeille" if genre == "restaurer" else "remis"
        return True, f"{dest.name} {verbe} → {dest.parent}{remarque}"
    if genre == "corbeille":
        p = Path(op.get("chemin") or "")
        if not str(p) or (not p.exists() and not p.is_symlink()):
            return False, f"{p.name} n'existe plus (rien à jeter)"
        _verifier(p)
        fichiers.mettre_corbeille(p)
        return True, f"{p.name} mis à la Corbeille"
    if genre == "supprimer_dossier_vide":
        p = Path(op.get("chemin") or "")
        if not p.is_dir():
            return True, ""
        _verifier(p)
        try:
            next(p.iterdir())
            return False, f"dossier {p.name} gardé (il n'est pas vide)"
        except StopIteration:
            p.rmdir()
            return True, f"dossier vide {p.name} retiré"
    return False, f"opération inconnue : {genre}"


def annuler(fichier: Path) -> dict:
    """Défait la dernière entrée. Renvoie {"ok", "texte", "restaures", "echecs", "description"}."""
    entree = derniere(fichier)
    if entree is None:
        return {"ok": True, "texte": "Rien à annuler : aucune action sur les fichiers n'est enregistrée.",
                "restaures": 0, "echecs": 0, "description": ""}
    # Retirée d'abord : une annulation ratée n'est pas rejouée en boucle (ni ne fait annuler l'action d'avant).
    _retirer(fichier, entree["id"])
    faits, echecs = [], []
    for op in reversed(entree["operations"]):
        try:
            ok, texte = _appliquer(op)
        except Exception as e:  # noqa: BLE001 - chaque opération est indépendante : on continue
            ok, texte = False, f"erreur ({e})"
        if texte:
            (faits if ok else echecs).append(texte)
    desc = entree.get("description", "dernière action")
    if not echecs:
        texte = f"Annulé : {desc}." + ("\n- " + "\n- ".join(faits) if faits else "")
    elif faits:
        texte = (f"Annulation partielle de « {desc} ».\nRestauré :\n- " + "\n- ".join(faits)
                 + "\nNon restauré :\n- " + "\n- ".join(echecs))
    else:
        texte = f"Je n'ai rien pu restaurer pour « {desc} » :\n- " + "\n- ".join(echecs)
    return {"ok": bool(faits) or not echecs, "texte": texte, "restaures": len(faits), "echecs": len(echecs),
            "description": desc}


# --- Aides pour les outils --------------------------------------------------------------

def dossiers_manquants(d: Path) -> list[Path]:
    """Dossiers qui seront créés par un mkdir(parents=True), du plus haut au plus profond."""
    manquants = []
    d = Path(d)
    while not d.exists() and d != d.parent:
        manquants.append(d)
        d = d.parent
    return list(reversed(manquants))


def ops_dossiers(manquants: list[Path]) -> list[dict]:
    return [{"type": "supprimer_dossier_vide", "chemin": str(m)} for m in manquants]
