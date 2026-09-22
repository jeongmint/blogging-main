"""SE-ONE 사진 '크기' 컨트롤 셀렉터 캡처용 1회성 프로브.

협찬 고지 사진을 '가장 작게' 표시하려면, 삽입한 이미지를 선택했을 때 뜨는 네이버
스마트에디터(SE-ONE)의 크기 컨트롤 셀렉터가 필요하다. 이 셀렉터는 라이브에서만 확인
가능하므로(로그인 세션 필요), 이 스크립트로 실제 DOM을 떠서 채운다.

실행:
    .venv/bin/python scripts/probe_image_resize.py [이미지경로]

이미지 경로를 안 주면 임시 PNG를 만들어 올린다. 로그인 세션(data/naver_state.json)이
없으면 브라우저에서 직접 로그인할 때까지 기다린다. 끝나면 아래를 출력한다:
  1) 사진을 선택한 직후 떠 있는 '크기 관련' 후보 버튼들(클래스/aria-label/텍스트)
  2) 선택된 이미지 컴포넌트(.se-component.se-image)의 outerHTML 일부

출력에서 '가장 작게'에 해당하는 버튼의 셀렉터를 골라
collect/selectors.py 의 SMART_EDITOR["image_size_smallest"](필요시 image_size_menu)에 넣으면 된다.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

# 사진을 선택하면 뜨는 툴바에서 '크기' 후보를 추려내는 JS.
# 화면에 보이는 button/li 중 클래스·aria-label·텍스트에 size/크기/% 가 들어간 것들을 덤프.
_DUMP_JS = r"""
() => {
  const hit = [];
  const want = /(size|크기|작|small|narrow|width|\d{2,3}\s*%|원본|기본)/i;
  const sel = 'button, li, a, [role=button], [data-name], [data-value]';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;            // 숨김 제외
    const label = (el.getAttribute('aria-label') || '') + ' '
                + (el.getAttribute('title') || '') + ' '
                + (el.getAttribute('data-name') || '') + ' '
                + (el.getAttribute('data-value') || '') + ' '
                + (el.textContent || '').trim().slice(0, 30);
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    if (!want.test(label) && !want.test(cls)) continue;
    hit.push({ tag: el.tagName.toLowerCase(), cls, label: label.trim(),
               aria: el.getAttribute('aria-label') || '',
               dataName: el.getAttribute('data-name') || '',
               dataValue: el.getAttribute('data-value') || '' });
  }
  const comp = document.querySelector('.se-component.se-image.se-is-selected')
            || document.querySelector('.se-component.se-image');
  return { hits: hit, compHtml: comp ? comp.outerHTML.slice(0, 1200) : '(선택된 이미지 컴포넌트 없음)' };
}
"""


def main() -> int:
    img = sys.argv[1] if len(sys.argv) > 1 else None
    if not img:
        from PIL import Image

        fd, img = tempfile.mkstemp(prefix="probe_", suffix=".png")
        Image.new("RGB", (1200, 600), "#cccccc").save(img)
        print(f"[probe] 테스트 이미지 생성: {img}")

    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 브라우저에서 직접 로그인하세요(최대 6분 대기)…")
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
        page.wait_for_timeout(3000)

        imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
        if not imgs:
            print("[probe] 본문에서 삽입된 이미지를 못 찾음(editor_image 셀렉터 확인 필요)")
            return 1
        imgs[-1].click()  # 방금 삽입한 사진 선택 → 크기 툴바 노출
        page.wait_for_timeout(600)

        data = page.evaluate(_DUMP_JS)
        print("\n===== 크기 관련 후보 버튼 =====")
        if not data["hits"]:
            print("(후보 없음 — 사진을 선택해도 크기 메뉴가 안 뜨거나, 먼저 다른 버튼을 눌러 펼쳐야 할 수 있음)")
        for h in data["hits"]:
            print(f"- <{h['tag']}> class={h['cls']!r}")
            if h["aria"]:
                print(f"    aria-label={h['aria']!r}")
            if h["dataName"] or h["dataValue"]:
                print(f"    data-name={h['dataName']!r} data-value={h['dataValue']!r}")
            if h["label"]:
                print(f"    text/label={h['label']!r}")

        print("\n===== 선택된 이미지 컴포넌트 outerHTML(앞부분) =====")
        print(data["compHtml"])
        print(
            "\n[probe] 위에서 '가장 작게'에 해당하는 버튼의 클래스/data-value로 셀렉터를 만들어\n"
            "        collect/selectors.py 의 SMART_EDITOR['image_size_smallest']에 넣으세요.\n"
            "        (브라우저는 열어둘게요 — 직접 사진을 클릭해 크기 메뉴를 눈으로 확인해도 됩니다.)"
        )
        input("[probe] 확인이 끝나면 Enter 를 누르면 브라우저를 닫습니다…")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
