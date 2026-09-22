"""협찬 사진 '작게' 후 가운데 정렬이 안 되는 원인 캡처용 1회성 프로브.

_center_image 가 쓰는 셀렉터(li.se-toolbar-item-align button →
button[data-name="align"][data-value="center"])가 '작게' 배치된 이미지 선택
상태에서 실제로 존재/보이는지, 정렬 후 se-section-align-center 가 붙는지 라이브
DOM에서 확인한다. 실패 시 화면에 보이는 정렬 후보 버튼을 전부 덤프한다.

실행:
    .venv/bin/python scripts/probe_image_center.py [--headless]
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

# 정렬 관련 DOM 상태 덤프: align 토큰이 들어간 보이는 버튼/리스트 전부 + 이미지 섹션 클래스.
_DUMP_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const hits = [];
  for (const el of document.querySelectorAll('button, li')) {
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    const dn = el.getAttribute('data-name') || '';
    const dv = el.getAttribute('data-value') || '';
    const aria = el.getAttribute('aria-label') || '';
    if (!/align|정렬/i.test(cls + ' ' + dn + ' ' + aria)) continue;
    hits.push({ tag: el.tagName.toLowerCase(), cls, dataName: dn, dataValue: dv,
                aria, visible: vis(el) });
  }
  const comp = document.querySelector('.se-component.se-image.se-is-selected')
            || document.querySelector('.se-component.se-image');
  const sec = comp ? comp.querySelector("[class*='se-section-']") : null;
  const alignBtn = document.querySelector('li.se-toolbar-item-align button');
  return {
    hits,
    compSelected: !!(comp && comp.className.toString().includes('se-is-selected')),
    secClass: sec ? sec.className.toString() : '(없음)',
    alignBtnFound: !!alignBtn,
    alignBtnVisible: alignBtn ? vis(alignBtn) : false,
    alignBtnCount: document.querySelectorAll('li.se-toolbar-item-align button').length,
  };
}
"""


def dump(page, label: str):
    data = page.evaluate(_DUMP_JS)
    print(f"\n===== {label} =====")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def main() -> int:
    headless = "--headless" in sys.argv
    from PIL import Image

    fd, img = tempfile.mkstemp(prefix="probe_", suffix=".png")
    Image.new("RGB", (1200, 600), "#cccccc").save(img)

    pub = BlogPublisher(headless=headless).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 브라우저에서 로그인하세요…")
            if not pub.wait_for_login():
                print("[probe] 로그인 실패/시간초과")
                return 1
        pub.open_write_page()
        page = pub._page
        page.click(SMART_EDITOR["content_component"])

        print("[probe] 이미지 업로드 중…")
        with page.expect_file_chooser() as fc:
            page.click(SMART_EDITOR["image_upload_button"])
        fc.value.set_files(img)
        for _ in range(30):
            page.wait_for_timeout(500)
            if page.query_selector_all(SMART_EDITOR["editor_image"]):
                break
        page.wait_for_timeout(800)

        imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
        if not imgs:
            print("[probe] 이미지 삽입 확인 실패")
            return 1
        imgs[-1].click()
        page.wait_for_timeout(400)
        dump(page, "이미지 선택 직후")

        print("[probe] '작게' 클릭…")
        page.click(SMART_EDITOR["image_size_smallest"], timeout=8000)
        page.wait_for_timeout(500)
        dump(page, "'작게' 클릭 후")

        print("[probe] _center_image() 실행…")
        ok = pub._center_image()
        print(f"[probe] _center_image → {ok}")
        after = dump(page, "_center_image 후")

        if not after["secClass"].count("se-section-align-center"):
            # 실패 — 정렬 드롭다운을 직접 열어 옵션 전체를 덤프
            imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
            imgs[-1].click()
            page.wait_for_timeout(300)
            page.evaluate(
                "()=>{const b=document.querySelector('li.se-toolbar-item-align button');if(b)b.click();}"
            )
            page.wait_for_timeout(400)
            dump(page, "정렬 드롭다운 연 상태(옵션 후보)")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
