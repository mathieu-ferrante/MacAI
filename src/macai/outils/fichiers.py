"""Fichiers et dossiers : lister, créer, écrire, déplacer, renommer, copier, Corbeille, ranger."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from ..mac import commun
from .base import ErreurOutil, Resultat, Risque, outil

# Jamais lus ni modifiés par l'agent : clés, mots de passe, cookies, messageries, historiques, navigateurs.
# Comparaison sans casse (APFS ne distingue pas ~/.SSH de ~/.ssh) sur le chemin réel (liens résolus).
INTERDITS = [".ssh", ".gnupg", ".aws", ".netrc", ".config", ".docker", ".kube", ".npmrc", ".pypirc", ".env",
             ".zsh_history", ".bash_history", ".python_history", ".lesshst", ".git-credentials",
             "library/keychains", "library/cookies", "library/messages", "library/mail", "library/safari",
             "library/accounts", "library/application support/google/chrome",
             "library/application support/bravesoftware", "library/application support/microsoft edge",
             "library/application support/arc", "library/application support/firefox",
             "library/application support/1password", "library/application support/bitwarden",
             "library/group containers/2bua8c4s2c.com.1password"]
MOTS_INTERDITS = ("login data", "cookies", "web data", "keychain", "id_rsa", "id_ed25519", ".pem", ".p12")


def _donnees_macai() -> Path:
    from ..config import dossier_donnees
    return Path(dossier_donnees()).expanduser().resolve()


def _depot_macai() -> Path:
    return Path(__file__).resolve().parents[3]  # …/MacAI (src/macai/outils/fichiers.py)


def chemin_interdit(chemin) -> bool:
    """Vrai si le chemin touche des secrets ou les fichiers de MacAI lui-même (jeton, journal, index, réglages)."""
    try:
        r = Path(os.path.realpath(Path(str(chemin)).expanduser()))
    except (OSError, ValueError):
        return True
    texte = r.as_posix().casefold()
    maison = Path.home().resolve().as_posix().casefold()
    relatif = texte[len(maison) + 1:] if texte.startswith(maison + "/") else ""
    if relatif and any(relatif == i or relatif.startswith(i + "/") for i in INTERDITS):
        return True
    if any(m in texte for m in MOTS_INTERDITS):
        return True
    return r.is_relative_to(_donnees_macai())


CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".svg", ".tiff", ".bmp", ".raw", ".cr2", ".nef"},
    "PDF": {".pdf"},
    "Documents": {".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pages", ".epub"},
    "Tableurs": {".xls", ".xlsx", ".csv", ".numbers", ".ods"},
    "Présentations": {".ppt", ".pptx", ".key", ".odp"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2"},
    "Installeurs": {".dmg", ".pkg", ".app", ".exe", ".msi"},
    "Vidéos": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"},
    "Audio": {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".swift", ".java", ".c", ".cpp", ".sh", ".ipynb"},
    "3D": {".stl", ".step", ".stp", ".obj", ".3mf", ".f3d", ".blend"},
}


def _ecriture_permise(p: Path) -> bool:
    """Dossier personnel (hors fichiers cachés et Bibliothèque), disques externes et dossier temporaire ; jamais
    le système, ni ce qui ferait exécuter du code plus tard (~/.zshenv, LaunchAgents, réglages et code de MacAI)."""
    r = Path(os.path.realpath(p))
    temporaire = Path(tempfile.gettempdir()).resolve()
    if r.is_relative_to(temporaire) or str(r).startswith("/Volumes/"):
        return True
    maison = Path.home().resolve()
    if not r.is_relative_to(maison):
        return False
    parties = r.relative_to(maison).parts
    if any(x.startswith(".") for x in parties):
        return False
    if parties and parties[0] == "Library" and "Mobile Documents" not in parties:
        return False  # seul iCloud Drive (Library/Mobile Documents) reste modifiable
    return not (r.is_relative_to(_donnees_macai()) or r.is_relative_to(_depot_macai()))


def verifier_chemin(p: Path, ecriture: bool = False) -> Path:
    if chemin_interdit(p):
        raise ErreurOutil(f"Accès refusé à {p} : dossier protégé (clés, mots de passe, messageries, navigateurs "
                          "ou fichiers de MacAI).")
    if ecriture and sys.platform == "darwin" and not _ecriture_permise(p):
        raise ErreurOutil(f"Écriture refusée : {p} (système, fichier caché, Bibliothèque ou fichiers de MacAI).")
    return p


def resoudre(chemin: str, ecriture: bool = False, doit_exister: bool = False) -> Path:
    p = verifier_chemin(commun.chemin(chemin), ecriture)
    if doit_exister and not p.exists():
        proche = fichier_proche(p, strict=ecriture)
        if proche is None:
            raise ErreurOutil(f"{p} n'existe pas. Utilise rechercher_fichiers pour retrouver le bon chemin.")
        p = verifier_chemin(proche, ecriture)
    return p


def fichier_proche(p: Path, strict: bool) -> Path | None:
    """Corrige un nom mal recopié par le modèle (« reunion.jpg » pour « reunion.txt ») s'il n'y a qu'un candidat.
    En écriture (strict) : seulement même nom avec une autre extension."""
    import difflib
    dossier = p.parent
    if not dossier.is_dir():
        return None
    try:
        noms = [e.name for e in dossier.iterdir() if not e.name.startswith(".")]
    except OSError:
        return None
    meme_nom = [n for n in noms if Path(n).stem.lower() == p.stem.lower()]
    if len(meme_nom) == 1:
        return dossier / meme_nom[0]
    if strict:
        return None
    proches = difflib.get_close_matches(p.name, noms, n=2, cutoff=0.85)
    return dossier / proches[0] if len(proches) == 1 else None


def taille_lisible(n: float) -> str:
    for u in ("o", "Ko", "Mo", "Go"):
        if n < 1024:
            return f"{n:.0f} {u}" if u in ("o", "Ko") else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} To"


def sans_collision(dest: Path) -> Path:
    """« rapport.pdf » existe déjà → « rapport (2).pdf ». Jamais d'écrasement silencieux."""
    if not dest.exists():
        return dest
    i = 2
    while (c := dest.with_name(f"{dest.stem} ({i}){dest.suffix}")).exists():
        i += 1
    return c


