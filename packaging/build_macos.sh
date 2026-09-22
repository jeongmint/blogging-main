#!/usr/bin/env bash
# macOS 데스크톱 앱 빌드 — PyInstaller(onedir) + Playwright Chromium 직접 복사.
#
# Chromium을 PyInstaller datas로 넣으면 .app 서명을 망가뜨려 빌드가 깨진다(검증됨).
# 그래서 PyInstaller로는 앱 골격만 만들고, 브라우저는 cp -R로 _internal에 복사한다.
#
# 사용: packaging/build_macos.sh
set -euo pipefail

cd "$(dirname "$0")/.."   # repo 루트
VENV="${VENV:-.venv}"
CHROMIUM_VER="${CHROMIUM_VER:-1223}"
CACHE="$HOME/Library/Caches/ms-playwright"
INTERNAL="dist/autoblog/_internal"

echo "▸ 1/3 PyInstaller 빌드(앱 골격, chromium 제외)…"
rm -rf build dist
"$VENV/bin/pyinstaller" packaging/autoblog.spec --noconfirm --distpath dist --workpath build >/dev/null

echo "▸ 2/3 Chromium 복사(.app 구조 보존)…"
mkdir -p "$INTERNAL/ms-playwright"
for name in "chromium-$CHROMIUM_VER" "chromium_headless_shell-$CHROMIUM_VER"; do
  src="$CACHE/$name"
  [ -d "$src" ] || { echo "  ✗ 브라우저 없음: $src (먼저 'playwright install chromium')"; exit 1; }
  cp -R "$src" "$INTERNAL/ms-playwright/$name"
  echo "  ✓ $name"
done

echo "▸ 3/3 셀프테스트(경로 + chromium 기동)…"
./dist/autoblog/autoblog --selftest

echo "✅ 완료 → dist/autoblog/  (크기: $(du -sh dist/autoblog | cut -f1))"
