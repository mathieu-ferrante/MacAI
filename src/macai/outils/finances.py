"""Papiers et dépenses : relevé des factures et tickets indexés, export Excel, classement des documents.

Tout est fait par des règles fixes (montants, dates, marchands, mots-clés) : aucun modèle, rien ne quitte le Mac.
Les fonctions de lecture (`lire_montant`, `montant_total`, `lire_dates`, `date_document`, `trouver_marchand`,
`categorie_depense`) sont pures et partagées avec `macai.classement`.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from .base import ErreurOutil, Resultat, Risque, outil

MOIS = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre",
        "novembre", "decembre"]
MOIS_ABREGES = {"janv": 1, "jan": 1, "fevr": 2, "fev": 2, "avr": 4, "juil": 7, "sept": 9, "sep": 9, "oct": 10,
                "nov": 11, "dec": 12}
MOIS_AFFICHES = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
                 "novembre", "décembre"]


def sans_accents(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t or "").lower().replace("’", "'"))
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# --- Montants -----------------------------------------------------------------------------------------------

ESPACES = "    "  # espace, insécable, fine insécable, fine
NOMBRE = rf"\d{{1,3}}(?:[{ESPACES}.,']\d{{3}})+(?:[.,]\d{{1,2}})?|\d+(?:[.,]\d{{1,2}})?"
DEVISE = r"(?:€|eur(?:os?)?\b)"
MONTANT_DEVISE = re.compile(rf"(?<![\d.,])(?:({NOMBRE})\s?{DEVISE}|€\s?({NOMBRE}))(?![\d])", re.I)
MONTANT_NU = re.compile(rf"(?<![\d.,/-])({NOMBRE})(?![\d/]|[.,]\d)")


def nombre(texte: str) -> float | None:
    """« 1 284,50 » → 1284.5 ; « 84.20 » → 84.2 ; « 1.284,50 » → 1284.5 ; « 1,284.50 » → 1284.5."""
    t = re.sub(rf"[{ESPACES}']", "", str(texte or "").strip())
    if not re.fullmatch(r"[\d.,]+", t) or not re.search(r"\d", t):
        return None
    m = re.search(r"[.,](\d{1,2})$", t)
    if m:
        entier, decimales = t[:m.start()], m.group(1)
    else:
        entier, decimales = t, ""
    entier = re.sub(r"[.,]", "", entier)
    try:
        return round(float(f"{entier or '0'}.{decimales or '0'}"), 2)
    except ValueError:
        return None


def lire_montant(texte: str) -> float | None:
    """Premier montant en euros d'un texte : « 1 284,50 € », « 84.20 EUR », « € 12 », « 9,99 euros »."""
    m = MONTANT_DEVISE.search(str(texte or ""))
    return nombre(m.group(1) or m.group(2)) if m else None


def montants(texte: str) -> list[float]:
    return [v for m in MONTANT_DEVISE.finditer(str(texte or "")) if (v := nombre(m.group(1) or m.group(2)))]


# Libellés du montant payé, du plus sûr au moins sûr. « Total HT », « TVA », « sous-total » sont écartés.
TOTAUX = [
    r"net [àa] payer", r"montant [àa] payer", r"total [àa] payer", r"reste [àa] payer", r"somme [àa] payer",
    r"montant (total )?ttc", r"total ttc", r"total t\.t\.c", r"[àa] r[ée]gler", r"montant pr[ée]lev[ée]",
    r"total pay[ée]", r"montant pay[ée]", r"montant d[ûu]", r"montant de (la|votre) facture", r"total factur[ée]",
    r"amount due", r"total due", r"grand total", r"total (de la )?commande", r"montant total", r"\btotal\b",
    r"\bmontant\b", r"\bpay[ée]\b",
]
EXCLUS_TOTAL = re.compile(r"\b(hors taxes?|h\.?t\.?|tva|sous[- ]total|remise|[ée]conomie|acompte vers[ée])\b", re.I)