@outil("lister_dossier", "Liste le contenu d'un dossier (nom, taille, date de modification).", "fichiers",
       {"chemin": ("string", "dossier, ex. ~/Downloads"),
        "tri": ("string", "ordre", ["nom", "date", "taille"])}, requis=["chemin"], mac_seulement=False)
def lister_dossier(ctx, chemin, tri="date"):
    d = resoudre(chemin, doit_exister=True)
    if not d.is_dir():
        raise ErreurOutil(f"{d} n'est pas un dossier.")
    elements = [e for e in d.iterdir() if not e.name.startswith(".")]
    cle = {"nom": lambda e: e.name.lower(), "taille": lambda e: -e.stat().st_size,
           "date": lambda e: -e.stat().st_mtime}.get(tri, lambda e: -e.stat().st_mtime)
    elements.sort(key=cle)
    lignes = []
    for e in elements[:150]:
        st = e.stat()
        genre = "📁" if e.is_dir() else taille_lisible(st.st_size)
        lignes.append(f"{e.name}  [{genre}, {time.strftime('%d/%m/%Y %H:%M', time.localtime(st.st_mtime))}]")
    reste = f"\n… et {len(elements) - 150} autres" if len(elements) > 150 else ""
    return Resultat(True, f"{d} ({len(elements)} éléments)\n" + "\n".join(lignes) + reste,
                    {"chemin": str(d), "nb": len(elements)})


@outil("creer_dossier", "Crée un dossier (et ses parents si besoin).", "fichiers",
       {"chemin": ("string", "dossier à créer")}, risque=Risque.CREATION, mac_seulement=False)
def creer_dossier(ctx, chemin):
    d = resoudre(chemin, ecriture=True)
    d.mkdir(parents=True, exist_ok=True)
    return f"Dossier prêt : {d}"


