#!/usr/bin/env bash
# Build macOS .app bundle and .dmg for Cove Meme Maker.
#
# Requirements: Python + PyInstaller, hdiutil, sips, iconutil (all macOS built-ins)
#
# Output lands in release/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="cove-meme-maker"
DISPLAY_NAME="Cove Meme Maker"
VERSION="${VERSION:-2.2.0}"
RELEASE_DIR="$ROOT/release"
DIST_DIR="$ROOT/dist"
BUILD_DIR="$ROOT/build"
ICON_SRC="$ROOT/src/cove_meme_maker/assets/cove_icon.png"

mkdir -p "$RELEASE_DIR" "$BUILD_DIR"
rm -rf "$DIST_DIR" "$BUILD_DIR/AppDir" "$BUILD_DIR/dmg-staging" "$BUILD_DIR/cove.iconset"

echo "==> Converting icon to .icns"
ICONSET="$BUILD_DIR/cove.iconset"
mkdir -p "$ICONSET"
for size in 16 32 64 128 256 512; do
    sips -z $size $size "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z $double $double "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
ICON_ICNS="$BUILD_DIR/cove_icon.icns"
iconutil -c icns "$ICONSET" -o "$ICON_ICNS"

echo "==> Running PyInstaller (macOS)"
export ICON_ICNS_PATH="$ICON_ICNS"
python -m PyInstaller --noconfirm --clean packaging/cove-meme-maker-macos.spec

APP_BUNDLE="$DIST_DIR/Cove Meme Maker.app"
[ -d "$APP_BUNDLE" ] || { echo "App bundle not found at: $APP_BUNDLE"; exit 1; }

echo "==> Ad-hoc signing .app"
codesign --force --deep --sign - "$APP_BUNDLE"

echo "==> Assembling DMG staging"
STAGING="$BUILD_DIR/dmg-staging"
mkdir -p "$STAGING"
cp -r "$APP_BUNDLE" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

DMG_OUT="$RELEASE_DIR/${DISPLAY_NAME// /-}-${VERSION}-macOS.dmg"

echo "==> Building DMG"
hdiutil create \
    -volname "$DISPLAY_NAME $VERSION" \
    -srcfolder "$STAGING" \
    -ov \
    -format UDZO \
    "$DMG_OUT"

echo "    -> $DMG_OUT"
echo ""
echo "Release artifacts in $RELEASE_DIR:"
ls -lh "$RELEASE_DIR"
