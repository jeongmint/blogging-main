"""엔드투엔드 오케스트레이션: 수집 → 초안(마커 자동) → 게시 플랜 (기획서 §7 통합).

CLI `post` 명령이 이 흐름을 호출한다. 게시(BlogPublisher)는 부수효과(브라우저)라 분리:
여기서는 사실카드·초안·게시플랜까지 조립하고, 실제 주입/발행은 CLI에서 BlogPublisher가 맡는다.

스티커 배선: stickers=True면 카탈로그의 상황 라벨을 초안에 주입(LLM이 [스티커:상황] emit)하고,
같은 카탈로그로 StickerPicker를 만들어 플랜이 마커를 (팩,인덱스)로 해석한다.
"""

from __future__ import annotations

from typing import Callable

from pydantic import BaseModel

from autoblog.collect.fact_card import CardType, FactCard

# 세션 동안 같은 URL/검색어의 스크래핑 결과를 재사용(네이버 지도/상품 재수집 방지).
# 키: "place:<url>" 또는 "product:<검색어>". 값은 사진 부착 전의 순수 수집 카드.
_SCRAPE_CACHE: dict[str, FactCard] = {}


def clear_scrape_cache() -> None:
    """수집 캐시 비우기(강제 새로고침용)."""
    _SCRAPE_CACHE.clear()


def cached_place_card(place_url: str | None) -> FactCard | None:
    """이미 수집해 캐시에 있는 가게 카드만 반환(없으면 None — 실시간 재수집 안 함).

    붙여넣기 경로에서 [지도] 마커용 가게명·주소를 채울 때, 예상치 못한 스크래핑
    (느림·차단)을 트리거하지 않으려고 캐시 조회 전용으로 쓴다."""
    if not place_url:
        return None
    return _SCRAPE_CACHE.get("place:" + place_url)


def last_cached_place() -> FactCard | None:
    """세션에서 가장 최근에 수집된 가게 카드 — 수집 링크가 빈 붙여넣기에서 [지도] 폴백용."""
    for key in reversed(_SCRAPE_CACHE):
        if key.startswith("place:"):
            return _SCRAPE_CACHE[key]
    return None
from autoblog.draft.generate import DraftRequest, DraftResult, generate_draft
from autoblog.draft.guideline import Guidelines
from autoblog.draft.rules import CommonRules
from autoblog.draft.style import StyleProfile
from autoblog.publish.plan import PublishPlan, build_publish_plan, load_structure_styles
from autoblog.publish.stickers import StickerCatalog, StickerPicker


class PipelineResult(BaseModel):
    card: FactCard
    draft: DraftResult
    plan: PublishPlan


def _place_info(card: FactCard | None) -> tuple[bool, str | None, str | None]:
    """맛집(장소) 카드면 (지도 마커 켜기, 검색용 가게명, 매칭용 도로명 주소) 반환.

    주소는 도로명(road_address) 우선 — SE 장소 검색 결과 주소가 도로명 기준이라
    동명 가게가 여럿일 때 정확한 결과를 고르는 데 쓴다. 없으면 지번(address)."""
    if card and card.type == CardType.place and card.place and card.place.name:
        p = card.place
        return True, p.name, (p.road_address or p.address)
    return False, None, None