def _risque_ecriture(args):
    try:
        return Risque.MODIFICATION if commun.chemin(args.get("chemin", "")).exists() else Risque.CREATION
    except OSError:
        return Risque.CREATION


@outil("ecrire_fichier_texte", "Crée un fichier texte (txt, md, py, html, json…) avec le contenu donné. "
       "Par défaut n'écrase pas un fichier existant.", "fichiers",
       {"chemin": ("string", "chemin du fichier, ex. ~/Desktop/notes.md"), "contenu": ("string", "texte complet"),
        "ecraser": ("boolean", "remplacer le fichier s'il existe")}, requis=["chemin", "contenu"],
       risque=_risque_ecriture, mac_seulement=False, annonce=lambda a: f"Écrire {a['chemin']}")
def ecrire_fichier_texte(ctx, chemin, contenu, ecraser=False):
    p = resoudre(chemin, ecriture=True)
    if p.exists() and not ecraser:
        p = sans_collision(p)
    elif p.exists():
        mettre_corbeille(p)  # l'ancienne version reste récupérable dans la Corbeille
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu, encoding="utf-8")
    return Resultat(True, f"Fichier écrit : {p} ({len(contenu)} caractères)", {"fichier": str(p)})


def _vers_dossier(src: Path, dest: Path, texte: str) -> bool:
    """La destination désigne-t-elle un dossier ? Oui s'il existe, finit par « / », ou s'il n'existe pas et n'a
    pas d'extension alors que la source en a une (« déplace a.pdf vers Factures » = dans le dossier Factures)."""
    if dest.is_dir() or str(texte).endswith("/"):
        return True
    return not dest.exists() and not dest.suffix and src.is_file() and bool(src.suffix)


@outil("deplacer", "Déplace un fichier ou dossier. Si la destination est un dossier, l'élément y est placé. "
       "N'écrase jamais : ajoute (2) au nom si besoin.", "fichiers",
       {"source": ("string", "chemin à déplacer"), "destination": ("string", "dossier ou nouveau chemin")},
       risque=Risque.MODIFICATION, mac_seulement=False,
       annonce=lambda a: f"Déplacer {a['source']} vers {a['destination']}")
def deplacer(ctx, source, destination):
    src = resoudre(source, ecriture=True, doit_exister=True)
    dest = resoudre(destination, ecriture=True)
    if _vers_dossier(src, dest, destination):
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / src.name
    dest = sans_collision(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return Resultat(True, f"Déplacé : {src.name} → {dest}", {"fichier": str(dest)})


@outil("renommer", "Renomme un fichier ou dossier (dans le même dossier).", "fichiers",
       {"chemin": ("string", "élément à renommer"), "nouveau_nom": ("string", "nouveau nom avec extension")},
       risque=Risque.MODIFICATION, mac_seulement=False,
       annonce=lambda a: f"Renommer {Path(a['chemin']).name} en {a['nouveau_nom']}")
def renommer(ctx, chemin, nouveau_nom):
    src = resoudre(chemin, ecriture=True, doit_exister=True)
    if "/" in nouveau_nom:
        raise ErreurOutil("Le nouveau nom ne doit pas contenir de « / » (utilise deplacer).")
    if not Path(nouveau_nom).suffix and src.suffix:
        nouveau_nom += src.suffix
    dest = sans_collision(src.with_name(nouveau_nom))
    src.rename(dest)
    return Resultat(True, f"Renommé en {dest.name}", {"fichier": str(dest)})


@outil("copier", "Copie un fichier ou dossier.", "fichiers",
       {"source": ("string", "chemin à copier"), "destination": ("string", "dossier ou nouveau chemin")},
       risque=Risque.CREATION, mac_seulement=False)
def copier(ctx, source, destination):
    src = resoudre(source, doit_exister=True)
    dest = resoudre(destination, ecriture=True)
    if _vers_dossier(src, dest, destination):
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / src.name
    dest = sans_collision(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    (shutil.copytree if src.is_dir() else shutil.copy2)(str(src), str(dest))
    return Resultat(True, f"Copié vers {dest}", {"fichier": str(dest)})


def _cible_corbeille(chemin: str) -> str:
    try:
        return str(commun.chemin(chemin))
    except (OSError, ValueError):
        return str(chemin)


def mettre_corbeille(p: Path) -> None:
    if sys.platform == "darwin":
        from Foundation import NSFileManager, NSURL
        ok, _, err = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            NSURL.fileURLWithPath_(str(p)), None, None)
        if not ok:
            raise ErreurOutil(f"Impossible de mettre {p.name} à la Corbeille : {err}")
    else:  # poste de développement : corbeille simulée
        corbeille = Path.home() / ".macai" / "corbeille"
        corbeille.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(sans_collision(corbeille / p.name)))


