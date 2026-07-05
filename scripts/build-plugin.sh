#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_NAME="BazaarPlusPlus"
STAGE="$ROOT/out/$PACKAGE_NAME"
VERSION="$(node -p "JSON.parse(require('fs').readFileSync('$ROOT/package.json', 'utf8')).version")"

cd "$ROOT"
pnpm run check
pnpm run test
pnpm run build

rm -rf "$ROOT/out"
mkdir -p "$STAGE/dist"
cp "$ROOT/dist/index.js" "$STAGE/dist/index.js"
cp "$ROOT/main.py" "$ROOT/package.json" "$ROOT/plugin.json" "$ROOT/LICENSE" "$ROOT/README.md" "$STAGE/"

cd "$ROOT/out"
zip -qr "BazaarPlusPlus-${VERSION}.zip" "$PACKAGE_NAME"
echo "Created $ROOT/out/BazaarPlusPlus-${VERSION}.zip"
