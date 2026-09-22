"""SE-ONE 사진 컴포넌트 '프로그램 드래그 재배치'(C안) 가능성 검증 프로브.

재배치 네이티브 버튼은 없고 드래그 전용임을 앞서 확인했다. 여기선 Playwright 마우스로
인접한 두 사진을 드래그해 순서가 실제로 바뀌는지 본다. 되면 in-place에서 영상 보존+유저비용0
으로 순서 제어까지 가능(C안 성립). 안 되면 D안(재배치 없이 LLM이 순서에 맞춰 본문)으로 간다.

식별: 각 컴포넌트의 data-compid(고정 ID)로 순서를 추적 — lazy-load/빈 src에 안 흔들림.
테스트: image[1]을 image[0] 앞으로 옮긴다(인접 swap, 둘 다 화면에 보임). compid 순서가
[A,B,...] → [B,A,...] 로 바뀌면 성공.

실행:
    .venv/bin/python scripts/probe_drag_reorder.py [draft_idx] [src_img] [dst_img]
  draft_idx: 사진 여러 장 있는 글(기본 0)
  src_img/dst_img: 옮길 사진/목표 위치 사진의 0-based 인덱스(기본 1 → 0)

비파괴: 임시저장 안 누름.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

# 사진 컴포넌트의 compid 순서(문서 순)를 반환 — 재배치 전/후 비교용.
_IMG_COMPIDS_JS = r"""
() => [...document.querySelectorAll('.se-component.se-image')]
        .map(c => c.getAttribute('data-compid') || '(no-id)')
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


def manual_drag(page, src_el, dst_el):
    """소스 컴포넌트를 마우스로 잡아 목표 컴포넌트의 '상단'에 떨군다(목표 앞으로 이동).

    SE는 드래그 중 drop-indicator를 띄운다. 네이티브 HTML5 DnD가 마우스 이벤트에 반응하지
    않을 수 있어, hover→down→여러 단계 move(중간에 dragover 유발)→up 으로 충분히 끌어준다."""
    sb = src_el.bounding_box()
    db = dst_el.bounding_box()
    if not sb or not db:
        print("[probe] 컴포넌트 bounding_box를 못 구함")
        return
    sx, sy = sb["x"] + sb["width"] / 2, sb["y"] + sb["height"] / 2
    # 목표의 '맨 위'에 떨궈야 그 앞으로 들어간다.
    tx, ty = db["x"] + db["width"] / 2, db["y"] + 6
    page.mouse.move(sx, sy)
    page.wait_for_timeout(200)
    page.mouse.down()
    page.wait_for_timeout(150)
    # 살짝 흔들어 dragstart 유발 후 단계적으로 이동
    steps = 18
    for i in range(1, steps + 1):
        mx = sx + (tx - sx) * i / steps
        my = sy + (ty - sy) * i / steps
        page.mouse.move(mx, my)
        page.wait_for_timeout(40)
    page.wait_for_timeout(200)
    page.mouse.up()
    page.wait_for_timeout(800)


def main() -> int:
    draft_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    src_i = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    dst_i = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 브라우저에서 직접 로그인(최대 6분)…")
            if not pub.wait_for_login():
                return 1
        pub.open_write_page()
        page = pub._page

        print(f"[probe] 임시저장 {draft_idx}번 불러오는 중…")
        if not load_draft(pub, draft_idx):
            return 1

        before = page.evaluate(_IMG_COMPIDS_JS)
        print(f"\n[probe] 사진 {len(before)}장. 순서(compid 뒤 6자리):")
        print("  BEFORE:", [c[-6:] for c in before])
        if max(src_i, dst_i) >= len(before):
            print(f"[probe] 인덱스 범위 초과(사진 {len(before)}장)")
            return 1

        comps = page.query_selector_all(".se-component.se-image")
        src_el, dst_el = comps[src_i], comps[dst_i]
        # 둘 다 화면에 보이도록 위쪽 사진을 기준으로 스크롤
        comps[min(src_i, dst_i)].scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        print(f"[probe] image[{src_i}](…{before[src_i][-6:]}) → image[{dst_i}](…{before[dst_i][-6:]}) 앞으로 드래그…")
        manual_drag(page, src_el, dst_el)

        after = page.evaluate(_IMG_COMPIDS_JS)
        print("  AFTER :", [c[-6:] for c in after])

        print("\n===== 판정 =====")
        if after == before:
            print("  ❌ 순서 변화 없음 — 마우스 드래그가 SE 재배치를 트리거하지 못함.")
            print("     → C안(프로그램 드래그) 이 방식으론 실패. drag_to/네이티브 DnD 이벤트 등 추가 시도 필요.")
        else:
            moved = before[src_i]
            new_pos = after.index(moved) if moved in after else -1
            expected = dst_i  # dst 앞으로 갔으면 새 위치가 dst_i 근처
            print(f"  ✅ 순서 바뀜! 옮긴 사진(…{moved[-6:]})이 위치 {src_i} → {new_pos} 로 이동.")
            if new_pos == expected:
                print("     → 의도한 위치로 정확히 이동. C안 성립(프로그램 재배치 가능).")
            else:
                print(f"     → 이동은 됐으나 위치가 기대({expected})와 다름. 드롭 지점 보정 필요하지만 C 가능성 확인.")

        if sys.stdin.isatty():
            try:
                input("\n[probe] Enter 로 닫기…")
            except EOFError:
                pass
        else:
            print("\n[probe] (비대화형 — 자동 종료)")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
