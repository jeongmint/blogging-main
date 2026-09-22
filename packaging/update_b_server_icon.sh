#!/bin/zsh
set -euo pipefail

PACKAGING_DIR="${0:A:h}"
APP_DIR="/Users/user/Desktop/b-server.app"
INFO_PLIST="$APP_DIR/Contents/Info.plist"
PNG_FILE="$PACKAGING_DIR/b-server-icon.png"
ICNS_FILE="$PACKAGING_DIR/b-server-icon.icns"
WORK_DIR="$(mktemp -d)"
ICONSET_DIR="$WORK_DIR/b-server.iconset"

trap 'rm -rf "$WORK_DIR"' EXIT

if [[ ! -d "$APP_DIR" ]]; then
  print -u2 "b-server.app을 찾을 수 없습니다: $APP_DIR"
  exit 1
fi

mkdir -p "$ICONSET_DIR"
swift "$PACKAGING_DIR/generate_b_server_icon.swift" "$PNG_FILE"

sips -z 16 16 "$PNG_FILE" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -z 32 32 "$PNG_FILE" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$PNG_FILE" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -z 64 64 "$PNG_FILE" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$PNG_FILE" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -z 256 256 "$PNG_FILE" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$PNG_FILE" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -z 512 512 "$PNG_FILE" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$PNG_FILE" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$PNG_FILE" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET_DIR" -o "$ICNS_FILE"

cp "$ICNS_FILE" "$APP_DIR/Contents/Resources/applet.icns"
plutil -replace CFBundleIconFile -string "applet.icns" "$INFO_PLIST"
if plutil -extract CFBundleIconName raw "$INFO_PLIST" >/dev/null 2>&1; then
  plutil -remove CFBundleIconName "$INFO_PLIST"
fi
if plutil -extract CFBundleVersion raw "$INFO_PLIST" >/dev/null 2>&1; then
  plutil -replace CFBundleVersion -string "2" "$INFO_PLIST"
else
  plutil -insert CFBundleVersion -string "2" "$INFO_PLIST"
fi
codesign --force --deep --sign - "$APP_DIR"
touch "$APP_DIR"
