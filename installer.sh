#!/bin/bash
# MacAI — installation complète en une commande :   ./installer.sh
# Relançable sans risque (sert aussi à mettre à jour après un `git pull`).
set -euo pipefail
cd "$(dirname "$0")"
RACINE="$(pwd)"
DONNEES="$HOME/Library/Application Support/MacAI"
VENV="$DONNEES/venv"
AGENT_OLLAMA="$HOME/Library/LaunchAgents/fr.mathieu.macai.ollama.plist"

titre() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }
ok() { printf "  \033[32m✓\033[0m %s\n" "$1"; }
info() { printf "  → %s\n" "$1"; }

# --- 0. Vérifications ------------------------------------------------------------------
titre "Vérifications"
[ "$(uname)" = "Darwin" ] || { echo "MacAI s'installe sur macOS."; exit 1; }
[ "$(uname -m)" = "arm64" ] || echo "  ! Mac Intel détecté : prévu pour Apple Silicon, ce sera lent."
ok "macOS $(sw_vers -productVersion), $(sysctl -n machdep.cpu.brand_string)"
if ! xcode-select -p >/dev/null 2>&1; then
    info "Installation des outils de développement Apple (une fenêtre va s'ouvrir)…"
    xcode-select --install || true
    echo "Relance ./installer.sh une fois l'installation terminée."
    exit 1
fi
ok "Outils de développement Apple"

