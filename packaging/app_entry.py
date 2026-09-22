"""데스크톱 앱 엔트리 — 더블클릭 시 로컬 UI 서버 기동 + 브라우저 자동 오픈.

PyInstaller로 묶이면 sys.frozen=True. 이 스크립트가 패키징 런타임을 준비한다:
  1) Playwright 브라우저 경로(PLAYWRIGHT_BROWSERS_PATH)를 번들 chromium으로 지정
  2) 번들 기본 설정(format/stickers.yaml)을 유저 설정 폴더로 시딩(없을 때만)
  3) UI 서버 기동(autoblog.webui.serve_ui) + 브라우저 열기

  --selftest        : 경로/크로미엄 기동만 점검하고 종료(빌드 검증용)
  --no-open-browser : 브라우저 자동 오픈 끔
"""

from __future__ import annotations

import os
import shutil
import sys
import webbrowser
from pathlib import Path


def _bundle_dir() -> Path:
    # frozen: PyInstaller 추출 폴더(_MEIPASS). dev: repo 루트.
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def _setup_browsers_path() -> None:
    """Playwright가 쓸 브라우저 경로 지정. playwright import 전에 호출돼야 함."""
    if not getattr(sys, "frozen", False):
        return
    bundled = _bundle_dir() / "ms-playwright"
    if bundled.exists() and any(bundled.glob("chromium-*")):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
    else:
        # 번들 chromium이 아직 없을 때(Chromium 미포함 빌드) — 유저 폴더로 폴백.
        from autoblog.config import USER_DATA_DIR

        os.environ.setdefault(
            "PLAYWRIGHT_BROWSERS_PATH", str(USER_DATA_DIR / "ms-playwright")
        )


def _seed_user_config() -> None:
    """쓰기 가능한 기본 설정을 유저 폴더로 시딩 + 데이터 폴더 생성."""
    from autoblog.config import CONFIG_DIR, DATA_DIR, USER_CONFIG_DIR

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("format.yaml", "stickers.yaml"):
        src, dst = CONFIG_DIR / name, USER_CONFIG_DIR / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)


def _selftest() -> int:
    """빌드 검증: 경로가 잡히고 번들 chromium이 실제로 뜨는지."""
    from autoblog.config import CONFIG_DIR, DATA_DIR, USER_CONFIG_DIR

    print("frozen           =", getattr(sys, "frozen", False))
    print("CONFIG_DIR       =", CONFIG_DIR, "(exists)" if CONFIG_DIR.exists() else "(MISSING)")
    print("DATA_DIR         =", DATA_DIR)
    print("USER_CONFIG_DIR  =", USER_CONFIG_DIR)
    print("BROWSERS_PATH    =", os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("about:blank")
            print("chromium launch  = OK ->", p.chromium.executable_path)
            browser.close()
    except Exception as e:  # noqa: BLE001
        print("chromium launch  = FAIL ->", repr(e))
        return 1
    return 0


def main() -> None:
    _setup_browsers_path()
    _seed_user_config()

    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    from autoblog.webui import serve_ui

    server = None
    port = 8770
    for p in range(8770, 8780):
        try:
            server = serve_ui(port=p)
            port = p
            break
        except OSError:
            continue
    if server is None:
        print("빈 포트를 찾지 못했습니다.")
        return

    url = f"http://127.0.0.1:{port}/"
    print(f"글쓰기 UI 열림 → {url}  (종료: Ctrl+C)")
    if "--no-open-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료.")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