@outil("mettre_a_la_corbeille", "Met un fichier ou dossier à la Corbeille (récupérable).", "fichiers",
       {"chemin": ("string", "élément à jeter")}, risque=Risque.SENSIBLE, toujours_confirmer=True,
       mac_seulement=False, annonce=lambda a: f"Mettre {_cible_corbeille(a.get('chemin', ''))} à la Corbeille")
def mettre_a_la_corbeille(ctx, chemin):
    p = resoudre(chemin, ecriture=True)
    if not p.exists():
        # Pas de correction automatique du nom ici : la confirmation doit porter sur le fichier exact.
        raise ErreurOutil(f"{p} n'existe pas. Vérifie le nom exact avec lister_dossier ou rechercher_fichiers.")
    maison = Path.home().resolve()
    if p.resolve() == maison or len(p.parts) <= 3 or p.resolve().parent == maison:
        raise ErreurOutil(f"Refusé : {p} est un dossier principal de ton compte.")
    mettre_corbeille(p)
    return f"{p.name} est dans la Corbeille."


def categorie(p: Path) -> str:
    ext = p.suffix.lower()
    for nom, exts in CATEGORIES.items():
        if ext in exts:
            return nom
    return "Dossiers" if p.is_dir() else "Autres"


def plan_rangement(d: Path) -> dict[str, list[Path]]:
    plan: dict[str, list[Path]] = defaultdict(list)
    for e in d.iterdir():
        if e.name.startswith(".") or (e.is_dir() and e.name in CATEGORIES) or e.name in ("Dossiers", "Autres"):
            continue
        if e.is_dir() and e.suffix.lower() != ".app":
            continue  # les dossiers existants restent en place
        plan[categorie(e)].append(e)
    return dict(plan)


def _annonce_rangement(args):
    d = commun.chemin(args.get("chemin", "~/Downloads"))
    plan = plan_rangement(d) if d.is_dir() else {}
    total = sum(len(v) for v in plan.values())
    detail = ", ".join(f"{k} ({len(v)})" for k, v in sorted(plan.items(), key=lambda x: -len(x[1])))
    return f"Ranger {total} fichiers de {d.name} dans des sous-dossiers : {detail}"


@outil("ranger_dossier", "Range les fichiers d'un dossier dans des sous-dossiers par type (Images, PDF, "
       "Documents, Installeurs, Archives…). Les sous-dossiers existants ne bougent pas.", "fichiers",
       {"chemin": ("string", "dossier à ranger, ex. ~/Downloads")}, risque=Risque.SENSIBLE,
       mac_seulement=False, annonce=_annonce_rangement)
def ranger_dossier(ctx, chemin):
    d = resoudre(chemin, ecriture=True, doit_exister=True)
    plan = plan_rangement(d)
    deplaces = 0
    for cat, elements in plan.items():
        (d / cat).mkdir(exist_ok=True)
        for e in elements:
            ctx.verifier_arret()
            shutil.move(str(e), str(sans_collision(d / cat / e.name)))
            deplaces += 1
    resume = ", ".join(f"{k} : {len(v)}" for k, v in plan.items())
    return Resultat(True, f"{deplaces} fichiers rangés dans {d}. {resume}", {"plan": {k: len(v) for k, v in plan.items()}})
