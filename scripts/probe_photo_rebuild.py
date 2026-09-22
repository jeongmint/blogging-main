"""Phase 4 검증: 영상을 고정 앵커로 두고 사진을 삭제→정확한 위치에 재삽입하는 rebuild mechanic.

'테스트' 글(사진19·영상2)로: 사진 전부 삭제(영상2 고정) → 목표 배치 재삽입.
목표: [A,B] 영상0 앞 / [C] 영상0~1 사이 / [D] 영상1 뒤  →  기대 순서: A B V C V D
비파괴(저장 안 함).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PV = REPO / "config" / "editor_previews"
IMGS = [PV / f for f in ("divider_line1.png", "divider_line2.png", "divider_line3.png", "divider_line4.png")]

_SEQ_JS = r"""
() => [...document.querySelectorAll('.se-component')].map(c => {
  const cls = c.className.toString();
  if (/se-documentTitle/.test(cls)) return 'T';
  if (/se-video/.test(cls)) return 'V';
  if (c.querySelector('img.se-image-resource')) return 'i';
  if (/se-text/.test(cls)) return 't';
  return '?';
}).join(' ')
"""


def seq(page, label):
    s = page.evaluate(_SEQ_JS)
    print(f"  {label}: {s}")
    return s


def delete_all_photos(page) -> int:
    n = 0
    for _ in range(60):
        imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
        if not imgs:
            break
        imgs[0].scroll_into_view_if_needed()
        imgs[0].click()
        page.wait_for_timeout(200)
        page.keyboard.press("Delete")
        page.wait_for_timeout(300)
        n += 1
    return n


def main() -> int:
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단")
            return 1
        pub.open_write_page()
        page = pub._page
        pub._load_draft_into_editor(idx)
        page.wait_for_timeout(1200)
        seq(page, "BEFORE")

        print(f"[probe] 사진 전부 삭제… (영상은 고정)")
        removed = delete_all_photos(page)
        print(f"[probe] {removed}장 삭제")
        skel = seq(page, "SKELETON")

        # segment0: 영상0 앞에 A, B (forward)
        pub._anchor_before_first_media()  # 제목 끝 Enter → 첫 미디어 위
        pub._insert_image(str(IMGS[0]))
        page.wait_for_timeout(500)
        page.keyboard.press("Enter")  # 방금 넣은 사진 뒤
        pub._insert_image(str(IMGS[1]))
        page.wait_for_timeout(500)

        # segment1: 영상0 바로 뒤에 C
        vids = page.query_selector_all(SMART_EDITOR["editor_video"])
        vids[0].scroll_into_view_if_needed(); vids[0].click(); page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        pub._insert_image(str(IMGS[2]))
        page.wait_for_timeout(500)

        # segment2: 영상1 바로 뒤에 D
        vids = page.query_selector_all(SMART_EDITOR["editor_video"])
        vids[1].scroll_into_view_if_needed(); vids[1].click(); page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        pub._insert_image(str(IMGS[3]))
        page.wait_for_timeout(500)

        after = seq(page, "AFTER")
        # 기대: 제목 T, 그다음 i i V i V i (텍스트 문단 t는 섞여도 됨 — 미디어 순서만 검증)
        media = [c for c in after.split() if c in ("i", "V")]
        expected = ["i", "i", "V", "i", "V", "i"]
        print(f"\n[probe] 미디어 순서: {' '.join(media)}")
        print(f"[probe] 기대:       {' '.join(expected)}")
        print(f"[probe] → {'OK ✅ 영상 고정 + 사진 정확 배치' if media == expected else '불일치 ❌'}")
        print("[probe] (비파괴 — 저장 안 함)")
        return 0
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
