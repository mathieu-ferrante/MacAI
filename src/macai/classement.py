"""Classement automatique des papiers : type (facture, relevé, impôts…), date, émetteur, montant, puis nom
« AAAA-MM Émetteur type montant.pdf » et dossier ~/Documents/Administratif/<Type>/<AAAA>.

Règles fixes (aucun modèle). `verifier_telechargements` est appelé périodiquement par l'application quand
[classement] actif = true : il ne déplace que ce qui est reconnu avec certitude, et chaque déplacement s'annule.
"""
from __future__ import annotations

import re
import shutil
import time
from datetime import date
from pathlib import Path

from . import annulation, extraction
from .outils import finances

SEUIL = 0.6                  # confiance minimale pour classer sans demander
AGE_MIN_S = 120              # un téléchargement plus récent peut être encore en cours d'écriture
AGE_MAX_S = 86_400           # au-delà d'un jour : déjà vu par l'utilisateur, on n'y touche plus d'office
FORMATS = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".txt"} | extraction.IMAGES
EN_COURS = {".crdownload", ".download", ".part", ".partial", ".tmp"}

# type → (dossier, libellé dans le nom, [(motif, poids)]). Poids 3 : décisif ; 1 : indice.
TYPES: dict[str, tuple[str, str, list[tuple[str, int]]]] = {
    "facture": ("Factures", "facture", [
        (r"\bfacture\b", 3), (r"\binvoice\b", 3), (r"n[°o] de facture|num[ée]ro de facture", 3),
        (r"total ttc|montant ttc|net [àa] payer|montant [àa] payer", 2), (r"\btva\b", 1), (r"\bticket\b", 2),
        (r"\bre[çc]u\b|\breceipt\b", 2), (r"\bht\b", 1), (r"[ée]ch[ée]ance", 1)]),
    "releve": ("Banque", "relevé bancaire", [
        (r"relev[ée] de (compte|vos comptes)|relev[ée] bancaire|extrait de compte", 4), (r"ancien solde", 3),
        (r"nouveau solde|solde (cr[ée]diteur|d[ée]biteur|au)", 3), (r"\biban\b", 1), (r"\bbic\b", 1),
        (r"op[ée]rations? (du|de la p[ée]riode)", 2), (r"\bd[ée]bit\b.*\bcr[ée]dit\b", 2)]),
    "impots": ("Impôts", "impôts", [
        (r"avis d.imp[ôo]t|imp[ôo]t sur le revenu", 4), (r"taxe fonci[èe]re|taxe d.habitation", 4),
        (r"impots\.gouv|imp[ôo]ts\.gouv|\bdgfip\b|finances publiques", 3),
        (r"revenu fiscal de r[ée]f[ée]rence|num[ée]ro fiscal|d[ée]claration de revenus", 3),
        (r"pr[ée]l[èe]vement [àa] la source", 2)]),
    "assurance": ("Assurances", "assurance", [
        (r"attestation d.assurance|contrat d.assurance|avis d.[ée]ch[ée]ance|certificat d.assurance", 4),
        (r"\bassurances?\b", 2), (r"\bassur[ée]\b|\bsouscripteur\b", 1), (r"\bsinistre\b", 2),
        (r"\bcotisation\b", 1), (r"responsabilit[ée] civile|multirisque|carte verte", 2),
        (r"\b(maif|macif|maaf|axa|allianz|groupama|gmf|matmut)\b", 2)]),
    "sante": ("Santé", "santé", [
        (r"\bordonnance\b", 4), (r"feuille de soins|d[ée]compte de (remboursement|prestations)", 4),
        (r"assurance maladie|\bameli\b|\bcpam\b", 3), (r"\bmutuelle\b|compl[ée]mentaire sant[ée]", 2),
        (r"\bpharmacie\b|\bm[ée]decin\b|\bdocteur\b|\bpatient\b|\bsoins\b", 1), (r"compte rendu (m[ée]dical|d.examen)", 3),
        (r"\banalyses? (de sang|m[ée]dicales?)|laboratoire d.analyses", 3)]),
    "contrat": ("Contrats", "contrat", [
        (r"\bcontrat (de|d')", 3), (r"conditions (g[ée]n[ée]rales|particuli[èe]res)", 2),
        (r"entre les soussign[ée]s|ci-apr[èe]s d[ée]nomm[ée]", 3), (r"\bbail\b|contrat de location", 3),
        (r"\bavenant\b", 2), (r"\bsignature\b|lu et approuv[ée]", 1), (r"\barticle \d+", 1)]),
    "paie": ("Fiches de paie", "fiche de paie", [
        (r"bulletin de (paie|salaire)|fiche de paie", 5), (r"salaire (de )?base|salaire brut", 3),
        (r"net imposable|net [àa] payer avant imp[ôo]t", 3), (r"cotisations? salariales?|\burssaf\b", 2),
        (r"\bconvention collective\b|\bemployeur\b", 1)]),
    "billet": ("Voyages", "billet", [
        (r"e-?billet|carte d.embarquement|boarding pass", 4), (r"num[ée]ro de (r[ée]servation|dossier)|\bpnr\b", 3),
        (r"\bbillet\b", 2), (r"confirmation de r[ée]servation|votre r[ée]servation", 3),
        (r"\bvoyageur\b|\bpassager\b|\bvol\b|\btrain\b|\bvoiture \d+|\bplace \d+", 1),
        (r"\bcheck-?in\b|\bh[ôo]tel\b|\bnuit(s|[ée]e)?\b", 1)]),
    "garantie": ("Garanties et notices", "garantie", [
        (r"certificat de garantie|bon de garantie|extension de garantie", 4), (r"\bgarantie\b", 2),
        (r"notice d.utilisation|mode d.emploi|manuel (d.utilisation|utilisateur)|user manual|user guide", 4),
        (r"\bconsignes de s[ée]curit[ée]\b|\bnum[ée]ro de s[ée]rie\b", 1)]),
}
_TYPES = {k: (d, l, [(re.compile(m, re.I), p) for m, p in ms]) for k, (d, l, ms) in TYPES.items()}
AVEC_MONTANT = {"facture", "impots", "assurance", "billet", "sante"}

