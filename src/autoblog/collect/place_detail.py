"""네이버 플레이스 상세 추출 — 사용자가 붙여넣은 플레이스 URL 기반 (기획서 §3.1).

자동 placeId 검색은 캡차/IP 차단에 막히므로, 사용자가 직접 플레이스 URL
(naver.me 단축링크 또는 m.place.naver.com)을 입력하면 그 상세 페이지만 추출한다.

추출 방식: CSS 셀렉터가 아니라 페이지에 SSR로 박힌 `window.__APOLLO_STATE__`
(정규화된 Apollo 캐시) JSON을 파싱한다 — 클래스명 변경에 덜 깨진다.
얻는 정보: 영업시간(가능 시)·메뉴/가격·평점·리뷰수·좌표(WGS84) 등 검색 API에 없는 항목.
"""

from __future__ import annotations

import json
import re

from collections import Counter

from autoblog.collect.fact_card import (
    MenuItem,
    PlaceFacts,
    ReviewKeyword,
    ReviewSnippet,
)

_HANGUL_RE = re.compile(r"[가-힣]")

# m.place.naver.com/restaurant/<id>/... · map.naver.com/p/entry/place/<id> 등
_ID_PATH_RE = re.compile(
    r"/(?:restaurant|place|hairshop|hospital|cafe|accommodation|entry/place)/(\d+)"
)
# 단축링크 리다이렉트 종착의 쿼리 파라미터(pinId=…&id=…)
_ID_QUERY_RE = re.compile(r"[?&](?:pinId|id|placeId)=(\d+)")


def resolve_place_id(url: str) -> str | None:
    """플레이스 URL에서 placeId 추출 (경로형/쿼리형 모두)."""
    m = _ID_PATH_RE.search(url) or _ID_QUERY_RE.search(url)
    return m.group(1) if m else None


_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)


def resolve_place_id_via_redirect(url: str) -> str | None:
    """naver.me 단축링크 등을 requests 리다이렉트로 따라가 placeId 해석(브라우저 불필요)."""
    import requests

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _MOBILE_UA},
            timeout=10,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None
    return resolve_place_id(resp.url)


def fetch_place_html_light(url: str) -> str | None:
    """requests만으로 플레이스 상세 HTML — 실패/차단이면 None.

    이름·주소는 SSR된 __APOLLO_STATE__에 이미 박혀 있어 브라우저 렌더가 필요 없다
    (메뉴 이미지·리뷰 등 graphql로 채워지는 항목은 여전히 fetch_place_html 필요).
    0.3초 vs 14초 차이라, 지도 마커 해석처럼 이름만 필요한 경로는 이쪽을 쓴다."""
    import requests

    try:
        resp = requests.get(url, headers={"User-Agent": _MOBILE_UA}, timeout=10)
    except requests.RequestException:
        return None
    resp.encoding = "utf-8"
    return None if is_rate_limited(resp.text) else resp.text


def place_name_address_from_url(url: str) -> tuple[str, str | None] | None:
    """플레이스 URL(naver.me 단축 포함) → (가게명, 도로명 주소). 실패 시 None.

    [지도:URL] 마커 해석용 — SE 장소 검색창은 가게명만 받고 URL은 결과 0건이라,
    검색 전에 이름·주소로 바꿔줘야 한다. 주소는 도로명 우선(SE 결과 매칭 기준)."""
    place_id = resolve_place_id(url) or resolve_place_id_via_redirect(url)
    if not place_id:
        return None
    html = fetch_place_html_light(menu_tab_url(place_id))
    if html is None:  # 차단·네트워크 실패 때만 브라우저 렌더로 폴백
        try:
            _, html = fetch_place_html(menu_tab_url(place_id))
        except Exception:  # noqa: BLE001 - 해석 실패 시 호출부가 폴백
            return None
    facts = parse_place_detail(extract_apollo_state(html), place_id)
    if not facts or not facts.name:
        return None
    return facts.name, (facts.road_address or facts.address)


def menu_tab_url(place_id: str) -> str:
    """메뉴 탭 — 홈 탭의 상위집합(기본정보+영업시간+소개글+편의시설+메뉴 설명글)."""
    return f"https://m.place.naver.com/restaurant/{place_id}/menu/list"


