"""SE-ONE '사진 사이에 텍스트 끼워넣기' 가능성 검증용 1회성 프로브.

지금 파이프라인은 임시저장 글에서 사진만 추출(다운로드)해 빈 새 글을 처음부터 쓴다.
대안: 임시저장 글을 '그대로' 열어, 사진들 사이사이에 텍스트를 직접 끼워넣고 임시저장(갱신).
이러면 다운로드 시간·용량·원본 삭제가 전부 사라진다. 단, SE-ONE에서 두 컴포넌트
'사이'에 커서를 놓고 타이핑이 거기에 꽂히는지는 라이브에서만 확인 가능 — 이 스크립트로 검증한다.

실행:
    .venv/bin/python scripts/probe_insert_between.py [draft_idx] [after_image_n]

  draft_idx     : 임시저장 목록에서 불러올 글 번호(기본 0 = 가장 최근). 사진 있는 글을 골라야 의미 있음.
  after_image_n : 몇 번째 사진 '뒤'에 끼워넣을지(0-based, 기본 0 = 첫 사진 뒤).

비파괴: 임시저장을 누르지 않으므로 원본 글은 변하지 않는다(브라우저를 직접 닫거나 Enter로 종료).
검증 마커: ★INSERT_TEST★ — 이 텍스트가 의도한 위치(N번째 사진과 그다음 사이)에 들어갔는지
컴포넌트 순서 덤프로 확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

MARKER = "★INSERT_TEST★"


def hold(msg: str):
    """대화형이면 Enter 대기로 브라우저를 열어두고, 비대화형(자동 실행)이면 건너뛴다."""
    if sys.stdin.isatty():
        try:
            input(msg)
        except EOFError:
            pass
    else:
        print(f"{msg} (비대화형 — 자동 종료)")

# 본문 컴포넌트 순서를 [type, 텍스트snippet]로 덤프 — 끼워넣기 전/후 비교용.
_DUMP_ORDER_JS = r"""
() => {
  const comps = [...document.querySelectorAll('.se-component')];
  return comps.map((c, i) => {
    const cls = c.className.toString();
    let kind = 'other';
    if (/se-image/.test(cls)) kind = 'image';
    else if (/se-text/.test(cls)) kind = 'text';
    else if (/se-horizontalLine/.test(cls)) kind = 'divider';
    else if (/se-quotation/.test(cls)) kind = 'quote';
    else if (/se-map|se-placesMap/.test(cls)) kind = 'place';
    const txt = (c.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    return { i, kind, txt };
  });
}
"""


def dump_order(page, label: str):
    rows = page.evaluate(_DUMP_ORDER_JS)
    print(f"\n===== {label} (총 {len(rows)} 컴포넌트) =====")
    for r in rows:
        mark = "  <-- 마커" if MARKER in (r["txt"] or "") else ""
        print(f"  [{r['i']:>2}] {r['kind']:<7} {r['txt']!r}{mark}")
    return rows


def load_draft(pub, idx: int) -> bool:
    """idx번 임시저장 글을 에디터에 로드(다운로드 없음). import_draft_photos의 로드 부분만 발췌."""
    page = pub._page
    pub._open_draft_list()
    buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
    if not buttons:
        print("[probe] 임시저장 글이 없음")
        return False
    if idx < 0 or idx >= len(buttons):
        print(f"[probe] draft_idx 범위 초과: {idx} (총 {len(buttons)}건)")
        return False
    buttons[idx].click()
    page.wait_for_timeout(1500)
    confirm = page.query_selector(SMART_EDITOR["draft_load_confirm"])
    if confirm and confirm.is_visible():
        confirm.click()
    page.wait_for_timeout(1500)
    return True


def insert_after_image(page, n: int) -> bool:
    """N번째 사진 컴포넌트를 선택 → Enter로 바로 뒤에 새 문단 생성 → 마커 타이핑.

    SE-ONE에서 이미지 컴포넌트를 클릭하면 객체 선택(se-is-selected)되고, 그 상태로 타이핑하면
    글자가 허공으로 사라진다(에디터 코드 주석 참고). 그래서 타이핑 전에 Enter를 눌러 사진 뒤에
    빈 문단을 만든 다음 거기 타이핑한다 — 이게 '사이 끼워넣기'의 핵심 동작."""
    imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
    if not imgs:
        print("[probe] 본문에 사진이 없음 — 사진 있는 draft_idx로 다시 시도하세요")
        return False
    if n < 0 or n >= len(imgs):
        print(f"[probe] after_image_n 범위 초과: {n} (사진 {len(imgs)}장)")
        return False
    print(f"[probe] {n}번째 사진 선택 → Enter → 타이핑 …")
    imgs[n].scroll_into_view_if_needed()
    imgs[n].click()  # 사진 컴포넌트 선택
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")  # 사진 바로 뒤에 새 문단
    page.wait_for_timeout(400)
    page.keyboard.type(f"{MARKER} 사진 사이에 끼워넣은 본문 한 줄입니다.", delay=8)
    page.wait_for_timeout(500)
    return True


def main() -> int:
    draft_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    after_n = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 브라우저에서 직접 로그인하세요(최대 6분 대기)…")
            if not pub.wait_for_login():
                print("[probe] 로그인 실패/시간초과")
                return 1
        pub.open_write_page()
        page = pub._page

        print(f"[probe] 임시저장 {draft_idx}번 글 불러오는 중…")
        if not load_draft(pub, draft_idx):
            return 1

        before = dump_order(page, "끼워넣기 BEFORE")
        ok = insert_after_image(page, after_n)
        if not ok:
            hold("[probe] Enter 로 종료…")
            return 1
        after = dump_order(page, "끼워넣기 AFTER")

        # 검증: 마커가 (after_n번째 image) 바로 다음 컴포넌트에 들어갔는가?
        img_positions = [r["i"] for r in after if r["kind"] == "image"]
        marker_rows = [r for r in after if MARKER in (r["txt"] or "")]
        print("\n===== 판정 =====")
        if not marker_rows:
            print("  ❌ 마커가 본문 어디에도 없음 — 타이핑이 사라짐(객체선택 문제 등). Enter 전략 실패.")
        else:
            m = marker_rows[0]["i"]
            target_img = img_positions[after_n] if after_n < len(img_positions) else None
            if target_img is not None and m == target_img + 1:
                print(f"  ✅ 성공: 마커가 {after_n}번째 사진(comp[{target_img}]) 바로 뒤 comp[{m}]에 들어감.")
                print("     → '사이 끼워넣기' 가능. 다운로드/재작성 없이 in-place 편집 경로가 열림.")
            else:
                print(f"  ⚠️ 마커는 comp[{m}]에 있으나 기대 위치(comp[{(target_img or 0)+1}])와 다름.")
                print("     → 끼워넣기 자체는 되지만 위치 제어에 추가 작업 필요(커서 타게팅).")

        print(
            "\n[probe] 브라우저는 열어둡니다 — 화면에서 마커가 사진 사이에 들어갔는지 눈으로 확인하세요.\n"
            "        ※ 임시저장은 누르지 않았으니 원본 글은 그대로입니다."
        )
        hold("[probe] 확인 끝나면 Enter 로 브라우저 닫기…")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
