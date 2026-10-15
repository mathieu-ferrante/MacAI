"""Outils de mémoire : retenir, oublier, consulter."""
from __future__ import annotations

import re
import time

from .base import ErreurOutil, Resultat, Risque, interdire_donnees_bancaires, outil

# La demande de l'utilisateur parle de mémoire ou de lui-même : « retenir » va de soi. Sinon (le fait vient
# d'une page web, d'un document, d'un mail…), rien n'est mémorisé sans son accord.
DEMANDE_DE_RETENIR = re.compile(
    r"\b(retiens|retenir|souviens|souvenir|rappelle[- ]toi|memorise|memoriser|note (?:que|bien)|n'oublie pas|"
    r"garde en (?:tete|memoire)|je suis|je m'appelle|appelle[- ]moi|j'aime|je n'aime pas|je deteste|je prefere|"
    r"j'habite|je vis|je travaille|mon|ma|mes)\b")


def _memoire(ctx):
    m = ctx.service("memoire")
    if m is None:
        raise ErreurOutil("Mémoire indisponible.")
    return m


SECRET = re.compile(r"mot de passe|password|passcode|code (pin|secret|d.acc[eè]s|de carte|confidentiel)|\bpin\b|"
                    r"\bcvv\b|\bcvc\b|cryptogramme|num[ée]ro de (carte|s[ée]cu|s[ée]curit[ée] sociale|passeport)|"
                    r"\biban\b|\bbic\b|cl[ée] (api|priv[ée]e|secr[eè]te)|\btoken\b|identifiants?", re.I)


@outil("retenir", "Retient durablement un fait sur l'utilisateur (préférence, information personnelle, habitude).",
       "memoire", {"fait": ("string", "le fait, à la 3e personne, ex. « Mathieu préfère les réponses courtes »")},
       risque=Risque.CREATION, mac_seulement=False)
def retenir(ctx, fait):
    # Jamais de secrets en mémoire (elle est relue dans chaque demande) : cartes, IBAN, mots de passe, codes.
    interdire_donnees_bancaires(fait)
    if SECRET.search(str(fait)):
        raise ErreurOutil("Je ne retiens pas les mots de passe, codes ou numéros confidentiels : garde-les dans "
                          "ton gestionnaire de mots de passe.")
    memoire = _memoire(ctx)
    demande = ctx.services.get("demande")  # posée par l'orchestrateur à chaque demande
    if demande is not None:
        from ..agent.routeur import normaliser
        if not DEMANDE_DE_RETENIR.search(normaliser(str(demande)).replace("\u2019", "'")):
            phrase = f"Retenir durablement : « {fait} »"
            ctx.emettre("confirmation", outil="retenir", arguments={"fait": fait}, phrase=phrase)
            if not ctx.demander_confirmation(phrase, "retenir", {"fait": fait}):
                raise ErreurOutil("Non retenu : la demande ne parlait pas de mémoriser, et l'utilisateur n'a pas "
                                  "confirmé. Ne réessaie pas.")
    f = memoire.retenir(fait, source="dit")
    return f"Retenu : {f.texte}"


@outil("oublier", "Oublie les souvenirs qui correspondent à une description (ou « tout »).", "memoire",
       {"quoi": ("string", "ce qu'il faut oublier, ou « tout »")}, risque=Risque.SENSIBLE, toujours_confirmer=True,
       mac_seulement=False,
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
