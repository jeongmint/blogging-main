"""게시 경로의 고정 대기(wait_for_timeout) 시간을 호출지점별로 프로파일링 — 라이브.

page.wait_for_timeout 을 래핑해 '호출한 editor.py 줄번호별 누적 ms/횟수'를 모은다.
대표 플랜(제목 + 텍스트 강조 + 구분선 + 인용구)을 임시저장하고, 총 벽시계 시간과
고정 대기 합, 그리고 가장 오래 잡아먹은 대기 지점 TOP을 출력한다.

→ 큰 대기부터, '요소 등장' 같은 관측 가능한 신호가 있는 것만 wait_for_selector로
  안전하게 교체하기 위한 근거 데이터.

실행: .venv/bin/python scripts/profile_publish_waits.py
"""

from __future__ import annotations

import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.emphasis import EmphasisStyle, StyledSpan  # noqa: E402
from autoblog.publish.plan import PublishBlock, PublishPlan  # noqa: E402

PROBE_TITLE = "ZZ_강조속도프로브_삭제대상"

# 대표 본문 — 텍스트 강조 여러 개 + 구분선 + 인용구로 주요 대기 경로를 두루 탄다.
PARA = ("정말 맛있는 집이었어요. 분위기도 좋고 직원분들도 친절했습니다. "
        "특히 시그니처 메뉴가 인상적이었고 가격도 합리적이라 만족스러웠어요.")
SPAN_TEXTS = ["맛있는", "친절", "시그니처", "합리적"]
STYLE = EmphasisStyle(text_color="#EB7D7D")


def build_plan() -> PublishPlan:
    blocks = []
    for i in range(3):  # 텍스트 문단 3개(각 강조 포함)
        spans = [StyledSpan(text=t, preset_id=None, style=STYLE) for t in SPAN_TEXTS if t in PARA]
        blocks.append(PublishBlock(kind="text", text=PARA, emphases=spans))
    blocks.append(PublishBlock(kind="divider", variant=1, align="center"))
    blocks.append(PublishBlock(kind="quote", text="한 줄 인용\n두 번째 줄", variant=1))
    blocks.append(PublishBlock(kind="text", text=PARA,
                               emphases=[StyledSpan(text="만족", preset_id=None, style=STYLE)]))
    return PublishPlan(title=PROBE_TITLE, blocks=blocks)


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
            print("[profile] 세션 없음 — 중단")
            return 1
        _cleanup(pub, pub._page)
        page = pub._page

        # wait_for_timeout 래핑 — editor.py 내 호출 지점(줄번호)별로 누적.
        orig = page.wait_for_timeout
        stats = defaultdict(lambda: [0.0, 0])  # site -> [총ms, 횟수]
        editor_file = "editor.py"

        def wrapped(ms, *a, **k):
            site = "?"
            for fr in reversed(traceback.extract_stack()):
                if editor_file in fr.filename:
                    site = f"editor.py:{fr.lineno}"
                    break
            stats[site][0] += ms
            stats[site][1] += 1
            return orig(ms, *a, **k)

        page.wait_for_timeout = wrapped

        t0 = time.perf_counter()
        warnings = pub.publish(build_plan(), save=True, submit=False, prune_same_title=False)
        wall = time.perf_counter() - t0
        page.wait_for_timeout = orig

        total_wait = sum(v[0] for v in stats.values())
        print(f"\n총 벽시계 {wall:.1f}s, 고정대기 합 {total_wait/1000:.1f}s "
              f"({total_wait/1000/wall*100:.0f}%), 경고={warnings or '없음'}\n")
        print(f"{'호출지점':<20}{'누적s':>8}{'횟수':>6}{'평균ms':>8}")
        print("-" * 44)
        for site, (ms, n) in sorted(stats.items(), key=lambda x: -x[1][0]):
            print(f"{site:<20}{ms/1000:>8.2f}{n:>6}{ms/n:>8.0f}")

        _cleanup(pub, page)
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
