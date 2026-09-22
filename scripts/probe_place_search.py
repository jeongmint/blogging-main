"""SE 장소(지도) 팝업 검색이 특정 가게명으로 뭘 돌려주는지 떠보는 1회성 프로브(읽기 전용).

글쓰기 페이지를 열고 툴바 '장소'를 눌러 인자로 준 검색어들을 차례로 검색, 결과
[{title, address}]만 출력하고 Escape로 닫는다 — 저장/발행하지 않는다.

실행:
    .venv/bin/python scripts/probe_place_search.py "우이락 수지구청점" "우이락 수지구청" "우이락"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.publish.editor import BlogPublisher  # noqa: E402


def main() -> None:
    queries = [a for a in sys.argv[1:] if not a.startswith("--")] or ["우이락 수지구청점"]
    pub = BlogPublisher(headless="--headful" not in sys.argv)
    pub.start()
    if not pub.is_logged_in():
        print("로그인 세션 없음 — 먼저 로그인 후 다시 실행하세요.")
        pub.close()
        return
    pub.open_write_page()
    page = pub._page
    page.click("button.se-map-toolbar-button")
    page.wait_for_timeout(1500)
    for q in queries:
        items = pub._search_place(q)
        print(f"\n===== '{q}' → {len(items)}건 =====")
        print(json.dumps(items, ensure_ascii=False, indent=2))
    page.keyboard.press("Escape")
    print("\n프로브 종료 — 저장/발행하지 않았습니다.")
    pub.close()


if __name__ == "__main__":
    main()


def probe_insert() -> None:
    """검색이 아니라 '카드 생성'까지 끝까지 — 새 글에서 삽입만 하고 저장 안 함."""
    pub = BlogPublisher(headless=True)
    pub.start()
    if not pub.is_logged_in():
        print("로그인 세션 없음")
        pub.close()
        return
    pub.open_write_page()
    page = pub._page
    page.click("p.se-text-paragraph")
    page.wait_for_timeout(300)
    why = pub._insert_place("우이락 수지구청점", "경기도 용인시 수지구 풍덕천로139번길 10-8 1층")
    n = page.evaluate(pub._MAP_COUNT_JS)
    print(f"삽입 결과: {'성공' if not why else '실패 — ' + why} (지도 카드 수={n})")
    pub.close()
