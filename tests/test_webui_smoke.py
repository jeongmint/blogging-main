"""웹 UI 스모크 테스트 — 실제 브라우저(Playwright)로 핵심 흐름이 깨지지 않는지 확인.

webui.py는 서버+HTML+JS가 한 파일이고 전역 상태를 통째로 재렌더하는 구조라,
한 곳을 고치면 다른 흐름이 조용히 깨지는 회귀가 반복됐다(흰 화면류 포함).
여기 테스트는 그 회귀를 커밋 전에 잡는 최소 안전망이다:
  · 부팅 시 JS 에러 0건            · 사진 타일 실제 로드(흰/깨진 타일 감지)
  · 클릭 분류 흐름                 · 탭 전환 시 상태 보존
  · 프런트 에러 → 서버 로그 수집

실행: uv run pytest tests/test_webui_smoke.py
"""

import threading

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

import autoblog.webui as webui  # noqa: E402


@pytest.fixture(scope="module")
def ui_url(tmp_path_factory):
    """격리 데이터로 UI 서버를 임시 포트에 띄운다(유저 사진·설정 절대 안 건드림)."""
    from PIL import Image

    root = tmp_path_factory.mktemp("ui")
    photos, uploads, cfg = root / "photos", root / "uploads", root / "cfg"
    for d in (photos, uploads, cfg):
        d.mkdir()
    for i, color in enumerate(["#c0392b", "#27ae60", "#2980b9"]):
        Image.new("RGB", (64, 64), color).save(photos / f"p{i}.jpg")
    (photos / "clip.mp4").write_bytes(b"")  # 영상 타일은 플레이스홀더 썸네일

    saved = {k: getattr(webui, k) for k in ("PHOTO_DIR", "UPLOAD_DIR", "PREFS_PATH", "FORMAT_CONFIG_PATH")}
    webui.PHOTO_DIR, webui.UPLOAD_DIR = photos, uploads
    webui.PREFS_PATH, webui.FORMAT_CONFIG_PATH = cfg / "prefs.json", cfg / "format.yaml"
    # 최초 1회 '임시저장 자동 정리' 안내 카드가 화면을 덮어 클릭을 막으므로 이미 답한 상태로 시드
    webui.PREFS_PATH.write_text('{"pruneDraftsAsked": true}')
    server = webui.serve_ui(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    for k, v in saved.items():
        setattr(webui, k, v)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(browser, ui_url):
    """빈 프로필로 페이지 로드. 테스트 중 JS 에러가 하나라도 나면 실패."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    # networkidle 금지 — 부팅 시 외부 조회(순위 추적 등)가 오래 걸려 타임아웃 난다.
    pg.goto(ui_url, wait_until="domcontentloaded")
    pg.wait_for_selector("#workbar .wtab")
    yield pg
    # smokeTestBoom은 에러 수집 테스트가 일부러 낸 에러라 제외
    real = [e for e in errors if "smokeTestBoom" not in e]
    assert real == [], f"JS 에러 발생: {real}"
    ctx.close()


def test_boot(page):
    """부팅: 핵심 요소가 있고 JS 에러가 없다."""
    for sel in ("#memo", "#photobtn", "#preview", "#workbar .wtab"):
        assert page.locator(sel).count() > 0, f"{sel} 없음"


def test_photo_tiles_load(page):
    """사진 모달: 타일 전 장이 실제 픽셀로 로드된다(흰/깨진 타일 회귀 감지)."""
    page.click("#photobtn")
    page.wait_for_selector("#pgrid .pcell img")
    page.wait_for_function(
        "[...document.querySelectorAll('#pgrid img')].every(i=>i.complete)"
    )
    states = page.evaluate(
        "[...document.querySelectorAll('#pgrid img')].map(i=>i.naturalWidth>0)"
    )
    assert len(states) == 4 and all(states), f"타일 로드 실패: {states}"
    assert page.locator("#pgrid .vidbadge").count() == 1  # 영상 1개는 ▶ 배지


def test_click_classify(page):
    """분류: 활성 칸이 있는 기본 상태에서 타일 클릭 → 즉시 담김 → 요약 카운트 갱신."""
    page.click("#photobtn")
    page.wait_for_selector("#pgrid .pcell")
    assert page.locator("#pmeta .pmlane.active").count() == 1  # 기본 활성 칸
    page.click("#pgrid .pcell")  # 클릭 = 활성 칸에 담기
    assert page.evaluate("SELP.length") == 1
    assert page.locator("#pmeta .pmlane img").count() == 1  # 칸 안에 타일 생김
    assert "1장 선택됨" in page.text_content("#photosum")


def test_tab_state_roundtrip(page):
    """탭: 새 탭에서 비고 다시 돌아오면 메모·상태가 보존된다."""
    page.fill("#memo", "테스트 메모 첫 줄")
    page.click("#workbar .wadd")
    assert page.input_value("#memo") == ""
    page.click("#workbar .wtab")  # 첫 탭으로 복귀
    assert page.input_value("#memo") == "테스트 메모 첫 줄"


def test_client_error_reaches_server_log(page, capfd):
    """프런트 JS 에러가 서버 로그로 수집된다(하얀 화면 사후 추적용)."""
    page.evaluate("setTimeout(()=>{ smokeTestBoom(); }, 0)")
    page.wait_for_timeout(500)
    out = capfd.readouterr().out
    assert "프런트 에러" in out and "smokeTestBoom" in out  # 스택까지 남는다
