"""SE-ONE 문단 '정렬(left/center/right)'이 DOM에 어떻게 표현되는지 캡처하는 1회성 프로브.

목적: 게시 후 '중앙정렬이 사라졌는지'를 검증(읽기)하려면, SE가 문단 정렬을
className(예: se-text-paragraph-align-center)으로 다는지, 인라인 text-align인지,
아니면 둘 다인지 라이브 DOM에서 확인해야 한다. 코드베이스엔 정렬을 '쓰기'만 있고
'읽기' 근거가 없어 여기서 떠 본다.

흐름: 글쓰기 페이지를 새로 열고 → 문단 3개를 만들어 각각 left/center/right를
_apply_align 으로 건 뒤, 모든 .se-text-paragraph 의 class/inline-style/computed
text-align 과 가까운 .se-component.se-text 의 class, 그리고 커서별 정렬 툴바 버튼
상태를 출력한다. 새 글이라 저장하지 않는다(본문만 만지고 끝).

실행:
    .venv/bin/python scripts/probe_align_dom.py
    .venv/bin/python scripts/probe_align_dom.py --headless

출력에서 고른 '정렬 읽기 셀렉터'를 검증/자동복구 패스에 쓴다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.publish.editor import BlogPublisher  # noqa: E402

# 모든 본문 문단의 정렬 표현을 떠내는 JS.
_DUMP_PARAS_JS = r"""
() => {
  const out = [];
  const paras = document.querySelectorAll('.se-component.se-text .se-text-paragraph');
  for (const p of paras) {
    const cs = getComputedStyle(p);
    const comp = p.closest('.se-component.se-text');
    out.push({
      text: (p.textContent || '').trim().slice(0, 12),
      paraClass: p.className && p.className.toString ? p.className.toString() : '',
      paraInline: p.getAttribute('style') || '',
      paraComputedAlign: cs.textAlign,
      compClass: comp ? comp.className.toString() : '',
      compAlignAttr: comp ? (comp.getAttribute('data-align') || comp.getAttribute('align') || '') : '',
    });
  }
  return out;
}
"""

# 현재 커서가 놓인 문단 기준, 정렬 툴바 버튼의 상태(active data-value 등).
_TOOLBAR_ALIGN_JS = r"""
() => {
  const btn = document.querySelector('li.se-toolbar-item-align button');
  if (!btn) return {found: false};
  return {
    found: true,
    btnClass: btn.className.toString(),
    dataValue: btn.getAttribute('data-value') || '',
    dataName: btn.getAttribute('data-name') || '',
    aria: btn.getAttribute('aria-label') || '',
  };
}
"""


def main() -> None:
    headless = "--headless" in sys.argv
    pub = BlogPublisher(headless=headless)
    pub.start()
    if not pub.is_logged_in():
        ok = pub.wait_for_login()
        if not ok:
            print("로그인 실패 — 세션이 없습니다. 먼저 로그인 후 다시 실행하세요.")
            pub.close()
            return

    pub.open_write_page()
    page = pub._page
    page.click("body")
    page.wait_for_timeout(200)

    # 본문 첫 문단으로 커서 이동.
    page.click(".se-component.se-text .se-text-paragraph")
    page.wait_for_timeout(200)

    plan = [("left", "WANT_LEFT"), ("center", "WANT_CENTER"), ("right", "WANT_RIGHT")]
    toolbar_states = []
    for value, text in plan:
        pub._apply_align(value)
        page.keyboard.type(text, delay=5)
        # 이 문단에서 정렬 툴바 상태도 같이 캡처(읽기 후보 2: 툴바 active 상태).
        toolbar_states.append({value: page.evaluate(_TOOLBAR_ALIGN_JS)})
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)

    paras = page.evaluate(_DUMP_PARAS_JS)
    print("\n===== 문단별 정렬 DOM 표현 =====")
    print(json.dumps(paras, ensure_ascii=False, indent=2))
    print("\n===== 커서별 정렬 툴바 상태 =====")
    print(json.dumps(toolbar_states, ensure_ascii=False, indent=2))
    print(
        "\n해석 가이드:\n"
        " - paraClass 에 align 토큰이 보이면 → className 으로 읽는다(가장 안정적).\n"
        " - 없고 paraInline/paraComputedAlign 만 다르면 → text-align(computed) 으로 읽는다.\n"
        " - left 문단의 paraComputedAlign 이 'start'/'left' 인지 확인(검증 기준값).\n"
    )
    print("프로브 종료 — 새 글이라 저장하지 않았습니다.")
    pub.close()


if __name__ == "__main__":
    main()
