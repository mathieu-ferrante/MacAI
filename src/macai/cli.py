"""Ligne de commande : `macai <commande>` (ou `python -m macai`)."""
from __future__ import annotations

import argparse
import json
import sys


def cmd_serveur(args) -> int:
    from .application import Application
    from .serveur import servir
    servir(Application(), port=args.port)
    return 0


def cmd_demander(args) -> int:
    """Pose une question au moteur directement dans le Terminal (sans l'app)."""
    from .application import Application
    app = Application(avec_fond=False)
    diffuse = {"texte": False}

    def afficher(type_, **d):
        if type_ == "outil_debut":
            print(f"  → {d['phrase']}", flush=True)
        elif type_ == "outil_fin" and not d["ok"]:
            print(f"    ✗ {d['texte'][:200]}", flush=True)
        elif type_ == "texte":
            diffuse["texte"] = True
            print(d["morceau"], end="", flush=True)
        elif type_ == "proposition_competence":
            print("\n  (Je peux en faire une compétence : tape « crée une compétence ».)")

    def confirmer(phrase, outil, a):
        return input(f"\n  ⚠ {phrase} — confirmer ? [o/N] ").strip().lower() in ("o", "oui", "y")

    app.ctx.emettre = afficher
    app.ctx.demander_confirmation = confirmer
    demandes = [" ".join(args.texte)] if args.texte else iter(lambda: input("\n> "), "quitter")
    try:
        for demande in demandes:
            if demande.strip():
                diffuse["texte"] = False
                texte = app.traiter(demande)
                print("" if diffuse["texte"] else texte)
    except (EOFError, KeyboardInterrupt):
        pass
    app.fermer()
    return 0


def cmd_indexer(args) -> int:
    from .config import charger
    from .llm.ollama import Ollama
    from .recherche.index import Index
    from .recherche.indexeur import Indexeur
    cfg = charger()
    ollama = Ollama(garder="30s")
    index = Index(cfg.chemin("index.db"), ollama if ollama.disponible() else None, cfg.modeles["embeddings"])
    r = Indexeur(cfg, index).executer(force=args.force, limite=args.limite)
    print(json.dumps(r, ensure_ascii=False))
    return 0


def cmd_outils(args) -> int:
    from .outils.base import charger_tous
    reg = charger_tous()
    for groupe, outils in sorted(reg.groupes().items()):
        print(f"\n[{groupe}]")
        for o in outils:
            print(f"  {o.nom:<28} {o.description[:90]}")
    return 0


def cmd_secret(args) -> int:
    from .secrets import definir_interactif
    definir_interactif(args.nom)
    return 0


def cmd_mcp(args) -> int:
    from .config import charger
    from .mcp.client import GestionnaireMCP
    from .outils.base import Registre
    cfg = charger()
    if args.action == "detecter":
        from pathlib import Path
        apps = sorted(p for d in ("/Applications", str(Path.home() / "Applications"))
                      for p in Path(d).glob("**/*Craft*.app") if p.is_dir())
        if not apps:
            print("Aucune application ArtCraft trouvée dans /Applications.")
        for a in apps:
            print(f"- {a.stem} : {a}")
        # Le serveur MCP d'ArtCraft est un programme à part (ex. lightcraft-cli), pas l'app elle-même.
        import shutil
        dossiers = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin"),
                    str(Path.home() / ".cargo/bin")]
        clis = sorted({str(p) for d in dossiers for p in Path(d).glob("*craft-cli") if p.is_file()}
                      | {c for a in apps if (c := shutil.which(a.stem.lower() + "-cli"))})
        if clis:
            print("\nServeurs MCP trouvés — à ajouter dans", cfg.fichier, ":")
            for c in clis:
                print(f'\n[[mcp]]\nnom = "{Path(c).name.removesuffix("-cli")}"\ncommande = ["{c}", "mcp"]')
            print("\nPuis `macai mcp tester` (si « mcp » n'est pas le bon argument, voir `<cli> --help`).")
        elif apps:
            print("\nAucun serveur MCP ArtCraft installé (programmes « photocraft-cli », « lightcraft-cli »…) : "
                  "installe-les depuis ArtCraft, puis relance `macai mcp detecter`.")
        return 0
    if not cfg.mcp:
        print(f"Aucun serveur MCP configuré dans {cfg.fichier}.")
        return 0
    cache = cfg.chemin("mcp_cache.json")
    cache.unlink(missing_ok=True)
    g = GestionnaireMCP(cfg.mcp, Registre(), cache)
    for nom, etat in g.enregistrer().items():
        print(f"- {nom} : {etat}")
    g.fermer()
    return 0


def cmd_verifier(args) -> int:
    from .verification import verifier
    return verifier(json_sortie=args.json)


def cmd_banc(args) -> int:
    from .banc import banc
    return banc(args.modeles, candidats=args.candidats)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="macai", description="Assistant local qui pilote le Mac.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serveur", help="démarre le moteur (lancé par l'app)")
    s.add_argument("--port", type=int, default=0)
    s.set_defaults(func=cmd_serveur)

    s = sub.add_parser("demander", help="pose une demande dans le Terminal")
    s.add_argument("texte", nargs="*")
    s.set_defaults(func=cmd_demander)

    s = sub.add_parser("indexer", help="indexe les fichiers (priorité basse)")
    s.add_argument("--force", action="store_true", help="même si le Mac est utilisé ou sur batterie")
    s.add_argument("--limite", type=int, default=None)
    s.set_defaults(func=cmd_indexer)

    sub.add_parser("outils", help="liste les outils disponibles").set_defaults(func=cmd_outils)

    s = sub.add_parser("secret", help="enregistre des clés dans le Trousseau (ex. onshape)")
    s.add_argument("nom")
    s.set_defaults(func=cmd_secret)

    s = sub.add_parser("mcp", help="connecteurs MCP : tester ou détecter")
    s.add_argument("action", choices=["tester", "detecter"])
    s.set_defaults(func=cmd_mcp)

    s = sub.add_parser("verifier", help="contrôle l'installation et produit un rapport")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_verifier)

    s = sub.add_parser("banc", help="mesure la vitesse des modèles et la justesse de l'agent")
    s.add_argument("modeles", nargs="*")
    s.add_argument("--candidats", action="store_true",
                   help="compare les meilleurs modèles pour 8 Go (propose de les télécharger)")
    s.set_defaults(func=cmd_banc)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