def montant_total(texte: str) -> float | None:
    """Montant payé d'une facture ou d'un ticket : celui qui suit le libellé le plus sûr (« net à payer »,
    « total TTC »…), sinon le plus grand montant en euros du document."""
    t = str(texte or "")
    for libelle in TOTAUX:
        for m in re.finditer(libelle, t, re.I):
            debut_ligne = t.rfind("\n", 0, m.start()) + 1
            fin_ligne = t.find("\n", m.end())
            ligne = t[debut_ligne:fin_ligne if fin_ligne >= 0 else len(t)]
            if EXCLUS_TOTAL.search(ligne) and not re.search(r"ttc", ligne, re.I):
                continue
            suite = t[m.end():m.end() + 90]
            v = lire_montant(suite)
            if v is None:  # « Total TTC : 84,20 » (devise en tête de colonne)
                n = MONTANT_NU.search(suite[:40])
                v = nombre(n.group(1)) if n and re.search(r"[.,]\d{2}$", n.group(1)) else None
            if v:
                return v
    tous = montants(t)
    return max(tous) if tous else None


def euros(v: float | None) -> str:
    """84.2 → « 84,20 € » ; 1284.5 → « 1 284,50 € »."""
    if v is None:
        return "?"
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " €"


# --- Dates --------------------------------------------------------------------------------------------------

_MOIS_RE = "|".join(sorted(MOIS + list(MOIS_ABREGES), key=len, reverse=True))
DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")
DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_TEXTE = re.compile(rf"(?<!\d)(\d{{1,2}})(?:er)?\s+({_MOIS_RE})\.?\s+(\d{{4}})(?!\d)")
LIBELLES_DATE = re.compile(r"date (de (la )?facture|d.[ée]mission|de facturation|du ticket|de l.op[ée]ration|"
                           r"de commande|d.achat)|factur[ée]e? le|[ée]mise? le|facture du|ticket du|"
                           r"pay[ée] le|command[ée]e? le|\bdate\b", re.I)


def _date(a: int, m: int, j: int) -> date | None:
    try:
        d = date(a, m, j)
    except ValueError:
        return None
    return d if 2000 <= d.year <= date.today().year + 2 else None


def lire_dates(texte: str) -> list[tuple[int, date]]:
    """Dates trouvées avec leur position : « 15/10/2026 », « 15-10-26 », « 2026-10-15 », « 15 octobre 2026 »,
    « 1er oct. 2026 »."""
    t = sans_accents(texte)
    trouvees = []
    for m in DATE_NUM.finditer(t):
        a = int(m.group(3))
        a += 2000 if a < 100 else 0
        if d := _date(a, int(m.group(2)), int(m.group(1))):
            trouvees.append((m.start(), d))
    for m in DATE_ISO.finditer(t):
        if d := _date(int(m.group(1)), int(m.group(2)), int(m.group(3))):
            trouvees.append((m.start(), d))
    for m in DATE_TEXTE.finditer(t):
        nom = m.group(2)
        mois = MOIS.index(nom) + 1 if nom in MOIS else MOIS_ABREGES[nom]
        if d := _date(int(m.group(3)), mois, int(m.group(1))):
            trouvees.append((m.start(), d))
    return sorted(trouvees)


def lire_date(texte: str) -> date | None:
    d = lire_dates(texte)
    return d[0][1] if d else None


def date_document(texte: str) -> date | None:
    """Date d'émission : celle qui suit un libellé (« date de facture », « émise le »…), sinon la première."""
    t = sans_accents(texte)
    dates = lire_dates(t)
    if not dates:
        return None
    for m in LIBELLES_DATE.finditer(t):
        proches = [d for pos, d in dates if m.end() <= pos <= m.end() + 40]
        if proches:
            return proches[0]
    return dates[0][1]


# --- Marchands et catégories ---------------------------------------------------------------------------------

