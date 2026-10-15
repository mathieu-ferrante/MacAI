"""Compétences apprises : recettes rejouables (suite d'appels d'outils paramétrés), en JSON lisible.

Exemple : « Exporter la facture » = rechercher_fichiers({requete}) → lire_document({etape1.premier})
→ creer_tableur(...). Rejouée sans réfléchir : rapide, fiable, et chaque étape garde les confirmations.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..outils.base import Outil, Registre, Resultat, Risque

MARQUEUR = re.compile(r"\{([a-zA-Z_][\w]*)(?:\.([\w]+))?\}")
MOTS_VIDES = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "a", "au", "en", "mon", "ma", "mes",
              "pour", "dans", "sur", "avec", "moi", "fais", "fait", "peux", "tu", "je", "me", "m"}


@dataclass
class Competence:
    nom: str
    description: str
    etapes: list[dict]
    parametres: dict[str, str] = field(default_factory=dict)
    declencheurs: list[str] = field(default_factory=list)
    cree_le: float = field(default_factory=time.time)
    utilisations: int = 0

    @property
    def nom_outil(self) -> str:
        return f"competence_{self.nom}"[:64]


def nom_valide(nom: str) -> str:
    n = unicodedata.normalize("NFD", nom.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", n).strip("_")[:40] or "competence"


def substituer(valeur, params: dict, resultats: list[Resultat]):
    """Remplace {param}, {etapeN} (texte du résultat) et {etapeN.cle} (donnée du résultat)."""
    if isinstance(valeur, dict):
        return {k: substituer(v, params, resultats) for k, v in valeur.items()}
    if isinstance(valeur, list):
        return [substituer(v, params, resultats) for v in valeur]
    if not isinstance(valeur, str):
        return valeur

    def resoudre(nom, cle):
        if m := re.fullmatch(r"etape(\d+)", nom):
            i = int(m.group(1)) - 1
            if not 0 <= i < len(resultats):
                raise KeyError(f"{{{nom}}} : étape inexistante")
            r = resultats[i]
            if cle is None:
                return r.texte
            d = r.donnees if isinstance(r.donnees, dict) else {}
            if cle == "premier":  # premier élément d'une liste de résultats (ex. fichier trouvé)
                liste = next((v for v in d.values() if isinstance(v, list) and v), None)
                if liste is None:
                    raise KeyError(f"{{{nom}.premier}} : aucun résultat à l'étape {i + 1}")
                return liste[0]
            if cle not in d:
                raise KeyError(f"{{{nom}.{cle}}} : donnée absente")
            return d[cle]
        if nom not in params:
            raise KeyError(f"paramètre {{{nom}}} non fourni")
        return params[nom]

    entier = MARQUEUR.fullmatch(valeur)
    if entier:  # valeur = un seul marqueur : on garde le type (liste, nombre…)
        return resoudre(entier.group(1), entier.group(2))
    return MARQUEUR.sub(lambda m: str(resoudre(m.group(1), m.group(2))), valeur)


class Bibliotheque:
    def __init__(self, dossier: Path, registre: Registre):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.registre = registre
        self.competences: dict[str, Competence] = {}
        for f in sorted(self.dossier.glob("*.json")):
            try:
                c = Competence(**json.loads(f.read_text(encoding="utf-8")))
                self._inscrire(c)
            except (ValueError, TypeError) as e:
                print(f"Compétence illisible {f.name} : {e}")

    # --- Gestion ---------------------------------------------------------------------

    def valider(self, c: Competence) -> list[str]:
        erreurs = []
        if not c.etapes:
            erreurs.append("aucune étape")
        for i, e in enumerate(c.etapes, 1):
            o = e.get("outil", "")
            if o.startswith("competence_"):
                erreurs.append(f"étape {i} : une compétence ne peut pas en appeler une autre")
            elif self.registre.get(o) is None:
                erreurs.append(f"étape {i} : outil inconnu « {o} »")
            for m in MARQUEUR.finditer(json.dumps(e.get("arguments", {}), ensure_ascii=False)):
                nom = m.group(1)
                if (n := re.fullmatch(r"etape(\d+)", nom)) and not 1 <= int(n.group(1)) < i:
                    erreurs.append(f"étape {i} : {{{nom}}} doit désigner une étape précédente")
                elif not nom.startswith("etape") and nom not in c.parametres:
                    erreurs.append(f"étape {i} : paramètre {{{nom}}} non déclaré")
        return erreurs

    def ajouter(self, c: Competence) -> Competence:
        c.nom = nom_valide(c.nom)
        erreurs = self.valider(c)
        if erreurs:
            raise ValueError("Compétence invalide : " + " ; ".join(erreurs))
        self._sauver(c)
        self._inscrire(c)
        return c

    def supprimer(self, nom: str) -> bool:
        c = self.competences.pop(nom_valide(nom), None)
        if c is None:
            return False
        (self.dossier / f"{c.nom}.json").unlink(missing_ok=True)
        self.registre.retirer(c.nom_outil)
        return True

    def _sauver(self, c: Competence) -> None:
        (self.dossier / f"{c.nom}.json").write_text(json.dumps(asdict(c), ensure_ascii=False, indent=2), encoding="utf-8")

    def _inscrire(self, c: Competence) -> None:
        self.competences[c.nom] = c
        mots = {m for d in c.declencheurs + [c.nom.replace("_", " ")] for m in re.findall(r"\w{4,}", d.lower())
                if m not in MOTS_VIDES}

        def jouer(ctx, **valeurs):
            return self.executer(ctx, c, valeurs)

        self.registre.ajouter(Outil(
            nom=c.nom_outil, description=f"Compétence apprise : {c.description}", fonction=jouer,
            groupe="competences", parametres={k: {"type": "string", "description": v} for k, v in c.parametres.items()},
            requis=list(c.parametres), risque=lambda valeurs: self.risque(c, valeurs), mac_seulement=False,
            mots_cles=sorted(mots)[:12]))

    def risque(self, c: Competence, valeurs: dict) -> Risque:
        """Le plus haut risque de ses étapes : rejouer une recette qui clique, tape ou envoie demande les mêmes
        confirmations que ces outils pris un par un. Étape inconnue ou risque incalculable : SENSIBLE."""
        pire = Risque.LECTURE
        for etape in c.etapes:
            o = self.registre.get(etape.get("outil", ""))
            if o is None:
                return Risque.SENSIBLE
            if o.toujours_confirmer:
                return Risque.SENSIBLE
            try:
                args = substituer(etape.get("arguments", {}), valeurs or {}, [])
            except KeyError:  # dépend du résultat d'une étape précédente : arguments bruts
                args = etape.get("arguments", {})
            try:
                pire = max(pire, Risque(o.risque_pour(args)))
            except Exception:  # noqa: BLE001 - fonction de risque déroutée par un marqueur : prudence
                return Risque.SENSIBLE
        return pire

    # --- Exécution -------------------------------------------------------------------

    def executer(self, ctx, c: Competence, valeurs: dict) -> Resultat:
        orch = ctx.service("orchestrateur")
        executer_outil = orch.executer_outil if orch else (lambda n, a: ctx.registre.get(n).executer(ctx, a))
        resultats: list[Resultat] = []
        for i, etape in enumerate(c.etapes, 1):
            ctx.verifier_arret()
            try:
                args = substituer(etape.get("arguments", {}), valeurs, resultats)
            except KeyError as e:
                return Resultat.echec(f"Compétence « {c.nom} », étape {i} : {e.args[0]}")
            r = executer_outil(etape["outil"], args)
            resultats.append(r)
            if not r.ok:
                return Resultat.echec(f"Compétence « {c.nom} » arrêtée à l'étape {i} ({etape['outil']}) : {r.texte}")
        c.utilisations += 1
        self._sauver(c)
        return Resultat(True, f"Compétence « {c.nom} » terminée ({len(c.etapes)} étapes).\n{resultats[-1].texte}",
                        resultats[-1].donnees)


GENERALISER = """Transforme cette tâche réussie en COMPÉTENCE réutilisable. Réponds UNIQUEMENT en JSON :
{{"nom": "nom_court_snake_case", "description": "ce que fait la compétence, en une phrase",
  "declencheurs": ["3 façons dont l'utilisateur pourrait la demander"],
  "parametres": {{"nom_param": "description"}},
  "etapes": [{{"outil": "nom_outil", "arguments": {{...}}}}]}}

