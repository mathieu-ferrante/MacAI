"""`macai banc [modèles…]` : mesure vitesse, mémoire et justesse des appels d'outils, sans rien exécuter.

Chaque demande de la batterie a un outil attendu. Les outils sont simulés : aucune action n'a lieu.
"""
from __future__ import annotations

import json
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


def banc(modeles: list[str] | None = None) -> int:
    cfg = charger()
    o = Ollama(garder="1m", contexte=int(cfg.modeles["contexte"]))
    if not o.disponible():
        print("Ollama n'est pas démarré : brew services start ollama")
        return 1
    reg = _registre_simule(charger_tous())
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
    f.write_text(json.dumps(resultats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Résultats : {f}")
    return 0