# (motif, nom affiché, catégorie). Les motifs ambigus exigent la casse (« Free », « Orange ») ou un contexte.
MARCHANDS: list[tuple[str, str, str, int]] = [
    (r"\bEDF\b|[ée]lectricit[ée] de france", "EDF", "énergie", re.I),
    (r"\bengie\b", "Engie", "énergie", re.I),
    (r"totalenergies [ée]lectricit[ée]|total ?energies (gaz|[ée]lectricit[ée])", "TotalEnergies", "énergie", re.I),
    (r"totalenergies|total ?energies|total access|relais total|station total", "TotalEnergies", "carburant", re.I),
    (r"\bekwateur\b|\benercoop\b|\bmint [ée]nergie\b|\bvattenfall\b|\bohm [ée]nergie\b|\bgrdf\b|\benedis\b",
     "Fournisseur d'énergie", "énergie", re.I),
    (r"\bveolia\b|\bsuez\b|\bsaur\b|service des eaux", "Eau", "énergie", re.I),
    (r"\besso\b", "Esso", "carburant", re.I), (r"\bshell\b", "Shell", "carburant", re.I),
    (r"\bstation BP\b|\bBP express\b", "BP", "carburant", re.I), (r"\bavia\b", "Avia", "carburant", re.I),
    (r"\bcarrefour\b", "Carrefour", "courses", re.I), (r"\bleclerc\b", "Leclerc", "courses", re.I),
    (r"\blidl\b", "Lidl", "courses", re.I), (r"\bauchan\b", "Auchan", "courses", re.I),
    (r"\bintermarch[ée]\b", "Intermarché", "courses", re.I), (r"\bsuper ?u\b|\bsyst[eè]me u\b|\bhyper ?u\b",
                                                             "Système U", "courses", re.I),
    (r"\bcasino\b", "Casino", "courses", re.I), (r"\bmonoprix\b", "Monoprix", "courses", re.I),
    (r"\bfranprix\b", "Franprix", "courses", re.I), (r"\baldi\b", "Aldi", "courses", re.I),
    (r"\bnetto\b", "Netto", "courses", re.I), (r"\bgrand frais\b", "Grand Frais", "courses", re.I),
    (r"\bpicard\b", "Picard", "courses", re.I), (r"\bbiocoop\b", "Biocoop", "courses", re.I),
    (r"\bOrange\b|\bORANGE\b|\b[Ss]osh\b", "Orange", "télécom", 0), (r"\bSFR\b|\bred by sfr\b", "SFR", "télécom", 0),
    (r"\bFree\b|\b[Ff]reebox\b|\b[Ff]ree [Mm]obile\b|\bFREE\b", "Free", "télécom", 0),
    (r"\bbouygues\b|\bb&you\b|\bbbox\b", "Bouygues Telecom", "télécom", re.I),
    (r"\bnetflix\b", "Netflix", "abonnements", re.I), (r"\bspotify\b", "Spotify", "abonnements", re.I),
    (r"\bdeezer\b", "Deezer", "abonnements", re.I), (r"\bdisney ?\+|\bdisney plus\b", "Disney+", "abonnements", re.I),
    (r"\bcanal ?\+", "Canal+", "abonnements", re.I), (r"amazon prime|prime video", "Amazon Prime", "abonnements", re.I),
    (r"youtube premium", "YouTube Premium", "abonnements", re.I), (r"\bicloud\+?|apple music|apple tv|apple one",
                                                                    "Apple", "abonnements", re.I),
    (r"\bapple\b(?! ?pay)", "Apple", "abonnements", re.I), (r"google one|google play", "Google", "abonnements", re.I),
    (r"microsoft 365|office 365", "Microsoft", "abonnements", re.I), (r"\badobe\b", "Adobe", "abonnements", re.I),
    (r"\bsncf\b|\bouigo\b|\btgv inoui\b", "SNCF", "transport", re.I), (r"\bTER\b", "SNCF", "transport", 0),
    (r"\buber eats\b", "Uber Eats", "restaurants", re.I), (r"\buber\b", "Uber", "transport", re.I),
    (r"\bbolt\b", "Bolt", "transport", re.I), (r"\bblablacar\b", "BlaBlaCar", "transport", re.I),
    (r"\bratp\b", "RATP", "transport", re.I), (r"air france", "Air France", "transport", re.I),
    (r"\beasyjet\b", "easyJet", "transport", re.I), (r"\bryanair\b", "Ryanair", "transport", re.I),
    (r"vinci autoroutes|\baprr\b|\bsanef\b|\bpéage\b|\bpeage\b", "Autoroute", "transport", re.I),
    (r"\bindigo\b|\bparking\b", "Parking", "transport", re.I),
    (r"\bpharmacie\b", "Pharmacie", "santé", re.I), (r"\bmutuelle\b|\bmgen\b|harmonie mutuelle", "Mutuelle",
                                                       "santé", re.I),
    (r"\bdoctolib\b|\bdocteur\b|\bm[ée]decin\b|\bdentiste\b|\bkin[ée]\b|\bopticien\b|"
     r"\blaboratoire\b|\bameli\b|\bcpam\b", "Santé", "santé", re.I),
    (r"\bmaif\b", "MAIF", "assurances", re.I), (r"\bmacif\b", "MACIF", "assurances", re.I),
    (r"\bmaaf\b", "MAAF", "assurances", re.I), (r"\baxa\b", "AXA", "assurances", re.I),
    (r"\ballianz\b", "Allianz", "assurances", re.I), (r"\bgroupama\b", "Groupama", "assurances", re.I),
    (r"\bgmf\b", "GMF", "assurances", re.I), (r"\bmatmut\b", "Matmut", "assurances", re.I),
    (r"\bfoncia\b|\bnexity\b|\bsyndic\b|\bloyer\b|quittance de loyer", "Logement", "logement", re.I),
    (r"\bamazon\b", "Amazon", "achats", re.I), (r"\bcdiscount\b", "Cdiscount", "achats", re.I),
    (r"\bfnac\b", "Fnac", "achats", re.I), (r"\bdarty\b", "Darty", "achats", re.I),
    (r"\bboulanger\b", "Boulanger", "achats", re.I), (r"leroy merlin", "Leroy Merlin", "achats", re.I),
    (r"\bcastorama\b", "Castorama", "achats", re.I), (r"\bikea\b", "Ikea", "achats", re.I),
    (r"\bdecathlon\b", "Decathlon", "achats", re.I),
    (r"mcdonald|burger king|\bkfc\b|\bdeliveroo\b|\brestaurant\b|\bbrasserie\b", "Restaurant", "restaurants", re.I),
    (r"\bdgfip\b|impots\.gouv|imp[ôo]ts\.gouv|tr[ée]sor public|finances publiques", "Impôts", "impôts", re.I),
]
_MARCHANDS = [(re.compile(m, f), nom, cat) for m, nom, cat, f in MARCHANDS]

