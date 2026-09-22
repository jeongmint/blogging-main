"""임시저장 목록 팝업의 '삭제' 버튼 셀렉터를 비대화식으로 캡처(저장 세션, 헤드리스).

draft_item_button(불러오기)만 셀렉터가 있고, 목록 항목의 '삭제' 버튼 셀렉터는 아직
없다. 이 스크립트는 저장된 세션으로 글쓰기 페이지를 열고 '저장글 N' 팝업을 띄운 뒤,
목록 li의 전체 구조와 항목 내부의 모든 버튼(data-click-area/aria-label 포함)을 떠서
JSON으로 남긴다. 여기서 '삭제' 버튼의 selector를 골라 SMART_EDITOR에 채운다.

실행:
    .venv/bin/python scripts/capture_draft_delete.py

결과: scratchpad/draft_delete_dump.json (+ 표준출력 요약). 아무것도 삭제하지 않는다(읽기 전용).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

OUT = Path(tempfile.gettempdir()) / "draft_delete_dump.json"

# 목록 li 하나하나의 전체 구조 + 내부 버튼들의 식별 속성을 떠 온다.
_DUMP_JS = r"""
() => {
  const ul = document.querySelector('ul[aria-label="임시저장된 글"]');
  if (!ul) return {error: 'draft_list not found'};
  const items = [...ul.querySelectorAll(':scope > li')].map((li, i) => {
    const buttons = [...li.querySelectorAll('button, a, [role=button]')].map(b => {
      const attrs = {};
      for (const a of b.attributes) attrs[a.name] = a.value;
      return {
        tag: b.tagName.toLowerCase(),
        cls: (b.className && b.className.toString) ? b.className.toString() : '',
        text: (b.textContent || '').trim().slice(0, 30),
        clickArea: b.getAttribute('data-click-area') || '',
        ariaLabel: b.getAttribute('aria-label') || '',
        title: b.getAttribute('title') || '',
        attrs,
      };
    });
    return {idx: i, html: li.outerHTML.slice(0, 1500), buttons};
  });
  return {count: items.length, items};
}
"""


def main() -> int:
    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.is_logged_in():
            print("[capture] 저장 세션이 로그인 상태가 아님 — 헤드풀로 직접 로그인 필요")
            return 2
        pub.open_write_page()
        page = pub._page
        # '저장글 N' 팝업 열기
        page.click(SMART_EDITOR["save_count_button"])
        page.wait_for_selector(SMART_EDITOR["draft_list"], timeout=8000)
        page.wait_for_timeout(800)

        dump = page.evaluate(_DUMP_JS)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[capture] 덤프 저장: {OUT}")
        if dump.get("error"):
            print(f"[capture] 오류: {dump['error']}")
            return 1
        print(f"[capture] 임시저장 항목 {dump['count']}건")
        for it in dump["items"]:
            print(f"\n  li[{it['idx']}] 버튼 {len(it['buttons'])}개:")
            for b in it["buttons"]:
                print(f"    <{b['tag']}> clickArea={b['clickArea']!r} "
                      f"aria={b['ariaLabel']!r} title={b['title']!r} "
                      f"text={b['text']!r} cls={b['cls']!r}")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