# Émetteurs non commerçants (banques, organismes) ; les marchands viennent de finances.MARCHANDS.
EMETTEURS = [
    (r"cr[ée]dit agricole", "Crédit Agricole"), (r"\bbnp\b|bnp paribas", "BNP Paribas"),
    (r"soci[ée]t[ée] g[ée]n[ée]rale", "Société Générale"), (r"\blcl\b", "LCL"),
    (r"caisse d.[ée]pargne", "Caisse d'Épargne"), (r"banque populaire", "Banque Populaire"),
    (r"boursorama|boursobank", "BoursoBank"), (r"la banque postale", "La Banque Postale"),
    (r"cr[ée]dit mutuel", "Crédit Mutuel"), (r"\bcic\b", "CIC"), (r"\bfortuneo\b", "Fortuneo"),
    (r"\brevolut\b", "Revolut"), (r"\bqonto\b", "Qonto"), (r"hello ?bank", "Hello bank!"),
    (r"assurance maladie|\bameli\b|\bcpam\b", "Assurance Maladie"), (r"\bcaf\b|allocations familiales", "CAF"),
    (r"\burssaf\b", "Urssaf"), (r"france travail|p[ôo]le emploi", "France Travail"),
]
_EMETTEURS = [(re.compile(m, re.I), n) for m, n in EMETTEURS]
NOMS_GENERIQUES = re.compile(r"^(document|scan|scanned|img|image|file|fichier|facture|invoice|download|"
                             r"telechargement|sans titre|untitled|print|pdf|doc)?[\s_\-\d()]*$", re.I)


def detecter_type(texte: str, nom: str = "") -> tuple[str | None, float, list[str]]:
    """(type, confiance 0–1, indices trouvés). La confiance tient au score et à l'écart avec le 2e type."""
    t = f"{nom}\n{texte[:20000]}"
    scores, indices = {}, {}
    for cle, (_, _, motifs) in _TYPES.items():
        trouves = [(m.pattern, p) for m, p in motifs if m.search(t)]
        scores[cle] = sum(p for _, p in trouves)
        indices[cle] = [m for m, _ in trouves]
    classes = sorted(scores.items(), key=lambda x: -x[1])
    (meilleur, s1), (_, s2) = classes[0], classes[1]
    if s1 < 3:
        return None, 0.0, []
    confiance = min(1.0, s1 / 7) * (1 - 0.6 * (s2 / s1))
    return meilleur, round(confiance, 2), indices[meilleur]


