"""publish_inplace(M1) 실행기 라이브 검증 — 저장 없이 동작만 확인(비파괴).

라이브 미디어 순서를 읽어 '각 미디어 뒤에 마커 텍스트 + 맨 앞 인트로'를 넣는 플랜을 만들고,
publish_inplace로 끼워넣은 뒤 컴포넌트 순서를 덤프해 검증한다:
  · 각 ★G{i} 텍스트가 i번째 미디어 '바로 뒤'에 들어갔는가
  · 영상 컴포넌트가 그대로 보존됐는가
저장(save=False)하지 않으므로 원본 글은 변하지 않는다.

실행: .venv/bin/python scripts/probe_inplace_executor.py [draft_idx]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.plan import PublishBlock, PublishPlan  # noqa: E402

_MEDIA_ORDER_JS = r"""
() => [...document.querySelectorAll('.se-component.se-image, .se-component.se-video')]
        .map(c => /se-video/.test(c.className) ? 'video' : 'image')
"""

_DUMP_JS = r"""
() => [...document.querySelectorAll('.se-component')].map((c,i) => {
  const cls = c.className.toString();
  let kind = 'other';
  if (/se-video/.test(cls)) kind='video';
  else if (/se-image/.test(cls)) kind='image';
  else if (/se-documentTitle/.test(cls)) kind='title';
  else if (/se-text/.test(cls)) kind='text';
  return {i, kind, txt:(c.innerText||'').trim().replace(/\s+/g,' ').slice(0,32)};
})
"""


def main() -> int:
    draft_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 직접 로그인(최대 6분)…")
            if not pub.wait_for_login():
                return 1
        pub.open_write_page()
        page = pub._page

        # 1) 미디어 순서 파악(플랜 구성용)
        pub._load_draft_into_editor(draft_idx)
        try:
            page.wait_for_selector(SMART_EDITOR["editor_image"], timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        media = page.evaluate(_MEDIA_ORDER_JS)
        print(f"[probe] 미디어 순서({len(media)}): {media}")
        if not media:
            print("[probe] 미디어 없는 글 — 사진/영상 있는 draft_idx로 시도하세요.")
            return 1

        # 2) 미디어 순서에 맞춘 플랜 구성: 인트로 + (미디어 + 그 뒤 텍스트)*
        blocks = [PublishBlock(kind="text", text="★INTRO 첫 미디어 위 인트로 한 줄.", align="center")]
        for i, kind in enumerate(media):
            blocks.append(PublishBlock(kind=("video" if kind == "video" else "image"),
                                       image_path=f"__probe_{i}"))
            blocks.append(PublishBlock(kind="text", text=f"★G{i} ({kind}) 뒤에 끼운 본문.", align="center"))
        plan = PublishPlan(title="(제목은 안 건드림)", blocks=blocks)

        # 3) 실행(저장 안 함) — publish_inplace가 글을 다시 로드해 끼워넣는다
        print("[probe] publish_inplace 실행(save=False)…")
        warnings, infos = pub.publish_inplace(plan, draft_idx=draft_idx, photo_paths=None, save=False)

        # 4) 결과 덤프 + 검증
        rows = page.evaluate(_DUMP_JS)
        print(f"\n===== 결과 컴포넌트({len(rows)}) =====")
        for r in rows:
            print(f"  [{r['i']:>2}] {r['kind']:<6} {r['txt']!r}")

        # 검증: 각 미디어 바로 다음 컴포넌트가 해당 ★G{i} 텍스트인가
        media_rows = [r for r in rows if r["kind"] in ("image", "video")]
        ok = True
        for i, mr in enumerate(media_rows):
            nxt = next((r for r in rows if r["i"] == mr["i"] + 1), None)
            if not nxt or f"★G{i}" not in (nxt["txt"] or ""):
                ok = False
                print(f"  ⚠️ 미디어#{i}(comp[{mr['i']}]) 뒤가 ★G{i} 아님: {nxt['txt'] if nxt else None!r}")
        has_video_before = "video" in media
        has_video_after = any(r["kind"] == "video" for r in rows)
        print("\n===== 판정 =====")
        print(f"  영상 보존: {has_video_before} → {has_video_after} {'✅' if has_video_before==has_video_after else '❌'}")
        intro_ok = any("★INTRO" in (r['txt'] or '') for r in rows)
        print(f"  인트로(맨 앞) 삽입: {'✅' if intro_ok else '❌'}")
        print(f"  미디어별 텍스트 위치: {'✅ 전부 정위치' if ok else '⚠️ 일부 어긋남(위 참고)'}")
        if sys.stdin.isatty():
            try:
                input("\n[probe] Enter 로 닫기…")
            except EOFError:
                pass
        else:
            print("\n[probe] (비대화형 — 자동 종료, 저장 안 함)")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