def collect_card(
    place_url: str | None = None,
    product: str | None = None,
    photos: list[str] | None = None,
    photo_meta: dict[str, dict] | None = None,
    *,
    card_kind: str | None = None,
    place_hint: str | None = None,
    use_cache: bool = False,
    progress: Callable[[str], None] | None = None,
) -> FactCard:
    """수집: 플레이스 URL 또는 상품 검색어 → 사실 카드. 사진 있으면 카드에 채움.

    photo_meta(경로→{label,caption})를 주면 그 값으로 채우고 Vision 호출을 건너뛴다
    (webui: 수동 분류·AI 자동 추천 결과). None이면 기존처럼 로컬 Vision 자동 분류(CLI 등).
    use_cache=True면 같은 URL/검색어의 수집 결과를 세션 캐시에서 재사용한다(webui 세션).
    progress(msg)를 주면 단계별 상태 메시지를 전달한다(예: '네이버 지도에서…').
    card_kind('place'|'product')는 URL·검색어가 비어 수집할 게 없을 때 만들 빈 카드의
    타입을 정한다 — 유저가 '상품'을 골랐는데 검색어를 안 넣어도(스마트스토어 WTM 차단으로
    어차피 못 긁음) 상품 카드가 나오게 해서 상품 프롬프트가 걸리도록.
    place_hint는 유저가 적은 '어떤 장소인지 메모'(예: "팝업스토어야") — 카드에 그대로
    실어 FactCard.is_venue(네이버 category 자동감지의 override)에 쓰인다.
    """

    def _say(msg: str) -> None:
        if progress:
            progress(msg)

    if place_url:
        key = "place:" + place_url
        cached = _SCRAPE_CACHE.get(key) if use_cache else None
        if cached is not None:
            _say("저장해둔 가게 정보를 재사용하는 중…")
            card = cached.model_copy(deep=True)
        else:
            _say("네이버 지도에서 가게 정보를 가져오는 중…")
            from autoblog.collect.place import collect_place_from_url

            card = collect_place_from_url(place_url)
            if use_cache and not card.is_fallback:  # 실패 카드는 캐시하지 않음(다음에 재시도)
                _SCRAPE_CACHE[key] = card.model_copy(deep=True)
    elif product:
        key = "product:" + product
        cached = _SCRAPE_CACHE.get(key) if use_cache else None
        if cached is not None:
            _say("저장해둔 상품 정보를 재사용하는 중…")
            card = cached.model_copy(deep=True)
        else:
            _say("스마트스토어에서 상품 정보를 가져오는 중…")
            from autoblog.collect.product import collect_product

            card = collect_product(product)
            if use_cache and not card.is_fallback:
                _SCRAPE_CACHE[key] = card.model_copy(deep=True)
    else:
        ctype = CardType.product if card_kind == "product" else CardType.place
        card = FactCard(type=ctype)
    if place_hint and place_hint.strip():
        card.place_hint = place_hint.strip()
    if photos:
        _say("사진을 정리하는 중…")
        if photo_meta is not None:
            from autoblog.collect.photos import attach_photos

            attach_photos(card, photos, photo_meta)
        else:
            from autoblog.collect.photos import classify_photos_into

            classify_photos_into(card, photos)
    return card


def build_photo_context(card: FactCard | None, memo: str = "") -> str:
    """사진 자동 추천용 맥락 텍스트 — 메모 + 수집한 가게/메뉴/상품 정보.

    이 맥락을 멀티모달 모델에 함께 줘서 '데미소스 돈까스'처럼 구체적으로 유추하게 한다.
    """
    parts: list[str] = []
    if memo and memo.strip():
        parts.append(f"메모: {memo.strip()}")
    if card and card.place:
        p = card.place
        if p.name:
            parts.append("가게: " + p.name + (f" ({p.category})" if p.category else ""))
        if p.description:
            parts.append(f"가게 소개: {p.description}")
        if p.menus:
            lines = []
            for m in p.menus[:30]:
                seg = m.name + (f" {m.price}" if m.price else "")
                if m.description:
                    seg += f" — {m.description}"
                lines.append(seg)
            parts.append("메뉴:\n" + "\n".join(lines))
    if card and card.product:
        pr = card.product
        if pr.name:
            parts.append("상품: " + pr.name + (f" ({pr.category})" if pr.category else ""))
        if pr.detail_text:
            parts.append("상세설명: " + pr.detail_text[:1500])
        if pr.selling_points:
            parts.append("셀링포인트: " + ", ".join(pr.selling_points))
    return "\n".join(parts)


def _categories_for(card: FactCard | None, review_type: str | None) -> list[str] | None:
    """리뷰 타입(또는 카드 종류)에 맞는 사진 카테고리 프리셋."""
    from autoblog.config import load_photo_categories

    cats = load_photo_categories()
    key = review_type or (card.type.value if (card and card.type) else None)
    return cats.get(key or "") or cats.get("place")