def trouver_emetteur(texte: str, nom: str = "") -> str | None:
    for t in (nom, texte[:1500], texte):
        meilleur = None
        for motif, n in _EMETTEURS:
            m = motif.search(t)
            if m and (meilleur is None or m.start() < meilleur[0]):
                meilleur = (m.start(), n)
        marchand = finances.premier_marchand(t)
        if marchand and (meilleur is None or marchand[0] < meilleur[0]):
            meilleur = (marchand[0], marchand[1])
        if meilleur:
            return meilleur[1]
    stem = re.sub(r"[_\-]+", " ", Path(nom).stem).strip() if nom else ""
    if stem and not NOMS_GENERIQUES.match(stem):
        mots = [m for m in stem.split() if len(m) >= 3 and not m.isdigit()
                and not re.fullmatch(r"facture|invoice|scan|releve|relevé|document|copie|final", m, re.I)]
        if mots:
            return " ".join(mots[:3])[:30]
    return None


def nom_propre(texte: str) -> str:
    t = re.sub(r"[/\\:*?\"<>|\n\r\t]+", " ", texte)
    return re.sub(r"\s+", " ", t).strip(" .")[:110]


def proposer_classement(chemin, texte: str | None = None, racine: Path | None = None) -> dict | None:
    """Proposition de classement d'un document, ou None s'il n'est pas reconnu (format, contenu vide, type)."""
    p = Path(chemin)
    ext = p.suffix.lower()
    if ext not in FORMATS or not p.is_file():
        return None
    if texte is None:
        try:
            texte = extraction.extraire(p, limite=30_000)
        except Exception:  # noqa: BLE001 - document abîmé : pas de classement
            return None
    texte = str(texte or "")
    if len(texte.strip()) < 30:
        return None
    genre, confiance, indices = detecter_type(texte, p.name)
    if genre is None:
        return None
    dossier, libelle, _ = TYPES[genre]
    jour = finances.date_document(texte)
    if jour is None or jour > date.today():
        jour = date.fromtimestamp(p.stat().st_mtime)
        confiance = round(confiance * 0.75, 2)
    emetteur = trouver_emetteur(texte, p.name)
    if emetteur is None:
        confiance = round(confiance * 0.75, 2)
    montant = finances.montant_total(texte) if genre in AVEC_MONTANT else None
    parties = [f"{jour:%Y-%m}", emetteur or "", libelle, finances.euros(montant) if montant else ""]
    nom = nom_propre(" ".join(x for x in parties if x)) + ext
    base = Path(racine) if racine else Path.home() / "Documents" / "Administratif"
    return {"source": str(p), "type": genre, "libelle": libelle, "dossier_type": dossier, "date": jour.isoformat(),
            "emetteur": emetteur, "montant": montant, "nom": nom,
            "destination": str(base / dossier / f"{jour:%Y}" / nom), "confiance": confiance, "indices": indices}


def classer(ctx, chemin, proposition: dict | None = None, racine: Path | None = None) -> str:
    """Applique une proposition : déplacement sans écrasement, dossiers créés, entrée dans « annuler »."""
    from .outils.base import ErreurOutil
    from .outils.fichiers import resoudre, sans_collision, verifier_chemin
    src = resoudre(str(chemin), ecriture=True, doit_exister=True)
    proposition = proposition or proposer_classement(src, racine=racine)
    if proposition is None:
        raise ErreurOutil(f"Type de {src.name} non reconnu : rien n'a été déplacé.")
    dest = verifier_chemin(Path(proposition["destination"]), ecriture=True)
    if src.resolve() == dest.resolve():
        return f"{src.name} est déjà classé."
    ops = annulation.ops_dossiers(annulation.dossiers_manquants(dest.parent))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = sans_collision(dest)
    shutil.move(str(src), str(dest))
    ops.append({"type": "deplacer", "de": str(dest), "vers": str(src)})
    annulation.enregistrer(ctx, f"Classement de {src.name} ({proposition['libelle']})", ops)
    proposition["arrivee"] = str(dest)
    try:
        lieu = dest.relative_to(Path.home())
    except ValueError:
        lieu = dest
    return f"Classé : {src.name} → {lieu}"


