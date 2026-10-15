#!/bin/bash
# Compile l'app Swift et assemble MacAI.app dans app/build/.
set -euo pipefail
cd "$(dirname "$0")"

echo "→ Compilation de l'app (Swift, release)…"
swift build -c release --arch arm64

APP="build/MacAI.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$(swift build -c release --arch arm64 --show-bin-path)/MacAI" "$APP/Contents/MacOS/MacAI"
cp Ressources/Info.plist "$APP/Contents/Info.plist"
[ -f Ressources/MacAI.icns ] && cp Ressources/MacAI.icns "$APP/Contents/Resources/" || true

# Signature : identité « Apple Development » si Xcode est connecté à un identifiant Apple, sinon certificat local
# « MacAI Local » (app/creer_certificat.sh). Une signature stable garde les autorisations macOS d'une mise à jour
# à l'autre ; en dernier recours, signature ad hoc (autorisations à redonner après chaque recompilation).
IDENTITE=$(security find-identity -v -p codesigning 2>/dev/null | grep -m1 "Apple Development" | sed -E 's/.*"(.*)"/\1/' || true)
if [ -z "${IDENTITE}" ] && security find-certificate -c "MacAI Local" >/dev/null 2>&1; then
    IDENTITE="MacAI Local"
fi
if [ -n "${IDENTITE}" ]; then
    echo "→ Signature avec : ${IDENTITE}"
    codesign --force --deep --sign "${IDENTITE}" "$APP"
else
    echo "→ Signature locale (ad hoc) : lance app/creer_certificat.sh pour garder les autorisations"
    codesign --force --deep --sign - "$APP"
fi
echo "✓ $APP prête"
