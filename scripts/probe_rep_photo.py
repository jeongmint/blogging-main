"""대표사진 mechanic 검증: '대표' 배지(.se-set-rep-image-button) 클릭으로 대표를 옮길 수 있는지.

배경: in-place는 사진을 전부 삭제→재삽입하는데, 네이버가 문서에 들고 있는 '대표' 플래그가
삭제 과정에서 남은 사진으로 넘어가 버려, ★ 지정 사진이 아닌 엉뚱한 사진이 대표로 남는다.
→ 저장 직전에 대표를 명시적으로 재지정하는 스텝이 필요. 그 클릭 mechanic을 여기서 검증.

임시저장 글을 불러와: 이미지별 대표 배지 상태 덤프 → 다른 이미지의 배지 클릭 → 플래그가
옮겨갔는지 확인. 비파괴(저장 안 함).

사용: python scripts/probe_rep_photo.py [draft_idx] [target_img_idx]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.publish.editor import BlogPublisher  # noqa: E402

_REP_STATE_JS = r"""
() => [...document.querySelectorAll('.se-component')]
  .filter(c => c.querySelector('img.se-image-resource'))
  .map((c, i) => {
    const btn = c.querySelector('.se-set-rep-image-button');
    return {i, cls: c.className.toString().slice(0, 60),
            hasBtn: !!btn, rep: !!(btn && /se-is-selected/.test(btn.className)),
            btnVisible: !!(btn && btn.offsetParent !== null)};
  })
"""


def dump_state(page, label):
    rows = page.evaluate(_REP_STATE_JS)
    print(f"\n== {label} ==")
    for r in rows:
        mark = " ★대표" if r["rep"] else ""
        print(f"  img[{r['i']}] btn={r['hasBtn']} visible={r['btnVisible']}{mark}  ({r['cls']})")
    return rows


def main() -> int:
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단")
            return 1
        pub.open_write_page()
        page = pub._page
        pub._load_draft_into_editor(idx)
        page.wait_for_timeout(1500)

        rows = dump_state(page, "로드 직후")
        if not rows:
            print("[probe] 이미지 없음 — 다른 draft_idx로 재시도")
            return 1
        target = min(target, len(rows) - 1)

        # 대상 이미지의 대표 배지 클릭(배지가 hover에서만 보이면 hover 후 클릭)
        comps = page.query_selector_all(".se-component")
        img_comps = [c for c in comps if c.query_selector("img.se-image-resource")]
        comp = img_comps[target]
        comp.scroll_into_view_if_needed()
        comp.hover()
        page.wait_for_timeout(300)
        btn = comp.query_selector(".se-set-rep-image-button")
        if btn is None:
            print(f"[probe] img[{target}]에 대표 배지 없음 ❌")
            return 1
        btn.click()
        page.wait_for_timeout(500)

        after = dump_state(page, f"img[{target}] 대표 배지 클릭 후")
        ok = after[target]["rep"] and sum(1 for r in after if r["rep"]) == 1
        print(f"\n[probe] → {'OK ✅ 대표 플래그 이동 확인' if ok else '불일치 ❌'}")
        print("[probe] (비파괴 — 저장 안 함)")
        return 0 if ok else 1
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