def caption_photos(
    memo: str = "",
    *,
    place_url: str | None = None,
    product: str | None = None,
    photos: list[str] | None = None,
    review_type: str | None = None,
    hint: str = "",
) -> list[dict]:
    """온디맨드 '✨ AI 자동 추천': (가능하면)수집 → 맥락 조립 → 멀티모달 배치 캡션.

    반환: [{"path","label","caption"}] (사진 순서대로). 수집 실패해도 메모 맥락만으로 진행.
    """
    paths = [p for p in (photos or []) if p]
    if not paths:
        return []
    card = None
    try:  # 메뉴·가게설명을 맥락으로 쓰려고 정보만 수집(사진 분류는 안 함)
        if place_url or product:
            card = collect_card(place_url=place_url, product=product, use_cache=True)
    except Exception:  # noqa: BLE001 — 수집 실패해도 메모만으로 캡션 진행
        card = None
    from autoblog.vision import smart_caption_photos

    meta = smart_caption_photos(
        paths, build_photo_context(card, memo), categories=_categories_for(card, review_type), hint=hint
    )
    return [{"path": p, **meta.get(p, {"label": "기타", "caption": ""})} for p in paths]


def build_export_prompt(
    memo: str,
    *,
    card: FactCard | None = None,
    place_url: str | None = None,
    product: str | None = None,
    card_kind: str | None = None,
    place_hint: str | None = None,
    photos: list[str] | None = None,
    style: StyleProfile | None = None,
    rules: CommonRules | None = None,
    guidelines: Guidelines | None = None,
    base_prompt: str | None = None,
    emphasis: bool = False,
    structure: bool = False,
    stickers: bool = False,
    sticker_catalog: StickerCatalog | None = None,
    sticker_favorites_only: bool = True,
    divider_variants: list[str] | None = None,
    quote_variants: list[str] | None = None,
    photo_meta: dict[str, dict] | None = None,
    use_cache: bool = False,
    inplace: bool = False,
    restyle: bool = False,
    wishlist: bool = False,
    consumed: bool = False,
    progress: Callable[[str], None] | None = None,
) -> str:
    """수집(선택)→프롬프트 조립까지만 하고, 다른 챗봇에 붙여넣을 단일 텍스트로 반환.

    run_pipeline과 동일한 지시문(강조/구조/스티커/규칙)을 넣되 LLM은 호출하지 않는다.
    system을 지시문으로, user를 입력 자료로 묶어 그대로 복사-붙여넣기 가능하게 만든다.
    photo_meta(경로→{label,caption})를 주면 사진을 그 값으로 채운다(Vision 분류 생략).
    use_cache=True면 같은 URL의 수집 결과를 재사용한다. progress(msg)로 단계 상태 전달.
    place_hint는 유저가 적은 '어떤 장소인지 메모' — 프롬프트 선택(default/venue) override.
    wishlist=True(상품 카드 전용)면 '아직 안 산 위시리스트' 관점으로 override한다.
    consumed=True(상품 카드 전용)면 '이번에 산 것들 모음' 목록형으로 override한다.
    """
    from autoblog.draft.generate import build_prompt

    if card is None:
        try:
            card = collect_card(
                place_url, product, photos, photo_meta=photo_meta,
                card_kind=card_kind, place_hint=place_hint, use_cache=use_cache, progress=progress,
            )
        except Exception:  # noqa: BLE001 — 수집 실패해도 내보내기는 메모만으로 진행
            if photos:
                card = collect_card(
                    photos=photos, photo_meta=photo_meta,
                    card_kind=card_kind, place_hint=place_hint,
                )
            else:
                ctype = CardType.product if card_kind == "product" else CardType.place
                card = FactCard(type=ctype, place_hint=(place_hint or "").strip() or None)
    if progress:
        progress("내 프롬프트와 입력 자료를 합치는 중…")
    labels: list[str] = []
    if stickers:
        if sticker_catalog is None:
            from autoblog.publish.stickers import load_sticker_catalog

            sticker_catalog = load_sticker_catalog()
        labels = sticker_catalog.labels(favorites_only=sticker_favorites_only)
    req = DraftRequest(
        fact_card=card,
        experience_memo=memo,
        base_prompt=base_prompt,
        style=style,
        rules=rules,
        guidelines=guidelines,
        emphasis=emphasis,
        structure=structure,
        divider_variants=divider_variants or [],
        quote_variants=quote_variants or [],
        sticker_labels=labels,
        place=_place_info(card)[0],
        inplace=inplace,
        restyle=restyle,
        wishlist=wishlist,
        consumed=consumed,
    )
    system, user = build_prompt(req)
    # 출력 프로토콜: 자가 점검은 속으로만, 본문은 한 번만 출력. (예전 '초안→점검→최종본'
    # 3단계는 본문이 두 번 나와 길고 느렸다. 붙여넣기 추출은 옛 형식 응답도 계속 지원.)
    return (
        "# 지시문 (이 규칙대로 블로그 글을 써줘)\n\n"
        f"{system}\n\n"
        "---\n\n"
        "# 입력 자료\n\n"
        f"{user}\n\n"
        "---\n\n"
        "위 지시문을 지켜서 네이버 블로그 글 본문을 완성해줘.\n"
        "출력하기 전에, 지시문 맨 끝의 자가 점검 목록을 한 항목씩 네가 쓴 글과 대조해서 "
        "어긴 곳을 전부 고쳐라. 이 점검 과정은 절대 출력하지 말고 속으로만 해.\n"
        "출력은 고친 완성본 전체 딱 한 번만. 초안·점검 결과·최종본 표시 등 단계를 나누지 말고, "
        "인사말·작업 설명·요약·마무리 코멘트 등 글 외의 말도 일절 쓰지 마."
    )


