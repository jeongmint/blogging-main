"""SE-ONE ① 사진 선택 시 네이티브 '순서 이동' 버튼 유무 ② 영상 컴포넌트 구조 확인 프로브.

배경: 임시저장 글을 in-place로 편집할 때, 사진 '재배치'가 필요하면 어떻게 할지가 관건.
- 사진을 선택하면 뜨는 컴포넌트 툴바에 위/아래 이동(순서) 버튼이 있으면 프로그램 재배치 가능.
- 영상(동영상)은 사진처럼 CDN 다운로드→재업로드가 안 되므로, '다운로드→새 글 재작성'(B)
  폴백을 쓰면 영상이 어떻게 되는지(살아남는지/사라지는지) 구조부터 확인해야 한다.

실행:
    .venv/bin/python scripts/probe_reorder_and_video.py [draft_idx]
  draft_idx: 사진+영상이 있는 임시저장 글 번호(기본 0).

비파괴: 임시저장 안 누름. 클릭으로 선택만 하고 구조를 덤프한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

# 본문 컴포넌트 전체를 종류+영상포함여부로 덤프.
_DUMP_COMPS_JS = r"""
() => {
  const comps = [...document.querySelectorAll('.se-component')];
  return comps.map((c, i) => {
    const cls = c.className.toString();
    const hasVideo = !!c.querySelector('video, iframe, .se-video, [class*=video]');
    let kind = 'other';
    if (/se-video/.test(cls) || hasVideo) kind = 'video';
    else if (/se-image/.test(cls)) kind = 'image';
    else if (/se-text/.test(cls)) kind = 'text';
    return { i, kind, cls: cls.slice(0, 80), hasVideo,
             html: /se-video/.test(cls) || hasVideo ? c.outerHTML.slice(0, 600) : '' };
  });
}
"""

# 현재 선택된(또는 화면에 보이는) 컴포넌트 툴바의 모든 버튼을 덤프 — '이동/순서' 후보 탐지.
_DUMP_TOOLBAR_JS = r"""
() => {
  const move = /(이동|순서|위치|앞|뒤|위로|아래|move|order|up|down|forward|backward|prev|next)/i;
  const out = [];
  // 컴포넌트 선택 시 뜨는 플로팅 툴바 후보들
  const sels = '.se-component-toolbar button, .se-toolbar button, [class*=component-toolbar] button, [class*=arrange] button, [class*=floating] button';
  for (const el of document.querySelectorAll(sels)) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;  // 숨김 제외
    const aria = el.getAttribute('aria-label') || '';
    const title = el.getAttribute('title') || '';
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    const txt = (el.textContent || '').trim().slice(0, 20);
    const blob = `${aria} ${title} ${cls} ${txt}`;
    out.push({ cls, aria, title, txt, isMove: move.test(blob) });
  }
  return out;
}
"""


def load_draft(pub, idx: int) -> bool:
    page = pub._page
    pub._open_draft_list()
    buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
    if not buttons or idx >= len(buttons):
        print(f"[probe] 임시저장 {idx}번 없음(총 {len(buttons)}건)")
        return False
    buttons[idx].click()
    page.wait_for_timeout(1500)
    confirm = page.query_selector(SMART_EDITOR["draft_load_confirm"])
    if confirm and confirm.is_visible():
        confirm.click()
    page.wait_for_timeout(1500)
    return True


def main() -> int:
    draft_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 브라우저에서 직접 로그인하세요(최대 6분)…")
            if not pub.wait_for_login():
                return 1
        pub.open_write_page()
        page = pub._page

        print(f"[probe] 임시저장 {draft_idx}번 불러오는 중…")
        if not load_draft(pub, draft_idx):
            return 1

        # 1) 컴포넌트 구조(영상 포함 여부)
        comps = page.evaluate(_DUMP_COMPS_JS)
        print(f"\n===== 컴포넌트 구조 (총 {len(comps)}) =====")
        for c in comps:
            v = " [VIDEO]" if c["hasVideo"] else ""
            print(f"  [{c['i']:>2}] {c['kind']:<6}{v} cls={c['cls']!r}")
        videos = [c for c in comps if c["kind"] == "video"]
        images = [c for c in comps if c["kind"] == "image"]

        # 2) 영상 컴포넌트 HTML
        if videos:
            print("\n===== 영상 컴포넌트 outerHTML(앞부분) =====")
            for v in videos:
                print(f"--- comp[{v['i']}] ---\n{v['html']}\n")
        else:
            print("\n[probe] 이 글엔 영상 컴포넌트가 없음(영상 있는 draft_idx로 다시 시도하면 구조 확인 가능)")

        # 3) 사진 선택 → 컴포넌트 툴바의 '이동/순서' 버튼 탐지
        imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
        if not imgs:
            print("\n[probe] 본문에 사진이 없어 이동 버튼 탐지를 건너뜀")
        else:
            pick = min(1, len(imgs) - 1)  # 가운데쯤 사진(앞뒤 이동 둘 다 가능한 위치)
            print(f"\n[probe] {pick}번째 사진 선택 → 컴포넌트 툴바 버튼 덤프…")
            imgs[pick].scroll_into_view_if_needed()
            imgs[pick].click()
            page.wait_for_timeout(600)
            btns = page.evaluate(_DUMP_TOOLBAR_JS)
            movers = [b for b in btns if b["isMove"]]
            print(f"\n===== 선택 시 보이는 툴바 버튼 ({len(btns)}개) =====")
            for b in btns:
                tag = " <== 이동후보" if b["isMove"] else ""
                label = b["aria"] or b["title"] or b["txt"]
                print(f"  - {label!r:<24} cls={b['cls'][:60]!r}{tag}")
            print("\n===== 판정 =====")
            if movers:
                print(f"  ✅ 순서 이동 후보 버튼 {len(movers)}개 발견 — 프로그램 재배치 가능성 있음:")
                for b in movers:
                    print(f"     {b['aria'] or b['title'] or b['txt']!r} cls={b['cls'][:60]!r}")
            else:
                print("  ❌ 이동/순서 관련 버튼 없음 — 네이티브 재배치 버튼 부재(드래그만 가능 추정).")

        if sys.stdin.isatty():
            try:
                input("\n[probe] Enter 로 브라우저 닫기…")
            except EOFError:
                pass
        else:
            print("\n[probe] (비대화형 — 자동 종료)")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
