"""SE-ONE 사진 재배치 C안 3차: 올바른 Locator.drag_to + hover 드래그핸들 탐색 + 핸들 포인터드래그.

확인됨: SE는 네이티브 HTML5 DnD 미사용(draggable 요소 0). hover 시 뜨는 전용 핸들을
포인터로 끄는 방식으로 추정. 세 갈래 시도:
  (1) page.locator(...).nth(src).drag_to(nth(dst))  ← 올바른 API
  (2) 소스 컴포넌트 hover → 새로 보이는 드래그핸들 후보 덤프
  (3) 그 핸들을 잡고 포인터(mouse) 드래그
각 시도 후 compid 순서 변화를 본다.

실행: .venv/bin/python scripts/probe_drag_reorder3.py [draft_idx] [src_img] [dst_img]
비파괴: 임시저장 안 누름.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

_IMG_COMPIDS_JS = "() => [...document.querySelectorAll('.se-component.se-image')].map(c => c.getAttribute('data-compid')||'(no-id)')"

# hover 직후, 화면에 보이는 드래그/핸들 후보 전부 덤프(문서 전역 — 핸들이 플로팅일 수 있음).
_HANDLE_JS = r"""
() => {
  const out = [];
  const want = /(drag|handle|grip|move|reorder|sort)/i;
  for (const el of document.querySelectorAll('*')) {
    const cls = (el.className && el.className.toString) ? el.className.toString() : '';
    if (!want.test(cls)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    out.push({tag: el.tagName.toLowerCase(), cls: cls.slice(0,90),
              x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)});
  }
  return out;
}
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


def order(page):
    return [c[-6:] for c in page.evaluate(_IMG_COMPIDS_JS)]


def main() -> int:
    draft_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    src_i = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    dst_i = int(sys.argv[3]) if len(sys.argv) > 3 else 0

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

        base = order(page)
        print(f"\n[probe] 사진 {len(base)}장. BEFORE: {base}")
        if max(src_i, dst_i) >= len(base):
            print("[probe] 인덱스 범위 초과")
            return 1

        loc = page.locator(".se-component.se-image")
        comps = page.query_selector_all(".se-component.se-image")
        comps[min(src_i, dst_i)].scroll_into_view_if_needed()
        page.wait_for_timeout(400)

        # --- (1) 올바른 Locator.drag_to ---
        print("\n[probe] (1) Locator.drag_to 시도(목표 상단으로)…")
        try:
            loc.nth(src_i).drag_to(loc.nth(dst_i), target_position={"x": 30, "y": 4})
            page.wait_for_timeout(800)
        except Exception as e:  # noqa: BLE001
            print(f"     예외: {e}")
        o1 = order(page)
        if o1 != base:
            print(f"     AFTER(1): {o1}\n  ✅ drag_to 성공 — C안 성립.")
            return _hold(0)
        print(f"     AFTER(1): 변화 없음")

        # --- (2) hover → 드래그 핸들 탐색 ---
        print("\n[probe] (2) 소스 컴포넌트 hover 후 드래그핸들 후보 탐색…")
        comps[src_i].hover()
        page.wait_for_timeout(500)
        handles = page.evaluate(_HANDLE_JS)
        print(f"     hover 시 보이는 drag/handle 후보 {len(handles)}개:")
        for h in handles:
            print(f"       <{h['tag']}> cls={h['cls']!r} @({h['x']},{h['y']}) {h['w']}x{h['h']}")

        # --- (3) 핸들(있으면 첫 후보) 잡고 포인터 드래그 ---
        if handles:
            h = handles[0]
            hx, hy = h["x"] + h["w"] / 2, h["y"] + h["h"] / 2
            db = comps[dst_i].bounding_box()
            tx, ty = db["x"] + db["width"] / 2, db["y"] + 6
            print(f"\n[probe] (3) 핸들 @({hx:.0f},{hy:.0f}) → 목표 상단({tx:.0f},{ty:.0f}) 포인터 드래그…")
            page.mouse.move(hx, hy)
            page.wait_for_timeout(150)
            page.mouse.down()
            page.wait_for_timeout(150)
            for i in range(1, 21):
                page.mouse.move(hx + (tx - hx) * i / 20, hy + (ty - hy) * i / 20)
                page.wait_for_timeout(35)
            page.wait_for_timeout(200)
            page.mouse.up()
            page.wait_for_timeout(800)
            o3 = order(page)
            if o3 != base:
                print(f"     AFTER(3): {o3}\n  ✅ 핸들 포인터 드래그 성공 — C안 성립.")
                return _hold(0)
            print(f"     AFTER(3): 변화 없음")
        else:
            print("\n[probe] (3) 드래그 핸들 후보가 안 보임 — hover로도 핸들이 안 뜸.")

        print("\n===== 판정 =====")
        print("  ❌ 세 방법 모두 실패. SE 재배치 드래그는 표준 자동화로 트리거하기 어려움(매우 불안정).")
        print("     → 현실적으로 C안은 비용 대비 위험이 큼. D안(재배치 없이 순서대로 본문) 권장.")
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
