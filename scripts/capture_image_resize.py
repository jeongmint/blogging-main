"""SE-ONE 사진 '크기' 컨트롤을 비대화식으로 캡처(저장 세션 사용, 헤드리스).

probe_image_resize.py는 헤드풀+Enter 대기라 자동 실행이 어렵다. 이 스크립트는 저장된
세션(data/naver_state.json)으로 자동 로그인해 이미지를 올리고 '선택'한 뒤, 선택 전후로
'새로 나타난' 인터랙티브 요소(=사진 전용 플로팅 툴바)를 통째로 떠서 JSON으로 남긴다.

실행:
    .venv/bin/python scripts/capture_image_resize.py

결과: scratchpad/image_resize_dump.json (+ 표준출력 요약). 여기서 '가장 작게' 버튼의
class/data-value를 골라 SMART_EDITOR['image_size_smallest']에 채운다.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

OUT = Path(tempfile.gettempdir()) / "image_resize_dump.json"  # 레포 밖 임시 파일

# 화면에 보이는 모든 인터랙티브 요소를 (식별자, 위치, 전체 속성)으로 덤프하는 JS.
# 선택 전/후 두 번 호출해 '새로 보이게 된' 요소만 추리면 사진 전용 툴바가 드러난다.
_DUMP_JS = r"""
() => {
  const out = [];
  const sel = 'button, li, a, [role=button], [data-name], [data-value], input[type=range]';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;  // 숨김 제외
    const attrs = {};
    for (const a of el.attributes) attrs[a.name] = a.value;
    out.push({
      key: el.tagName.toLowerCase() + '|' + (el.className||'') + '|'
           + (el.getAttribute('data-value')||'') + '|'
           + (el.getAttribute('aria-label')||'') + '|'
           + (el.textContent||'').trim().slice(0,20),
      tag: el.tagName.toLowerCase(),
      cls: (el.className && el.className.toString) ? el.className.toString() : '',
      text: (el.textContent||'').trim().slice(0,40),
      rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
      attrs,
    });
  }
  return out;
}
"""

_COMP_JS = r"""
() => {
  const pick = s => { const e = document.querySelector(s); return e ? e.outerHTML.slice(0, 2500) : null; };
  return {
    selectedImage: pick('.se-component.se-image.se-is-selected'),
    anyImage: pick('.se-component.se-image'),
    // 크기/이미지 관련 컨테이너 후보
    sizeish: [...document.querySelectorAll('[class*=size],[class*=Size],[class*=image-toolbar],[class*=resize]')]
      .filter(e => e.getBoundingClientRect().width > 0)
      .slice(0, 12)
      .map(e => ({cls: e.className.toString(), html: e.outerHTML.slice(0, 600)})),
  };
}
"""


def main() -> int:
    from PIL import Image

    fd, img = tempfile.mkstemp(prefix="capshot_", suffix=".png")
    Image.new("RGB", (1200, 600), "#bcd").save(img)

    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.is_logged_in():
            print("[capture] 저장 세션이 로그인 상태가 아님 — 헤드풀 probe로 직접 로그인 필요")
            return 2
        pub.open_write_page()
        page = pub._page
        page.click(SMART_EDITOR["content_component"])

        before = page.evaluate(_DUMP_JS)
        print("[capture] 이미지 업로드 중…")
        with page.expect_file_chooser() as fc:
            page.click(SMART_EDITOR["image_upload_button"])
        fc.value.set_files(img)
        page.wait_for_timeout(3500)

        imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
        if not imgs:
            print("[capture] 삽입 이미지 못 찾음(editor_image 셀렉터 확인)")
            return 1
        imgs[-1].click()  # 방금 삽입한 사진 선택 → 크기 툴바 노출
        page.wait_for_timeout(700)
        after = page.evaluate(_DUMP_JS)
        comp = page.evaluate(_COMP_JS)

        before_keys = {b["key"] for b in before}
        appeared = [a for a in after if a["key"] not in before_keys]

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps({"appeared": appeared, "comp": comp, "all_after": after}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[capture] 덤프 저장: {OUT}")
        print(f"[capture] 사진 선택 후 '새로 나타난' 요소 {len(appeared)}개:")
        for a in appeared:
            print(f"  <{a['tag']}> rect={a['rect']} class={a['cls']!r}")
            interesting = {k: v for k, v in a["attrs"].items() if k in
                           ("data-name", "data-value", "aria-label", "title", "data-log")}
            if interesting:
                print(f"      attrs={interesting}")
            if a["text"]:
                print(f"      text={a['text']!r}")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
