"""사실 카드(FactCard) — 정보 수집 결과의 표준 형식.

맛집/상품 두 유형이 공통으로 채워 넣는 구조화 데이터.
- 초안 작성 시 '조연'으로 투입 (없는 사실을 지어내지 않기 위한 근거).
- 출처(source)와 신뢰도(confidence)를 함께 들고 다녀 fallback 여부를 추적한다.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CardType(str, Enum):
    place = "place"  # 맛집 후기
    product = "product"  # 상품 리뷰


# 네이버 플레이스 category(예: '숙박>호텔', '전시,미술관')나 유저가 적은 장소 메모에서
# '메뉴가 중심이 아닌 방문·체험형 장소' 여부를 판별하는 키워드 — FactCard.is_venue와
# 베이스 프롬프트 선택(venue.md)의 단일 출처. 숙소·전시·문화시설·공연·팝업스토어·
# 테마파크·스파처럼 맛집 포맷(메뉴·가격 중심)이 안 맞는 유형을 포괄한다.
_VENUE_KEYWORDS = (
    # 숙박
    "숙박", "호텔", "펜션", "모텔", "리조트", "게스트하우스", "한옥스테이",
    "풀빌라", "글램핑", "민박", "에어비앤비", "숙소",
    # 전시·문화·공연
    "전시", "미술관", "박물관", "갤러리", "문화시설", "공연", "영화관", "극장",
    "콘서트홀", "팝업스토어", "팝업",
    # 체험·레저
    "테마파크", "놀이공원", "워터파크", "아쿠아리움", "동물원", "식물원",
    "체험", "클래스", "공방", "스파", "찜질방", "사우나",
)


def is_venue_hint(category: str | None, place_hint: str | None = None) -> bool:
    """category(네이버 플레이스) 또는 place_hint(유저의 '어떤 장소인지 메모')로 체험형 장소 판별.

    유저 메모는 category 자동감지가 애매하거나(팝업스토어가 '기타'로 잡히는 등) 확실히
    지정하고 싶을 때의 override 용도 — 둘 중 하나라도 걸리면 체험형 장소로 본다.
    """
    text = f"{category or ''} {place_hint or ''}"
    return any(kw in text for kw in _VENUE_KEYWORDS)


class Source(str, Enum):
    search_api = "search_api"  # 네이버 검색 API
    scrape = "scrape"  # Playwright 스크래핑
    vision = "vision"  # 이미지형 상세설명 Vision 추출
    web = "web"  # 일반 웹페이지 크롤링
    fallback = "fallback"  # 스크래핑 실패 → 최소 정보


class MenuItem(BaseModel):
    name: str
    price: str | None = None
    description: str | None = None  # 메뉴 설명글 (메뉴 탭에만 실림)
    recommend: bool = False  # 대표/추천 메뉴 여부
    image: str | None = None  # 대표 이미지 URL


class ReviewKeyword(BaseModel):
    """방문자가 많이 고른 감상 키워드 (예: '음식이 맛있어요')."""

    name: str
    count: int


class ReviewSnippet(BaseModel):
    """방문자 리뷰 한 건 — 초안의 '경험' 보조 재료."""

    body: str
    keywords: list[str] = Field(default_factory=list)
    visited: str | None = None
    visit_count: int | None = None


class PlaceFacts(BaseModel):
    """맛집 — 네이버 플레이스 사실 정보."""

    name: str
    category: str | None = None
    address: str | None = None
    road_address: str | None = None
    phone: str | None = None
    lat: float | None = None
    lng: float | None = None
    business_hours: str | None = None
    rating: float | None = None
    menus: list[MenuItem] = Field(default_factory=list)
    # 정보 탭 (홈 탭 state에 함께 실림)
    description: str | None = None  # 사장님 소개글
    micro_reviews: list[str] = Field(default_factory=list)  # 대표 한줄평
    directions: str | None = None  # 찾아오시는 길(사장님 작성) — 주차 위치 안내가 주로 여기 실림
    conveniences: list[str] = Field(default_factory=list)  # 편의시설
    payment_info: list[str] = Field(default_factory=list)  # 결제수단
    # 방문자 리뷰(경험 재료) — 리뷰 탭에서 수집
    review_keywords: list[ReviewKeyword] = Field(default_factory=list)
    reviews: list[ReviewSnippet] = Field(default_factory=list)
    place_url: str | None = None


class ProductSpec(BaseModel):
    key: str  # 예: 재질, 크기, 사용법, 주의사항
    value: str


class ProductFacts(BaseModel):
    """상품 사실 정보.

    스마트스토어 상품 페이지는 WTM 봇 차단으로 직접 스크래핑 불가 →
    기본정보는 네이버 쇼핑 검색 API, 상세 스펙은 사용자 제공 이미지의 Vision 추출.
    """

    name: str
    price: str | None = None  # 최저가(lprice)
    brand: str | None = None
    maker: str | None = None
    category: str | None = None  # category1>2>3>4 결합
    mall_name: str | None = None
    image: str | None = None  # 대표 이미지 URL
    product_url: str | None = None
    # 상세설명 — 사용자 제공 이미지(Vision 전사) 또는 텍스트 입력
    detail_text: str | None = None  # 상세설명 본문(이미지 전사 또는 직접 입력)
    selling_points: list[str] = Field(default_factory=list)  # 핵심 셀링포인트/특징
    specs: list[ProductSpec] = Field(default_factory=list)  # 스펙(재질/크기 등, 있을 때)
    detail_images: list[str] = Field(default_factory=list)  # 사용자 제공 상세 이미지 경로


class PhotoItem(BaseModel):
    """입력 사진 1장 + 분류 라벨 + 맥락 캡션."""

    path: str
    label: str = "기타"  # 음식/메뉴판/외관/내부/영수증/상품/기타
    caption: str = ""  # 맥락 유추 캡션(예: '데미소스 돈까스'). AI 자동 추천 또는 사용자 입력.
    thumbnail: bool = False  # 대표 썸네일 — 글 맨 위 첫 사진으로 강제 배치(최대 1장)
    ai_generated: bool = False  # AI 생성 이미지(FLUX 썸네일·외부 AI 대체) — 게시 시 'AI 활용' 자율 표기 대상
    media_kind: str = "image"  # "image" | "video" — 영상도 같은 리스트로 흘려보낸다(확장자로 판별)


class FactCard(BaseModel):
    """수집 결과 표준 컨테이너."""

    type: CardType
    sources: list[Source] = Field(default_factory=list)
    is_fallback: bool = False
    place: PlaceFacts | None = None
    product: ProductFacts | None = None
    # 입력 사진 + Vision 자동 분류 (1단계 정보 수집)
    photos: list[PhotoItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # 유저가 직접 적은 '어떤 장소인지' 메모(예: "팝업스토어 방문 후기야"). 네이버 category
    # 자동감지가 애매할 때 베이스 프롬프트 선택(default/venue)의 override로 쓰인다.
    place_hint: str | None = None

    @property
    def is_product(self) -> bool:
        """상품 글 판정의 단일 출처 — 프롬프트 선택·자가 점검·후처리가 같은 기준을 써야 한다.

        타입이 상품이거나(WTM 차단으로 데이터를 못 긁어도 유저가 상품으로 고른 카드),
        상품 데이터가 붙어 있으면 상품으로 본다.
        """
        return self.type == CardType.product or self.product is not None

    @property
    def is_venue(self) -> bool:
        """체험형 장소(숙소·전시·팝업스토어·테마파크 등) 글 판정의 단일 출처.

        프롬프트 선택·자가 점검이 같은 기준을 써야 한다. 상품 글이면 체험형 장소일 수
        없다(우선순위: 상품 > 체험형 장소 > 맛집). 네이버 category나 유저가 적은
        place_hint 중 하나라도 관련 키워드에 걸리면 체험형 장소로 본다.
        """
        if self.is_product:
            return False
        category = self.place.category if self.place else None
        return is_venue_hint(category, self.place_hint)
