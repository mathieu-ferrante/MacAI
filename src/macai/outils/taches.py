"""Annuler la dernière action sur les fichiers, et tâches planifiées (« chaque matin à 8 h, résume… »)."""
from __future__ import annotations

from datetime import datetime

from .base import ErreurOutil, Resultat, Risque, outil

MOTS_ANNULER = ["annule ca", "annule la derniere", "annuler la derniere", "annule ce que tu", "reviens en arriere",
                "retour en arriere", "defais", "ctrl z", "cmd z", "undo", "remets comme avant"]
MOTS_HISTORIQUE = ["historique des actions", "dernieres actions", "qu'as-tu fait", "qu'est-ce que tu as fait",
                   "tu as fait quoi"]
MOTS_TACHES = ["planifie", "programme", "tous les jours", "chaque matin", "chaque soir", "chaque lundi",
               "chaque mardi", "chaque mercredi", "chaque jeudi", "chaque vendredi", "chaque samedi",
               "chaque dimanche", "chaque semaine", "toutes les heures", "rappelle-moi chaque", "automatise",
               "tache planifiee", "taches planifiees", "en semaine", "tous les matins"]


def _fichier_annulations(ctx):
    from .. import annulation
    f = annulation.fichier_pour(ctx)
    if f is None:
        raise ErreurOutil("Dossier de données indisponible.")
    return f


def _annonce_annuler(args) -> str:
    from .. import annulation
    e = annulation.derniere(annulation.fichier_courant())
    return f"Annuler : {e['description']}" if e else "Annuler la dernière action (rien d'enregistré)"


@outil("annuler_derniere_action", "Annule la dernière action faite sur les FICHIERS (déplacement, renommage, copie, "
       "fichier écrit, dossier créé, rangement, mise à la Corbeille) et dit ce qui a été restauré. À appeler UNE "
       "seule fois par demande. Ne sert pas à annuler un rendez-vous, un mail ou un rappel.", "taches",
       {}, risque=Risque.MODIFICATION, mac_seulement=False, annonce=_annonce_annuler, mots_cles=MOTS_ANNULER)
def annuler_derniere_action(ctx):
    from .. import annulation
    r = annulation.annuler(_fichier_annulations(ctx))
    # Toujours un succès quand la pile a été traitée : le texte dit précisément ce qui a (ou n'a pas) été
    # restauré, et le modèle ne doit pas relancer l'outil (il annulerait l'action d'avant).
    return Resultat(True, r["texte"], {"restaures": r["restaures"], "echecs": r["echecs"]})


@outil("historique_actions", "Liste les dernières actions sur les fichiers que l'on peut annuler.", "taches",
       {"nombre": ("integer", "combien d'actions (5 par défaut)")}, requis=[], mac_seulement=False,
       mots_cles=MOTS_HISTORIQUE)
def historique_actions(ctx, nombre=5):
    from .. import annulation
    entrees = annulation.historique(_fichier_annulations(ctx), min(max(int(nombre or 5), 1), 50))
    if not entrees:
        return "Aucune action annulable enregistrée."
    lignes = []
    for i, e in enumerate(entrees, 1):
        try:
            quand = datetime.fromisoformat(e["quand"]).strftime("%d/%m %H:%M")
        except (KeyError, ValueError):
            quand = "?"
        lignes.append(f"{i}. {quand} — {e.get('description', '')}" + ("  ← annulée en premier" if i == 1 else ""))
    return Resultat(True, "Actions annulables (la plus récente d'abord) :\n" + "\n".join(lignes),
                    {"nb": len(entrees)})


# --- Tâches planifiées ----------------------------------------------------------------------

def _fichier_taches(ctx):
    return ctx.config.chemin("taches.json")


