"""중앙정렬 자동복구(_verify_and_fix_alignment) 동작 검증용 1회성 프로브.

버그 재현: 어떤 문단을 left/right 로 만든 뒤, 그 정렬을 상속한 다음 문단에 _apply_align
없이 본문을 타이핑한다(= 왼쪽정렬 사진 뒤 끼워넣기와 같은 상황). 그 결과 중앙정렬이 빠진
문단이 생긴다 → 복구 전 정렬을 찍고 → _verify_and_fix_alignment('center') 를 돌린 뒤
다시 찍어, center 가 아니던 문단들이 모두 center 로 복구됐는지 확인한다.

실행:
    .venv/bin/python scripts/probe_align_heal.py
저장하지 않는 새 글에서만 동작한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.publish.editor import BlogPublisher  # noqa: E402


def dump(pub) -> list[dict]:
    return pub._read_paragraph_aligns()


def main() -> None:
    pub = BlogPublisher(headless="--headless" in sys.argv)
    pub.start()
    if not pub.is_logged_in() and not pub.wait_for_login():
        print("로그인 실패 — 세션 없음.")
        pub.close()
        return

    pub.open_write_page()
    page = pub._page
    page.click(".se-component.se-text .se-text-paragraph")
    page.wait_for_timeout(200)

    # 1) 왼쪽 정렬 문단을 만든다.
    pub._apply_align("left")
    page.keyboard.type("LEFT_SEED", delay=5)
    page.keyboard.press("Enter")
    page.wait_for_timeout(150)
    # 2) (버그 상황) 정렬을 다시 안 걸고 그냥 타이핑 → 위 left 를 상속해 left 로 들어간다.
    page.keyboard.type("INHERITS_LEFT_SHOULD_BE_CENTER", delay=5)
    page.keyboard.press("Enter")
    page.wait_for_timeout(150)
    # 3) right 문단도 하나 만들어 상속 케이스를 늘린다.
    pub._apply_align("right")
    page.keyboard.type("RIGHT_THEN", delay=5)
    page.keyboard.press("Enter")
    page.keyboard.type("INHERITS_RIGHT_SHOULD_BE_CENTER", delay=5)
    page.wait_for_timeout(150)

    before = dump(pub)
    print("\n===== 복구 전 =====")
    print(json.dumps(before, ensure_ascii=False, indent=2))

    fixed = pub._verify_and_fix_alignment("center")
    print(f"\n_verify_and_fix_alignment → 복구한 문단 수: {fixed}")

    after = dump(pub)
    print("\n===== 복구 후 =====")
    print(json.dumps(after, ensure_ascii=False, indent=2))

    not_center = [p for p in after if p["hasText"] and p["align"] != "center"]
    print("\n결과:", "PASS — 내용 있는 문단 전부 center" if not not_center
          else f"FAIL — center 아닌 문단 {len(not_center)}개 남음: {not_center}")
    pub.close()


if __name__ == "__main__":
    main()