def plan_from_text(
    text: str,
    *,
    photos: list[str] | None = None,
    emphasis: bool = False,
    structure: bool = False,
    stickers: bool = False,
    sticker_catalog: StickerCatalog | None = None,
    consistent_pack: bool = False,
    sticker_favorites_only: bool = True,
    divider_variant: int = 1,
    quote_variant: int = 1,
    place_query: str | None = None,
    place_address: str | None = None,
    sponsored: bool = False,
    sponsor_links: list[str] | None = None,
    product_links: list[str] | None = None,
    sponsor_sticker: str = "",
    photo_meta: dict[str, dict] | None = None,
    inplace: bool = False,
    guidelines: Guidelines | None = None,
) -> PipelineResult:
    """외부 챗봇에서 받아온 초안 텍스트 → 마커 파싱·후처리 → 게시 플랜.

    수집·LLM 호출 없이 run_pipeline의 후반부(초안→플랜)만 재현한다. 선택한 사진은
    플랜에 이미지 블록으로 배치된다. place_query를 주면 [지도] 마커를 그 가게명으로
    해석하고, place_address(도로명)를 주면 검색 결과를 그 주소로 매칭한다.
    photo_meta(경로→{label,caption})를 주면 사진을 그 값으로 채운다(Vision 분류 생략).
    guidelines를 주면 받아온 글도 생성 경로와 동일하게 자동 대조한다(반려 예방) —
    프롬프트는 가이드라인으로 만들었는데 받아온 글 검증이 빠지면 킬러 기능이 새는 셈.
    """
    catalog = None
    labels: list[str] = []
    if stickers:
        if sticker_catalog is None:
            from autoblog.publish.stickers import load_sticker_catalog

            sticker_catalog = load_sticker_catalog()
        catalog = sticker_catalog
        labels = catalog.labels(favorites_only=sticker_favorites_only)
    if catalog is None and sponsored:  # 협찬 고지 스티커(태그명) 해석용 카탈로그
        from autoblog.publish.stickers import load_sticker_catalog

        catalog = load_sticker_catalog()
    card = FactCard(type=CardType.place)
    if photos:
        if photo_meta is not None:
            from autoblog.collect.photos import attach_photos

            attach_photos(card, photos, photo_meta)
        else:
            from autoblog.collect.photos import classify_photos_into

            classify_photos_into(card, photos)
    req = DraftRequest(
        fact_card=card,
        experience_memo="",
        emphasis=emphasis,
        structure=structure,
        sticker_labels=labels,
        inplace=inplace,
        guidelines=guidelines,
    )
    draft = generate_draft(req, raw_override=text)
    picker = (
        StickerPicker(catalog, consistent=consistent_pack, favorites_only=sticker_favorites_only)
        if (catalog and labels)
        else None
    )
    plan = build_publish_plan(
        draft, photos=card.photos, picker=picker,
        divider_variant=divider_variant, quote_variant_default=quote_variant,
        structure_styles=load_structure_styles(), place_query=place_query,
        place_address=place_address, sponsor=sponsored, sponsor_links=sponsor_links,
        product_links=product_links,
        sponsor_sticker=sponsor_sticker, sticker_catalog=catalog,
        inplace=inplace, bare_text_sticker=True,
    )
    return PipelineResult(card=card, draft=draft, plan=plan)