@outil("planifier_tache", "Programme une demande à refaire automatiquement (tous les jours, en semaine, chaque "
       "lundi, toutes les heures ou une fois). Exemple : « fais-moi un résumé chaque matin » → "
       "demande=« résume mes mails non lus et mon agenda du jour », frequence=« quotidien », heure=« 08:00 ». "
       "La tâche tourne sans toi : rien qui envoie, supprime, publie ou paie.", "taches",
       {"demande": ("string", "ce qu'il faudra faire, en français, ex. « résume mes mails non lus »"),
        "frequence": ("string", "quotidien, jours_ouvres, hebdomadaire, horaire ou une_fois (ou « tous les jours », "
                                "« chaque lundi », « demain »…)"),
        "heure": ("string", "HH:MM, 08:00 par défaut"),
        "jour": ("string", "jour de la semaine pour hebdomadaire (lundi … dimanche)"),
        "date": ("string", "pour une_fois : demain, JJ/MM/AAAA ou AAAA-MM-JJ")},
       requis=["demande", "frequence"], risque=Risque.CREATION, mac_seulement=False, mots_cles=MOTS_TACHES,
       annonce=lambda a: f"Planifier « {a.get('demande', '')} » ({a.get('frequence', '')}"
                         f"{', ' + str(a['heure']) if a.get('heure') else ''})")
def planifier_tache(ctx, demande, frequence, heure="08:00", jour="", date=""):
    from .. import planificateur as pl
    if ctx.services.get("tache_planifiee"):
        raise ErreurOutil("Une tâche planifiée ne peut pas en programmer d'autres.")
    try:
        tache = pl.creer(demande, frequence, heure or "08:00", jour or "", date or "")
    except ValueError as e:
        raise ErreurOutil(str(e)) from None
    fichier = _fichier_taches(ctx)
    if any(t["demande"] == tache["demande"] and t["frequence"] == tache["frequence"] and t["heure"] == tache["heure"]
           and t.get("jour") == tache["jour"] and t.get("active", True) for t in pl.charger(fichier)):
        return Resultat(True, f"Cette tâche existe déjà : {tache['description']}.")
    pl.ajouter(fichier, tache)
    prochaine = pl.prochaine_execution(tache, datetime.now())
    quand = f" Première fois : {prochaine:%d/%m à %H:%M}." if prochaine else ""
    return Resultat(True, f"C'est programmé : {tache['description']}.{quand} Tu recevras une notification avec le "
                          "résultat ; les actions qui demandent ton accord seront refusées.",
                    {"id": tache["id"]})


@outil("lister_taches", "Liste les tâches planifiées (ce qui tourne automatiquement et quand).", "taches",
       {}, mac_seulement=False, mots_cles=["taches planifiees", "tache planifiee", "taches programmees",
                                           "qu'as-tu programme", "ce qui est programme"])
def lister_taches(ctx):
    from .. import planificateur as pl
    taches = [t for t in pl.charger(_fichier_taches(ctx)) if t.get("active", True)]
    if not taches:
        return "Aucune tâche planifiée."
    lignes = []
    for t in taches:
        r = pl.resume(t)
        prochaine = datetime.fromisoformat(r["prochaine"]).strftime("%d/%m %H:%M") if r["prochaine"] else "—"
        lignes.append(f"[{t['id']}] {r['description']} — prochaine : {prochaine}")
    return Resultat(True, "Tâches planifiées :\n" + "\n".join(lignes), {"nb": len(taches)})


@outil("supprimer_tache", "Supprime une tâche planifiée (par son identifiant ou un mot de sa description).",
       "taches", {"id_ou_description": ("string", "identifiant entre crochets, ou un mot de la tâche")},
       risque=Risque.MODIFICATION, mac_seulement=False,
       mots_cles=["supprime la tache", "arrete la tache", "deprogramme", "annule la tache", "ne fais plus"],
       annonce=lambda a: f"Supprimer la tâche planifiée « {a.get('id_ou_description', '')} »")
def supprimer_tache(ctx, id_ou_description):
    from .. import planificateur as pl
    fichier = _fichier_taches(ctx)
    trouvees = pl.trouver(pl.charger(fichier), id_ou_description)
    if not trouvees:
        raise ErreurOutil(f"Aucune tâche ne correspond à « {id_ou_description} ». Utilise lister_taches.")
    if len(trouvees) > 1:
        raise ErreurOutil("Plusieurs tâches correspondent, précise l'identifiant : "
                          + " ; ".join(f"[{t['id']}] {t.get('description', '')}" for t in trouvees))
    pl.supprimer(fichier, trouvees[0]["id"])
    return f"Tâche supprimée : {trouvees[0].get('description', '')}."
