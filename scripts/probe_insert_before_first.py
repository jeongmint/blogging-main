"""'첫 사진 위에 본문 삽입'의 신뢰할 방법 탐색(맨 위 사진은 선택 툴바가 edge를 덮어 클릭이 막힘).

여러 후보를 글을 리로드하며 차례로 시도하고, 마커가 첫 사진 '앞'(문서 더 앞쪽 컴포넌트)에
들어갔는지 검증한다. 성공한 방법을 _anchor_before_first_media에 채택한다.

실행: .venv/bin/python scripts/probe_insert_before_first.py [draft_idx]
비파괴: 저장 안 함.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

_ORDER_JS = r"""
() => [...document.querySelectorAll('.se-component')].map((c,i) => {
  const cls=c.className.toString();
  let k='other';
  if(/se-video/.test(cls))k='video'; else if(/se-image/.test(cls))k='image';
  else if(/se-documentTitle/.test(cls))k='title'; else if(/se-text/.test(cls))k='text';
  return {i,k,txt:(c.innerText||'').trim().replace(/\s+/g,' ').slice(0,30)};
})
"""


def first_image_idx(rows):
    return next((r["i"] for r in rows if r["k"] == "image"), None)


def marker_before_first_image(page, marker) -> bool:
    rows = page.evaluate(_ORDER_JS)
    fi = first_image_idx(rows)
    mi = next((r["i"] for r in rows if marker in (r["txt"] or "")), None)
    return fi is not None and mi is not None and mi < fi


def reload(pub, idx):
    pub._load_draft_into_editor(idx)
    try:
        pub._page.wait_for_selector(SMART_EDITOR["editor_image"], timeout=8000)
    except Exception:
        pass
    pub._page.wait_for_timeout(800)


def m_title_enter(page, marker):
    """제목 칸 클릭 → End → Enter → 타이핑(본문 첫 문단이 생기는지)."""
    page.click(SMART_EDITOR["title_component"])
    page.wait_for_timeout(200)
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    page.keyboard.type(marker + " 인트로", delay=8)
    page.wait_for_timeout(400)


def m_ctrl_home(page, marker):
    """본문 클릭 → Ctrl+Home(문서 시작) → 타이핑."""
    page.click(SMART_EDITOR["content_component"])
    page.wait_for_timeout(200)
    page.keyboard.press("Control+Home")
    page.wait_for_timeout(300)
    page.keyboard.type(marker + " 인트로", delay=8)
    page.wait_for_timeout(400)


def m_edge_topleft(page, marker):
    """첫 미디어 top edge-button의 '좌상단 모서리'를 좌표 클릭(중앙 아이콘 회피) → 타이핑."""
    comp = page.query_selector(".se-component.se-image, .se-component.se-video")
    if not comp:
        return
    comp.scroll_into_view_if_needed()
    edge = comp.query_selector("button.se-component-edge-button-top")
    box = edge.bounding_box() if edge else None
    if not box:
        return
    page.mouse.click(box["x"] + 4, box["y"] + 2)
    page.wait_for_timeout(400)
    page.keyboard.type(marker + " 인트로", delay=8)
    page.wait_for_timeout(400)


def m_force_then_focus(page, marker):
    """edge force 클릭 → 새로 생긴 첫 본문 문단을 실제 클릭해 포커스 → 타이핑."""
    comp = page.query_selector(".se-component.se-image, .se-component.se-video")
    if not comp:
        return
    comp.scroll_into_view_if_needed()
    edge = comp.query_selector("button.se-component-edge-button-top")
    if edge:
        try:
            edge.click(force=True)
        except Exception:
            pass
    page.wait_for_timeout(400)
    para = page.query_selector(SMART_EDITOR["content_component"] + " .se-text-paragraph")
    if para:
        para.click()
        page.wait_for_timeout(200)
    page.keyboard.type(marker + " 인트로", delay=8)
    page.wait_for_timeout(400)


METHODS = [
    ("title_enter", m_title_enter),
    ("ctrl_home", m_ctrl_home),
    ("edge_topleft", m_edge_topleft),
    ("force_then_focus", m_force_then_focus),
]


def main() -> int:
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 필요(최대 6분)…")
            if not pub.wait_for_login():
                return 1
        pub.open_write_page()
        page = pub._page
        results = {}
        for name, fn in METHODS:
            marker = f"★BF_{name}★"
            reload(pub, idx)
            before = page.evaluate(_ORDER_JS)
            fi = first_image_idx(before)
            print(f"\n[{name}] 첫 사진 comp[{fi}] — 시도…")
            try:
                fn(page, marker)
            except Exception as e:  # noqa: BLE001
                print(f"  예외: {e}")
            ok = marker_before_first_image(page, marker)
            present = any(marker in (r["txt"] or "") for r in page.evaluate(_ORDER_JS))
            results[name] = (ok, present)
            print(f"  결과: 마커존재={present} 첫사진앞={ok} {'✅' if ok else '❌'}")

        print("\n===== 요약 =====")
        for name, (ok, present) in results.items():
            print(f"  {name:<16} {'✅ 첫사진 앞 삽입 성공' if ok else ('마커는 들어갔으나 위치 틀림' if present else '삽입 실패')}")
        winner = next((n for n, (ok, _) in results.items() if ok), None)
        print(f"\n채택 후보: {winner or '없음 — 추가 방법 필요'}")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
