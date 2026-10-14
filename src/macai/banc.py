"""`macai banc [modèles…]` : mesure vitesse, mémoire et justesse des appels d'outils, sans rien exécuter.

Chaque demande de la batterie a un outil attendu. Les outils sont simulés : aucune action n'a lieu.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .agent import consignes, routeur
from .config import charger
from .llm.ollama import ErreurOllama, Ollama
from .outils.base import Registre, charger_tous

BATTERIE = [
    ("Retrouve ma facture EDF de mars", "rechercher_fichiers"),
    ("Résume le fichier ~/Documents/rapport.pdf", "lire_document"),
    ("Crée un tableur Excel sur le bureau avec les mois et les montants 120 et 95", "creer_tableur"),
    ("Range mon dossier Téléchargements", "ranger_dossier"),
    ("Mets un rappel demain à 9h pour appeler la banque", "creer_rappel"),
    ("Pourquoi mon Mac est lent ?", "etat_memoire"),
    ("Fais-moi un cube de 1 mètre dans Onshape", "onshape_creer_piece"),
    ("Cherche des tutos Blender sur YouTube", "chrome_rechercher"),
    ("Qu'est-ce qu'il y a sur la page ouverte dans Chrome ?", "lire_page"),
    ("Clique sur le bouton Exporter dans la fenêtre de Pages", "lire_fenetre"),
    ("Retiens que je préfère les réponses courtes", "retenir"),
    ("Écris un fichier notes.md sur le bureau avec la liste des courses : pain, lait", "ecrire_fichier_texte"),
]


# Meilleurs candidats pour un Mac 8 Go (recherche d'octobre 2026, voir MODELES.md). Tailles approximatives.
CANDIDATS = [
    ("qwen3.5:4b", "3,3 Go", "défaut : outils + vision + réflexion en un seul modèle"),
    ("qwen3.5:2b", "~1,9 Go", "plus rapide et plus léger, moins fiable sur les tâches en plusieurs étapes"),
    ("gemma4:e4b", "~3,5 Go", "Google, multimodal, nettement moins bon en tâches d'agent (TAU2)"),
    ("phi4-mini", "~2,5 Go", "appels d'outils solides, pas de vision"),
    ("qwen3:4b", "~2,5 Go", "génération précédente, référence"),
]
CANDIDATS_EMBEDDINGS = [
    ("qwen3-embedding:0.6b", "~640 Mo", "défaut : meilleur multilingue sous 1 milliard de paramètres"),
    ("embeddinggemma", "~620 Mo", "Google, 300 M paramètres, contexte 2 K"),
    ("bge-m3", "~1,2 Go", "multilingue solide, plus lourd"),
]

# Petit jeu de recherche en français : (document, requête qui doit le retrouver).
PAIRES_FR = [
    ("Facture EDF électricité mars 2026, montant 84,20 euros, échéance 15 avril.", "ma facture d'électricité de mars"),
    ("Cours de réseaux : le protocole TCP établit une connexion en trois temps (SYN, SYN-ACK, ACK).",
     "le cours sur la poignée de main TCP"),
    ("Recette des crêpes : 250 g de farine, 4 oeufs, un demi-litre de lait, une pincée de sel.", "comment faire des crêpes"),
    ("Contrat de location : préavis de trois mois, loyer de 650 euros charges comprises.", "bail avec préavis de 3 mois"),
    ("Attestation de mutuelle santé valable du 1er janvier au 31 décembre 2026.", "papier de la complémentaire santé"),
    ("Compte rendu de réunion : budget validé à 4 500 euros, commande des pièces avant vendredi.",
     "réunion où on a validé le budget"),
    ("Billet de train Toulon Paris, départ 7 h 42, voiture 12 place 54.", "mon billet SNCF pour Paris"),
    ("Notice de montage de l'étagère KALLAX : visser les panneaux latéraux avant les tablettes.",
     "instructions pour monter le meuble Ikea"),
    ("Relevé de notes du semestre : mathématiques 15, physique 13, anglais 17.", "mes notes de cette année"),
    ("Devis du garagiste : remplacement des plaquettes de frein avant, 180 euros TTC.", "prix pour changer les freins de la voiture"),
]


def banc_embeddings(o: Ollama, modeles: list[str]) -> list[dict]:
    """Rappel@1 sur PAIRES_FR : la bonne fiche doit sortir en premier pour chaque requête."""
    import numpy as np
    from .recherche.index import DIMENSIONS, INSTRUCTION_REQUETE
    resultats = []
    docs = [d for d, _ in PAIRES_FR]
    for m in modeles:
        print(f"\n== embeddings : {m} ==", flush=True)
        try:
            debut = time.monotonic()
            vd = np.asarray(o.vecteurs(m, docs, DIMENSIONS), dtype=np.float32)
            instr = INSTRUCTION_REQUETE if m.startswith("qwen3-embedding") else ""
            vq = np.asarray(o.vecteurs(m, [instr + q for _, q in PAIRES_FR], DIMENSIONS), dtype=np.float32)
            duree = time.monotonic() - debut
        except ErreurOllama as e:
            print(f"  erreur : {e}")
            resultats.append({"modele": m, "erreur": str(e)[:200]})
            continue
        vd /= np.linalg.norm(vd, axis=1, keepdims=True) + 1e-9
        vq /= np.linalg.norm(vq, axis=1, keepdims=True) + 1e-9
        justes = int(sum(int(np.argmax(vd @ q)) == i for i, q in enumerate(vq)))
        print(f"  {justes}/{len(PAIRES_FR)} retrouvés en premier, {duree:.1f} s pour {2 * len(PAIRES_FR)} textes")
        resultats.append({"modele": m, "rappel_1": f"{justes}/{len(PAIRES_FR)}", "score": justes / len(PAIRES_FR),
                          "duree_s": round(duree, 1)})
        o.decharger(m)
    return resultats


def preparer_candidats(o: Ollama, liste) -> list[str]:
    """Propose de télécharger les candidats absents (sur le Mac, à la demande de l'utilisateur)."""
    installes = o.installes()
    absents = [(n, t, d) for n, t, d in liste if not any(i == n or i.startswith(n + ":") or i == n + ":latest"
                                                          for i in installes)]
    if absents:
        print("Modèles à télécharger pour la comparaison :")
        for n, t, d in absents:
            print(f"  - {n} ({t}) : {d}")
        if input("Les télécharger maintenant ? [o/N] ").strip().lower() in ("o", "oui", "y"):
            for n, _, _ in absents:
                print(f"→ ollama pull {n}", flush=True)
                subprocess.run(["ollama", "pull", n])
    installes = o.installes()
    return [n for n, _, _ in liste if any(i == n or i.startswith(n + ":") or i == n + ":latest" for i in installes)]


def _registre_simule(reel: Registre) -> Registre:
    return reel  # seuls les schémas servent : on n'appelle jamais les fonctions


def mesurer(o: Ollama, modele: str, reg: Registre) -> dict:
    o.decharger_tout_sauf("")
    debut = time.monotonic()
    try:
        o.discuter(modele, [{"role": "user", "content": "Bonjour"}])
    except ErreurOllama as e:
        return {"modele": modele, "erreur": str(e)[:200]}
    chargement = time.monotonic() - debut
    taille = next((m.get("size", 0) for m in o.charges() if m.get("name", "").startswith(modele.split(":")[0])), 0)

    justes, durees, vitesses = 0, [], []
    details = []
    for demande, attendu in BATTERIE:
        noms = routeur.choisir(demande, reg)
        msgs = [{"role": "system", "content": consignes.construire("Mathieu")}, {"role": "user", "content": demande}]
        t = time.monotonic()
        r = o.discuter(modele, msgs, reg.schemas(noms))
        d = time.monotonic() - t
        durees.append(d)
        if r.jetons_sortie and r.duree_s:
            vitesses.append(r.jetons_sortie / max(r.duree_s, 1e-3))
        appele = r.appels[0].nom if r.appels else "(aucun)"
        ok = appele == attendu
        justes += ok
        details.append({"demande": demande, "attendu": attendu, "obtenu": appele, "ok": ok, "duree_s": round(d, 1),
                        "outil_propose": attendu in noms})
    return {"modele": modele, "chargement_s": round(chargement, 1), "ram_go": round(taille / 1024**3, 1),
            "justesse": f"{justes}/{len(BATTERIE)}", "score": justes / len(BATTERIE),
            "duree_moyenne_s": round(sum(durees) / len(durees), 1),
            "jetons_par_s": round(sum(vitesses) / len(vitesses), 1) if vitesses else None, "details": details}


def banc(modeles: list[str] | None = None, candidats: bool = False) -> int:
    cfg = charger()
    o = Ollama(garder="1m", contexte=int(cfg.modeles["contexte"]))
    if not o.disponible():
        print("Ollama n'est pas démarré : relance ./installer.sh")
        return 1
    reg = _registre_simule(charger_tous())
    resultats_emb = []
    if candidats:
        modeles = preparer_candidats(o, CANDIDATS)
        resultats_emb = banc_embeddings(o, preparer_candidats(o, CANDIDATS_EMBEDDINGS))
        if resultats_emb and any("score" in r for r in resultats_emb):
            m = max((r for r in resultats_emb if "score" in r), key=lambda r: (r["score"], -r["duree_s"]))
            print(f"\nEmbeddings recommandés : {m['modele']} ([modeles] embeddings = \"{m['modele']}\").")
    modeles = modeles or [cfg.modeles["agent"]]
    resultats = []
    for m in modeles:
        print(f"\n== {m} ==", flush=True)
        r = mesurer(o, m, reg)
        resultats.append(r)
        if "erreur" in r:
            print(f"  erreur : {r['erreur']}")
            continue
        for d in r["details"]:
            print(f"  {'✓' if d['ok'] else '✗'} {d['demande'][:60]:<60} → {d['obtenu']} ({d['duree_s']} s)")
        print(f"  Justesse {r['justesse']}, {r['duree_moyenne_s']} s par demande, {r['jetons_par_s']} jetons/s, "
              f"{r['ram_go']} Go de RAM, chargement {r['chargement_s']} s")
        o.decharger(m)
    valides = [r for r in resultats if "erreur" not in r]
    if valides:
        meilleur = max(valides, key=lambda r: (r["score"], -r["duree_moyenne_s"]))
        print(f"\nRecommandé : {meilleur['modele']} — à mettre dans macai.toml ([modeles] agent = \"{meilleur['modele']}\").")
    dossier = cfg.chemin("banc")
    dossier.mkdir(exist_ok=True)
    f = dossier / f"banc-{time.strftime('%Y-%m-%d_%H%M')}.json"
    f.write_text(json.dumps({"agents": resultats, "embeddings": resultats_emb}, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    print(f"Résultats : {f}")
    return 0
