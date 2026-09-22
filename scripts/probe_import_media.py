"""import_draft_media가 '테스트' 글의 미디어를 문서 순서대로(사진/영상/콜라주) 뽑는지 검증."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.config import DATA_DIR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402


def main() -> int:
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단")
            return 1
        pub.open_write_page()
        manifest = pub.import_draft_media(idx, DATA_DIR / "uploads")
        seq = " ".join(
            {"image": "i", "video": "V", "collage": "C"}.get(m["kind"], "?") for m in manifest
        )
        print(f"\n[probe] manifest 순서: {seq}")
        print(f"[probe] 총 {len(manifest)}개 "
              f"(사진 {sum(m['kind']=='image' for m in manifest)}, "
              f"영상 {sum(m['kind']=='video' for m in manifest)}, "
              f"콜라주 {sum(m['kind']=='collage' for m in manifest)})")
        for i, m in enumerate(manifest):
            extra = f"  {Path(m['path']).name}" if m.get("path") else ""
            print(f"  [{i:>2}] {m['kind']}{extra}")
        return 0
    finally:
        pub.close()


if __name__ == "__main__":
    raise SystemExit(main())
