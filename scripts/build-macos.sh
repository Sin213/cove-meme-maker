#!/usr/bin/env bash
# Build the macOS Apple-Silicon (arm64) .app bundle, ZIP and DMG for
# Cove Meme Maker.
#
# Scope: arm64 only. Not x86_64, not universal2. The app is ad-hoc signed by
# PyInstaller (required for arm64 Mach-O to run at all); it is deliberately
# NOT Developer ID signed and NOT notarized.
#
# Requirements: Python + PyInstaller, ditto, hdiutil, lipo, sips, iconutil,
# codesign (all macOS built-ins).
#
# Primary artifact:   release/Cove-Meme-Maker-<version>-macOS-arm64.zip
# Secondary artifact: release/Cove-Meme-Maker-<version>-macOS-arm64.dmg
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="cove-meme-maker"
DISPLAY_NAME="Cove Meme Maker"
SLUG="${DISPLAY_NAME// /-}"

# Canonical version lives in the package; VERSION may override it (CI does).
# Kept on one line with no heredoc: macOS ships bash 3.2, which cannot parse a
# heredoc inside $( ).
if [ -z "${VERSION:-}" ]; then
    VERSION="$(PYTHONPATH=src python -c 'import cove_meme_maker; print(cove_meme_maker.__version__)')"
fi
[ -n "$VERSION" ] || { echo "VERSION is empty"; exit 1; }

RELEASE_DIR="$ROOT/release"
DIST_DIR="$ROOT/dist"
BUILD_DIR="$ROOT/build"
ICON_SRC="$ROOT/src/cove_meme_maker/assets/cove_icon.png"

echo "==> Environment"
echo "    uname -m          : $(uname -m)"
echo "    platform.machine(): $(python -c 'import platform; print(platform.machine())')"
echo "    version           : $VERSION"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This script only runs on macOS (uname -s = $(uname -s))"
    exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
    echo "Apple Silicon required: expected uname -m = arm64, got $(uname -m)"
    exit 1
fi

mkdir -p "$RELEASE_DIR" "$BUILD_DIR"
# Clean only the macOS build outputs - never other platforms' release files.
rm -rf "$DIST_DIR" "$BUILD_DIR/dmg-staging" "$BUILD_DIR/cove.iconset" \
       "$BUILD_DIR/$APP_NAME" "$BUILD_DIR/cove_icon.icns"

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

echo "==> Running PyInstaller (macOS arm64)"
export ICON_ICNS_PATH="$ICON_ICNS"
export VERSION
python -m PyInstaller --noconfirm --clean packaging/cove-meme-maker-macos.spec

APP_BUNDLE="$DIST_DIR/$DISPLAY_NAME.app"
APP_EXE="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
[ -d "$APP_BUNDLE" ] || { echo "App bundle not found at: $APP_BUNDLE"; exit 1; }
[ -x "$APP_EXE" ] || { echo "App executable not found at: $APP_EXE"; exit 1; }

echo "==> Validating architecture"
ARCHS="$(lipo -archs "$APP_EXE")"
echo "    lipo -archs -> ${ARCHS:-<empty>}"
if [ "$ARCHS" != "arm64" ]; then
    echo "Architecture check failed: expected exactly 'arm64', got '${ARCHS:-<empty>}'"
    echo "x86_64, universal2 and fat binaries are out of scope for this release."
    exit 1
fi

# PyInstaller ad-hoc signs the bundle during assembly; do not re-sign or strip
# it here. Report the signature state for the build log only.
echo "==> Signature state (ad-hoc; not Developer ID, not notarized)"
codesign --display --verbose=2 "$APP_BUNDLE" 2>&1 | sed 's/^/    /' || true

echo "==> Building ZIP (primary artifact)"
ZIP_OUT="$RELEASE_DIR/${SLUG}-${VERSION}-macOS-arm64.zip"
rm -f "$ZIP_OUT"
# ditto preserves bundle symlinks, resource forks and extended attributes;
# a plain `zip` can corrupt the .app.
ditto -c -k --sequesterRsrc --keepParent "$APP_BUNDLE" "$ZIP_OUT"
[ -s "$ZIP_OUT" ] || { echo "ZIP missing or empty: $ZIP_OUT"; exit 1; }
if ! unzip -l "$ZIP_OUT" | grep -q "$DISPLAY_NAME.app/Contents/MacOS/$APP_NAME"; then
    echo "ZIP does not contain the app executable: $ZIP_OUT"
    unzip -l "$ZIP_OUT" | head -20
    exit 1
fi
echo "    -> $ZIP_OUT"

echo "==> Assembling DMG staging"
STAGING="$BUILD_DIR/dmg-staging"
mkdir -p "$STAGING"
ditto "$APP_BUNDLE" "$STAGING/$DISPLAY_NAME.app"
ln -s /Applications "$STAGING/Applications"

echo "==> Building DMG (secondary artifact)"
DMG_OUT="$RELEASE_DIR/${SLUG}-${VERSION}-macOS-arm64.dmg"
rm -f "$DMG_OUT"
hdiutil create \
    -volname "$DISPLAY_NAME $VERSION" \
    -srcfolder "$STAGING" \
    -ov \
    -format UDZO \
    "$DMG_OUT"
[ -s "$DMG_OUT" ] || { echo "DMG missing or empty: $DMG_OUT"; exit 1; }
echo "    -> $DMG_OUT"

echo ""
echo "App bundle:  $APP_BUNDLE"
echo "Executable:  $APP_EXE"
echo "Release artifacts in $RELEASE_DIR:"
ls -lh "$RELEASE_DIR"
