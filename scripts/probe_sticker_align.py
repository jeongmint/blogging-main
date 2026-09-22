"""스티커 컴포넌트의 DOM 클래스와 '가운데 정렬' 메커니즘을 검증하는 1회성 프로브.

목적: 스티커가 왼쪽 정렬로 남는 문제의 수정(_align_stickers_center)이 쓰는
셀렉터(.se-component.se-sticker / se-section-align-center)가 실제 SE-ONE DOM과
맞는지 확인한다 — 코드베이스에 스티커 '본문 컴포넌트' DOM 근거가 없어 떠 본다.

흐름: 글쓰기 페이지를 새로 열고 → 스티커 패널에서 활성 팩의 첫 스티커를 그대로
클릭(정렬 보정 없이 raw 삽입) → 본문 컴포넌트 클래스 덤프(BEFORE) →
_align_stickers_center() 실행 → 재덤프(AFTER). 새 글이라 저장하지 않는다.

실행:
    .venv/bin/python scripts/probe_sticker_align.py --headless
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

_DUMP_COMPS_JS = r"""
() => [...document.querySelectorAll('.se-component')].map(c => ({
  comp: c.className.toString(),
  sec: (() => { const s = c.querySelector("[class*='se-section-']");
                return s ? s.className.toString() : ''; })(),
}))
"""


def main() -> None:
    headless = "--headless" in sys.argv
    pub = BlogPublisher(headless=headless)
    pub.start()
    if not pub.is_logged_in():
        if not pub.wait_for_login():
            print("로그인 실패 — 세션이 없습니다. 먼저 로그인 후 다시 실행하세요.")
            pub.close()
            return

    pub.open_write_page()
    page = pub._page
    page.click(SMART_EDITOR["content_component"])
    page.wait_for_timeout(300)

    # raw 삽입: 정렬 보정 없이 활성 팩 첫 스티커를 그대로 클릭(기본 정렬 상태 관찰용)
    pub._open_sticker_panel()
    page.click(
        f"{SMART_EDITOR['sticker_active_list']} {SMART_EDITOR['sticker_element']}[data-index='0']"
    )
    page.wait_for_timeout(800)

    print("\n===== BEFORE(삽입 직후) 컴포넌트 클래스 =====")
    print(json.dumps(page.evaluate(_DUMP_COMPS_JS), ensure_ascii=False, indent=2))

    pub._align_stickers_center()

    print("\n===== AFTER(_align_stickers_center 후) =====")
    print(json.dumps(page.evaluate(_DUMP_COMPS_JS), ensure_ascii=False, indent=2))
    print(
        "\n해석 가이드:\n"
        " - BEFORE의 comp에 'se-sticker' 토큰이 있어야 수정의 셀렉터가 유효.\n"
        " - AFTER의 그 컴포넌트 sec에 'se-section-align-center'가 붙으면 메커니즘 검증 완료.\n"
    )
    print("프로브 종료 — 새 글이라 저장하지 않았습니다.")
    pub.close()


if __name__ == "__main__":
    main()
