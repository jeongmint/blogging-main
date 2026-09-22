"""Phase 4 통합 검증: 실제 publish_inplace로 사진 재배치(영상 고정)를 비파괴(save=False) 확인.

'테스트' 글(사진19·영상2)에: 사진 5장을 알려진 순서로, 영상 2개를 구간 경계로 두는 플랜을
publish_inplace에 넣고 결과 문서 순서를 덤프한다. 기대 미디어 순서: i V i i V i i.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.config import DATA_DIR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.plan import PublishBlock, PublishPlan  # noqa: E402

_SEQ_JS = r"""
() => [...document.querySelectorAll('.se-component')].map(c => {
  const cls = c.className.toString();
  if (/se-documentTitle/.test(cls)) return 'T';
  if (/se-video/.test(cls)) return 'V';
  if (c.querySelector('img.se-image-resource')) return 'i';
  if (/se-text/.test(cls)) return 't';
  return '?';
}).join(' ')
"""


def main() -> int:
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단")
            return 1
        pub.open_write_page()

        manifest = pub.import_draft_media(idx, DATA_DIR / "uploads")
        imgs = [m["path"] for m in manifest if m["kind"] == "image"]
        nvid = sum(m["kind"] == "video" for m in manifest)
        print(f"[probe] import: 사진 {len(imgs)} / 영상 {nvid}")
        if len(imgs) < 5 or nvid < 2:
            print("[probe] 이 검증엔 사진 5장·영상 2개 이상 필요 — 중단")
            return 1

        # 알려진 재배치 플랜: [img0, T0] V [img1, img2, T1] V [img3, img4, T2]
        blocks = [
            PublishBlock(kind="image", image_path=imgs[0]),
            PublishBlock(kind="text", text="① 구간0 — 영상1 앞 첫 사진 설명", align="center"),
            PublishBlock(kind="video"),
            PublishBlock(kind="image", image_path=imgs[1]),
            PublishBlock(kind="image", image_path=imgs[2]),
            PublishBlock(kind="text", text="② 구간1 — 두 영상 사이 사진들", align="center"),
            PublishBlock(kind="video"),
            PublishBlock(kind="image", image_path=imgs[3]),
            PublishBlock(kind="image", image_path=imgs[4]),
            PublishBlock(kind="text", text="③ 구간2 — 영상2 뒤 사진들", align="center"),
        ]
        plan = PublishPlan(title="재배치 검증", blocks=blocks)

        print("[probe] publish_inplace(save=False) 실행 — 사진 삭제→재배치…")
        warnings, infos = pub.publish_inplace(
            plan, draft_idx=idx, photo_paths=imgs[:5], save=False, clean_imported=True
        )

        seq = pub._page.evaluate(_SEQ_JS)
        media = [c for c in seq.split() if c in ("i", "V")]
        expected = ["i", "V", "i", "i", "V", "i", "i"]
        print(f"\n[probe] 전체 순서: {seq}")
        print(f"[probe] 미디어:   {' '.join(media)}")
        print(f"[probe] 기대:     {' '.join(expected)}")
        print(f"[probe] → {'OK ✅ 영상 고정 + 사진 플랜순서 배치' if media == expected else '불일치 ❌'}")
        if warnings:
            print("[probe] warnings:")
            for w in warnings:
                print("   -", w)
        print("[probe] (비파괴 — 저장 안 함)")
        return 0
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
