"""Outils de l'agent pour le texte copié et une zone de l'écran (les raccourcis ⌥⇧T / ⌥⇧S passent par texte.py)."""
from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from .. import texte as tx
from .base import ErreurOutil, Resultat, Risque, outil


@outil("transformer_texte", "Corrige, reformule, traduit, résume, explique ou rédige une réponse à un texte : "
       "celui donné, sinon celui du presse-papiers (ce que l'utilisateur a copié). Le résultat est copié dans le "
       "presse-papiers.", "fichiers",
       {"action": ("string", "ce qu'il faut faire", ["corriger", "reformuler", "traduire", "resumer", "expliquer",
                                                      "repondre", "libre"]),
        "consigne": ("string", "pour action=libre : la consigne, ex. « mets au format liste »"),
        "texte": ("string", "le texte, facultatif (sinon le presse-papiers)")},
       requis=["action"], risque=Risque.CREATION, mac_seulement=False,
       mots_cles=["copie", "copié", "presse-papier", "presse-papiers", "corrige", "reformule", "traduis",
                  "resume ce texte", "relis"])
def transformer_texte(ctx, action, consigne="", texte=""):
    source = str(texte or "").strip() or tx.lire_presse_papiers().strip()
    if not source:
        raise ErreurOutil("Aucun texte : copie-le (Cmd+C) ou donne-le directement.")
    resultat = tx.transformer(ctx, action, source, consigne)
    if not resultat:
        return Resultat.echec("Le modèle n'a rien renvoyé.")
    try:
        tx.ecrire_presse_papiers(resultat)
        note = "\n\n(Copié dans le presse-papiers.)"
    except ImportError:
        note = ""
    return Resultat(True, resultat + note)


@outil("regarder_zone_ecran", "Laisse l'utilisateur sélectionner une zone de l'écran à la souris, puis l'explique, "
       "la traduit, en extrait le texte ou un tableau Excel, ou répond à une question sur elle.", "fenetres",
       {"action": ("string", "quoi faire", ["expliquer", "traduire", "texte", "tableau", "libre"]),
        "question": ("string", "pour action=libre : la question sur la zone")},
       requis=["action"], risque=Risque.LECTURE,
       mots_cles=["zone", "cette partie de l'ecran", "regarde ca", "capture de zone", "selectionne a l'ecran"])
def regarder_zone_ecran(ctx, action, question=""):
    from .fenetres import _verifier_capture_autorisee
    _verifier_capture_autorisee()
    chemin = Path(tempfile.gettempdir()) / f"macai-zone-{int(time.time() * 1000)}.png"
    try:
        subprocess.run(["/usr/sbin/screencapture", "-i", "-x", str(chemin)], timeout=120, check=False)
        if not chemin.exists():
            return Resultat(True, "Sélection annulée : aucune zone capturée.")
        return Resultat(True, tx.analyser_image(ctx, str(chemin), action, question))
    finally:
        chemin.unlink(missing_ok=True)