Règles :
- Remplace dans les arguments les valeurs propres à cette fois-ci (noms, dates, textes) par {{nom_param}}.
- Pour réutiliser le résultat d'une étape précédente : {{etapeN}} (texte) ou {{etapeN.cle}} (donnée ; clés
  disponibles indiquées ci-dessous), {{etapeN.premier}} = premier élément trouvé.
- Garde les mêmes outils, dans le même ordre ; enlève les étapes inutiles ou ratées.

{source}"""


def generer(ctx, demande: str, actions: list[dict] | None, description: str = "") -> Competence:
    """Demande au modèle de généraliser une trace (ou une description libre) en compétence."""
    if actions:
        lignes = [f"Demande d'origine : {demande}", "Actions réussies :"]
        for i, a in enumerate(actions, 1):
            cles = f"  (données : {', '.join(a.get('cles', []))})" if a.get("cles") else ""
            lignes.append(f"{i}. {a['outil']}({json.dumps(a['arguments'], ensure_ascii=False)}){cles}")
        source = "\n".join(lignes)
    else:
        outils = "\n".join(f"- {o.nom} : {o.description[:90]}" for o in ctx.registre.disponibles()
                           if not o.nom.startswith("competence_"))
        source = f"Description voulue par l'utilisateur : {description or demande}\nOutils disponibles :\n{outils}"
    rep = ctx.ollama.discuter(ctx.config.modeles["agent"], [{"role": "user", "content": GENERALISER.format(source=source)}],
                              options={"temperature": 0})
    m = re.search(r"\{.*\}", rep.texte, re.S)
    if not m:
        raise ValueError("le modèle n'a pas produit de JSON")
    d = json.loads(m.group(0))
    return Competence(nom=d.get("nom", "competence"), description=d.get("description", demande),
                      etapes=d.get("etapes", []), parametres=d.get("parametres", {}) or {},
                      declencheurs=d.get("declencheurs", []) or [])
