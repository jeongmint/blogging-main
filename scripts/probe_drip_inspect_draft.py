"""최근 임시저장 글의 헤더(대제목·드립) 문단 DOM 검사 — 읽기 전용, 저장 안 함.

유저 보고(드립 줄 서식 미적용)의 실물 확인: 임시저장 목록 상위 몇 개를 열어
본문 앞쪽 텍스트 문단들의 클래스(se-ff-*, se-fs*)와 색을 덤프한다.

실행: .venv/bin/python scripts/probe_drip_inspect_draft.py [개수=2 | 제목키워드...]
(숫자면 최근 N개, 아니면 제목에 키워드가 포함된 글만 검사 — 예: 속초 보정동)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

_HEAD_JS = r"""
() => {
  const out = [];
  const comps = document.querySelectorAll('.se-component');
  for (const c of comps) {
    const cls = c.className.toString();
    let kind = 'etc';
    if (/se-text(\s|$)/.test(cls)) kind = 'text';
    else if (/se-image/.test(cls)) kind = 'image';
    else if (/se-horizontalLine/.test(cls)) kind = 'divider';
    if (kind === 'text') {
      for (const p of c.querySelectorAll('p.se-text-paragraph')) {
        const t = (p.textContent || '').trim();
        if (!t) continue;
        const span = p.querySelector('span');
        out.push({kind, text: t.slice(0, 40), cls: span ? span.className : '',
                  style: span ? (span.getAttribute('style') || '') : ''});
        if (out.length > 8) return out;
      }
    } else {
      out.push({kind, text: '', cls: '', style: ''});
    }
    if (out.length > 8) return out;
  }
  return out;
}
"""


def main() -> int:
    args = sys.argv[1:]
    keywords = [a for a in args if not a.isdigit()]
    n = int(args[0]) if args and args[0].isdigit() else 2
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단.")
            return 1
        page = pub._page
        pub.open_write_page()
        pub._open_draft_list()
        items = pub._read_draft_items()
        print("[probe] 임시저장 목록:")
        for it in items[:10]:
            print("   ", it.get("idx"), (it.get("title") or "")[:40], it.get("date"))
        if keywords:  # 제목 키워드 일치 글만
            targets = [i for i, it in enumerate(items)
                       if any(kw in (it.get("title") or "") for kw in keywords)]
        else:
            targets = list(range(min(n, len(items))))
        for j, k in enumerate(targets):
            if j > 0:  # 첫 글은 이미 목록이 열려 있음
                pub.open_write_page()
                pub._open_draft_list()
                items = pub._read_draft_items()
            buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
            if k >= len(buttons):
                break
            buttons[k].click()
            page.wait_for_timeout(1500)
            conf = page.query_selector(SMART_EDITOR["draft_load_confirm"])
            if conf and conf.is_visible():
                conf.click()
            page.wait_for_timeout(2500)
            print(f"\n===== 글 #{k}: {(items[k].get('title') or '')[:40]} =====")
            for row in page.evaluate(_HEAD_JS):
                print("   ", row)
            sys.stdout.flush()
        print("\n[probe] 읽기 전용 종료(저장 안 함).")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
