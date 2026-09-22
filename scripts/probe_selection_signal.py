"""드래그 선택 직후 SE에서 관측 가능한 '선택 신호'가 뭔지 확인 — 라이브.

_select_body_text 드래그 후 window.getSelection()과 SE 관련 상태를 시점별로 덤프해,
718 고정대기(200ms)를 어떤 신호로 바꿀 수 있는지(있긴 한지) 판별한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher, _RANGE_RECT_JS  # noqa: E402

DUMP = r"""
(t) => {
  const s = window.getSelection();
  return {
    rangeCount: s ? s.rangeCount : -1,
    toStr: s ? (s.toString() || '').slice(0, 40) : null,
    includes: s ? (s.toString() || '').includes(t) : false,
    isCollapsed: s ? s.isCollapsed : null,
    activeTag: document.activeElement ? document.activeElement.tagName : null,
  };
}
"""


def main() -> int:
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("세션 없음"); return 1
        pub.open_write_page()
        page = pub._page
        page.click(SMART_EDITOR["content_component"])
        page.keyboard.type("선택신호 테스트 문장입니다 핵심어구 포함", delay=4)
        page.wait_for_timeout(600)
        text = "핵심어구"
        rect = page.evaluate(_RANGE_RECT_JS, text)
        if not rect:
            print("대상 못 찾음"); return 1
        y = rect["y"] + rect["h"] / 2
        page.mouse.move(rect["x"] + 1, y)
        page.mouse.down()
        page.mouse.move(rect["x"] + rect["w"] - 1, y, steps=6)
        page.mouse.up()
        # 드래그 직후부터 시점별로 선택 상태를 덤프
        for ms in (0, 20, 50, 100, 200):
            if ms:
                page.wait_for_timeout(ms if ms == 20 else ms - 20)
            print(f"+{ms:>4}ms:", page.evaluate(DUMP, text))
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