# La catégorie passe avant le marchand quand le contenu est sans ambiguïté.
CATEGORIES_MOTS = [
    ("carburant", re.compile(r"gazole|gasoil|sans plomb|\bsp ?9[58]\b|\be10\b|\be85\b|\bcarburant|\bdiesel\b|"
                             r"station[- ]service|\bessence\b|\bgpl\b", re.I)),
    ("logement", re.compile(r"assurance habitation|multirisque habitation|\bloyer\b|charges de copropri", re.I)),
    ("impôts", re.compile(r"avis d.imp[ôo]t|taxe fonci[èe]re|taxe d.habitation|imp[ôo]t sur le revenu", re.I)),
    ("énergie", re.compile(r"\b(kwh|consommation d.[ée]lectricit[ée]|abonnement [ée]lectricit[ée]|gaz naturel)\b",
                           re.I)),
]
CATEGORIES = ["énergie", "carburant", "courses", "télécom", "abonnements", "transport", "santé", "logement",
              "assurances", "achats", "restaurants", "impôts", "autres"]
SYNONYMES_CATEGORIES = {
    "essence": "carburant", "gasoil": "carburant", "gazole": "carburant", "plein": "carburant",
    "station": "carburant", "electricite": "énergie", "gaz": "énergie", "energie": "énergie", "eau": "énergie",
    "telephone": "télécom", "internet": "télécom", "mobile": "télécom", "box": "télécom", "telecom": "télécom",
    "forfait": "télécom", "nourriture": "courses", "supermarche": "courses", "alimentation": "courses",
    "course": "courses", "train": "transport", "taxi": "transport", "avion": "transport", "peage": "transport",
    "voyage": "transport", "medecin": "santé", "pharmacie": "santé", "sante": "santé", "mutuelle": "santé",
    "loyer": "logement", "maison": "logement", "abonnement": "abonnements", "streaming": "abonnements",
    "assurance": "assurances", "restaurant": "restaurants", "resto": "restaurants", "impot": "impôts",
    "taxe": "impôts", "achat": "achats", "shopping": "achats",
}


def trouver_marchand(*textes: str) -> tuple[str, str] | None:
    """(nom, catégorie) du marchand : le premier reconnu dans les textes donnés (expéditeur, nom de fichier, puis
    contenu) ; dans un même texte, celui qui apparaît le plus tôt (l'en-tête d'un ticket porte l'enseigne)."""
    for texte in textes:
        if trouve := premier_marchand(str(texte or "")):
            return trouve[1], trouve[2]
    return None


