"""Outils pour créer, lister et supprimer les compétences apprises."""
from __future__ import annotations

from .base import ErreurOutil, Resultat, Risque, outil


def _biblio(ctx):
    b = ctx.service("competences")
    if b is None:
        raise ErreurOutil("Compétences indisponibles.")
    return b


@outil("creer_competence", "Crée une compétence réutilisable : à partir de la dernière tâche réussie, ou d'une "
       "description (ex. « mode travail : ouvre VS Code et Slack, volume à 20 »).", "competences",
       {"description": ("string", "description de la compétence, facultatif si on part de la dernière tâche"),
        "nom": ("string", "nom souhaité, facultatif")}, requis=[], risque=Risque.CREATION, mac_seulement=False)
def creer_competence(ctx, description="", nom=""):
    from ..competences.competences import generer
    biblio = _biblio(ctx)
    trace = ctx.services.get("derniere_trace") if not description else None
    if not trace and not description:
        raise ErreurOutil("Aucune tâche récente à transformer : décris la compétence voulue.")
    derniere_erreur = ""
    for _ in range(2):  # une seconde chance si le modèle produit une recette invalide
        try:
            c = generer(ctx, trace["demande"] if trace else description, trace["actions"] if trace else None,
                        description + (f"\n(Correction demandée : {derniere_erreur})" if derniere_erreur else ""))
            if nom:
                c.nom = nom
            c = biblio.ajouter(c)
            break
        except ValueError as e:
            derniere_erreur = str(e)
    else:
        raise ErreurOutil(f"Je n'ai pas réussi à créer une compétence valide : {derniere_erreur}")
    ctx.services["derniere_trace"] = None
    params = ", ".join(c.parametres) or "aucun"
    etapes = "\n".join(f"  {i}. {e['outil']}" for i, e in enumerate(c.etapes, 1))
    return Resultat(True, f"Compétence « {c.nom} » créée : {c.description}\nParamètres : {params}\nÉtapes :\n{etapes}",
                    {"competence": c.nom})


@outil("lister_competences", "Liste les compétences apprises.", "competences", {}, mac_seulement=False)
def lister_competences(ctx):
    comps = _biblio(ctx).competences.values()
    if not comps:
        return "Aucune compétence pour l'instant."
    return "\n".join(f"- {c.nom} : {c.description} (paramètres : {', '.join(c.parametres) or 'aucun'}, "
                     f"utilisée {c.utilisations} fois)" for c in comps)


@outil("supprimer_competence", "Supprime une compétence apprise.", "competences",
       {"nom": ("string", "nom de la compétence")}, risque=Risque.MODIFICATION, mac_seulement=False,
       annonce=lambda a: f"Supprimer la compétence {a['nom']}")
def supprimer_competence(ctx, nom):
    if not _biblio(ctx).supprimer(nom):
        raise ErreurOutil(f"Compétence « {nom} » introuvable.")
    return f"Compétence « {nom} » supprimée."
