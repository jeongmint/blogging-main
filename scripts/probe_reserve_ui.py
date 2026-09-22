"""SE-ONE 발행 레이어의 '예약 발행' UI 구조를 캡처하는 1회성 프로브(읽기 전용).

목적: 예약 발행 자동화를 붙이려면 발행 레이어에서 '발행시점 → 예약' 라디오를 고르면
나타나는 날짜/시간 피커의 실제 셀렉터를 알아야 한다. 코드베이스엔 아직 없다.
이 프로브는 발행 레이어를 '열기'만 하고 예약 라디오까지만 눌러 DOM을 떠낸 뒤
**Escape로 닫는다 — 절대 발행(tpb*i.publish)을 클릭하지 않는다**(새 글도 저장 안 함).

흐름: 글쓰기 페이지 새로 열기 → 더미 제목/본문 → 발행 레이어 열기 →
(예약 클릭 전) 발행시점 영역 라디오/버튼 덤프 → '예약' 클릭 → (클릭 후) 새로
나타난 날짜/시간 입력·버튼·select 덤프 → Escape.

실행:
    .venv/bin/python scripts/probe_reserve_ui.py            # 헤드풀(직접 눈으로도 확인)
    .venv/bin/python scripts/probe_reserve_ui.py --headless

출력에서 고른 셀렉터를 collect/selectors.py SMART_EDITOR와 editor.set_reserve_time에 채운다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

# 발행 레이어 안의 라디오/버튼/입력/select를 라벨·속성과 함께 떠내는 JS.
# 발행 레이어는 팝업(layer)이라 문서 전체에서 보이는 것만 추린다.
_DUMP_LAYER_JS = r"""
() => {
  const vis = el => el && el.offsetParent !== null;
  const brief = el => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || '',
    cls: (el.className && el.className.toString) ? el.className.toString().slice(0,120) : '',
    id: el.id || '',
    name: el.getAttribute('name') || '',
    value: el.getAttribute('value') || (el.value || ''),
    dataClick: el.getAttribute('data-click-area') || '',
    aria: el.getAttribute('aria-label') || '',
    text: (el.innerText || el.textContent || '').trim().slice(0, 30),
    placeholder: el.getAttribute('placeholder') || '',
  });
  // 발행 레이어 후보 컨테이너(있으면 그 안만, 없으면 문서 전체).
  const layer = document.querySelector('[class*=layer_content], [class*=paper_layer], [class*=option_area]')
             || document;
  const out = {radios: [], buttons: [], inputs: [], selects: [], reserveLabels: []};
  layer.querySelectorAll('label[class*=radio_label], label').forEach(el => {
    if (!vis(el)) return;
    const t = (el.innerText || '').trim();
    if (t) out.radios.push({...brief(el), label: t.split('\n').pop().trim()});
    if (/예약|현재/.test(t)) out.reserveLabels.push({...brief(el), label: t});
  });
  layer.querySelectorAll('button').forEach(el => { if (vis(el)) out.buttons.push(brief(el)); });
  layer.querySelectorAll('input').forEach(el => { if (vis(el)) out.inputs.push(brief(el)); });
  layer.querySelectorAll('select').forEach(el => {
    if (!vis(el)) return;
    const opts = [...el.querySelectorAll('option')].slice(0,6).map(o => o.value + ':' + o.textContent.trim());
    out.selects.push({...brief(el), options: opts});
  });
  return out;
}
"""


def _dump(page, label: str) -> None:
    data = page.evaluate(_DUMP_LAYER_JS)
    print(f"\n===== {label} =====")
    print(json.dumps(data, ensure_ascii=False, indent=2))


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
    pub._type_title("예약 UI 프로브 — 저장/발행 안 함")
    page.click(SMART_EDITOR["content_component"])
    page.keyboard.type("프로브용 임시 본문입니다.")
    page.wait_for_timeout(300)

    # 발행 레이어 열기(발행 아님 — 설정 레이어만 뜬다)
    page.click(SMART_EDITOR["publish_button"])
    page.wait_for_timeout(1500)
    _dump(page, "예약 클릭 전 — 발행 레이어(발행시점 라디오/버튼)")

    # '예약' 라디오 클릭 시도(텍스트로) — 날짜/시간 피커가 나타나는지 본다.
    clicked = False
    for sel in ('label:has-text("예약")', 'text=예약'):
        try:
            page.click(sel, timeout=2000)
            clicked = True
            break
        except Exception:
            continue
    page.wait_for_timeout(800)
    print(f"\n[예약 라디오 클릭 {'성공' if clicked else '실패 — 셀렉터 확인 필요'}]")
    _dump(page, "예약 클릭 후 — 새로 나타난 날짜/시간 입력·select·버튼")

    print(
        "\n해석 가이드:\n"
        " - reserveLabels 에서 '예약' 라벨의 for/id·class 로 라디오 셀렉터를 잡는다.\n"
        " - 예약 클릭 후 inputs/selects 에 날짜·시(hour)·분(minute) 컨트롤이 보이면 그걸 쓴다.\n"
        " - 날짜가 input[type=text] + 달력 버튼이면 값 직접 입력 가능한지, select면 옵션 value 형식 확인.\n"
        " - 이 값들을 selectors.py 와 editor.set_reserve_time 에 채운 뒤, 반드시 '예약됨' 상태를\n"
        "   읽어 확인(fail-closed)하는 가드까지 두고서야 실제 예약 발행을 켠다.\n"
    )
    # 절대 발행하지 않는다 — 레이어만 닫고 종료(새 글이라 저장도 안 함).
    page.keyboard.press("Escape")
    print("프로브 종료 — 발행/저장하지 않았습니다(Escape로 레이어만 닫음).")
    pub.close()


if __name__ == "__main__":
    main()