def run_pipeline(
    memo: str,
    *,
    card: FactCard | None = None,
    place_url: str | None = None,
    product: str | None = None,
    card_kind: str | None = None,
    place_hint: str | None = None,
    photos: list[str] | None = None,
    style: StyleProfile | None = None,
    rules: CommonRules | None = None,
    guidelines: Guidelines | None = None,
    base_prompt: str | None = None,
    template_text: str | None = None,
    emphasis: bool = False,
    structure: bool = False,
    stickers: bool = False,
    sticker_catalog: StickerCatalog | None = None,
    consistent_pack: bool = False,
    sticker_favorites_only: bool = True,
    divider_variant: int = 1,
    quote_variant: int = 1,
    divider_variants: list[str] | None = None,
    quote_variants: list[str] | None = None,
    sponsored: bool = False,
    sponsor_links: list[str] | None = None,
    product_links: list[str] | None = None,
    sponsor_sticker: str = "",
    model: str | None = None,
    photo_meta: dict[str, dict] | None = None,
    use_cache: bool = False,
    inplace: bool = False,
    restyle: bool = False,
    wishlist: bool = False,
    consumed: bool = False,
    progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    """수집→초안(강조/구조/스티커 마커 자동)→게시 플랜까지 한 번에 조립.

    card를 직접 주면 수집을 건너뛴다(테스트/재사용). stickers=True면 카탈로그 라벨을
    초안에 주입하고 같은 카탈로그로 picker를 만들어 플랜에서 스티커를 해석한다.
    photo_meta(경로→{label,caption})를 주면 사진을 그 값으로 채우고 Vision 분류를 건너뛴다.
    use_cache=True면 같은 URL의 수집 결과를 재사용한다(webui 세션).
    place_hint는 유저가 적은 '어떤 장소인지 메모' — 프롬프트 선택(default/venue) override.
    wishlist=True(상품 카드 전용)면 '아직 안 산 위시리스트' 관점으로 override한다.
    consumed=True(상품 카드 전용)면 '이번에 산 것들 모음' 목록형으로 override한다.
    """
    if card is None:
        card = collect_card(
            place_url, product, photos, photo_meta=photo_meta,
            card_kind=card_kind, place_hint=place_hint, use_cache=use_cache, progress=progress,
        )
    elif photos and not card.photos:
        # 카드를 직접 넘긴 경우에도 사진은 붙인다 — 수집만 건너뛰는 경로인데 사진까지
        # 버려져 플랜에 이미지 블록이 하나도 안 생기던 실측 버그(글이 사진 없이 저장됨).
        from autoblog.collect.photos import attach_photos, classify_photos_into

        if photo_meta is not None:
            attach_photos(card, photos, photo_meta)
        else:
            classify_photos_into(card, photos)

    catalog = None
    labels: list[str] = []
    if stickers:
        if sticker_catalog is None:
            from autoblog.publish.stickers import load_sticker_catalog

            sticker_catalog = load_sticker_catalog()
        catalog = sticker_catalog
        labels = catalog.labels(favorites_only=sticker_favorites_only)
    if catalog is None and sponsored:  # 협찬 고지 스티커(태그명) 해석용 카탈로그
        from autoblog.publish.stickers import load_sticker_catalog

        catalog = load_sticker_catalog()

    place_on, place_query, place_address = _place_info(card)

    req = DraftRequest(
        fact_card=card,
        experience_memo=memo,
        base_prompt=base_prompt,
        template_text=template_text,
        style=style,
        rules=rules,
        guidelines=guidelines,
        emphasis=emphasis,
        structure=structure,
        divider_variants=divider_variants or [],
        quote_variants=quote_variants or [],
        sticker_labels=labels,
        place=place_on,
        inplace=inplace,
        restyle=restyle,
        wishlist=wishlist,
        consumed=consumed,
    )
    draft = generate_draft(req, model=model)

    picker = (
        StickerPicker(catalog, consistent=consistent_pack, favorites_only=sticker_favorites_only)
        if (catalog and labels)
        else None
    )
    plan = build_publish_plan(
        draft, photos=card.photos, picker=picker,
        divider_variant=divider_variant, quote_variant_default=quote_variant,
        structure_styles=load_structure_styles(), place_query=place_query,
        place_address=place_address, sponsor=sponsored, sponsor_links=sponsor_links,
        product_links=product_links,
        sponsor_sticker=sponsor_sticker, sticker_catalog=catalog,
        inplace=inplace, bare_text_sticker=True,
    )
    return PipelineResult(card=card, draft=draft, plan=plan)
