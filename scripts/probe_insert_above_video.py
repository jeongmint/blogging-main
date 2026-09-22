"""'영상 앵커' 설계의 전제 검증: 영상 컴포넌트 '위'에 콘텐츠를 끼워넣을 수 있는가?

아이디어(유저): 영상은 재업로드가 안 되니 고정 앵커로 두고, 사진(다운로드→재삽입 가능)과
글을 영상 앞/뒤에 배치 → LLM이 영상 위치를 자유롭게 잡음. 이게 되려면 영상이 맨 위에 있을 때
'영상 위'에 텍스트/사진을 넣을 수 있어야 한다. 그 가능 여부를 라이브로 확인한다.

여러 방법을 순서대로 시도하고, 마커가 영상 컴포넌트 '앞'에 들어갔는지 본다:
  (M1) 영상의 top edge-button(se-component-edge-button-top) 클릭 → 타이핑
  (M2) 영상 선택 → Enter는 '뒤'였으니, 위는 ArrowUp/Home 등으로 시도
  (M3) 문서 맨 앞(제목 다음)에 커서를 두고 타이핑

실행: .venv/bin/python scripts/probe_insert_above_video.py [draft_idx]
비파괴: 임시저장 안 누름.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

MARKER = "★ABOVE_VIDEO★"

# 컴포넌트 순서를 [kind, txt]로. 영상/텍스트/사진 구분 + 마커 위치 확인용.
_ORDER_JS = r"""
() => [...document.querySelectorAll('.se-component')].map((c,i) => {
  const cls = c.className.toString();
  let kind = 'other';
  if (/se-video/.test(cls)) kind = 'video';
  else if (/se-image/.test(cls)) kind = 'image';
  else if (/se-documentTitle/.test(cls)) kind = 'title';
  else if (/se-text/.test(cls)) kind = 'text';
  return {i, kind, txt: (c.innerText||'').trim().replace(/\s+/g,' ').slice(0,30)};
})
"""


def load_draft(pub, idx: int) -> bool:
    page = pub._page
    pub._open_draft_list()
    buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
    if not buttons or idx >= len(buttons):
        print(f"[probe] 임시저장 {idx}번 없음(총 {len(buttons)}건)")
        return False
    buttons[idx].click()
    page.wait_for_timeout(1500)
    confirm = page.query_selector(SMART_EDITOR["draft_load_confirm"])
    if confirm and confirm.is_visible():
        confirm.click()
    page.wait_for_timeout(1500)
    return True


def dump(page, label):
    rows = page.evaluate(_ORDER_JS)
    print(f"\n--- {label} ---")
    for r in rows[:8]:
        m = "  <== 마커" if MARKER in (r["txt"] or "") else ""
        print(f"  [{r['i']:>2}] {r['kind']:<6} {r['txt']!r}{m}")
    return rows


def video_index(rows):
    for r in rows:
        if r["kind"] == "video":
            return r["i"]
    return None


def marker_before_video(page) -> bool:
    rows = page.evaluate(_ORDER_JS)
    vi = video_index(rows)
    mi = next((r["i"] for r in rows if MARKER in (r["txt"] or "")), None)
    return vi is not None and mi is not None and mi < vi


def main() -> int:
    draft_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 직접 로그인(최대 6분)…")
            if not pub.wait_for_login():
                return 1
        pub.open_write_page()
        page = pub._page
        print(f"[probe] 임시저장 {draft_idx}번 불러오는 중…")
        if not load_draft(pub, draft_idx):
            return 1

        rows = dump(page, "BEFORE")
        vi = video_index(rows)
        if vi is None:
            print("\n[probe] 이 글엔 영상이 없음 — 영상 있는 draft_idx로 시도하세요.")
            return _hold(1)
        print(f"\n[probe] 영상 컴포넌트 위치: comp[{vi}]")

        video_el = page.query_selector_all(".se-component.se-video")[0]
        video_el.scroll_into_view_if_needed()
        page.wait_for_timeout(300)

        # (M1) 영상 top edge-button 클릭 → 타이핑
        print("\n[probe] (M1) 영상 top edge-button 클릭 → 타이핑…")
        try:
            edge = video_el.query_selector("button.se-component-edge-button-top")
            if edge:
                edge.click()
                page.wait_for_timeout(400)
                page.keyboard.type(f"{MARKER} 영상 위 줄", delay=8)
                page.wait_for_timeout(500)
                if marker_before_video(page):
                    dump(page, "AFTER M1")
                    print("  ✅ M1 성공: 마커가 영상 '앞'에 들어감 — 영상 위 삽입 가능. 앵커 설계 성립.")
                    return _hold(0)
                print("     M1: 마커가 영상 앞에 안 들어감(또는 사라짐).")
        except Exception as e:  # noqa: BLE001
            print(f"     M1 예외: {e}")

        # (M2) 영상 선택 → ArrowUp/Home 후 타이핑
        print("\n[probe] (M2) 영상 선택 → ArrowUp → 타이핑…")
        try:
            video_el.click()
            page.wait_for_timeout(300)
            page.keyboard.press("ArrowUp")
            page.wait_for_timeout(300)
            page.keyboard.type(f"{MARKER} 영상 위 줄", delay=8)
            page.wait_for_timeout(500)
            if marker_before_video(page):
                dump(page, "AFTER M2")
                print("  ✅ M2 성공: 영상 위 삽입 가능(ArrowUp). 앵커 설계 성립.")
                return _hold(0)
            print("     M2: 영상 앞에 안 들어감.")
        except Exception as e:  # noqa: BLE001
            print(f"     M2 예외: {e}")

        # (M3) 문서 맨 앞에 커서 두고 타이핑(제목 영역 클릭 후 아래로)
        print("\n[probe] (M3) 제목 클릭 → ArrowDown → 타이핑(문서 본문 첫 위치)…")
        try:
            page.click(SMART_EDITOR["title_component"])
            page.wait_for_timeout(200)
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(200)
            page.keyboard.type(f"{MARKER} 영상 위 줄", delay=8)
            page.wait_for_timeout(500)
            if marker_before_video(page):
                dump(page, "AFTER M3")
                print("  ✅ M3 성공: 문서 맨 앞 삽입 가능. 앵커 설계 성립.")
                return _hold(0)
            print("     M3: 영상 앞에 안 들어감.")
        except Exception as e:  # noqa: BLE001
            print(f"     M3 예외: {e}")

        dump(page, "최종 상태")
        print("\n===== 판정 =====")
        print("  ❌ 세 방법 모두 영상 '위'에 삽입 실패 — 영상이 맨 위면 그 위로 콘텐츠를 못 올릴 수 있음.")
        print("     → 영상 위치 자유 배치에 제약. (영상을 아래로 못 내림). 추가 방법 검토 필요.")
        return _hold(0)
    finally:
        pub.close(save_session=False)


def _hold(code: int) -> int:
    if sys.stdin.isatty():
        try:
            input("\n[probe] Enter 로 닫기…")
        except EOFError:
            pass
    else:
        print("\n[probe] (비대화형 — 자동 종료)")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
