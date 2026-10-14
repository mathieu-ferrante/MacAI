#!/bin/bash
# Désinstalle MacAI. Les données (mémoire, index, compétences) et les modèles ne sont supprimés que si tu le confirmes.
set -uo pipefail
DONNEES="$HOME/Library/Application Support/MacAI"

pgrep -xq MacAI && osascript -e 'tell application "MacAI" to quit' >/dev/null 2>&1
pkill -f "macai serveur" >/dev/null 2>&1
launchctl bootout "gui/$(id -u)/fr.mathieu.macai.ollama" >/dev/null 2>&1
rm -f "$HOME/Library/LaunchAgents/fr.mathieu.macai.ollama.plist"
rm -rf /Applications/MacAI.app
rm -f "$(brew --prefix 2>/dev/null || echo /opt/homebrew)/bin/macai"
echo "✓ Application, service Ollama de MacAI et commande macai retirés."

read -r -p "Supprimer aussi tes données MacAI (mémoire, index, compétences, réglages) ? [o/N] " r
if [[ "$r" =~ ^[oOyY] ]]; then
    rm -rf "$DONNEES"
    security delete-generic-password -s MacAI-memoire >/dev/null 2>&1
    security delete-generic-password -s MacAI-onshape >/dev/null 2>&1
    echo "✓ Données et clés du Trousseau supprimées."
fi
read -r -p "Supprimer les modèles d'IA téléchargés (~5 Go) ? [o/N] " r
if [[ "$r" =~ ^[oOyY] ]]; then
    for m in qwen3:4b qwen3-vl:2b qwen3-embedding:0.6b; do ollama rm "$m" >/dev/null 2>&1; done
    echo "✓ Modèles supprimés."
fi
