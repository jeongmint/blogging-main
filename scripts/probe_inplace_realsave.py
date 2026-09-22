"""publish_inplace 실제 저장 e2e 검증 — ⚠️ 지정한 임시저장 글을 실제로 수정/저장한다.

확인 항목:
  1) 저장 후 임시저장 '글 개수'가 그대로인가(= 같은 글 갱신, 새 글 안 생김)
  2) 그 글을 다시 열었을 때 우리가 넣은 본문(★RS 마커)이 실제로 들어가 있는가
  3) 영상이 보존됐는가

반드시 '버려도 되는' 임시저장 글 번호로만 실행하세요.
실행: .venv/bin/python scripts/probe_inplace_realsave.py <draft_idx>   (idx 필수)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.plan import PublishBlock, PublishPlan  # noqa: E402

_MEDIA_JS = "() => [...document.querySelectorAll('.se-component.se-image, .se-component.se-video')].map(c => /se-video/.test(c.className)?'video':'image')"
_BODYTEXT_JS = "() => [...document.querySelectorAll('.se-component.se-text')].map(c => (c.innerText||'').trim()).join(' | ')"


def main() -> int:
    if len(sys.argv) < 2:
        print("draft_idx(버려도 되는 글 번호)가 필요합니다.")
        return 2
    idx = int(sys.argv[1])
    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.wait_for_login():
            print("로그인 필요")
            return 1
        pub.open_write_page()
        page = pub._page

        # BEFORE: 목록 스냅샷 + 대상 글의 제목/날짜
        before = pub.list_drafts()
        print(f"[before] 임시저장 {len(before)}건")
        if idx >= len(before):
            print(f"idx 범위 초과(총 {len(before)}건)")
            return 1
        target = before[idx]
        print(f"[target] idx={idx} title={target['title']!r} date={target['date']!r}")

        # 대상 글의 미디어 순서 파악 → 그에 맞는 플랜 구성
        pub._load_draft_into_editor(idx)
        try:
            page.wait_for_selector(SMART_EDITOR["editor_image"], timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        media = page.evaluate(_MEDIA_JS)
        print(f"[media] {media}")
        blocks = [PublishBlock(kind="text", text="★RS 인트로(실저장 테스트).", align="center")]
        for i, k in enumerate(media):
            blocks.append(PublishBlock(kind=("video" if k == "video" else "image"), image_path=f"__rs_{i}"))
            blocks.append(PublishBlock(kind="text", text=f"★RS{i} ({k}) 뒤 본문.", align="center"))
        plan = PublishPlan(title=target["title"], blocks=blocks)

        # 실제 저장 — 제목+날짜로 글 재식별해서 그 글을 갱신
        print("[run] publish_inplace(save=True) …")
        warnings, infos = pub.publish_inplace(
            plan, draft_title=target["title"], draft_date=target["date"],
            photo_paths=None, save=True,
        )
        if warnings:
            print("[warn]", warnings)
        if infos:
            print("[info]", infos)
        page.wait_for_timeout(1500)

        # AFTER: 목록 개수 비교(새 글 생겼는지)
        after = pub.list_drafts()
        print(f"\n[after] 임시저장 {len(after)}건 (before {len(before)}건)")
        same_count = len(after) == len(before)

        # 그 글을 다시 열어 본문/영상 확인
        idx2 = pub._resolve_draft_idx(target["title"], target["date"])
        if idx2 is None:
            # 날짜가 갱신됐을 수 있으니 제목으로만 재탐색
            idx2 = pub._resolve_draft_idx(target["title"], "")
        reopened_ok = False
        media_after = []
        if idx2 is not None:
            pub._load_draft_into_editor(idx2)
            try:
                page.wait_for_selector(SMART_EDITOR["editor_image"], timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(800)
            body = page.evaluate(_BODYTEXT_JS)
            media_after = page.evaluate(_MEDIA_JS)
            reopened_ok = "★RS" in body
            print(f"[reopen] 본문에 ★RS 포함: {reopened_ok}")
            print(f"[reopen] 본문 미리보기: {body[:160]}")

        print("\n===== 판정 =====")
        print(f"  새 글 안 생김(개수 동일): {'✅' if same_count else '❌ (새 글 생성됨 — 갱신 아님!)'}")
        print(f"  본문 실제 저장됨: {'✅' if reopened_ok else '❌'}")
        print(f"  영상 보존: {media.count('video')} → {media_after.count('video')} "
              f"{'✅' if media.count('video')==media_after.count('video') else '❌'}")
        return 0
    finally:
        pub.close(save_session=True)


if __name__ == "__main__":
    raise SystemExit(main())
