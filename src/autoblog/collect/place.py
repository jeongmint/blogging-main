"""맛집 — 네이버 플레이스 수집 (기획서 §3.1).

두 경로:
- collect_place_from_url(url): 사용자가 붙여넣은 플레이스 URL → 상세 추출(권장).
  메뉴/가격/평점/좌표 등은 place_detail.py가 __APOLLO_STATE__ 파싱으로 얻는다.
- collect_place(query): 검색 API로 가게 식별만(주소/좌표/전화). 자동 placeId
  검색은 캡차/IP 차단에 막혀, 상세는 URL 경로를 권장.
"""

from __future__ import annotations

import html
import re

import requests

from autoblog.config import load_env
from autoblog.collect.fact_card import CardType, FactCard, PlaceFacts, Source

_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/local"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


def ping_search_api() -> tuple[bool, str]:
    """검색 API 키가 실제로 동작하는지 라이브로 점검.

    반환: (성공여부, 메시지). doctor 명령에서 연동 검증에 사용.
    """
    env = load_env()
    if not env.has_naver_api:
        return False, "키 미설정 (.env)"
    try:
        resp = requests.get(
            _SEARCH_URL,
            params={"query": "스타벅스", "display": 1},
            headers={
                "X-NCP-APIGW-API-KEY-ID": env.naver_client_id or "",
                "X-NCP-APIGW-API-KEY": env.naver_client_secret or "",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        return False, f"네트워크 오류: {exc}"
    if resp.status_code == 200:
        return True, "OK"
    if resp.status_code == 401:
        return False, "401 인증 실패 — Client ID/Secret 확인"
    return False, f"HTTP {resp.status_code}: {resp.text[:120]}"


def search_place(query: str) -> PlaceFacts | None:
    """네이버 지역검색 API로 가게 식별.

    제약: 결과 5개·start=1 고정(2020.07~), 상세정보 없음. 식별 + 주소/좌표/전화만.
    좌표는 KATECH(TM128)으로 내려오므로 표시는 가능하나 WGS84 변환은 별도.
    """
    env = load_env()
    if not env.has_naver_api:
        return None

    resp = requests.get(
        _SEARCH_URL,
        params={"query": query, "display": 5},
        headers={
            "X-NCP-APIGW-API-KEY-ID": env.naver_client_id or "",
            "X-NCP-APIGW-API-KEY": env.naver_client_secret or "",
        },
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None

    top = items[0]
    return PlaceFacts(
        name=_strip(top.get("title", "")),
        category=top.get("category") or None,
        address=top.get("address") or None,
        road_address=top.get("roadAddress") or None,
        phone=top.get("telephone") or None,
        place_url=top.get("link") or None,
    )


def collect_place_from_url(
    url: str, with_reviews: bool = True, review_limit: int = 12
) -> FactCard:
    """사용자가 붙여넣은 플레이스 URL → 상세 사실 카드 (기획서 §3.1, 권장 경로).

    홈 탭(기본정보/메뉴/영업시간) + 리뷰 탭(방문자 경험 키워드/본문)을 수집.
    Apollo state 파싱으로 추출하며, 실패·IP 차단 시 경고와 함께 가능한 만큼만 채운다.
    """
    import time

    from autoblog.collect.place_detail import (
        extract_apollo_state,
        fetch_place_html,
        is_rate_limited,
        menu_tab_url,
        parse_place_detail,
        parse_visitor_reviews,
        resolve_place_id,
        resolve_place_id_via_redirect,
        review_tab_url,
    )

    card = FactCard(type=CardType.place, sources=[Source.scrape])

    # placeId 먼저 해석(단축링크는 requests 리다이렉트로 — 브라우저 불필요)
    place_id = resolve_place_id(url) or resolve_place_id_via_redirect(url)
    if place_id is None:
        card.is_fallback = True
        card.warnings.append(f"placeId를 URL에서 찾지 못함: {url}")
        return card

    # 메뉴 탭이 홈 탭의 상위집합 → 기본정보+영업시간+소개글+메뉴 설명글을 한 번에
    final_url, html_text = fetch_place_html(menu_tab_url(place_id))
    state = extract_apollo_state(html_text)
    facts = parse_place_detail(state, place_id) if state else None
    if facts is None or not facts.name:
        card.is_fallback = True
        if is_rate_limited(html_text):
            card.warnings.append("네이버 IP 차단(과도한 접근) — 잠시 후 재시도")
        else:
            card.warnings.append("상세 데이터 추출 실패 (페이지 구조 변경 가능)")
        return card

    if with_reviews:
        time.sleep(2)  # 폴라이트 딜레이 (연속 요청 차단 방지)
        try:
            _, review_html = fetch_place_html(review_tab_url(place_id))
            if is_rate_limited(review_html):
                card.warnings.append("리뷰 탭 IP 차단 — 기본 정보만 수집")
            else:
                rstate = extract_apollo_state(review_html)
                facts.review_keywords, facts.reviews = parse_visitor_reviews(
                    rstate, limit=review_limit
                )
        except Exception as exc:  # noqa: BLE001 - 리뷰는 보조라 실패해도 진행
            card.warnings.append(f"리뷰 수집 실패: {exc}")

    card.place = facts
    return card


def collect_place(query: str) -> FactCard:
    """검색 API로 가게 식별만 (주소/좌표/전화). 상세는 collect_place_from_url 권장."""
    facts = search_place(query)
    if facts is None:
        return FactCard(
            type=CardType.place,
            sources=[Source.fallback],
            is_fallback=True,
            warnings=["네이버 검색 API 키 미설정 또는 검색 결과 없음"],
        )
    return FactCard(type=CardType.place, sources=[Source.search_api], place=facts)
