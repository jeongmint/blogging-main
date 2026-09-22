"""in-place처럼 본문 '중간'에 협찬 사진을 넣었을 때 크기·정렬이 그 사진에 걸리는지 검증.

기존 버그: _resize_image_smallest가 imgs[-1](문서 마지막 사진)을 잡아, 역순 삽입되는
in-place에선 엉뚱한 사진이 작아지고 협찬 사진은 그대로였다. 수정 후에는 업로드 전
src 목록과 대조해 '새로 생긴' 사진을 정확히 잡는다.

흐름: 새 글 → 사진 A, B 업로드(끝) → A 뒤에 앵커(Enter) → 협찬 사진 C를 size="small"로
삽입(중간) → 세 컴포넌트의 섹션 클래스를 덤프해 '가운데(C만) + 작게'가 C에 걸렸는지 확인.
새 글이라 저장하지 않는다.

실행: .venv/bin/python scripts/probe_inplace_sponsor_resize.py [--headless]
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402


def make_img(color: str) -> str:
    from PIL import Image

    fd, p = tempfile.mkstemp(prefix=f"probe_{color}_", suffix=".png")
    Image.new("RGB", (1200, 600), color).save(p)
    return p


def dump_sections(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('.se-component.se-image')].map((c, i) => {
             const sec = c.querySelector("[class*='se-section-']");
             const im = c.querySelector('img');
             return {i, cls: sec ? sec.className.toString() : '',
                     w: im ? Math.round(im.getBoundingClientRect().width) : 0};
           })"""
    )


def main() -> int:
    headless = "--headless" in sys.argv
    a, b, c = make_img("red"), make_img("green"), make_img("blue")
    pub = BlogPublisher(headless=headless).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음")
            return 1
        pub.open_write_page()
        page = pub._page
        page.click(SMART_EDITOR["content_component"])

        print("[probe] A, B 업로드(끝에)…")
        assert pub._insert_image(a) is None
        assert pub._insert_image(b) is None

        print("[probe] A 뒤에 앵커 → C를 size=small로 중간 삽입…")
        assert pub._anchor_after_photo(0)
        warn = pub._insert_image(c, size="small")
        print(f"[probe] _insert_image(C, small) 경고: {warn!r}")

        secs = dump_sections(page)
        for s in secs:
            print(f"  img[{s['i']}] w={s['w']}px {s['cls']}")
        # C는 중간(인덱스 1)에 들어가야 하고, C만 가운데 정렬 + 다른 사진보다 좁아야 한다
        centered = [s["i"] for s in secs if "se-section-align-center" in s["cls"]]
        assert len(secs) == 3, f"사진 3장이어야 함: {len(secs)}"
        assert centered == [1], f"가운데 정렬은 중간 사진(C)만이어야 함: {centered}"
        assert secs[1]["w"] < secs[0]["w"], f"C({secs[1]['w']}px)가 A({secs[0]['w']}px)보다 작아야 함"
        print("[probe] PASS — 중간 삽입된 협찬 사진에만 작게+가운데가 걸림")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