def candidats(dossier: Path, maintenant: float | None = None, age_min: float = AGE_MIN_S,
              age_max: float | None = AGE_MAX_S) -> list[Path]:
    """Fichiers du dossier (sans les sous-dossiers) au format lisible, terminés d'écrire, assez récents."""
    maintenant = maintenant or time.time()
    sortie = []
    try:
        entrees = list(Path(dossier).iterdir())
    except OSError:
        return []
    for p in entrees:
        if p.name.startswith(".") or p.suffix.lower() in EN_COURS or p.suffix.lower() not in FORMATS:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if not p.is_file() or st.st_size == 0:
            continue
        age = maintenant - st.st_mtime
        if age < age_min or (age_max is not None and age > age_max):
            continue
        if any(p.with_name(p.name + e).exists() for e in EN_COURS):
            continue  # téléchargement en cours sous un nom voisin
        sortie.append(p)
    return sorted(sortie, key=lambda p: p.stat().st_mtime, reverse=True)


def verifier_telechargements(ctx, deja_vus: set, dossier: Path | None = None, racine: Path | None = None,
                             maintenant: float | None = None, seuil: float = SEUIL) -> list[str]:
    """À appeler périodiquement (toutes les quelques minutes) quand [classement] actif = true. Nouveaux fichiers de
    ~/Downloads âgés de 2 min à 1 jour : classés si le type est sûr, sinon laissés en place. Chaque fichier n'est
    examiné qu'une fois (`deja_vus`, gardé par l'appelant). Renvoie les phrases à notifier (une par classement)."""
    d = Path(dossier) if dossier else Path.home() / "Downloads"
    faits = []
    for p in candidats(d, maintenant):
        cle = f"{p}|{p.stat().st_size}|{int(p.stat().st_mtime)}"
        if cle in deja_vus:
            continue
        deja_vus.add(cle)
        try:
            proposition = proposer_classement(p, racine=racine)
            if proposition is None or proposition["confiance"] < seuil:
                continue
            faits.append(classer(ctx, p, proposition))
        except Exception as e:  # noqa: BLE001 - un fichier à problème n'arrête pas la surveillance
            journal = getattr(ctx, "journal", None)
            if journal is not None:
                journal.ecrire("erreur_classement", fichier=str(p), texte=str(e))
    return faits


def classer_dossier(ctx, dossier: Path, racine: Path | None = None, seuil: float = SEUIL,
                    nombre_max: int = 40, age_max_jours: int = 365) -> dict:
    """Pour l'outil classer_telechargements : classe les documents sûrs, liste les autres."""
    bilan: dict[str, list] = {"classes": [], "incertains": [], "inconnus": []}
    for p in candidats(dossier, age_min=0, age_max=age_max_jours * 86_400)[:nombre_max]:
        ctx.verifier_arret()
        proposition = proposer_classement(p, racine=racine)
        if proposition is None:
            bilan["inconnus"].append(p.name)
        elif proposition["confiance"] < seuil:
            bilan["incertains"].append((p.name, proposition["libelle"], proposition["confiance"]))
        else:
            bilan["classes"].append(classer(ctx, p, proposition))
    return bilan


def resume_bilan(bilan: dict, dossier: Path) -> str:
    lignes = []
    if bilan["classes"]:
        lignes.append(f"{len(bilan['classes'])} document(s) classé(s) (annulable avec « annuler ») :")
        lignes += [f"- {c}" for c in bilan["classes"]]
    else:
        lignes.append(f"Aucun document administratif reconnu avec certitude dans {dossier}.")
    if bilan["incertains"]:
        lignes.append("Type incertain, laissés en place (classer_document pour les classer un par un) :")
        lignes += [f"- {n} (peut-être : {lib}, confiance {c:.0%})" for n, lib, c in bilan["incertains"]]
    if bilan["inconnus"]:
        lignes.append(f"Non reconnus comme papiers administratifs : {len(bilan['inconnus'])} fichier(s).")
    return "\n".join(lignes)
