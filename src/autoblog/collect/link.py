"""URL 타입 자동 감지 → 수집 전략 분기 (기획서 §3.3)."""

from __future__ import annotations

from enum import Enum
from urllib.parse import urlparse


class LinkType(str, Enum):
    naver_place = "naver_place"  # → Playwright 구조화 추출
    product = "product"  # 쿠팡·스마트스토어 등 → 상품 파이프라인
    homepage = "homepage"  # 식당 홈페이지·인스타 → requests+bs4 → LLM 정리
    article = "article"  # 뉴스·블로그 → 배경 컨텍스트
    unknown = "unknown"


_PLACE_HOSTS = ("place.naver.com", "m.place.naver.com", "naver.me")
_PRODUCT_HOSTS = (
    "coupang.com",
    "smartstore.naver.com",
    "brand.naver.com",
    "shopping.naver.com",
    "11st.co.kr",
    "gmarket.co.kr",
)
_ARTICLE_HINTS = ("news.", "blog.naver.com", "tistory.com", "brunch.co.kr")


def detect_link_type(url: str) -> LinkType:
    host = (urlparse(url).hostname or "").lower().lstrip("www.")
    if any(h in host for h in _PLACE_HOSTS):
        return LinkType.naver_place
    if any(h in host for h in _PRODUCT_HOSTS):
        return LinkType.product
    if any(h in host for h in _ARTICLE_HINTS):
        return LinkType.article
    if host:
        return LinkType.homepage
    return LinkType.unknown