# --- 1. Homebrew, Ollama, uv ------------------------------------------------------------------
titre "Logiciels"
if ! command -v brew >/dev/null 2>&1; then
    [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
fi
if ! command -v brew >/dev/null 2>&1; then
    info "Installation de Homebrew (ton mot de passe de session sera demandé)…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi
ok "Homebrew"
for paquet in ollama uv; do
    if ! brew list "$paquet" >/dev/null 2>&1; then
        info "brew install $paquet"
        brew install "$paquet"
    fi
    ok "$paquet"
done
OLLAMA_BIN="$(brew --prefix)/bin/ollama"

# --- 2. Ollama réglé pour 8 Go -----------------------------------------------------------------
titre "Ollama (réglé pour 8 Go de RAM)"
if pgrep -xq "Ollama" 2>/dev/null; then
    echo "  ! L'application Ollama.app est ouverte : quitte-la (elle entrerait en conflit avec le service MacAI)."
    osascript -e 'tell application "Ollama" to quit' >/dev/null 2>&1 || true
    sleep 2
fi
brew services stop ollama >/dev/null 2>&1 || true
mkdir -p "$HOME/Library/LaunchAgents" "$DONNEES"
cat > "$AGENT_OLLAMA" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>fr.mathieu.macai.ollama</string>
    <key>ProgramArguments</key><array><string>${OLLAMA_BIN}</string><string>serve</string></array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_HOST</key><string>127.0.0.1:11434</string>
        <key>OLLAMA_KEEP_ALIVE</key><string>2m</string>
        <key>OLLAMA_MAX_LOADED_MODELS</key><string>2</string>
        <key>OLLAMA_NUM_PARALLEL</key><string>1</string>
        <key>OLLAMA_FLASH_ATTENTION</key><string>1</string>
        <key>OLLAMA_KV_CACHE_TYPE</key><string>q8_0</string>
        <key>OLLAMA_NOPRUNE</key><string>1</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Interactive</string>
    <key>StandardErrorPath</key><string>${DONNEES}/ollama.log</string>
    <key>StandardOutPath</key><string>${DONNEES}/ollama.log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/fr.mathieu.macai.ollama" >/dev/null 2>&1 || true
for _ in 1 2 3 4 5; do   # bootout est asynchrone : on réessaie
    launchctl bootstrap "gui/$(id -u)" "$AGENT_OLLAMA" 2>/dev/null && break
    sleep 1
done
launchctl print "gui/$(id -u)/fr.mathieu.macai.ollama" >/dev/null
for _ in $(seq 1 30); do curl -sf http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
curl -sf http://127.0.0.1:11434/api/version >/dev/null || { echo "Ollama ne démarre pas : voir $DONNEES/ollama.log"; exit 1; }
ok "Ollama démarré (modèles déchargés après 2 min, cache réduit, un seul calcul à la fois)"

# --- 3. Modèles locaux ---------------------------------------------------------------------------
titre "Modèles d'IA locaux (~4 Go à télécharger la première fois)"
MODELES="qwen3.5:4b-q4_K_M qwen3-embedding:0.6b"
if [ -f "$DONNEES/macai.toml" ]; then  # modèles personnalisés (bash 3.2 de macOS : pas de mapfile)
    PERSO=$(sed -nE 's/^(agent|vision|embeddings) *= *"([^"]+)".*/\2/p' "$DONNEES/macai.toml" | sort -u | tr '\n' ' ')
    if [ -n "$(echo "$PERSO" | tr -d ' ')" ]; then MODELES="$PERSO"; fi
fi
for m in $MODELES; do
    info "ollama pull $m"
    "$OLLAMA_BIN" pull "$m"
done
ok "Modèles prêts"

# --- 4. Moteur Python ---------------------------------------------------------------------------
titre "Moteur MacAI (Python 3.12)"
uv venv --quiet --allow-existing --python 3.12 "$VENV"
# Installation éditable : après un `git pull`, relancer ce script suffit à mettre le moteur à jour.
uv pip install --quiet --python "$VENV/bin/python" -e "${RACINE}[tout]"
cat > "$DONNEES/lancement.json" <<JSON
{"python": "$VENV/bin/python", "source": "$RACINE"}
JSON
ln -sf "$VENV/bin/macai" "$(brew --prefix)/bin/macai"
"$VENV/bin/macai" outils >/dev/null   # crée macai.toml au premier lancement
ok "Moteur installé — commande \`macai\` disponible dans le Terminal"

# --- 5. Application ----------------------------------------------------------------------------
titre "Application MacAI"
if pgrep -xq "MacAI" 2>/dev/null; then osascript -e 'tell application "MacAI" to quit' >/dev/null 2>&1 || true; sleep 1; fi
pkill -f "macai serveur" >/dev/null 2>&1 || true
./app/creer_certificat.sh || echo "  ! Certificat local non créé : les autorisations seront à redonner après chaque mise à jour"
./app/construire.sh
rm -rf /Applications/MacAI.app
cp -R app/build/MacAI.app /Applications/
ok "/Applications/MacAI.app"
open /Applications/MacAI.app

# --- 6. Vérification -------------------------------------------------------------------------------
titre "Vérification"
sleep 3
"$VENV/bin/macai" verifier || true

cat <<'FIN'

========================================================================
 MacAI est installé. Dernières étapes (une seule fois) :

 1. Autorise MacAI quand macOS le demande : Accessibilité, Enregistrement
    de l'écran, Micro, Automatisation (Chrome, Finder, Rappels…).
    Réglages Système > Confidentialité et sécurité, si tu as refusé.
 2. Touche Fn pour parler : Réglages Système > Clavier >
    « Appuyer sur la touche 🌐 pour » : Ne rien faire.
 3. Chrome : menu Présentation > Options pour les développeurs >
    « Autoriser JavaScript à partir des Apple Events ».
 4. Après avoir accordé l'Accessibilité : menu 🧠 > Quitter, puis rouvre MacAI.
 5. Facultatif : `macai secret onshape` (clés API Onshape)
                 `macai mcp detecter`   (suite ArtCraft)

 Utilisation : Option + Espace pour écrire ; Option + Maj + Espace maintenus
 (ou Fn maintenue) pour parler.
 La recherche dans tes fichiers se construit Mac branché et inutilisé
 (ou tout de suite : menu 🧠 > Indexer mes fichiers maintenant).
========================================================================
FIN