def review_tab_url(place_id: str) -> str:
    return f"https://m.place.naver.com/restaurant/{place_id}/review/visitor"


def extract_apollo_state(html: str) -> dict:
    """SSR HTML에서 window.__APOLLO_STATE__ 객체를 균형 중괄호로 추출 → dict."""
    marker = html.find("__APOLLO_STATE__")
    if marker == -1:
        return {}
    brace = html.find("{", marker)
    if brace == -1:
        return {}
    depth = 0
    in_str = False
    esc = False
    for i in range(brace, len(html)):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[brace : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _find_new_business_hours(state: dict) -> list | None:
    """ROOT_QUERY.placeDetail(...).newBusinessHours(...) 배열을 찾는다.

    Apollo 키는 인자 JSON이 박혀 동적이라 prefix로 매칭한다.
    """
    rq = state.get("ROOT_QUERY")
    if not isinstance(rq, dict):
        return None
    pd = next((v for k, v in rq.items() if k.startswith("placeDetail(")), None)
    if not isinstance(pd, dict):
        return None
    nbh = next((v for k, v in pd.items() if k.startswith("newBusinessHours")), None)
    return nbh if isinstance(nbh, list) else None


def _shop_description(state: dict) -> str | None:
    """ROOT_QUERY.placeDetail(...).description(...) — 사장님 소개글(shopWindow)."""
    rq = state.get("ROOT_QUERY")
    if not isinstance(rq, dict):
        return None
    pd = next((v for k, v in rq.items() if k.startswith("placeDetail(")), None)
    if not isinstance(pd, dict):
        return None
    desc = next((v for k, v in pd.items() if k.startswith("description(")), None)
    return desc.strip() if isinstance(desc, str) and desc.strip() else None


def _format_business_hours(state: dict) -> str | None:
    """요일별 영업시간 → 읽기 좋은 한 줄.

    예: '목~화 10:30~21:00 (L.O. 20:30) / 수 정기휴무 (매주 수요일)'
    동일 시간대 연속 요일은 'A~B'로 묶는다.
    """
    nbh = _find_new_business_hours(state)
    if not nbh:
        return None
    days = (nbh[0] or {}).get("businessHours") or []
    if not days:
        return None

    def signature(d: dict) -> tuple:
        bh = d.get("businessHours") or {}
        start, end = bh.get("start"), bh.get("end")
        if not start or not end:
            return ("CLOSED", d.get("description") or "휴무")
        lo = next((t.get("time") for t in (d.get("lastOrderTimes") or []) if t.get("time")), None)
        breaks = tuple(
            (b.get("start"), b.get("end")) for b in (d.get("breakHours") or [])
        )
        return ("OPEN", start, end, lo, breaks)

    # 연속 동일 시그니처 요일 묶기
    groups: list[tuple[list[str], tuple]] = []
    for d in days:
        day = d.get("day")
        if not day:
            continue
        sig = signature(d)
        if groups and groups[-1][1] == sig:
            groups[-1][0].append(day)
        else:
            groups.append(([day], sig))

    parts: list[str] = []
    for day_list, sig in groups:
        label = day_list[0] if len(day_list) == 1 else f"{day_list[0]}~{day_list[-1]}"
        if sig[0] == "CLOSED":
            parts.append(f"{label} {sig[1]}")
            continue
        _, start, end, lo, breaks = sig
        seg = f"{label} {start}~{end}"
        if breaks:
            seg += " (브레이크 " + ", ".join(f"{s}~{e}" for s, e in breaks) + ")"
        if lo:
            seg += f" (L.O. {lo})"
        parts.append(seg)
    return " / ".join(parts) or None


def _won(price) -> str | None:
    """가격 정수/문자 → '15,900원' 형식."""
    if price is None or price == "":
        return None
    try:
        return f"{int(price):,}원"
    except (TypeError, ValueError):
        return str(price)


def parse_place_detail(state: dict, place_id: str) -> PlaceFacts | None:
    """Apollo state에서 PlaceDetailBase + Menu 엔티티를 PlaceFacts로 변환."""
    base = state.get(f"PlaceDetailBase:{place_id}")
    if not base:
        # placeId 불일치 시 첫 PlaceDetailBase로 폴백
        base = next(
            (v for k, v in state.items() if k.startswith("PlaceDetailBase:")), None
        )
    if not base:
        return None

    coord = base.get("coordinate") or {}
    lat = lng = None
    try:
        lat = float(coord["y"]) if coord.get("y") else None
        lng = float(coord["x"]) if coord.get("x") else None
    except (TypeError, ValueError):
        pass

    score = base.get("visitorReviewsScore")
    rating = float(score) if score else None  # 0/None → 별점 미운영

    menus = []
    for k, v in state.items():
        if not k.startswith(f"Menu:{place_id}") or not v.get("name"):
            continue
        images = v.get("images") or []
        desc = (v.get("description") or "").strip() or None
        menus.append(
            MenuItem(
                name=v["name"],
                price=_won(v.get("price")),
                description=desc,
                recommend=bool(v.get("recommend")),
                image=images[0] if images and isinstance(images[0], str) else None,
            )
        )

    phone = base.get("phone") or base.get("virtualPhone")
    # 영업시간은 base.openingHours가 종종 null이라 ROOT_QUERY.newBusinessHours에서 조립
    hours = _format_business_hours(state)

    def _str_list(val) -> list[str]:
        return [s for s in val if isinstance(s, str)] if isinstance(val, list) else []

    return PlaceFacts(
        name=base.get("name", ""),
        category=base.get("category"),
        address=base.get("address"),
        road_address=base.get("roadAddress"),
        phone=phone,
        lat=lat,
        lng=lng,
        business_hours=hours,
        rating=rating,
        description=_shop_description(state),
        micro_reviews=_str_list(base.get("microReviews")),
        directions=(base.get("road") or "").strip() or None,
        conveniences=_str_list(base.get("conveniences")),
        payment_info=_str_list(base.get("paymentInfo")),
        menus=menus,
        place_url=f"https://m.place.naver.com/restaurant/{place_id}/home",
    )


def parse_visitor_reviews(
    state: dict, limit: int = 12
) -> tuple[list[ReviewKeyword], list[ReviewSnippet]]:
    """리뷰 탭 apollo state → (키워드 집계, 의미있는 리뷰 스니펫).

    - 키워드: 모든 리뷰의 votedKeywords name을 빈도순 집계.
    - 스니펫: 한글 포함 10자 이상 본문만(이모지/단문 제외), 페이지 순서대로 limit개.
    """
    reviews = [v for k, v in state.items() if k.startswith("VisitorReview:")]

    counter: Counter[str] = Counter()
    for r in reviews:
        for kw in r.get("votedKeywords") or []:
            name = kw.get("name")
            if name:
                counter[name] += 1
    keywords = [ReviewKeyword(name=n, count=c) for n, c in counter.most_common()]

    snippets: list[ReviewSnippet] = []
    for r in reviews:
        body = (r.get("body") or "").strip()
        if len(body) < 10 or not _HANGUL_RE.search(body):
            continue
        snippets.append(
            ReviewSnippet(
                body=body,
                keywords=[kw["name"] for kw in (r.get("votedKeywords") or []) if kw.get("name")],
                visited=r.get("visited"),
                visit_count=r.get("visitCount"),
            )
        )
        if len(snippets) >= limit:
            break

    return keywords, snippets


def fetch_place_html(url: str, timeout_ms: int = 25000) -> tuple[str, str]:
    """Playwright로 플레이스 상세 페이지를 렌더해 (최종 URL, HTML) 반환.

    requests로는 __APOLLO_STATE__가 빈 셸이라(클라이언트 graphql로 채움)
    실제 브라우저로 JS 실행이 필요하다. 모바일 UA 사용.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                "Mobile/15E148 Safari/604.1"
            ),
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            locale="ko-KR",
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(3000)  # 하이드레이션 + 과도요청 방지용 여유
            return page.url, page.content()
        finally:
            browser.close()


def is_rate_limited(html: str) -> bool:
    return "이용이 제한" in html or "과도한 접근" in html
