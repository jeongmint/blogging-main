"""스와치 우선 _apply_color 검증 — 라이브 세션(비대화형).

실제 게시 경로(publish, 임시저장만)로 강조 4건을 넣고:
  · 1~3건: 파워단축키 색(SE 프리셋 멤버) → 스와치 1클릭 경로
  · 4건째: 임의색 #E53935(프리셋에 없음) → 더보기 hex 폴백 경로
저장→재로드 후 각 문구의 적용색이 목표색과 일치하는지 확인하고, 총 소요시간을 잰다.

실행: .venv/bin/python scripts/verify_swatch_apply.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.emphasis import EmphasisStyle, StyledSpan  # noqa: E402
from autoblog.publish.plan import PublishBlock, PublishPlan  # noqa: E402

PROBE_TITLE = "ZZ_강조속도프로브_삭제대상"

# (문구, 스타일, 기대 글자색RGB, 기대 배경RGB)  기대색이 None이면 검사 안 함
CASES = [
    ("강조하나", EmphasisStyle(text_color="#EB7D7D"), (235, 125, 125), None),
    ("강조둘", EmphasisStyle(text_color="#EB7D7D", background_color="#FEF3C7"),
     (235, 125, 125), (254, 243, 199)),
    ("주의셋", EmphasisStyle(text_color="#BE123C", background_color="#FFE4E6"),
     (190, 18, 60), (255, 228, 230)),
    ("폴백넷", EmphasisStyle(text_color="#E53935"), (229, 57, 53), None),  # 프리셋에 없음 → 더보기 폴백
]

BODY = (
    "여기 " + CASES[0][0] + " 그리고 " + CASES[1][0] + " 또 " + CASES[2][0]
    + " 마지막으로 " + CASES[3][0] + " 까지 네 곳에 강조를 넣어 검증합니다."
)

_APPLIED_STYLE_JS = r"""
(t) => {
  const roots = document.querySelectorAll('.se-component.se-text');
  for (const root of roots) {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while (n = w.nextNode()) {
      if ((n.textContent || '').indexOf(t) === -1) continue;
      let color = '', bg = '', cur = n.parentElement;
      for (let i = 0; i < 4 && cur; i++) {
        const cs = getComputedStyle(cur);
        if (!color && cs.color && cs.color !== 'rgb(0, 0, 0)') color = cs.color;
        if (!bg && cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)') bg = cs.backgroundColor;
        cur = cur.parentElement;
      }
      return {color, bg};
    }
  }
  return null;
}
"""


def rgb_of(s):
    import re
    m = re.findall(r"\d+", s or "")
    return (int(m[0]), int(m[1]), int(m[2])) if len(m) >= 3 else None


def close(a, b, tol=12):
    if a is None or b is None:
        return False
    return sum((x - y) ** 2 for x, y in zip(a, b)) <= tol ** 2


def _cleanup(pub, page):
    try:
        if "postwrite" not in (page.url or ""):
            pub.open_write_page()
        pub._open_draft_list()
        for _ in range(8):
            items = pub._read_draft_items()
            idxs = [it["idx"] for it in items if (it.get("title") or "").strip() == PROBE_TITLE]
            if not idxs:
                return
            dels = page.query_selector_all(SMART_EDITOR["draft_item_delete"])
            if idxs[0] >= len(dels):
                return
            try:
                dels[idxs[0]].click(timeout=4000)
            except Exception:
                return
            page.wait_for_timeout(500)
            conf = page.query_selector(SMART_EDITOR["draft_delete_confirm"])
            if conf and conf.is_visible():
                conf.click()
                page.wait_for_timeout(600)
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] 경고(무시): {exc}")


def main() -> int:
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[verify] 세션 없음 — 중단")
            return 1
        _cleanup(pub, pub._page)

        spans = [StyledSpan(text=t, preset_id=None, style=st) for t, st, _, _ in CASES]
        plan = PublishPlan(
            title=PROBE_TITLE,
            blocks=[PublishBlock(kind="text", text=BODY, emphases=spans)],
        )
        t0 = time.perf_counter()
        warnings = pub.publish(plan, save=True, submit=False, prune_same_title=False)
        dt = time.perf_counter() - t0
        print(f"\n[verify] publish(강조 {len(spans)}건) 총 {dt:.1f}s, 경고={warnings or '없음'}")

        # 재로드 후 색 검증
        pub.open_write_page()
        page = pub._page
        pub._open_draft_list()
        items = pub._read_draft_items()
        tgt = next((it["idx"] for it in items
                    if (it.get("title") or "").strip() == PROBE_TITLE), None)
        ok_all = True
        if tgt is None:
            print("[verify] 재로드 실패 — 목록에서 프로브 글 못 찾음")
            ok_all = False
        else:
            buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
            buttons[tgt].click()
            page.wait_for_timeout(1500)
            conf = page.query_selector(SMART_EDITOR["draft_load_confirm"])
            if conf and conf.is_visible():
                conf.click()
            page.wait_for_timeout(1800)
            print(f"\n{'문구':<8}{'기대 글자색':<16}{'실제':<16}{'배경 기대→실제':<22}판정")
            print("-" * 72)
            for text, _, want_c, want_b in CASES:
                st = page.evaluate(_APPLIED_STYLE_JS, text) or {}
                got_c = rgb_of(st.get("color"))
                got_b = rgb_of(st.get("bg"))
                c_ok = close(got_c, want_c)
                b_ok = (want_b is None) or close(got_b, want_b)
                ok = c_ok and b_ok
                ok_all = ok_all and ok
                print(f"{text:<8}{str(want_c):<16}{str(got_c):<16}"
                      f"{str(want_b)+'→'+str(got_b):<22}{'✅' if ok else '❌'}")
        print("\n[verify] 결과:", "전부 통과 ✅" if ok_all else "일부 실패 ❌ — 확인 필요")

        _cleanup(pub, page)
        return 0 if ok_all else 2
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
