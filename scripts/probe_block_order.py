"""블록 순서 검증 프로브 — '지도가 맨 위로, 1번 문단이 맨 아래로' 버그의 회귀 검사.

증상(실측): 로컬 웹 미리보기는 순서가 맞는데 네이버로 넣으면 지도 카드가 최상단으로 튀고
번호 소제목 '1.' 문단이 최하단으로 밀렸다. 원인은 두 가지였다.

  ① _insert_place 가 장소 팝업을 열고 닫는 사이 contenteditable 의 selection(캐럿)을 잃고,
     캐럿 없이 '확인'을 누르면 SE 가 카드를 문서 기본 위치(=맨 위)에 꽂았다.
     (_insert_link 에는 activeElement 복구 방어가 있었지만 지도 경로에만 없었다.)
  ② publish_inplace 의 역순 삽입 트릭은 '매번 같은 지점에 앵커가 잡힘'을 전제하는데,
     _anchor_* 가 실패로 False 를 돌려줘도 호출부가 무시했다. 앵커가 빗나가면 그 블록은
     커서가 남아 있던 자리(=직전에 넣은 블록 뒤)에 붙는다. 역순이라 '1.' 문단이 가장
     마지막에 삽입되므로, 그 시점의 실패가 정확히 '1.'을 최하단에 남겼다.

이 프로브는 라이브 세션에서 플랜 순서 ↔ 실제 컴포넌트 순서를 대조해 회귀를 잡는다.
캐럿 헬퍼(_mark_caret/_restore_caret)의 DOM 동작도 함께 검증한다 — 팝업을 여닫은 뒤에도
캐럿이 원래 문단으로 돌아오는지가 ①의 핵심이다.

실행:
    .venv/bin/python scripts/probe_block_order.py [--publish]

  기본은 비파괴(임시저장/발행 안 함 — 브라우저를 닫으면 원본은 그대로).
  --publish 를 주면 임시저장까지 수행해 저장 결과에 내부 표식(data-ab-caret)이 남지 않는지도 본다.

판정: 플랜의 블록 순서와 본문 컴포넌트 순서가 같은 상대 순서인지(지도/텍스트/사진 기준).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.draft.generate import DraftResult  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.plan import build_publish_plan, load_structure_styles  # noqa: E402

# 증상을 그대로 재현하는 최소 초안: 대제목 → 번호 소제목 1./2. → 지도 마커.
# 지도가 '본문 중간'에 있고 그 앞에 번호 문단이 있는 게 재현 조건이다.
DRAFT = """제목 테스트 순서검증

콘셉트 한 줄

1. 첫 번째 문단입니다
여기가 최하단으로 밀리던 자리예요

[구분선]

2. 두 번째 문단입니다
지도 앞 문단이에요

[지도:스타벅스 강남역점]

3. 세 번째 문단입니다
마지막 문단이에요
"""


def hold(msg: str):
    """대화형이면 Enter 대기로 브라우저를 열어두고, 비대화형이면 건너뛴다."""
    if sys.stdin.isatty():
        try:
            input(msg)
        except EOFError:
            pass
    else:
        print(f"{msg} (비대화형 — 자동 종료)")


# 본문 컴포넌트를 문서 순으로 덤프 — 종류와 앞부분 텍스트만.
DUMP_JS = r"""
() => [...document.querySelectorAll('.se-component')].map(c => {
  const cls = c.className.toString();
  let kind = 'text';
  if (/se-documentTitle/.test(cls)) kind = 'title';
  else if (/placesMap|se-map/.test(cls) || c.querySelector('.se-map-image')) kind = 'place';
  else if (/se-horizontalLine/.test(cls)) kind = 'divider';
  else if (/se-sticker/.test(cls)) kind = 'sticker';
  else if (/se-quotation/.test(cls)) kind = 'quote';
  else if (/se-video/.test(cls)) kind = 'video';
  else if (c.querySelector('img.se-image-resource')) kind = 'image';
  return {kind, text: (c.textContent || '').trim().slice(0, 24)};
})
"""


def main() -> int:
    do_publish = "--publish" in sys.argv
    # 실제 발행 경로와 동일하게 구조 서식을 넣는다 — 이때 '1.' 소제목이 별도 인용구(밑줄형)
    # 블록으로 빠지므로, 순서 판정도 텍스트가 아닌 그 블록을 대상으로 해야 재현과 일치한다.
    plan = build_publish_plan(
        DraftResult(text=DRAFT, emphases=[]), structure_styles=load_structure_styles()
    )
    print("=== 플랜 블록 순서(미리보기와 동일한 기준) ===")
    for i, b in enumerate(plan.blocks):
        print(f"  {i:2d} {b.kind:8s} {(b.text or '')[:30]!r}")

    pub = BlogPublisher()
    pub.start()
    if not pub.is_logged_in():
        print("\n로그인이 필요합니다 — 브라우저에서 로그인해 주세요.")
        if not pub.wait_for_login():
            print("로그인 대기 시간이 지났습니다.")
            return 2

    warnings = pub.publish(plan, save=do_publish, submit=False, prune_same_title=False)

    print("\n=== 실제 에디터 컴포넌트 순서 ===")
    comps = pub._page.evaluate(DUMP_JS)
    for i, c in enumerate(comps):
        print(f"  {i:2d} {c['kind']:8s} {c['text']!r}")

    # 판정 ①: 지도가 최상단으로 튀지 않았는지 — 지도 앞에 본문 텍스트가 있어야 한다.
    kinds = [c["kind"] for c in comps if c["kind"] != "title"]
    ok_place = True
    if "place" in kinds:
        before = kinds[: kinds.index("place")]
        ok_place = any(k == "text" for k in before)
        print(f"\n[① 지도 위치] 지도 앞 본문 텍스트 있음 = {ok_place}"
              f" {'OK' if ok_place else '← 회귀! 지도가 최상단으로 튐'}")

    # 판정 ②: '1.' 문단이 '2.'·'3.' 보다 앞에 있는지(최하단으로 밀리지 않았는지).
    order = []
    for i, c in enumerate(comps):
        for n in ("1.", "2.", "3."):
            if c["text"].startswith(n):
                order.append((n, i))
    seq = [n for n, _ in sorted(order, key=lambda x: x[1])]
    ok_order = seq == sorted(seq)
    print(f"[② 문단 순서] 발견 순서 = {seq} {'OK' if ok_order else '← 회귀! 번호 문단이 뒤섞임'}")

    # 판정 ③: 내부 캐럿 표식이 본문에 남지 않았는지.
    left = pub._page.evaluate("()=>document.querySelectorAll('[data-ab-caret]').length")
    print(f"[③ 내부 표식 잔여] {left}개 {'OK' if left == 0 else '← 회귀! 표식이 본문에 남음'}")

    if warnings:
        print("\n경고:")
        for w in warnings:
            print(f"  - {w}")

    hold("\n확인 후 Enter를 누르면 브라우저를 닫습니다...")
    return 0 if (ok_place and ok_order and left == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
