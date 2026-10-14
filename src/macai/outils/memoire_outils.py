"""Outils de mémoire : retenir, oublier, consulter."""
from __future__ import annotations

import time

from .base import ErreurOutil, Resultat, Risque, outil


def _memoire(ctx):
    m = ctx.service("memoire")
    if m is None:
        raise ErreurOutil("Mémoire indisponible.")
    return m


@outil("retenir", "Retient durablement un fait sur l'utilisateur (préférence, information personnelle, habitude).",
       "memoire", {"fait": ("string", "le fait, à la 3e personne, ex. « Mathieu préfère les réponses courtes »")},
       risque=Risque.CREATION, mac_seulement=False)
def retenir(ctx, fait):
    f = _memoire(ctx).retenir(fait, source="dit")
    return f"Retenu : {f.texte}"


@outil("oublier", "Oublie les souvenirs qui correspondent à une description (ou « tout »).", "memoire",
       {"quoi": ("string", "ce qu'il faut oublier, ou « tout »")}, risque=Risque.MODIFICATION, mac_seulement=False,
       annonce=lambda a: f"Oublier : {a['quoi']}")
def oublier(ctx, quoi):
    effaces = _memoire(ctx).oublier(quoi)
    if not effaces:
        return "Aucun souvenir ne correspond."
    return "Oublié :\n" + "\n".join(f"- {t}" for t in effaces)


@outil("lister_souvenirs", "Liste tout ce que l'assistant sait de l'utilisateur.", "memoire", {}, mac_seulement=False)
def lister_souvenirs(ctx):
    faits = _memoire(ctx).tous()
    if not faits:
        return "Je ne sais encore rien de toi."
    return Resultat(True, "\n".join(f"- {f.texte} ({'appris' if f.source == 'appris' else 'dit'} le "
                                    f"{time.strftime('%d/%m/%Y', time.localtime(f.cree_le))})" for f in faits),
                    {"nb": len(faits)})
