"""SE-ONE 발행 레이어의 '태그 입력칸'을 캡처하는 1회성 프로브(읽기 전용).

목적: plan.tags를 네이버 발행 태그칸에 자동 입력하려면 태그 input의 실제 셀렉터를
알아야 한다. 현재 selectors.py의 tag_input('input[placeholder*="태그"]')은 추정치다.
이 프로브는 발행 레이어를 '열기'만 하고 input들을 떠낸 뒤, 추정 셀렉터로 실제로
태그 하나를 쳐서 칩이 생기는지까지 확인하고 **Escape로 닫는다 — 절대 발행하지 않는다**.

흐름: 글쓰기 페이지 새로 열기 → 더미 제목/본문 → 발행 레이어 열기 →
input/태그영역 덤프 → tag_input 셀렉터로 '프로브태그' 입력+Enter → 칩 생성 확인 →
칩 삭제(가능하면) → Escape.

실행:
    .venv/bin/python scripts/probe_tag_input.py            # 헤드풀(직접 눈으로도 확인)
    .venv/bin/python scripts/probe_tag_input.py --headless

출력에서 확정한 셀렉터를 collect/selectors.py SMART_EDITOR["tag_input"]에 채운다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

# 발행 레이어 안의 input과 '태그' 관련 요소를 속성과 함께 떠내는 JS.
_DUMP_TAGS_JS = r"""
() => {
  const vis = el => el && el.offsetParent !== null;
  const brief = el => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || '',
    cls: (el.className && el.className.toString) ? el.className.toString().slice(0,120) : '',
    id: el.id || '',
    name: el.getAttribute('name') || '',
    placeholder: el.getAttribute('placeholder') || '',
    aria: el.getAttribute('aria-label') || '',
    dataClick: el.getAttribute('data-click-area') || '',
    text: (el.innerText || el.textContent || '').trim().slice(0, 40),
  });
  const out = {inputs: [], tagArea: [], chips: []};
  document.querySelectorAll('input').forEach(el => { if (vis(el)) out.inputs.push(brief(el)); });
  // 클래스/텍스트에 '태그(tag)'가 들어간 컨테이너·라벨 후보
  document.querySelectorAll('[class*=tag], label, strong, h3').forEach(el => {
    if (!vis(el)) return;
    const cls = (el.className && el.className.toString) ? el.className.toString() : '';
    const t = (el.innerText || '').trim();
    if (/tag/i.test(cls) || /태그/.test(t.slice(0, 10))) out.tagArea.push(brief(el));
  });
  return out;
}
"""


def _dump(page, label: str):
    data = page.evaluate(_DUMP_TAGS_JS)
    print(f"\n===== {label} =====")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


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
    # 더미 내용(발행 레이어가 열리려면 제목/본문이 있어야 함)
    pub._type_title("태그칸 프로브 — 저장/발행 안 함")
    page.click(SMART_EDITOR["content_component"])
    page.keyboard.type("프로브용 임시 본문입니다.")
    page.wait_for_timeout(300)

    # 발행 레이어 열기(발행 아님 — 설정 레이어만 뜬다)
    page.click(SMART_EDITOR["publish_button"])
    page.wait_for_timeout(1500)
    _dump(page, "발행 레이어 — input/태그영역 후보")

    # 추정 셀렉터로 실제 입력 시험: '프로브태그' + Enter → 칩 생성 확인
    sel = SMART_EDITOR["tag_input"]
    print(f"\n[tag_input 추정 셀렉터] {sel}")
    try:
        inp = page.wait_for_selector(sel, timeout=3000)
        inp.click()
        inp.type("프로브태그")
        page.keyboard.press("Enter")
        page.wait_for_timeout(800)
        chip = page.evaluate(
            "() => (document.body.innerText.match(/#?프로브태그/) || [null])[0]"
        )
        print(f"[입력 시험] 칩 생성 {'성공: ' + chip if chip else '실패 — 칩이 안 보임'}")
        _dump(page, "태그 입력 후 — 칩 상태")
        # 정리: 방금 만든 칩 삭제 시도(백스페이스는 마지막 칩을 지우는 표준 동작)
        if chip:
            inp.click()
            page.keyboard.press("Backspace")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(300)
            left = page.evaluate(
                "() => (document.body.innerText.match(/#?프로브태그/) || [null])[0]"
            )
            print(f"[정리] 칩 삭제 {'실패 — 남아있음(발행 안 하므로 무해)' if left else '성공'}")
    except Exception as exc:  # noqa: BLE001 - 프로브는 진단용
        print(f"[입력 시험] 셀렉터 매칭 실패: {type(exc).__name__}: {exc}")
        print(" → 위 덤프의 inputs에서 태그 input의 class/id/placeholder로 셀렉터를 다시 잡는다.")

    # 절대 발행하지 않는다 — 레이어만 닫고 종료(새 글이라 저장도 안 함).
    page.keyboard.press("Escape")
    print("\n프로브 종료 — 발행/저장하지 않았습니다(Escape로 레이어만 닫음).")
    pub.close()


if __name__ == "__main__":
    main()
