"""드립 한 줄 해시태그 서식(system 11 #4383BF) 라이브 재현 프로브 — 1회성, 저장 안 함.

유저 보고: 드립 문장에 예전 해시태그 줄의 크기/폰트/색이 안 입혀짐.
플랜 단계는 정상(테스트 통과) → 실행기 _apply_emphasis 경로를 라이브로 검증한다.

퍼블리시와 동일한 순서로 대제목·드립 문장을 타이핑한 뒤, 드립 문장 3종
(평문 / ',,..' / '.ᐟ' 특수문자)에 hashtags 서식을 적용하고 DOM에서
font-size·font-family·color 가 실제로 박혔는지 읽는다.

실행: .venv/bin/python scripts/probe_drip_style.py  (저장/발행 안 함, 창만 닫음)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.emphasis import EmphasisStyle  # noqa: E402
from autoblog.publish.plan import load_structure_styles  # noqa: E402

BIG = "또 오고 말았잖아요"
DRIPS = [
    "아니근데 진짜 맛있당께요",       # 평문 대조군
    "재방문에는 다 이유가 있는법 ,,..",  # 쉼표·점 꾸밈
    "너로 정했다 .ᐟ",                # 특수문자 .ᐟ
]

# 문구가 든 문단의 실제 적용 스타일 + 텍스트 노드 분할 상태를 읽는다.
_DOM_JS = r"""
(t) => {
  const roots = document.querySelectorAll('.se-component.se-text');
  for (const root of roots) {
    for (const p of root.querySelectorAll('p, .se-text-paragraph')) {
      if ((p.textContent || '').includes(t)) {
        const spans = [...p.childNodes].map(n => ({
          tag: n.nodeType === 3 ? '#text' : n.tagName,
          cls: n.nodeType === 1 ? n.className : '',
          text: (n.textContent || '').slice(0, 30),
        }));
        const el = p.querySelector('span') || p;
        const cs = getComputedStyle(el);
        return {nodes: spans, fontSize: cs.fontSize, fontFamily: cs.fontFamily.slice(0, 40),
                color: cs.color, html: p.outerHTML.slice(0, 400)};
      }
    }
  }
  return null;
}
"""


def main() -> int:
    st = load_structure_styles().hashtags
    style = EmphasisStyle(
        text_color=st.color, font_family=st.font, font_size=str(st.size) if st.size else None
    )
    print(f"[probe] hashtags 서식: font={st.font} size={st.size} color={st.color}")

    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단.")
            return 1
        pub.open_write_page()
        page = pub._page
        pub._type_title("ZZ_드립서식프로브_저장안함")
        page.click(SMART_EDITOR["content_component"])
        pub._reset_text_toggles()
        # 퍼블리시와 동일하게: 대제목 → 드립들(각각 문단)
        for line in [BIG, *DRIPS]:
            page.keyboard.type(line, delay=4)
            page.keyboard.press("Enter")
        page.wait_for_timeout(800)

        for drip in DRIPS:
            print(f"\n===== 드립: {drip!r} =====")
            before = page.evaluate(_DOM_JS, drip)
            print("적용 전 노드:", before and before["nodes"])
            pub._apply_emphasis(drip, style)  # 내부에서 한 번만 선택(실제 퍼블리시와 동일)
            after = page.evaluate(_DOM_JS, drip)
            if after:
                print(f"적용 후: size={after['fontSize']} color={after['color']} "
                      f"font={after['fontFamily']}")
                print("HTML:", after["html"])
            else:
                print("적용 후: 문단 못 찾음")
        print("\n[probe] 저장 없이 종료.")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