def premier_marchand(t: str) -> tuple[int, str, str] | None:
    """(position, nom, catégorie) du marchand cité le plus tôt dans `t`."""
    meilleur = None
    for motif, nom, cat in _MARCHANDS:
        m = motif.search(t)
        if m and (meilleur is None or m.start() < meilleur[0]):
            meilleur = (m.start(), nom, cat)
    return meilleur


def categorie_depense(texte: str, marchand: tuple[str, str] | None = None) -> str:
    for cat, motif in CATEGORIES_MOTS:
        if motif.search(str(texte or "")):
            if cat == "énergie" and marchand and marchand[1] == "carburant":
                continue
            return cat
    return marchand[1] if marchand else "autres"


def normaliser_categorie(texte: str) -> str:
    """« essence » → carburant ; « électricité » → énergie ; « » → « »."""
    t = sans_accents(texte).strip(" .s") if texte else ""
    if not t:
        return ""
    for c in CATEGORIES:
        if sans_accents(c).rstrip("s") == t.rstrip("s"):
            return c
    for mot, c in SYNONYMES_CATEGORIES.items():
        if mot in t:
            return c
    raise ErreurOutil(f"Catégorie inconnue : « {texte} ». Catégories : {', '.join(CATEGORIES)}.")


# --- Justificatifs -------------------------------------------------------------------------------------------

JUSTIFICATIF = re.compile(r"\bfacture\b|\bticket\b|\bre[çc]u\b|\breceipt\b|\binvoice\b|note de frais|"
                          r"confirmation de (commande|paiement)|votre (commande|paiement)|avis d.[ée]ch[ée]ance|"
                          r"[ée]ch[ée]ancier|pr[ée]l[èe]vement|net [àa] payer|montant [àa] payer|total ttc|"
                          r"carte bancaire|\bcb\b|paiement accept[ée]|quittance", re.I)
PAS_UNE_DEPENSE = re.compile(r"\bdevis\b|proposition commerciale|relev[ée] de compte|relev[ée] bancaire|"
                             r"bulletin de (paie|salaire)|fiche de paie|avoir n|\bremboursement\b", re.I)
REQUETE_JUSTIFICATIFS = ('"facture"* OR "ticket"* OR "recu" OR "receipt"* OR "invoice"* OR "total"* OR '
                         '"payer"* OR "paiement"* OR "commande"* OR "prelevement"* OR "quittance"*')
GENRES_DEPENSES = ["pdf", "document", "mail", "image", "capture"]


def lire_justificatif(doc: dict, aujourdhui: date | None = None) -> dict | None:
    """Une dépense {date, montant, marchand, categorie, source} tirée d'une entrée de l'index, ou None."""
    texte, entete = str(doc.get("texte") or ""), str(doc.get("entete") or "")
    tout = f"{entete}\n{texte}"
    if not JUSTIFICATIF.search(tout) or PAS_UNE_DEPENSE.search(entete + "\n" + texte[:1500]):
        return None
    montant = montant_total(texte) or montant_total(entete)
    if not montant or montant <= 0 or montant > 50_000:
        return None
    jour = date_document(texte)
    ts = doc.get("mtime") or 0
    if doc.get("genre") == "mail" or jour is None or (aujourdhui and jour > aujourdhui + timedelta(days=1)):
        jour = date.fromtimestamp(ts) if ts else jour  # un mail : sa date de réception
    if jour is None:
        return None
    chemin = str(doc.get("chemin") or "")
    nom_fichier = "" if "://" in chemin else Path(chemin).stem.replace("_", " ")
    marchand = trouver_marchand(entete if doc.get("genre") == "mail" else "", nom_fichier, texte[:800], texte)
    return {"date": jour, "montant": montant, "marchand": marchand[0] if marchand else (nom_fichier or "?")[:40],
            "categorie": categorie_depense(texte, marchand), "source": chemin, "genre": doc.get("genre")}


