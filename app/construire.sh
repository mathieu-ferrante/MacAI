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

# Signature : identité « Apple Development » si Xcode est connecté à un identifiant Apple (les autorisations
# macOS survivent alors aux mises à jour) ; sinon signature locale (autorisations à redonner après chaque
# recompilation).
IDENTITE=$(security find-identity -v -p codesigning 2>/dev/null | grep -m1 "Apple Development" | sed -E 's/.*"(.*)"/\1/' || true)
if [ -n "${IDENTITE}" ]; then
    echo "→ Signature avec : ${IDENTITE}"
    codesign --force --deep --sign "${IDENTITE}" "$APP"
else
    echo "→ Signature locale (ad hoc)"
    codesign --force --deep --sign - "$APP"
fi
echo "✓ $APP prête"
