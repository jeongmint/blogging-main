"""SE-ONE 사진 재배치 C안 2차 시도: 드래그 핸들 탐색 + Playwright drag_to + 합성 HTML5 DnD.

1차(수동 마우스 이동)는 실패. SE가 네이티브 HTML5 DnD거나 전용 핸들을 요구할 수 있어
세 갈래를 순서대로 시도하고, 각 시도 뒤 compid 순서 변화를 본다. 하나라도 성공하면 C 성립.

실행:
    .venv/bin/python scripts/probe_drag_reorder2.py [draft_idx] [src_img] [dst_img]
  기본: draft 0, image[1] → image[0] 앞으로.
비파괴: 임시저장 안 누름.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

_IMG_COMPIDS_JS = r"""
() => [...document.querySelectorAll('.se-component.se-image')]
        .map(c => c.getAttribute('data-compid') || '(no-id)')
"""

# 소스 컴포넌트 안에서 draggable 요소 / 드래그 핸들 후보를 찾는다.
_INSPECT_JS = r"""
(srcIdx) => {
  const comp = document.querySelectorAll('.se-component.se-image')[srcIdx];
  if (!comp) return {err: 'no comp'};
  const draggables = [...comp.querySelectorAll('[draggable=true], [draggable=""]')]
      .map(e => ({tag: e.tagName.toLowerCase(), cls: (e.className||'').toString().slice(0,80)}));
  const handles = [...comp.querySelectorAll('[class*=drag], [class*=handle], [class*=move], [class*=edge-button]')]
      .map(e => ({tag: e.tagName.toLowerCase(), cls: (e.className||'').toString().slice(0,80),
                  dir: e.getAttribute('data-direction') || ''}));
  return {
    compDraggable: comp.getAttribute('draggable'),
    compCls: comp.className.toString().slice(0,90),
    draggables, handles,
    htmlHead: comp.outerHTML.slice(0, 700),
  };
}
"""

# 합성 HTML5 DnD: 공유 DataTransfer로 dragstart→dragenter→dragover→drop→dragend 발사.
_SYNTH_DND_JS = r"""
([srcIdx, dstIdx]) => {
  const imgs = [...document.querySelectorAll('.se-component.se-image')];
  const src = imgs[srcIdx], dst = imgs[dstIdx];
  if (!src || !dst) return 'no comp';
  const dt = new DataTransfer();
  const rs = src.getBoundingClientRect(), rd = dst.getBoundingClientRect();
  const ev = (type, el, x, y) => el.dispatchEvent(new DragEvent(type,
      {bubbles:true, cancelable:true, composed:true, dataTransfer:dt, clientX:x, clientY:y}));
  // 드롭 타깃: 목표 컴포넌트의 '상단' 근처(그 앞으로 들어가도록)
  const tx = rd.x + rd.width/2, ty = rd.y + 5;
  ev('dragstart', src, rs.x + rs.width/2, rs.y + rs.height/2);
  ev('drag',      src, tx, ty);
  ev('dragenter', dst, tx, ty);
  ev('dragover',  dst, tx, ty);
  ev('drop',      dst, tx, ty);
  ev('dragend',   src, tx, ty);
  return 'fired';
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

        # --- 0) 구조 점검 ---
        info = page.evaluate(_INSPECT_JS, src_i)
        print("\n===== 소스 컴포넌트 구조 =====")
        print(f"  comp draggable={info.get('compDraggable')!r} cls={info.get('compCls')!r}")
        print(f"  draggable 요소: {info.get('draggables')}")
        print(f"  핸들 후보: {info.get('handles')}")
        print(f"  htmlHead: {info.get('htmlHead','')[:400]}")

        comps = page.query_selector_all(".se-component.se-image")
        comps[min(src_i, dst_i)].scroll_into_view_if_needed()
        page.wait_for_timeout(400)

        # --- 1) Playwright 내장 drag_to (목표 상단으로) ---
        print("\n[probe] (1) Playwright drag_to 시도…")
        try:
            comps[src_i].drag_to(comps[dst_i], target_position={"x": 30, "y": 4})
            page.wait_for_timeout(800)
        except Exception as e:  # noqa: BLE001
            print(f"     drag_to 예외: {e}")
        o1 = order(page)
        print(f"     AFTER(1): {o1}")
        if o1 != base:
            print("  ✅ drag_to 로 순서 변경 성공 — C안 성립(Playwright 내장 드래그).")
            return _hold(0)

        # --- 2) 합성 HTML5 DnD 이벤트 ---
        print("\n[probe] (2) 합성 HTML5 DnD 이벤트 디스패치 시도…")
        r = page.evaluate(_SYNTH_DND_JS, [src_i, dst_i])
        print(f"     dispatch: {r}")
        page.wait_for_timeout(800)
        o2 = order(page)
        print(f"     AFTER(2): {o2}")
        if o2 != base:
            print("  ✅ 합성 DnD 로 순서 변경 성공 — C안 성립(JS 이벤트 디스패치).")
            return _hold(0)

        print("\n===== 판정 =====")
        print("  ❌ drag_to·합성 DnD 모두 순서 변화 없음.")
        print("     → 위 '구조 점검'의 draggable/핸들 정보를 보고 다음 수를 정한다(전용 핸들 grab 등).")
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
