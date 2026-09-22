# PyInstaller spec — autoblog 데스크톱 앱 (onedir)
#   빌드: packaging/build_macos.sh  (pyinstaller + chromium 복사를 함께 처리)
#
# Chromium은 여기서 번들하지 않는다. PyInstaller가 chromium .app 안의 서명된 Chrome
# 바이너리를 "처리(재서명)"하려다 깨뜨리기 때문. 대신 빌드 후 build_macos.sh가
# `cp -R`로 _internal/ms-playwright/ 에 직접 복사해 .app 구조·서명을 보존한다.
# 크로스컴파일 불가 → 윈도우는 윈도우에서 빌드.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # packaging/ 의 부모 = repo 루트

# Playwright 파이썬 패키지 전체(node 드라이버 포함) 수집
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")

datas = [(str(ROOT / "config"), "config")] + pw_datas

hiddenimports = (
    pw_hidden
    + collect_submodules("autoblog")
    + collect_submodules("anthropic")
    + collect_submodules("google")
    + ["openai", "yaml", "dotenv", "bs4", "lxml", "PIL"]
)

a = Analysis(
    [str(ROOT / "packaging" / "app_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=pw_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["watchfiles", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="autoblog",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 초기엔 콘솔로 로그 확인. 배포판은 windowed로.
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="autoblog",
)