def dedoublonner(depenses: list[dict]) -> list[dict]:
    """Même montant, même marchand, à 3 jours près (la facture PDF et le mail qui l'annonce) : une seule ligne,
    le document plutôt que le mail."""
    gardees: list[dict] = []
    for d in sorted(depenses, key=lambda d: d.get("genre") == "mail"):
        if any(abs(d["montant"] - g["montant"]) < 0.005 and d["marchand"] == g["marchand"]
               and abs((d["date"] - g["date"]).days) <= 3 for g in gardees):
            continue
        gardees.append(d)
    return sorted(gardees, key=lambda d: d["date"])


# --- Périodes ------------------------------------------------------------------------------------------------

def _mois(a: int, m: int) -> tuple[date, date]:
    debut = date(a, m, 1)
    fin = date(a + (m == 12), m % 12 + 1, 1)
    return debut, fin


def bornes_periode(periode: str = "ce mois", aujourdhui: date | None = None) -> tuple[date, date, str]:
    """(début inclus, fin exclue, libellé) : « ce mois », « le mois dernier », « octobre », « octobre 2026 »,
    « 2026-10 », « cette année », « l'année dernière », « 2025 », « cette semaine », « 3 derniers mois »,
    « 30 jours », « aujourd'hui », « hier »."""
    j = aujourdhui or date.today()
    t = re.sub(r"\s+", " ", sans_accents(periode).strip(" .?!")).removeprefix("le ").removeprefix("du ")
    t = re.sub(r"^(depuis |sur |pour |de |en )", "", t)
    demain = j + timedelta(days=1)
    if t in ("", "ce mois", "ce mois-ci", "ce mois ci", "mois en cours", "le mois en cours", "mois"):
        d, f = _mois(j.year, j.month)
        return d, f, f"{MOIS_AFFICHES[j.month - 1]} {j.year}"
    if re.fullmatch(r"(le )?mois (dernier|precedent|passe)", t):
        a, m = (j.year - 1, 12) if j.month == 1 else (j.year, j.month - 1)
        d, f = _mois(a, m)
        return d, f, f"{MOIS_AFFICHES[m - 1]} {a}"
    if t in ("cette annee", "annee en cours", "l'annee en cours", "cette annee-ci", "annee"):
        return date(j.year, 1, 1), date(j.year + 1, 1, 1), str(j.year)
    if re.fullmatch(r"(l')?(annee|an) (derniere|dernier|passee|precedente)", t):
        return date(j.year - 1, 1, 1), date(j.year, 1, 1), str(j.year - 1)
    if m := re.fullmatch(r"(\d{4})", t):
        a = int(m.group(1))
        return date(a, 1, 1), date(a + 1, 1, 1), str(a)
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", t):
        a, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            d, f = _mois(a, mo)
            return d, f, f"{MOIS_AFFICHES[mo - 1]} {a}"
    if m := re.fullmatch(rf"(?:mois d')?({'|'.join(MOIS)})(?: (\d{{4}}))?", t):
        mo = MOIS.index(m.group(1)) + 1
        a = int(m.group(2)) if m.group(2) else (j.year if mo <= j.month else j.year - 1)
        d, f = _mois(a, mo)
        return d, f, f"{MOIS_AFFICHES[mo - 1]} {a}"
    if t in ("cette semaine", "semaine"):
        d = j - timedelta(days=j.weekday())
        return d, demain, f"semaine du {d:%d/%m}"
    if t in ("semaine derniere", "la semaine derniere"):
        d = j - timedelta(days=j.weekday() + 7)
        return d, d + timedelta(days=7), f"semaine du {d:%d/%m}"
    if t in ("aujourd'hui", "aujourdhui"):
        return j, demain, "aujourd'hui"
    if t == "hier":
        return j - timedelta(days=1), j, "hier"
    if m := re.fullmatch(r"(?:les? )?(\d+) (?:derniers? |dernieres? )?(jours?|semaines?|mois|ans?|annees?)"
                         r"(?: derniers?| dernieres?)?", t):
        n, u = int(m.group(1)), m.group(2)
        jours = n * (1 if u.startswith("jour") else 7 if u.startswith("semaine") else 30 if u == "mois" else 365)
        d = j - timedelta(days=jours)
        return d, demain, f"{n} derniers {u}"
    raise ErreurOutil(f"Période non comprise : « {periode} ». Exemples : ce mois, le mois dernier, octobre, "
                      "octobre 2026, cette année, 2025, 3 derniers mois.")


