"""드립 서식 E2E 프로브 — 실제 publish() 경로(저장 안 함)로 드립 줄 서식 재현.

플랜: 대제목 → 드립 → (히어로 이미지) → 구분선 → 본문+사진 2장.
publish(save=False, submit=False)로 본문 주입·강조 적용까지만 하고, DOM에서
대제목·드립 문단의 폰트/크기/색을 읽는다. 창 닫으면 글은 사라진다.

실행: .venv/bin/python scripts/probe_drip_style_e2e.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.draft.generate import DraftResult  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.plan import PhotoItem, build_publish_plan, load_structure_styles  # noqa: E402

SCRATCH = Path("/private/tmp/claude-501/-Users-noino-dev-side-blogging/f77bb558-8e21-4daf-a5f3-3b9f0d206535/scratchpad")

TEXT = """ZZ_드립E2E프로브_저장안함 제목줄입니다 지우세요

또 오고 말았잖아요

내가 쓰는 스킨.. 통만 바뀌면
완벽할 것 같지 않을까 ..,?

[사진:입구]
입구부터 심상치 않았어요

[사진:메뉴판]
메뉴판입니다
"""

_DOM_JS = r"""
(t) => {
  for (const root of document.querySelectorAll('.se-component.se-text')) {
    for (const p of root.querySelectorAll('p, .se-text-paragraph')) {
      if ((p.textContent || '').includes(t)) {
        return {html: p.outerHTML.slice(0, 500)};
      }
    }
  }
  return null;
}
"""


def main() -> int:
    draft = DraftResult(title="t", text=TEXT, emphases=[], debug={})
    photos = [
        PhotoItem(path=str(SCRATCH / "a.jpg"), label="입구"),
        PhotoItem(path=str(SCRATCH / "b.jpg"), label="메뉴판", thumbnail=True),
    ]
    plan = build_publish_plan(draft, photos=photos, structure_styles=load_structure_styles())
    print("[probe] 블록:", [(b.kind, (b.text or "")[:12], len(b.emphases or [])) for b in plan.blocks])

    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단.")
            return 1
        warnings = pub.publish(plan, save=False, submit=False)
        print("[probe] warnings:", warnings)
        page = pub._page
        for probe_text in ["또 오고", "통만 바뀌면", "않을까"]:
            got = page.evaluate(_DOM_JS, probe_text)
            print(f"\n===== {probe_text} =====")
            print(got and got["html"])
        print("\n[probe] 저장 없이 종료.")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
