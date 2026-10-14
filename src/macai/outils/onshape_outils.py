"""Outils Onshape : créer une pièce simple (cube, pavé, cylindre), chercher et ouvrir des documents."""
from __future__ import annotations

from ..connecteurs.onshape import Onshape, en_metres
from .base import ErreurOutil, Resultat, Risque, outil


def _annonce(a):
    return f"Créer dans Onshape : {a.get('forme', 'pièce')} {a.get('largeur', '')}"


@outil("onshape_creer_piece", "Crée dans Onshape une pièce simple : cube, pavé (largeur × profondeur × hauteur) "
       "ou cylindre (diamètre × hauteur), dans un nouveau document, puis l'ouvre dans Chrome. Dimensions avec "
       "unité, ex. « 1 m », « 250 mm ».", "onshape",
       {"forme": ("string", "forme", ["cube", "pave", "cylindre"]),
        "largeur": ("string", "côté du cube, largeur du pavé ou diamètre du cylindre"),
        "profondeur": ("string", "profondeur du pavé, facultatif"),
        "hauteur": ("string", "hauteur du pavé ou du cylindre, facultatif"),
        "nom": ("string", "nom du document, facultatif")}, requis=["forme", "largeur"],
       risque=Risque.CREATION, annonce=_annonce, mac_seulement=False, mots_cles=["onshape"])
def onshape_creer_piece(ctx, forme, largeur, profondeur="", hauteur="", nom=""):
    forme = forme.lower().replace("é", "e")
    if forme not in ("cube", "pave", "cylindre"):
        raise ErreurOutil("Formes possibles : cube, pave, cylindre.")
    l = en_metres(largeur)
    p = en_metres(profondeur) if profondeur and forme == "pave" else l
    h = en_metres(hauteur) if hauteur and forme != "cube" else l
    titre = nom or {"cube": f"Cube {largeur}", "pave": f"Pavé {largeur} x {profondeur or largeur} x {hauteur or largeur}",
                    "cylindre": f"Cylindre Ø{largeur} x {hauteur or largeur}"}[forme]
    api = Onshape()
    did, wid, eid = api.creer_document(titre)
    api.piece(did, wid, eid, forme, l, p, h, titre)
    url = Onshape.url(did, wid, eid)
    try:
        from .chrome import ouvrir_onglet
        ouvrir_onglet(ctx, url)
        ouvert = " et ouvert dans Chrome"
    except Exception:  # noqa: BLE001 - la pièce existe même si Chrome ne s'ouvre pas
        ouvert = ""
    volume = l * p * h if forme != "cylindre" else 3.14159265 * (l / 2) ** 2 * h
    return Resultat(True, f"« {titre} » créé dans Onshape{ouvert} (volume {volume:g} m³).", {"url": url})


@outil("onshape_documents", "Cherche les documents Onshape de l'utilisateur.", "onshape",
       {"requete": ("string", "nom ou mot du document, vide pour les plus récents")}, requis=[], mac_seulement=False)
def onshape_documents(ctx, requete=""):
    docs = Onshape().chercher_documents(requete)
    if not docs:
        return "Aucun document trouvé."
    return "\n".join(f"- {d['name']} (modifié {d.get('modifiedAt', '')[:10]}) : https://cad.onshape.com/documents/{d['id']}"
                     for d in docs)