def collecter_depenses(index, debut: date, fin: date, categorie: str = "") -> list[dict]:
    """Dépenses justifiées par les documents indexés, dans [début, fin[ (et d'une catégorie si donnée)."""
    import time as _time
    apres = _time.mktime((debut - timedelta(days=1)).timetuple())  # un justificatif est enregistré après sa date
    docs = index.documents(REQUETE_JUSTIFICATIFS, genres=GENRES_DEPENSES, apres=apres, limite=600)
    depenses = []
    for doc in docs:
        d = lire_justificatif(doc, fin)
        if d and debut <= d["date"] < fin and (not categorie or d["categorie"] == categorie):
            depenses.append(d)
    return dedoublonner(depenses)


def resume_depenses(depenses: list[dict], libelle: str, categorie: str = "", lignes_max: int = 15) -> str:
    quoi = f"en {categorie} " if categorie else ""
    if not depenses:
        return (f"Aucune dépense {quoi}trouvée pour {libelle} dans les factures, tickets et mails indexés. "
                "(Seuls les achats dont un justificatif est sur le Mac ou dans Mail sont comptés.)")
    total = sum(d["montant"] for d in depenses)
    lignes = [f"Dépenses {quoi}— {libelle} : {euros(total)} sur {len(depenses)} justificatif(s)."]
    if not categorie:
        par_cat: dict[str, list[float]] = {}
        for d in depenses:
            par_cat.setdefault(d["categorie"], []).append(d["montant"])
        lignes.append("Par catégorie :")
        lignes += [f"- {c} : {euros(sum(v))} ({len(v)})" for c, v in
                   sorted(par_cat.items(), key=lambda x: -sum(x[1]))]
    lignes.append("Détail" + (" (les plus gros)" if len(depenses) > lignes_max else "") + " :")
    for d in sorted(depenses, key=lambda d: -d["montant"])[:lignes_max]:
        lignes.append(f"- {d['date']:%d/%m/%Y} {d['marchand']} — {euros(d['montant'])} [{d['categorie']}] — "
                      f"{d['source']}")
    lignes.append("(D'après les justificatifs indexés : un paiement sans facture ni ticket n'apparaît pas.)")
    return "\n".join(lignes)


MOTS_DEPENSES = ["depense", "depenses", "j'ai depense", "combien j'ai paye", "mes factures", "mes tickets",
                 "budget", "combien en essence", "combien d'essence", "en carburant", "mes achats",
                 "releve de depenses"]


@outil("releve_depenses", "Relevé des dépenses d'après les factures, tickets et mails de paiement indexés : "
       "total, total par catégorie (énergie, carburant, courses, télécom, abonnements, transport, santé, logement, "
       "assurances, achats, restaurants, impôts) et principales lignes avec leur fichier. Ex. « combien j'ai "
       "dépensé en essence ce mois-ci » → periode « ce mois », categorie « carburant ».", "recherche",
       {"periode": ("string", "ce mois (défaut), le mois dernier, octobre, octobre 2026, cette année, 3 derniers mois"),
        "categorie": ("string", "catégorie précise, facultatif (ex. carburant, courses, énergie)")}, requis=[],
       mac_seulement=False, mots_cles=MOTS_DEPENSES, delai_max=120)
def releve_depenses(ctx, periode="ce mois", categorie=""):
    index = ctx.service("index")
    if index is None:
        raise ErreurOutil("Recherche indisponible : l'index des documents n'est pas chargé.")
    debut, fin, libelle = bornes_periode(periode)
    cat = normaliser_categorie(categorie)
    depenses = collecter_depenses(index, debut, fin, cat)
    return Resultat(True, resume_depenses(depenses, libelle, cat),
                    {"total": round(sum(d["montant"] for d in depenses), 2), "nombre": len(depenses),
                     "periode": [debut.isoformat(), fin.isoformat()]})


@outil("exporter_depenses", "Crée sur le Bureau un tableau Excel des dépenses d'une période (date, marchand, "
       "catégorie, montant, fichier source) avec le total.", "recherche",
       {"periode": ("string", "ce mois (défaut), le mois dernier, octobre 2026, cette année…"),
        "categorie": ("string", "catégorie précise, facultatif")}, requis=[], risque=Risque.CREATION,
       mac_seulement=False, annonce=lambda a: f"Créer sur le Bureau le tableau des dépenses ({a.get('periode') or 'ce mois'})",
       mots_cles=["exporte mes depenses", "tableau des depenses", "depenses dans excel", "depenses en excel"])
