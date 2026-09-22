"""네이버 SE-ONE 이미지 'AI 활용' 표시 토글 mechanic 검증(라이브 확정 2026-07-23). 저장/발행 안 함.

구조(라이브 확인):
    <div class="se-set-ai-mark-button-wrapper">
      <div class="se-set-ai-mark-button">
        <p class="se-set-ai-mark-button-text">AI 활용 설정</p>
        <button class="se-set-ai-mark-button-toggle"></button>   ← 클릭 대상
      </div>
    </div>
이미지에 hover(선택 X)하면 배지가 뜨고, 토글을 클릭하면 se-is-selected가 붙는다(=켜짐). 발행 시
이미지 우하단에 'AI 활용' 아이콘이 붙는다. editor._mark_ai_images가 이 mechanic을 그대로 쓴다.

흐름: 글쓰기 새로 열기 → 더미 이미지 1장 삽입 → 본문 클릭(선택 해제) → 이미지 hover → 토글 클릭 →
se-is-selected 부착 확인 → Escape(저장·발행 안 함).

사용:
    .venv/bin/python scripts/probe_ai_label.py [이미지경로]        # 헤드풀
    .venv/bin/python scripts/probe_ai_label.py [이미지경로] --headless
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

_DEFAULT_IMG = str(
    Path(__file__).resolve().parents[1] / "config/editor_previews/quote_quotation_postit.png"
)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    headless = "--headless" in sys.argv
    img = args[0] if args else _DEFAULT_IMG
    if not Path(img).exists():
        print(f"[probe] 이미지 없음: {img}")
        return 2
    sel = SMART_EDITOR["image_ai_label"]

    pub = BlogPublisher(headless=headless).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단(먼저 로그인한 세션이 필요)")
            return 1
        pub.open_write_page()
        page = pub._page
        pub._type_title("AI 표시 프로브(저장 안 함)")
        pub._insert_image(img)
        page.wait_for_timeout(1500)
        page.click(SMART_EDITOR["content_component"])  # 이미지 선택 해제(배지는 hover에서만)
        page.wait_for_timeout(400)

        comps = [
            c for c in page.query_selector_all(".se-component")
            if c.query_selector("img.se-image-resource")
        ]
        if not comps:
            print("[probe] 본문에 이미지가 안 들어감 ❌")
            return 1
        comp = comps[-1]
        comp.scroll_into_view_if_needed()
        comp.hover()
        page.wait_for_timeout(300)

        toggle = comp.query_selector(sel)
        if toggle is None:
            print(f"[probe] AI 토글({sel}) 못 찾음 ❌ — hover 배지가 안 떴거나 셀렉터 변경")
            return 1
        before = "se-is-selected" in (toggle.get_attribute("class") or "")
        toggle.click()
        page.wait_for_timeout(500)
        after = "se-is-selected" in (toggle.get_attribute("class") or "")
        print(f"[probe] 토글 클릭: se-is-selected {before} → {after}")
        ok = (not before) and after
        print(f"[probe] → {'OK ✅ AI 활용 표시 켜짐' if ok else '불일치 ❌'}")
        print("[probe] (비파괴 — 저장·발행 안 함)")
        page.keyboard.press("Escape")
        return 0 if ok else 1
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
