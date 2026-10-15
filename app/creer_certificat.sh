#!/bin/bash
# Crée (une fois) un certificat local « MacAI Local » pour signer l'app. Avec une signature stable, macOS garde
# les autorisations (Accessibilité, Micro, Bureau…) d'une mise à jour à l'autre ; avec la signature ad hoc, chaque
# recompilation est vue comme une nouvelle application et les autorisations sont perdues.
# Le certificat reste dans le trousseau de session ; il ne sert qu'à signer MacAI sur ce Mac.
set -euo pipefail
NOM="MacAI Local"
if security find-certificate -c "$NOM" >/dev/null 2>&1; then
    echo "✓ Certificat « $NOM » déjà présent"
    exit 0
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
# OpenSSL de macOS (LibreSSL) : son format PKCS#12 est celui qu'accepte le trousseau.
OSSL=/usr/bin/openssl
$OSSL req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$NOM" \
    -keyout "$TMP/cle.pem" -out "$TMP/cert.pem" \
    -addext "basicConstraints=critical,CA:false" \
    -addext "keyUsage=critical,digitalSignature" \
    -addext "extendedKeyUsage=critical,codeSigning" 2>/dev/null
MDP=$($OSSL rand -hex 16)
$OSSL pkcs12 -export -inkey "$TMP/cle.pem" -in "$TMP/cert.pem" -name "$NOM" -out "$TMP/macai.p12" \
    -passout "pass:$MDP" 2>/dev/null
TROUSSEAU="$HOME/Library/Keychains/login.keychain-db"
# Clé privée utilisable par codesign seulement, sans fenêtre de confirmation.
security import "$TMP/macai.p12" -k "$TROUSSEAU" -f pkcs12 -P "$MDP" -T /usr/bin/codesign >/dev/null
echo "✓ Certificat « $NOM » créé dans le trousseau de session"