def exporter_depenses(ctx, periode="ce mois", categorie=""):
    from .documents import creer_tableur
    index = ctx.service("index")
    if index is None:
        raise ErreurOutil("Recherche indisponible : l'index des documents n'est pas chargé.")
    debut, fin, libelle = bornes_periode(periode)
    cat = normaliser_categorie(categorie)
    depenses = collecter_depenses(index, debut, fin, cat)
    if not depenses:
        return Resultat(True, resume_depenses(depenses, libelle, cat))
    lignes = [[f"{d['date']:%d/%m/%Y}", d["marchand"], d["categorie"], d["montant"], d["source"]] for d in depenses]
    nom = "~/Desktop/" + re.sub(r"[/:\\]", "-", f"Dépenses {libelle}{' ' + cat if cat else ''}") + ".xlsx"
    r = creer_tableur(ctx, nom, ["Date", "Marchand", "Catégorie", "Montant (€)", "Source"], lignes, total=True)
    total = sum(d["montant"] for d in depenses)
    return Resultat(r.ok, f"{r.texte}. Total : {euros(total)} ({len(depenses)} lignes).", r.donnees)


# --- Classement des papiers (voir macai.classement) ---------------------------------------------------------

@outil("classer_document", "Classe un document administratif (facture, relevé bancaire, impôts, assurance, santé, "
       "contrat, fiche de paie, billet, garantie) : le renomme « AAAA-MM Émetteur type montant » et le range dans "
       "Documents/Administratif/<Type>/<Année>. N'écrase jamais ; annulable.", "fichiers",
       {"chemin": ("string", "fichier à classer (PDF, image, Word)")}, risque=Risque.MODIFICATION,
       mac_seulement=False, annonce=lambda a: f"Classer {Path(str(a.get('chemin', ''))).name} dans "
                                              "Documents/Administratif",
       mots_cles=["classe ce document", "classe cette facture", "classer le document", "range cette facture",
                  "classe le pdf", "administratif"], delai_max=240)
def classer_document(ctx, chemin):
    from .. import classement
    from .fichiers import resoudre
    p = resoudre(chemin, ecriture=True, doit_exister=True)
    if p.is_dir():
        raise ErreurOutil(f"{p} est un dossier : donne un fichier (ou utilise classer_telechargements).")
    proposition = classement.proposer_classement(p)
    if proposition is None:
        raise ErreurOutil(f"Je ne reconnais pas le type de {p.name} (ni facture, ni relevé, ni impôts…). "
                          "Dis-moi où le ranger et j'utiliserai deplacer.")
    texte = classement.classer(ctx, p, proposition)
    if proposition["confiance"] < classement.SEUIL:
        texte += f" (type deviné avec une confiance moyenne : {proposition['type']} ; « annuler » si c'est faux)"
    return Resultat(True, texte, {"fichier": proposition.get("arrivee"), "type": proposition["type"]})


@outil("classer_telechargements", "Classe d'un coup les documents administratifs du dossier Téléchargements "
       "(factures, relevés, impôts, assurance, santé, contrats, fiches de paie, billets, garanties) dans "
       "Documents/Administratif. Seuls les documents reconnus avec certitude bougent ; les autres sont listés.",
       "fichiers", {"dossier": ("string", "dossier à examiner (~/Downloads par défaut)")}, requis=[],
       risque=Risque.MODIFICATION, mac_seulement=False,
       annonce=lambda a: f"Classer les documents administratifs de {a.get('dossier') or '~/Downloads'}",
       mots_cles=["classe mes telechargements", "classer mes telechargements", "range mes factures",
                  "classe mes papiers", "classe mes documents", "papiers administratifs"], delai_max=300)
def classer_telechargements(ctx, dossier="~/Downloads"):
    from .. import classement
    from .fichiers import resoudre
    d = resoudre(dossier or "~/Downloads", ecriture=True, doit_exister=True)
    if not d.is_dir():
        raise ErreurOutil(f"{d} n'est pas un dossier.")
    bilan = classement.classer_dossier(ctx, d)
    return Resultat(True, classement.resume_bilan(bilan, d),
                    {"classes": len(bilan["classes"]), "incertains": len(bilan["incertains"])})
