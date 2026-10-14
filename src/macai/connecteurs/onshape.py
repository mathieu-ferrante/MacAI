"""Connecteur Onshape (API REST officielle) : documents et pièces simples.

Authentification par clés d'API (Trousseau, `macai secret onshape`). Les pièces sont créées par une
esquisse sur le plan de dessus puis une extrusion : exactement ce que ferait l'utilisateur, mais en
quelques secondes et sans dépendre de l'affichage 3D.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request

from .. import secrets
from ..outils.base import ErreurOutil

BASE = "https://cad.onshape.com"
PLAN_DESSUS = "JDC"   # identifiant déterministe du plan « Top » dans tout Part Studio

UNITES = {"mm": 0.001, "cm": 0.01, "dm": 0.1, "m": 1.0, "metre": 1.0, "metres": 1.0, "mètre": 1.0,
          "mètres": 1.0, "in": 0.0254, "pouce": 0.0254, "pouces": 0.0254}


def en_metres(valeur) -> float:
    """« 1 m », « 250mm », « 2,5 cm », 40 (mm par défaut) → mètres."""
    if isinstance(valeur, (int, float)):
        return float(valeur) * 0.001
    m = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*([a-zA-Zèé]*)\s*", str(valeur))
    if not m:
        raise ErreurOutil(f"Dimension non comprise : « {valeur} » (ex. « 1 m », « 250 mm »).")
    nombre = float(m.group(1).replace(",", "."))
    unite = (m.group(2) or "mm").lower()
    if unite not in UNITES:
        raise ErreurOutil(f"Unité inconnue : {unite}")
    v = nombre * UNITES[unite]
    if not 1e-5 <= v <= 100:
        raise ErreurOutil(f"Dimension hors limites : {valeur}")
    return v


class Onshape:
    def __init__(self, cles: tuple[str, str] | None = None):
        cles = cles or secrets.lire("onshape")
        if not cles:
            raise ErreurOutil("Onshape n'est pas connecté. Dans le Terminal : `macai secret onshape` "
                              "(clés à créer sur https://dev-portal.onshape.com/keys).")
        self._auth = "Basic " + base64.b64encode(f"{cles[0]}:{cles[1]}".encode()).decode()

    def requete(self, methode: str, chemin: str, corps: dict | None = None) -> dict:
        req = urllib.request.Request(BASE + chemin, method=methode,
                                     data=json.dumps(corps).encode() if corps is not None else None,
                                     headers={"Authorization": self._auth, "Content-Type": "application/json",
                                              "Accept": "application/json;charset=UTF-8; qs=0.09"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                texte = r.read().decode()
                return json.loads(texte) if texte else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (401, 403):
                raise ErreurOutil("Onshape refuse les clés (expirées ou droits insuffisants) : relance "
                                  "`macai secret onshape`.") from e
            raise ErreurOutil(f"Onshape {e.code} : {detail}") from e
        except urllib.error.URLError as e:
            raise ErreurOutil(f"Onshape injoignable : {e.reason}") from e

    # --- Documents -------------------------------------------------------------------

    def creer_document(self, nom: str) -> tuple[str, str, str]:
        d = self.requete("POST", "/api/v6/documents", {"name": nom, "isPublic": False})
        did, wid = d["id"], d["defaultWorkspace"]["id"]
        elements = self.requete("GET", f"/api/v6/documents/d/{did}/w/{wid}/elements?elementType=PARTSTUDIO")
        if not elements:
            raise ErreurOutil("Le document créé n'a pas de Part Studio.")
        return did, wid, elements[0]["id"]

    def chercher_documents(self, requete: str, nombre: int = 10) -> list[dict]:
        from urllib.parse import quote
        r = self.requete("GET", f"/api/v6/documents?q={quote(requete)}&limit={nombre}&sortColumn=modifiedAt&sortOrder=desc")
        return r.get("items", [])

    @staticmethod
    def url(did: str, wid: str, eid: str) -> str:
        return f"{BASE}/documents/{did}/w/{wid}/e/{eid}"

    # --- Fonctions (features) ----------------------------------------------------------

    def ajouter_fonction(self, did: str, wid: str, eid: str, fonction: dict) -> str:
        r = self.requete("POST", f"/api/v6/partstudios/d/{did}/w/{wid}/e/{eid}/features", {"feature": fonction})
        etat = (r.get("featureState") or {}).get("featureStatus", "OK")
        if etat not in ("OK", "INFO"):
            raise ErreurOutil(f"Onshape a refusé la fonction « {fonction.get('name')} » (état {etat}).")
        return r["feature"]["featureId"]

    def piece(self, did: str, wid: str, eid: str, forme: str, largeur: float, profondeur: float,
              hauteur: float, nom: str) -> None:
        """Esquisse centrée sur le plan de dessus + extrusion de `hauteur` (mètres)."""
        esquisse = esquisse_rectangle(largeur, profondeur, nom) if forme != "cylindre" \
            else esquisse_cercle(largeur / 2, nom)
        fid = self.ajouter_fonction(did, wid, eid, esquisse)
        self.ajouter_fonction(did, wid, eid, extrusion(fid, hauteur, nom))


def _ligne(ident: str, x: float, y: float, dx: float, dy: float, longueur: float) -> dict:
    return {"btType": "BTMSketchCurveSegment-155", "entityId": ident, "startPointId": f"{ident}.start",
            "endPointId": f"{ident}.end", "startParam": 0.0, "endParam": longueur,
            "geometry": {"btType": "BTCurveGeometryLine-117", "pntX": x, "pntY": y, "dirX": dx, "dirY": dy}}


def _plan() -> list[dict]:
    return [{"btType": "BTMParameterQueryList-148", "parameterId": "sketchPlane",
             "queries": [{"btType": "BTMIndividualQuery-138", "deterministicIds": [PLAN_DESSUS]}]}]


def esquisse_rectangle(largeur: float, profondeur: float, nom: str) -> dict:
    x0, y0 = -largeur / 2, -profondeur / 2
    lignes = [_ligne("bas", x0, y0, 1, 0, largeur), _ligne("droite", -x0, y0, 0, 1, profondeur),
              _ligne("haut", -x0, -y0, -1, 0, largeur), _ligne("gauche", x0, -y0, 0, -1, profondeur)]
    coins = [("bas.end", "droite.start"), ("droite.end", "haut.start"), ("haut.end", "gauche.start"),
             ("gauche.end", "bas.start")]
    contraintes = [{"btType": "BTMSketchConstraint-2", "constraintType": "COINCIDENT", "entityId": f"c{i}",
                    "parameters": [{"btType": "BTMParameterString-149", "parameterId": "localFirst", "value": a},
                                   {"btType": "BTMParameterString-149", "parameterId": "localSecond", "value": b}]}
                   for i, (a, b) in enumerate(coins)]
    return {"btType": "BTMSketch-151", "featureType": "newSketch", "name": f"Esquisse {nom}",
            "parameters": _plan(), "entities": lignes, "constraints": contraintes}


def esquisse_cercle(rayon: float, nom: str) -> dict:
    return {"btType": "BTMSketch-151", "featureType": "newSketch", "name": f"Esquisse {nom}", "parameters": _plan(),
            "entities": [{"btType": "BTMSketchCurve-4", "entityId": "cercle", "centerId": "cercle.center",
                          "geometry": {"btType": "BTCurveGeometryCircle-115", "radius": rayon, "xCenter": 0.0,
                                       "yCenter": 0.0, "xDir": 1.0, "yDir": 0.0, "clockwise": False}}],
            "constraints": []}


def extrusion(id_esquisse: str, hauteur: float, nom: str) -> dict:
    return {"btType": "BTMFeature-134", "featureType": "extrude", "name": nom, "parameters": [
        {"btType": "BTMParameterEnum-145", "parameterId": "bodyType", "enumName": "ExtendedToolBodyType", "value": "SOLID"},
        {"btType": "BTMParameterEnum-145", "parameterId": "operationType", "enumName": "NewBodyOperationType", "value": "NEW"},
        {"btType": "BTMParameterQueryList-148", "parameterId": "entities",
         "queries": [{"btType": "BTMIndividualSketchRegionQuery-140", "featureId": id_esquisse}]},
        {"btType": "BTMParameterEnum-145", "parameterId": "endBound", "enumName": "BoundingType", "value": "BLIND"},
        {"btType": "BTMParameterQuantity-147", "parameterId": "depth", "expression": f"{hauteur * 1000:g} mm"},
    ]}
