"""'테스트' 임시저장 글로 in-place 사진 재배치 프리미티브를 검증하는 1회성 probe(비파괴).

검증 항목:
  1) 구조 덤프 — 콜라주/영상/사진/텍스트가 SE DOM에서 어떤 클래스·순서인지 실측.
  2) 삭제 — 특정 사진 컴포넌트를 선택→Delete로 지울 수 있는가.
  3) 위치 재삽입 — 커서를 '영상1 바로 뒤'에 두고 이미지 업로드 시, 그 위치에 꽂히는가
     (맨 끝에 붙는 게 아니라).

전부 비파괴: 임시저장을 누르지 않으므로 원본 '테스트' 글은 변하지 않는다(브라우저만 닫음).
헤드리스(백그라운드)로 돈다.

실행:
    .venv/bin/python scripts/probe_test_draft_structure.py [draft_idx]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
INSERT_IMG = str(REPO / "config" / "editor_previews" / "divider_default.png")

# 각 .se-component의 종류/내부 img·video 개수/텍스트 조각을 컴팩트하게 덤프.
_DUMP_JS = r"""
() => {
  const comps = [...document.querySelectorAll('.se-component')];
  return comps.map((c, i) => {
    const cls = c.className.toString();
    const imgs = c.querySelectorAll('img.se-image-resource').length;
    const isVid = /se-video/.test(cls);
    const isTitle = /se-documentTitle/.test(cls);
    let kind = 'other';
    if (isTitle) kind = 'title';
    else if (isVid) kind = 'video';
    else if (imgs >= 2) kind = 'collage';
    else if (imgs === 1) kind = 'image';
    else if (/se-text/.test(cls)) kind = 'text';
    const txt = (c.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 24);
    return { i, kind, imgs, txt };
  });
}
"""


def dump(page, label: str):
    rows = page.evaluate(_DUMP_JS)
    seq = " ".join(r["kind"][0].upper() if r["kind"] != "image" else "i" for r in rows)
    print(f"\n===== {label} (총 {len(rows)}) =====")
    print(f"  순서: {seq}")
    for r in rows:
        extra = f" img={r['imgs']}" if r["kind"] in ("image", "collage") else ""
        t = f"  {r['txt']!r}" if r["txt"] else ""
        print(f"  [{r['i']:>2}] {r['kind']:<7}{extra}{t}")
    return rows


def main() -> int:
    draft_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단")
            return 1
        pub.open_write_page()
        page = pub._page

        print(f"[probe] 임시저장 {draft_idx}번(맨 위=테스트) 불러오는 중…")
        pub._load_draft_into_editor(draft_idx)
        page.wait_for_timeout(1500)

        dump(page, "BEFORE")
        n_img0 = len(page.query_selector_all(SMART_EDITOR["editor_image"]))
        n_vid = len(page.query_selector_all(SMART_EDITOR["editor_video"]))
        print(f"\n[probe] 사진 {n_img0}장 / 영상 {n_vid}개")

        # ---- 검증 2: 사진 삭제 (영상1 바로 뒤 첫 사진 = editor_image[1]) ----
        print("\n[probe] === 삭제 테스트: editor_image[1] 선택→Delete ===")
        imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
        target = imgs[1]
        target.scroll_into_view_if_needed()
        target.click()  # 이미지 컴포넌트 객체 선택
        page.wait_for_timeout(300)
        page.keyboard.press("Delete")
        page.wait_for_timeout(600)
        n_img1 = len(page.query_selector_all(SMART_EDITOR["editor_image"]))
        print(f"[probe] 삭제 후 사진 {n_img1}장 (기대 {n_img0 - 1}) → {'OK' if n_img1 == n_img0 - 1 else '실패'}")
        dump(page, "AFTER DELETE")

        # ---- 검증 3: 위치 재삽입 (영상1 바로 뒤에 커서 → 이미지 업로드) ----
        print("\n[probe] === 위치삽입 테스트: 영상1 뒤에 커서 → 이미지 업로드 ===")
        vids = page.query_selector_all(SMART_EDITOR["editor_video"])
        vids[0].scroll_into_view_if_needed()
        vids[0].click()  # 영상1 객체 선택
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")  # 영상1 바로 뒤 빈 문단 + 커서
        page.wait_for_timeout(300)
        pub._insert_image(INSERT_IMG)  # 현재 커서 위치에 업로드
        page.wait_for_timeout(1500)
        n_img2 = len(page.query_selector_all(SMART_EDITOR["editor_image"]))
        print(f"[probe] 삽입 후 사진 {n_img2}장 (기대 {n_img1 + 1}) → {'OK' if n_img2 == n_img1 + 1 else '실패'}")
        after = dump(page, "AFTER INSERT")

        # 삽입된 사진이 '영상1 바로 뒤'인지 위치 확인
        kinds = [r["kind"] for r in after]
        vpos = [i for i, k in enumerate(kinds) if k == "video"]
        if vpos:
            right_after = kinds[vpos[0] + 1] if vpos[0] + 1 < len(kinds) else None
            print(f"[probe] 영상1 바로 뒤 컴포넌트 종류 = {right_after} "
                  f"→ {'OK(사진이 영상 바로 뒤)' if right_after == 'image' else '위치 확인 필요'}")

        print("\n[probe] (비파괴 — 저장 안 함)")
        return 0
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
