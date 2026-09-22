"""상품 — 네이버 쇼핑 검색 API 기본정보 + 사용자 이미지 Vision 상세 (기획서 §3.2).

스마트스토어/brand.naver 상품 페이지는 네이버 WTM 봇 챌린지로 직접 스크래핑이
사실상 불가하다. 그래서:
- 기본정보(상품명/가격/브랜드/이미지/카테고리)는 쇼핑 검색 API(공식·무료)로 수집.
- 이미지형 상세설명(재질/크기/사용법/주의사항)은 사용자가 제공한 상세 이미지를
  Vision LLM으로 추출(autoblog.vision). 즉 우리가 상품 페이지를 긁지 않으므로
  WTM 우회가 필요 없다.
"""

from __future__ import annotations

import html
import re

import requests

from autoblog.collect.fact_card import CardType, FactCard, ProductFacts, Source

_TAG_RE = re.compile(r"<[^>]+>")


def _strip(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _won(lprice: str | None) -> str | None:
    if not lprice:
        return None
    try:
        return f"{int(lprice):,}원"
    except ValueError:
        return lprice


def parse_shop_item(item: dict) -> ProductFacts:
    """쇼핑 검색 API item → ProductFacts."""
    cats = [item.get(f"category{i}") for i in range(1, 5)]
    category = ">".join(c for c in cats if c) or None
    return ProductFacts(
        name=_strip(item.get("title", "")),
        price=_won(item.get("lprice")),
        brand=item.get("brand") or None,
        maker=item.get("maker") or None,
        category=category,
        mall_name=item.get("mallName") or None,
        image=item.get("image") or None,
        product_url=item.get("link") or None,
    )


class ShopSearchUnavailable(RuntimeError):
    """네이버 쇼핑 검색 API가 2026-07-31부로 서비스 종료되어 더 이상 호출할 수 없을 때."""


def search_product(query: str, display: int = 5) -> list[ProductFacts]:
    """쇼핑 검색 API로 상품 기본정보 목록 조회.

    네이버 쇼핑/책/전문자료 검색 API는 2026-07-31 서비스가 완전히 종료되었고
    NAVER API HUB(NCP)로도 이관되지 않았다(공지 developers.naver.com/notice/article/32564,
    32530). 대체 엔드포인트가 없으므로 --product/--text 상품명 자동조회는 현재 불가하며,
    detail_text/detail_images 직접 입력 경로만 남아 있다.
    """
    raise ShopSearchUnavailable(
        "네이버 쇼핑 검색 API는 2026-07-31부로 서비스가 종료되어 상품 자동조회를 쓸 수 없어요. "
        "--text로 상품 설명을 직접 입력하거나 --image로 상세 이미지를 넣어주세요."
    )


def download_image(url: str) -> str:
    """이미지 URL을 임시 파일로 내려받아 경로 반환. 쇼핑 CDN은 WTM 없이 접근 가능."""
    import tempfile

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    suffix = ".png" if "png" in resp.headers.get("content-type", "") else ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


def collect_product(
    query: str,
    detail_images: list[str] | None = None,
    detail_text: str | None = None,
    vision_on_main: bool = False,
) -> FactCard:
    """상품 사실 카드 조립.

    query로 쇼핑 API 기본정보(최상위 결과)를 잡고, 상세설명은 두 경로 중 하나로:
    - detail_text: 사용자가 상세설명을 텍스트로 직접 입력 → Vision 없이 그대로 사용.
    - detail_images: 사용자가 상세설명 이미지 제공 → Vision으로 전사+셀링포인트+스펙 추출.
    - vision_on_main=True: 쇼핑 API 메인 이미지도 내려받아 Vision에 포함(시각 묘사 위주).
    상세 이미지 URL은 쇼핑 API가 주지 않으므로(상품 페이지는 WTM 차단) 사용자가 직접 제공한다.

    쇼핑 검색 API는 2026-07-31 서비스 종료로 더 이상 호출할 수 없다(search_product 참고).
    기본정보는 자동조회 대신 query를 상품명으로 그대로 쓰고, warnings로 안내한다.
    """
    try:
        results = search_product(query, display=5)
    except ShopSearchUnavailable as exc:
        results = []
        shop_unavailable_msg = str(exc)
    else:
        shop_unavailable_msg = None

    if not results:
        facts = ProductFacts(name=query)
        card = FactCard(
            type=CardType.product,
            sources=[Source.fallback],
            is_fallback=True,
            product=facts,
            warnings=[shop_unavailable_msg or "네이버 검색 API 키 미설정 또는 검색 결과 없음"],
        )
    else:
        facts = results[0]
        card = FactCard(type=CardType.product, sources=[Source.search_api], product=facts)

    # 상세설명 본문은 텍스트 입력 + 이미지 전사를 모두 합친다(둘 다 선택적).
    text_parts: list[str] = []
    if detail_text and detail_text.strip():
        text_parts.append(detail_text.strip())

    # 이미지 경로: Vision으로 전사+셀링포인트+스펙
    images = list(detail_images or [])
    if vision_on_main and facts.image:
        try:
            images.insert(0, download_image(facts.image))
        except Exception as exc:  # noqa: BLE001 - 메인 이미지 다운로드 실패는 비치명적
            card.warnings.append(f"메인 이미지 다운로드 실패: {exc}")

    if images:
        facts.detail_images = list(detail_images or [])
        from autoblog.vision import VisionUnavailable, extract_product_detail

        context = " / ".join(c for c in (facts.name, facts.category) if c)
        try:
            detail = extract_product_detail(images, context=context)
            if detail.text:
                text_parts.append(detail.text)
            facts.selling_points = detail.selling_points
            facts.specs = detail.specs
            card.sources.append(Source.vision)
        except VisionUnavailable as exc:
            card.warnings.append(f"Vision 미연동 — 이미지 상세 생략: {exc}")
        except Exception as exc:  # noqa: BLE001 - 상세는 보조라 실패해도 기본정보 유지
            card.warnings.append(f"Vision 상세 추출 실패: {exc}")

    facts.detail_text = "\n\n".join(text_parts) or None
    return card
