"""`macai verifier` : contrôle complet de l'installation, avec la marche à suivre pour chaque problème.

Le rapport est aussi enregistré sur le Bureau (MacAI-verification.txt) pour pouvoir être renvoyé.
"""
from __future__ import annotations

import importlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

from .config import charger

OK, ATTENTION, ECHEC = "✓", "!", "✗"


def _cmd(cmd: list[str], delai: float = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=delai).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def controles() -> list[tuple[str, str, str, str]]:
    """[(statut, élément, détail, solution)]"""
    res = []
    ajout = lambda s, e, d="", sol="": res.append((s, e, d, sol))  # noqa: E731
    cfg = charger()

    # --- Système -------------------------------------------------------------------
    mac = sys.platform == "darwin"
    ajout(OK if mac else ECHEC, "macOS", _cmd(["sw_vers", "-productVersion"]) if mac else sys.platform,
          "" if mac else "MacAI fonctionne uniquement sur macOS.")
    puce = _cmd(["sysctl", "-n", "machdep.cpu.brand_string"]) if mac else platform.machine()
    ajout(OK if "Apple" in puce or not mac else ATTENTION, "Puce", puce)
    ram = int(_cmd(["sysctl", "-n", "hw.memsize"]) or 0) / 1024**3 if mac else 0
    ajout(OK if ram >= 8 or not mac else ATTENTION, "Mémoire", f"{ram:.0f} Go")
    ajout(OK if sys.version_info >= (3, 11) else ECHEC, "Python", platform.python_version(),
          "Relance ./installer.sh (installe Python 3.12 via uv).")

    # --- Dépendances ----------------------------------------------------------------
    modules = {"pypdf": "PDF", "docx": "Word", "openpyxl": "Excel", "pptx": "PowerPoint", "numpy": "recherche",
               "cryptography": "mémoire chiffrée"}
    if mac:
        modules |= {"Quartz": "clavier/souris", "ApplicationServices": "fenêtres", "Vision": "OCR",
                    "AppKit": "applications"}
    for m, role in modules.items():
        try:
            importlib.import_module(m)
            ajout(OK, f"Module {m}", role)
        except ImportError:
            ajout(ECHEC, f"Module {m}", role, "Relance ./installer.sh")

    # --- Ollama et modèles -----------------------------------------------------------
    from .llm.ollama import Ollama
    o = Ollama()
    if o.disponible():
        installes = o.installes()
        ajout(OK, "Ollama", "démarré")
        for role, nom in (("agent", cfg.modeles["agent"]), ("vision", cfg.modeles["vision"]),
                          ("embeddings", cfg.modeles["embeddings"])):
            present = any(i == nom or i == f"{nom}:latest" or i.startswith(nom + ":") for i in installes)
            ajout(OK if present else ECHEC, f"Modèle {role}", nom, f"ollama pull {nom}")
        if mac:
            import plistlib
            agent = Path.home() / "Library/LaunchAgents/fr.mathieu.macai.ollama.plist"
            try:
                env = plistlib.loads(agent.read_bytes()).get("EnvironmentVariables", {})
            except (OSError, plistlib.InvalidFileException):
                env = {}
            for var, attendu in (("OLLAMA_KEEP_ALIVE", "2m"), ("OLLAMA_MAX_LOADED_MODELS", "2"),
                                 ("OLLAMA_FLASH_ATTENTION", "1"), ("OLLAMA_KV_CACHE_TYPE", "q8_0")):
                val = env.get(var, "")
                ajout(OK if val == attendu else ATTENTION, var, val or "non défini",
                      "Relance ./installer.sh (configure le service Ollama de MacAI).")
    else:
        ajout(ECHEC, "Ollama", "injoignable", "brew services start ollama")

    # --- Autorisations macOS -----------------------------------------------------------
    if mac:
        try:
            import ApplicationServices as AS
            confiance = AS.AXIsProcessTrusted()
            ajout(OK if confiance else ATTENTION, "Accessibilité", "autorisée" if confiance else "non autorisée pour ce Terminal",
                  "Normal depuis le Terminal. L'autorisation compte pour MacAI.app : Réglages > Confidentialité > Accessibilité.")
        except ImportError:
            pass

    # --- Chrome --------------------------------------------------------------------------
    chrome_app = Path("/Applications/Google Chrome.app")
    if mac:
        ajout(OK if chrome_app.exists() else ATTENTION, "Google Chrome", "installé" if chrome_app.exists() else "absent")
        prefs = Path.home() / "Library/Application Support/Google/Chrome/Default/Preferences"
        try:
            js = json.loads(prefs.read_text(encoding="utf-8")).get("browser", {}).get("allow_javascript_apple_events")
        except (OSError, ValueError):
            js = None
        ajout(OK if js else ATTENTION, "Chrome : JavaScript depuis Apple Events", "activé" if js else "désactivé",
              "Chrome > Présentation > Options pour les développeurs > Autoriser JavaScript à partir des Apple Events")

    # --- Connecteurs -----------------------------------------------------------------------
    from . import secrets
    ajout(OK if secrets.lire("onshape") else ATTENTION, "Onshape", "clés présentes" if secrets.lire("onshape") else "non connecté",
          "macai secret onshape (facultatif)")
    if cfg.mcp:
        cache = {}
        try:
            cache = json.loads(cfg.chemin("mcp_cache.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        for s in cfg.mcp:
            n = len(cache.get(s.get("nom"), []))
            ajout(OK if n else ATTENTION, f"MCP {s.get('nom')}", f"{n} outils" if n else "jamais contacté", "macai mcp tester")
    else:
        ajout(ATTENTION, "MCP (ArtCraft…)", "aucun serveur configuré", "macai mcp detecter, puis macai.toml")

    # --- Données ----------------------------------------------------------------------------
    try:
        from .recherche.index import Index
        st = Index(cfg.chemin("index.db")).stats()
        ajout(OK if st["fichiers"] else ATTENTION, "Index de recherche", f"{st['fichiers']} fichiers, {st['taille_mo']} Mo",
              "Se remplit Mac branché et inutilisé, ou : macai indexer --force")
    except Exception as e:  # noqa: BLE001
        ajout(ECHEC, "Index de recherche", str(e))
    app = Path("/Applications/MacAI.app")
    if mac:
        ajout(OK if app.exists() else ECHEC, "MacAI.app", "installée" if app.exists() else "absente", "./installer.sh")
        try:
            infos = json.loads(cfg.chemin("serveur.json").read_text())
            rss = int(_cmd(["ps", "-o", "rss=", "-p", str(infos["pid"])]) or 0) / 1024
            ajout(OK if rss < 120 else ATTENTION, "Moteur en marche", f"{rss:.0f} Mo de RAM (pid {infos['pid']})")
        except (OSError, ValueError, KeyError):
            ajout(ATTENTION, "Moteur", "arrêté (normal si l'app n'est pas lancée)")
    return res


def essai_agent(cfg) -> tuple[str, str, str, str]:
    """Une vraie demande au modèle : vérifie qu'il sait appeler un outil."""
    from .llm.ollama import ErreurOllama, Ollama
    o = Ollama(garder="30s")
    outil = {"type": "function", "function": {"name": "regler_volume", "description": "Règle le volume (0-100)",
                                              "parameters": {"type": "object", "properties": {"niveau": {"type": "integer"}},
                                                             "required": ["niveau"]}}}
    debut = time.monotonic()
    try:
        r = o.discuter(cfg.modeles["agent"], [{"role": "user", "content": "Mets le volume à 40"}], [outil])
    except ErreurOllama as e:
        return ECHEC, "Essai de l'agent", str(e)[:150], "Vérifie le modèle agent (ollama pull)."
    duree = time.monotonic() - debut
    ok = any(a.nom == "regler_volume" and int(a.arguments.get("niveau", 0)) == 40 for a in r.appels)
    return (OK if ok else ECHEC), "Essai de l'agent", f"{'appel d’outil correct' if ok else 'pas d’appel correct'} en {duree:.1f} s", \
        "" if ok else "Essaie un autre modèle avec : macai banc"


def verifier(json_sortie: bool = False, essai: bool = True) -> int:
    res = controles()
    if essai:
        res.append(essai_agent(charger()))
    if json_sortie:
        print(json.dumps([dict(zip(("statut", "element", "detail", "solution"), r)) for r in res], ensure_ascii=False, indent=1))
    lignes = [f"MacAI — vérification du {time.strftime('%d/%m/%Y %H:%M')}", ""]
    for statut, element, detail, solution in res:
        lignes.append(f" {statut} {element:<42} {detail}")
        if statut != OK and solution:
            lignes.append(f"     → {solution}")
    echecs = sum(r[0] == ECHEC for r in res)
    attentions = sum(r[0] == ATTENTION for r in res)
    lignes += ["", f"{len(res) - echecs - attentions} OK, {attentions} à regarder, {echecs} problème(s)."]
    rapport = "\n".join(lignes)
    if not json_sortie:
        print(rapport)
    bureau = Path.home() / "Desktop"
    if bureau.is_dir():
        (bureau / "MacAI-verification.txt").write_text(rapport, encoding="utf-8")
        if not json_sortie:
            print(f"\nRapport enregistré : {bureau / 'MacAI-verification.txt'}")
    return 1 if echecs else 0
