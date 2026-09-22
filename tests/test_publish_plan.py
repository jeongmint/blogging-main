from autoblog.collect.fact_card import PhotoItem
from autoblog.draft.generate import DraftResult
from autoblog.publish.editor import selectors_ready
from autoblog.publish.emphasis import EmphasisStyle, StyledSpan
from autoblog.publish.plan import (
    HashtagStyle,
    RoleStyle,
    StructureStyles,
    build_publish_plan,
)


def test_build_plan_title_and_blocks():
    draft = DraftResult(
        text="수지골 추어탕 후기\n\n비 오는 날 갔어요.\n[사진]\n추어탕이 진했어요.",
    )
    photos = [PhotoItem(path="food.jpg", label="음식")]
    plan = build_publish_plan(draft, photos)

    assert plan.title == "수지골 추어탕 후기"
    kinds = [b.kind for b in plan.blocks]
    assert kinds == ["text", "image", "text"]
    assert plan.blocks[1].image_path == "food.jpg"
    assert "비 오는 날" in plan.blocks[0].text
    assert "추어탕이 진했어요" in plan.blocks[2].text


def test_build_plan_photo_label_matching():
    # 외관 문단 뒤 [사진:외관], 음식 문단 뒤 [사진:음식] — 업로드 순서(음식 먼저)와 무관하게 라벨로 매칭
    draft = DraftResult(text="제목\n\n외관이 멋졌어요.\n[사진:외관]\n파스타가 맛있었어요.\n[사진:음식]")
    photos = [PhotoItem(path="food.jpg", label="음식"), PhotoItem(path="exterior.jpg", label="외관")]
    plan = build_publish_plan(draft, photos)
    imgs = [b for b in plan.blocks if b.kind == "image"]
    assert [b.image_path for b in imgs] == ["exterior.jpg", "food.jpg"]


def test_build_plan_photo_label_fallback_and_leftover():
    # 라벨 없는 [사진]은 남은 순서대로, 매칭 안 된 사진은 끝에 첨부
    draft = DraftResult(text="제목\n\n본문.\n[사진:메뉴판]\n다음.\n[사진]")
    photos = [PhotoItem(path="a.jpg", label="음식"), PhotoItem(path="b.jpg", label="외관")]
    plan = build_publish_plan(draft, photos)
    imgs = [b.image_path for b in plan.blocks if b.kind == "image"]
    # [사진:메뉴판] 매칭 실패 → 남은 첫 사진(a), [사진] → 남은 사진(b)
    assert imgs == ["a.jpg", "b.jpg"]


def test_build_plan_video_marker_matches_only_video():
    # [사진]은 영상을 집지 않고, [영상]은 영상만 집는다(media_kind로 분리)
    draft = DraftResult(text="제목\n\n매장 외관.\n[사진]\n분위기 영상.\n[영상]")
    photos = [
        PhotoItem(path="ext.jpg", label="외관", media_kind="image"),
        PhotoItem(path="clip.mp4", label="기타", media_kind="video"),
    ]
    plan = build_publish_plan(draft, photos)
    kinds = [b.kind for b in plan.blocks]
    assert kinds == ["text", "image", "text", "video"]
    assert plan.blocks[1].image_path == "ext.jpg"
    assert plan.blocks[3].kind == "video" and plan.blocks[3].image_path == "clip.mp4"


def test_build_plan_video_label_used_as_block_label():
    # 캡션이 있으면 영상 블록 라벨(=업로더 제목)로 쓰인다
    draft = DraftResult(text="제목\n\n본문.\n[영상]")
    photos = [PhotoItem(path="clip.mp4", caption="조리 과정", media_kind="video")]
    plan = build_publish_plan(draft, photos)
    vid = next(b for b in plan.blocks if b.kind == "video")
    assert vid.image_label == "조리 과정"


def test_build_plan_leftover_video_spread_as_video_block():
    # [영상] 마커가 없어도 남은 영상은 본문에 분산되며 kind='video'로 생성(image로 새지 않음)
    draft = DraftResult(text="제목\n\n첫 문단.\n[구분선]\n둘째 문단.")
    photos = [
        PhotoItem(path="a.jpg", label="외관", media_kind="image"),
        PhotoItem(path="v.mp4", label="기타", media_kind="video"),
    ]
    plan = build_publish_plan(draft, photos)
    kinds = [b.kind for b in plan.blocks]
    assert kinds == ["text", "image", "divider", "text", "video"]
    assert plan.blocks[4].image_path == "v.mp4"


def test_build_plan_distributes_emphasis():
    span = StyledSpan(text="13,000원", preset_id=20, style=EmphasisStyle(text_color="#C2410C"))
    draft = DraftResult(text="제목\n\n추어탕은 13,000원이었어요.", emphases=[span])
    plan = build_publish_plan(draft)
    text_block = next(b for b in plan.blocks if b.kind == "text")
    assert text_block.emphases == [span]  # 해당 텍스트 블록에 배분


def test_build_plan_leftover_photos_spread_across_body():
    # 마커가 부족해도 남은 사진은 본문 텍스트 블록들 사이에 분산(끝에 몰지 않음)
    draft = DraftResult(text="제목\n\n첫 문단.\n[구분선]\n둘째 문단.")
    photos = [PhotoItem(path="a.jpg", label="외관"), PhotoItem(path="b.jpg", label="음식")]
    plan = build_publish_plan(draft, photos)
    kinds = [b.kind for b in plan.blocks]
    # 두 텍스트 블록 각각 뒤에 사진이 분산됨 (끝에 [..image, image]로 몰리지 않음)
    assert kinds == ["text", "image", "divider", "text", "image"]
    assert [b.image_path for b in plan.blocks if b.kind == "image"] == ["a.jpg", "b.jpg"]


def test_build_plan_leftover_photos_skip_header_blocks():
    # 태그줄은 본문 블록 대신 plan.tags(네이버 태그칸)로 빠지고,
    # 남은 사진 분산이 헤더(대제목) 블록 뒤에 꽂히지 않는다.
    draft = DraftResult(
        text=(
            "제목 스물자 내외로 맞춘 예시\n"
            "대제목 한 줄\n"
            "#태그1 #태그2 #태그3\n\n"
            "인트로 문단.\n\n"
            "본문 문단."
        )
    )
    photos = [PhotoItem(path="a.jpg", label="음식"), PhotoItem(path="b.jpg", label="내부")]
    plan = build_publish_plan(draft, photos, structure_styles=_structure_styles())
    assert plan.tags == ["태그1", "태그2", "태그3"]
    assert all("#태그1" not in b.text for b in plan.blocks)  # 태그줄은 본문에 안 남는다
    big = next(i for i, b in enumerate(plan.blocks) if b.text == "대제목 한 줄")
    # 헤더(대제목) 바로 뒤에는 사진이 없다 — 태그줄 자리 구분선이 온다
    assert plan.blocks[big + 1].kind == "divider"
    # 사진은 전부 본문에 들어간다
    assert [b.image_path for b in plan.blocks if b.kind == "image"] == ["a.jpg", "b.jpg"]


def test_build_plan_leftover_not_between_photo_and_caption_text():
    # 남은 사진이 '마커 사진 → 설명 문단' 짝 사이에 끼어들지 않는다
    draft = DraftResult(
        text="제목\n\n인트로 문단.\n[사진:외관]\n외관 설명 문단.\n[구분선]\n마무리 문단."
    )
    photos = [PhotoItem(path="ext.jpg", label="외관"), PhotoItem(path="rest.jpg", label="음식")]
    plan = build_publish_plan(draft, photos)
    ext = next(i for i, b in enumerate(plan.blocks) if b.image_path == "ext.jpg")
    # 마커 사진 바로 다음은 설명 문단(사진이 연달아 붙지 않음)
    assert plan.blocks[ext + 1].kind == "text" and "외관 설명" in plan.blocks[ext + 1].text


def test_build_plan_photo_caption_marker_pins_exact_photo():
    # 같은 라벨 사진이 여러 장일 때 [사진:캡션]으로 특정 사진을 콕 집을 수 있다
    draft = DraftResult(
        text="제목\n\n본문.\n[사진:떡볶이]\n떡볶이 설명.\n[사진:음식]\n치즈카츠 설명."
    )
    photos = [
        PhotoItem(path="katsu.jpg", label="음식", caption="치즈카츠 클로즈업"),
        PhotoItem(path="tteok.jpg", label="음식", caption="떡볶이"),
    ]
    plan = build_publish_plan(draft, photos)
    imgs = [b.image_path for b in plan.blocks if b.kind == "image"]
    # [사진:떡볶이]는 캡션 매칭으로 tteok을, [사진:음식]은 남은 katsu를 집는다
    assert imgs == ["tteok.jpg", "katsu.jpg"]


def test_build_plan_leftover_photos_no_text_appended():
    # 본문 텍스트 블록이 없으면 남은 사진은 그대로 첨부
    draft = DraftResult(text="제목\n\n[구분선]")
    photos = [PhotoItem(path="a.jpg", label="외관")]
    plan = build_publish_plan(draft, photos)
    assert [b.image_path for b in plan.blocks if b.kind == "image"] == ["a.jpg"]


def test_build_plan_divider_and_quote():
    draft = DraftResult(text=(
        "제목\n\n첫 문단이에요.\n[구분선]\n[인용구:3]\n인상 깊은 한마디\n[/인용구]\n마지막 문단."
    ))
    plan = build_publish_plan(draft)
    kinds = [(b.kind, b.variant) for b in plan.blocks]
    assert ("divider", 1) in kinds
    quote = next(b for b in plan.blocks if b.kind == "quote")
    assert quote.variant == 3
    assert quote.text == "인상 깊은 한마디"
    assert quote.align == "center"  # 말풍선(3)은 가운데정렬
    # 텍스트 블록은 구분선/인용구 기준으로 분리
    texts = [b.text for b in plan.blocks if b.kind == "text"]
    assert "첫 문단이에요." in texts and "마지막 문단." in texts


def test_quote_align_follows_variant():
    # 왼쪽줄(2)·밑줄형(4)은 에디터 기본이 왼쪽정렬 → align 없음. 나머지는 가운데정렬.
    for variant, expected in ((1, "center"), (2, None), (3, "center"),
                              (4, None), (5, "center"), (6, "center")):
        plan = build_publish_plan(
            DraftResult(text=f"제목\n\n글\n[인용구:{variant}]\n한마디\n[/인용구]")
        )
        quote = next(b for b in plan.blocks if b.kind == "quote")
        assert quote.align == expected, f"variant={variant}"


def test_build_plan_divider_variant():
    plan = build_publish_plan(DraftResult(text="제목\n\n글\n[구분선:5]\n끝"))
    div = next(b for b in plan.blocks if b.kind == "divider")
    assert div.variant == 5


def test_build_plan_sticker_marker_resolved():
    from autoblog.publish.stickers import Sticker, StickerCatalog, StickerPicker

    cat = StickerCatalog(
        stickers=[Sticker(pack="ogq_a", index=3, tags=["맛있음"])], favorites=["ogq_a:3"]
    )
    picker = StickerPicker(cat)  # 즐겨찾기-온리 기본 → 즐겨찾기한 스티커만 게시에 쓰임
    draft = DraftResult(text="제목\n\n정말 맛있었어요.\n[스티커:맛있음]\n또 갈래요.")
    plan = build_publish_plan(draft, picker=picker)
    sticker = next(b for b in plan.blocks if b.kind == "sticker")
    assert sticker.sticker_pack == "ogq_a" and sticker.sticker_index == 3
    # 텍스트는 스티커 기준으로 분리
    texts = [b.text for b in plan.blocks if b.kind == "text"]
    assert "정말 맛있었어요." in texts and "또 갈래요." in texts


def test_build_plan_sticker_dropped_without_match():
    # picker 없거나 매칭 실패면 마커는 본문에 누수되지 않고 사라진다
    draft = DraftResult(text="제목\n\n본문\n[스티커:없음]\n끝")
    plan = build_publish_plan(draft)  # picker 없음
    assert all(b.kind != "sticker" for b in plan.blocks)
    assert all("[스티커" not in b.text for b in plan.blocks)


def _filler_picker():
    from autoblog.publish.stickers import Sticker, StickerCatalog, StickerPicker

    cat = StickerCatalog(
        stickers=[
            Sticker(pack="ogq_a", index=1, tags=["기쁨"]),
            Sticker(pack="ogq_a", index=2, tags=["신남"]),
        ],
        favorites=["ogq_a:1", "ogq_a:2"],
    )
    return StickerPicker(cat)


def test_bare_text_gets_filler_sticker():
    # 옵션(기본 꺼짐)을 켜면: 사진이 앞에 몰려 뒤쪽 문단이 텍스트만 남으면 그 끝에 이모티콘을 채운다.
    # 사진 2장을 앞에서 다 쓰고, 뒤 두 섹션(구분선으로 나뉜 텍스트)은 사진이 없다.
    draft = DraftResult(text="제목\n\n인트로.\n[사진]\n[사진]\n[구분선]\n둘째 섹션.\n[구분선]\n셋째 섹션.")
    photos = [PhotoItem(path="a.jpg", label="음식"), PhotoItem(path="b.jpg", label="음식")]
    plan = build_publish_plan(draft, photos, picker=_filler_picker(), bare_text_sticker=True)
    kinds = [b.kind for b in plan.blocks]
    # 사진 배치·순서는 그대로, 사진 없는 뒤쪽 텍스트 문단에만 스티커가 붙는다
    assert [b.image_path for b in plan.blocks if b.kind == "image"] == ["a.jpg", "b.jpg"]
    assert kinds.count("sticker") >= 1
    # 스티커는 항상 텍스트 문단 바로 뒤에 오고, 사진 옆에는 끼지 않는다
    for i, b in enumerate(plan.blocks):
        if b.kind == "sticker":
            assert plan.blocks[i - 1].kind == "text"


def test_bare_text_skips_header_and_photo_adjacent():
    # 첫 사진 앞(인트로)과 사진에 붙은 문단에는 스티커를 넣지 않는다
    draft = DraftResult(text="제목\n\n인트로 문단.\n[사진]\n사진 옆 문단.")
    photos = [PhotoItem(path="a.jpg", label="음식")]
    plan = build_publish_plan(draft, photos, picker=_filler_picker(), bare_text_sticker=True)
    # 인트로(첫 사진 앞)·사진 바로 뒤 문단 모두 사진과 붙어 있어 스티커 없음
    assert all(b.kind != "sticker" for b in plan.blocks)
    assert [b.kind for b in plan.blocks] == ["text", "image", "text"]


def test_bare_text_no_sticker_without_picker():
    # picker가 없으면(스티커 미설정) 아무것도 넣지 않는다
    draft = DraftResult(text="제목\n\n인트로.\n[사진]\n[구분선]\n뒤 문단.")
    photos = [PhotoItem(path="a.jpg", label="음식")]
    plan = build_publish_plan(draft, photos)  # picker 없음
    assert all(b.kind != "sticker" for b in plan.blocks)


def test_bare_text_disabled():
    # bare_text_sticker=False면 채우지 않는다
    draft = DraftResult(text="제목\n\n인트로.\n[사진]\n[구분선]\n뒤 문단.")
    photos = [PhotoItem(path="a.jpg", label="음식")]
    plan = build_publish_plan(draft, photos, picker=_filler_picker(), bare_text_sticker=False)
    assert all(b.kind != "sticker" for b in plan.blocks)


def test_bare_text_skipped_when_no_photos():
    # 옵션을 켜도, 사진이 아예 없는 글은 대상 아님(허전한 문단 채우기 안 함)
    draft = DraftResult(text="제목\n\n첫 문단.\n[구분선]\n둘째 문단.")
    plan = build_publish_plan(draft, picker=_filler_picker(), bare_text_sticker=True)
    assert all(b.kind != "sticker" for b in plan.blocks)


def _structure_styles():
    return StructureStyles(
        big_title=RoleStyle(font="nanummaruburi", size=30, color="#395D73"),
        subheading=RoleStyle(font="nanumuriddalsongeulssi", size=19, color="#EB7D7D"),
        hashtags=HashtagStyle(font="system", size=11, color="#4383BF", per_line=2, divider="line3"),
    )


def test_structure_styles_header_and_subheading():
    draft = DraftResult(
        text=(
            "혜화 치즈철판카츠 메종아카이\n"
            "친구랑 주말 대학로 데이트 코스\n"
            "아니근데 진짜 맛있당께요\n"
            "혜화맛집 #대학로맛집 #혜화내돈내산 #메종아카이\n\n"
            "인트로 한 줄.\n\n"
            "1. 치즈철판카츠 후기\n"
            "겉은 바삭 속은 촉촉."
        )
    )
    plan = build_publish_plan(draft, structure_styles=_structure_styles())

    # 첫 줄은 제목칸, 본문 대제목은 별도(마루부리30). 13자라 균형 있게 두 줄로 접히고
    # 두 줄 각각 같은 대제목 서식 span이 붙는다.
    assert plan.title == "혜화 치즈철판카츠 메종아카이"
    big = next(b for b in plan.blocks if b.text.replace("\n", " ") == "친구랑 주말 대학로 데이트 코스")
    assert big.text == "친구랑 주말\n대학로 데이트 코스"
    assert len(big.emphases) == 2
    assert all(sp.style.font_family == "nanummaruburi" for sp in big.emphases)
    assert all(sp.style.font_size == "30" for sp in big.emphases)
    assert all(sp.style.text_color == "#395D73" for sp in big.emphases)

    # 태그줄은 본문에 렌더하지 않고 발행 태그칸용 plan.tags로 수집한다
    # (첫 태그의 빠진 #("혜화맛집")도 그냥 태그로 인정).
    assert plan.tags == ["혜화맛집", "대학로맛집", "혜화내돈내산", "메종아카이"]
    assert all("#대학로맛집" not in b.text for b in plan.blocks)

    # 드립 한 줄(예전 해시태그 자리)에는 해시태그 서식(system 11 파랑·가운데)이 입혀지고,
    # 그 뒤에 가운데 꺾인 선(variant 4)이 온다
    drip = next(b for b in plan.blocks if b.text == "아니근데 진짜 맛있당께요")
    assert drip.align == "center"
    assert len(drip.emphases) == 1
    assert drip.emphases[0].style.font_family == "system"
    assert drip.emphases[0].style.font_size == "11"
    assert drip.emphases[0].style.text_color == "#4383BF"
    idx = plan.blocks.index(drip)
    assert plan.blocks[idx + 1].kind == "divider" and plan.blocks[idx + 1].variant == 4

    # 소제목("1. ...")은 인용구 밑줄형 블록으로 렌더(텍스트 "1. " 자동 번호목록 누수 회피)
    from autoblog.publish.plan import QUOTE_META

    sub = next(b for b in plan.blocks if b.text == "1. 치즈철판카츠 후기")
    assert sub.kind == "quote"
    assert sub.variant == QUOTE_META["quotation_underline"][0]


def test_drip_line_styled_without_tag_line():
    # 리스타일 초안(태그줄 없음)도 대제목 아래 한 줄 문단(드립)에 해시태그 서식+헤더 구분선
    draft = DraftResult(
        text=(
            "다이소 공병 펌프 스프레이 차이 후기\n"
            "요즘 스킨 쓸 맛 나는 이유\n\n"
            "통만 바뀌면 완벽한데 말이야\n\n"
            "인트로 첫 줄이에요\n이어지는 둘째 줄이에요"
        )
    )
    plan = build_publish_plan(draft, structure_styles=_structure_styles())

    drip = next(b for b in plan.blocks if b.text == "통만 바뀌면 완벽한데 말이야")
    assert drip.align == "center"
    assert len(drip.emphases) == 1
    assert drip.emphases[0].style.font_size == "11"
    assert drip.emphases[0].style.text_color == "#4383BF"
    idx = plan.blocks.index(drip)
    assert plan.blocks[idx + 1].kind == "divider" and plan.blocks[idx + 1].variant == 4
    assert plan.tags == []

    # 대제목 아래 짧은 2줄 문단도 드립 — 모델이 '한 줄 한 절' 습관으로 드립을 두 줄로
    # 쪼개 쓴 실측 사례(리스타일). 작은 글씨라 줄 나눌 이유가 없어 한 줄로 합쳐진다.
    two_line = DraftResult(
        text=(
            "다이소 공병 펌프 스프레이 차이 후기\n"
            "요즘 스킨 쓸 맛 나는 이유\n\n"
            "내가 쓰는 스킨.. 통만 바뀌면\n완벽할 것 같지 않을까 ..,?\n\n"
            "인트로 첫 줄이에요\n이어지는 둘째 줄이에요"
        )
    )
    plan3 = build_publish_plan(two_line, structure_styles=_structure_styles())
    drip2 = next(b for b in plan3.blocks if "통만 바뀌면" in b.text)
    assert drip2.text == "내가 쓰는 스킨.. 통만 바뀌면 완벽할 것 같지 않을까 ..,?"
    assert len(drip2.emphases) == 1
    assert drip2.emphases[0].style.font_size == "11"
    idx2 = plan3.blocks.index(drip2)
    assert plan3.blocks[idx2 + 1].kind == "divider"


def test_short_intro_after_tag_line_stays_body():
    # 드립 없이 '대제목→태그줄→짧은 인트로'로 쓴 초안(우이락 실측) — 태그줄을 빈 줄
    # 취급하면 인트로 첫 줄이 가짜 드립(작은 파란 글씨)으로 잡히는 회귀가 났다.
    # 태그줄은 헤더 경계: 그 뒤 짧은 문단은 본문으로 남아야 한다.
    draft = DraftResult(
        text=(
            "우이락 수지구청점 두부과자 후기\n"
            "한 번 사면 순삭되는 그 과자\n\n"
            "#우이락 #수지구청간식 #두부과자\n\n"
            "지나가다 우연히 들렀는데요\n\n"
            "본문 문단입니다 이어집니다"
        )
    )
    plan = build_publish_plan(draft, structure_styles=_structure_styles())
    assert plan.tags == ["우이락", "수지구청간식", "두부과자"]
    intro = next(b for b in plan.blocks if "지나가다 우연히" in b.text)
    assert intro.emphases == []  # 드립 서식(11pt 파랑)이 붙으면 안 된다


def test_tag_line_above_big_title_keeps_title_style():
    # 모델이 태그줄을 대제목보다 위에 쓴 이탈 — 태그줄은 렌더되지 않으니 '본문 시작'이
    # 아니고, 그 아래 첫 짧은 줄은 여전히 대제목 서식을 받아야 한다.
    draft = DraftResult(
        text=(
            "우이락 수지구청점 두부과자 후기\n"
            "#우이락 #수지구청간식 #두부과자\n\n"
            "한 번 사면 순삭되는 그 과자\n\n"
            "본문 문단입니다 이어집니다"
        )
    )
    plan = build_publish_plan(draft, structure_styles=_structure_styles())
    assert plan.tags == ["우이락", "수지구청간식", "두부과자"]
    big = next(b for b in plan.blocks if "순삭되는" in b.text)
    assert {sp.style.font_size for sp in big.emphases} == {"30"}

    # 대제목 아래 2줄 문단이 글의 전부면(뒤에 본문 없음) 드립이 아니라 본문 — 오적용 방지
    no_drip = DraftResult(
        text=(
            "다이소 공병 펌프 스프레이 차이 후기\n"
            "요즘 스킨 쓸 맛 나는 이유\n\n"
            "이 스킨.. 통만 바뀌면\n완벽할 것 같지 않나요?"
        )
    )
    plan2 = build_publish_plan(no_drip, structure_styles=_structure_styles())
    body = next(b for b in plan2.blocks if "이 스킨" in b.text)
    assert not any(sp.style.font_size == "11" for sp in body.emphases)


def test_drip_styled_with_sponsor_marker_in_header():
    # 협찬 사진 마커가 헤더 위/사이에 껴도 드립 해시태그 서식은 유지된다 — 마커 줄 때문에
    # 드립 감지가 통째로 꺼지고(맨 위), 직전 블록 체크에 걸려(사이) 서식이 사라지던 실측 버그.
    photos = [PhotoItem(path="spon.jpg", label="협찬"), PhotoItem(path="food.jpg", label="음식")]
    for marker_pos in ("top", "between"):
        head = "다이소 공병 후기\n요즘 스킨 쓸 맛 나는 이유\n\n"
        if marker_pos == "top":
            text = "다이소 공병 후기\n[사진:협찬]\n\n요즘 스킨 쓸 맛 나는 이유\n\n"
        else:
            text = head + "[사진:협찬]\n\n"
        text += "통만 바뀌면 완벽한데 말이야\n\n인트로 첫 줄이에요\n둘째 줄이에요"
        for inplace in (False, True):
            plan = build_publish_plan(
                DraftResult(text=text), list(photos),
                structure_styles=_structure_styles(), inplace=inplace,
            )
            drip = next(b for b in plan.blocks if b.text == "통만 바뀌면 완벽한데 말이야")
            assert drip.emphases and drip.emphases[0].style.font_size == "11", (marker_pos, inplace)
            big = next(b for b in plan.blocks if "요즘 스킨" in (b.text or ""))
            assert big.emphases, (marker_pos, inplace)
            # 협찬 고지 사진은 in-place 경로에서도 '작게'가 붙는다(안 붙어 크기·정렬이 안 되던 버그)
            spon = next(b for b in plan.blocks if b.kind == "image" and b.image_path == "spon.jpg")
            assert spon.image_size == "small", (marker_pos, inplace)


def test_rep_photo_pulled_under_drip_line():
    # 대표사진(★ 지정, 없으면 첫 비협찬 이미지)은 드립 한 줄 바로 아래로 올라온다
    text = (
        "제목 한 줄\n"
        "요즘 스킨 쓸 맛 나는 이유\n\n"
        "통만 바뀌면 완벽한데 말이야\n\n"
        "인트로 문단이에요\n\n[사진:음식]\n\n음식 설명 문단\n\n[사진:외관]"
    )
    photos = [PhotoItem(path="a.jpg", label="음식"), PhotoItem(path="b.jpg", label="외관", thumbnail=True)]
    plan = build_publish_plan(DraftResult(text=text), photos, structure_styles=_structure_styles())
    drip_i = next(i for i, b in enumerate(plan.blocks) if b.text == "통만 바뀌면 완벽한데 말이야")
    assert plan.blocks[drip_i + 1].kind == "image" and plan.blocks[drip_i + 1].image_path == "b.jpg"
    assert plan.rep_image_path == "b.jpg"

    # ★ 없으면 첫 비협찬 이미지가 히어로로 올라온다 (태그줄 있는 기존 헤더에서도 동일)
    text2 = (
        "제목 한 줄\n"
        "요즘 스킨 쓸 맛 나는 이유\n"
        "통만 바뀌면 완벽한데 말이야\n"
        "#태그하나 #태그둘\n\n"
        "인트로 문단이에요\n\n[사진:음식]\n\n음식 설명 문단\n\n[사진:외관]"
    )
    photos2 = [PhotoItem(path="a.jpg", label="음식"), PhotoItem(path="b.jpg", label="외관")]
    plan2 = build_publish_plan(DraftResult(text=text2), photos2, structure_styles=_structure_styles())
    drip_i2 = next(i for i, b in enumerate(plan2.blocks) if b.text == "통만 바뀌면 완벽한데 말이야")
    assert plan2.blocks[drip_i2 + 1].kind == "image" and plan2.blocks[drip_i2 + 1].image_path == "a.jpg"


def test_subheading_variants_and_year_line():
    # 모델이 "1)"로 쓰거나 마크다운 볼드로 감싸도 소제목으로 잡히고("**"는 후처리가 제거),
    # "2026. 7월에" 같은 연도 줄은 본문으로 남는다
    from autoblog.draft.postprocess import enforce_format

    text = enforce_format(
        "제목 한 줄\n\n1. 첫 섹션 제목\n본문.\n\n**2. 둘째 섹션**\n본문.\n\n"
        "3) 셋째 섹션\n본문.\n\n2026. 7월에 다녀왔어요\n"
    )
    assert "**" not in text
    plan = build_publish_plan(DraftResult(text=text), structure_styles=_structure_styles())
    subs = [b.text for b in plan.blocks if b.kind == "quote"]
    assert subs == ["1. 첫 섹션 제목", "2. 둘째 섹션", "3) 셋째 섹션"]
    assert any("2026. 7월에 다녀왔어요" in b.text for b in plan.blocks if b.kind == "text")


def test_structure_styles_off_by_default():
    # structure_styles 미지정이면 기존 동작 그대로(대제목 서식 부여 안 함)
    draft = DraftResult(text="제목\n\n짧은 첫 줄\n다음 줄")
    plan = build_publish_plan(draft)
    assert all(not b.emphases for b in plan.blocks if b.kind == "text")


def test_balance_wrap_splits_long_big_title_evenly():
    from autoblog.publish.plan import balance_wrap

    assert balance_wrap("달콤함은 그대로 칼로리는 가볍게") == "달콤함은 그대로\n칼로리는 가볍게"
    # 위/아래 글자 수(공백 제외) 차이가 최소가 되는 어절 경계에서 나뉜다
    top, bot = balance_wrap("바삭바삭 멈출 수 없는 인생 간식").split("\n")
    assert abs(len(top.replace(" ", "")) - len(bot.replace(" ", ""))) <= 1


def test_balance_wrap_leaves_short_prewrapped_or_spaceless():
    from autoblog.publish.plan import balance_wrap

    assert balance_wrap("짧은 대제목") == "짧은 대제목"  # 공백 제외 10자 이하
    assert balance_wrap("이미\n나눈 대제목 길어도") == "이미\n나눈 대제목 길어도"  # 이미 줄바꿈됨
    assert balance_wrap("띄어쓰기없는아주긴한줄짜리대제목") == "띄어쓰기없는아주긴한줄짜리대제목"  # 나눌 공백 없음


def test_big_title_wrapped_with_per_line_spans():
    # 대제목이 길면 두 줄로 접히고, 줄마다 대제목 서식 span이 하나씩(두 줄 다 큰 글씨).
    draft = DraftResult(text="제목칸\n바삭바삭 멈출 수 없는 인생 간식\n본문 첫 문단.")
    plan = build_publish_plan(draft, structure_styles=_structure_styles())
    big = next(b for b in plan.blocks if "바삭바삭" in b.text)
    assert "\n" in big.text
    assert len(big.emphases) == big.text.count("\n") + 1
    assert all(sp.style.font_size == "30" for sp in big.emphases)


def test_sponsor_sticker_prepended_at_top():
    draft = DraftResult(text="제목\n\n본문 첫 줄.\n본문 둘째 줄.")
    ss = StructureStyles(sponsor_sticker="ogq_cp:7")

    # 토글 OFF면 안 들어감
    off = build_publish_plan(draft, structure_styles=ss, sponsor=False)
    assert all(b.kind != "sticker" for b in off.blocks)

    # 토글 ON이면 본문 맨 위 블록이 그 스티커
    on = build_publish_plan(draft, structure_styles=ss, sponsor=True)
    assert on.blocks[0].kind == "sticker"
    assert on.blocks[0].sticker_pack == "ogq_cp"
    assert on.blocks[0].sticker_index == 7

    # ref 형식이 어긋나거나 비면(카탈로그 없음) 토글 ON이어도 안 들어감
    bad = build_publish_plan(draft, structure_styles=StructureStyles(sponsor_sticker="없음"), sponsor=True)
    assert all(b.kind != "sticker" for b in bad.blocks)


def test_sponsor_sticker_resolved_by_tag():
    from autoblog.publish.stickers import Sticker, StickerCatalog

    draft = DraftResult(text="제목\n\n본문.")
    cat = StickerCatalog(stickers=[
        Sticker(pack="ogq_z", index=2, tags=["기쁨"]),
        Sticker(pack="ogq_p", index=5, tags=["파트너스"]),
    ])
    ss = StructureStyles(sponsor_sticker="파트너스")  # ref이 아니라 태그 이름

    on = build_publish_plan(draft, structure_styles=ss, sponsor=True, sticker_catalog=cat)
    assert on.blocks[0].kind == "sticker"
    assert (on.blocks[0].sticker_pack, on.blocks[0].sticker_index) == ("ogq_p", 5)

    # 없는 태그면 안 들어감
    miss = build_publish_plan(
        draft, structure_styles=StructureStyles(sponsor_sticker="없는태그"), sponsor=True, sticker_catalog=cat
    )
    assert all(b.kind != "sticker" for b in miss.blocks)


def test_sponsor_sticker_from_catalog_pick():
    # structure_styles에 수동 지정이 없으면 UI에서 고른 catalog.sponsor(ref)를 쓴다
    from autoblog.publish.stickers import Sticker, StickerCatalog

    draft = DraftResult(text="제목\n\n본문.")
    cat = StickerCatalog(
        stickers=[Sticker(pack="ogq_p", index=5, tags=["협찬"])], sponsor="ogq_p:5"
    )
    plan = build_publish_plan(
        draft, structure_styles=StructureStyles(), sponsor=True, sticker_catalog=cat
    )
    assert plan.blocks[0].kind == "sticker"
    assert (plan.blocks[0].sticker_pack, plan.blocks[0].sticker_index) == ("ogq_p", 5)


def test_sponsor_links_spread_in_middle():
    # 문단 사이 구분선이 있어야 텍스트 블록이 여러 개로 나뉜다(실제 글 구조)
    draft = DraftResult(text="제목\n\n첫째.\n[구분선]\n둘째.\n[구분선]\n셋째.\n[구분선]\n넷째.\n[구분선]\n다섯째.")
    links = ["https://coupa.ng/a", "https://coupa.ng/b", "https://coupa.ng/c"]
    plan = build_publish_plan(draft, sponsor_links=links)

    link_blocks = [b for b in plan.blocks if b.kind == "link"]
    assert [b.link_url for b in link_blocks] == links  # 순서·개수 보존

    # 중간중간: 첫 블록·마지막 블록은 본문(링크가 맨 위/맨 끝에 몰리지 않음)
    kinds = [b.kind for b in plan.blocks]
    assert kinds[0] == "text" and kinds[-1] == "text"

    # 공백/빈 줄은 무시
    p2 = build_publish_plan(draft, sponsor_links=["  ", "https://coupa.ng/x", ""])
    assert [b.link_url for b in p2.blocks if b.kind == "link"] == ["https://coupa.ng/x"]


def test_coupang_partners_link_no_raw_url_text():
    # 쿠팡파트너스 링크는 협찬 칸에 넣어도 생 URL 텍스트를 남기지 않는다(카드만).
    # 체험단 캠페인 URL은 크롤러 인식용으로 텍스트 줄을 남긴다.
    draft = DraftResult(text="제목\n\n첫째.\n[구분선]\n둘째.\n[구분선]\n셋째.")
    links = [
        "https://link.coupang.com/a/xyz",
        "https://coupa.ng/abc",
        "https://www.coupang.com/vp/products/123",
        "https://campaign.revu.net/cp/999",
    ]
    plan = build_publish_plan(draft, sponsor_links=links)
    keep = {b.link_url: b.keep_url_text for b in plan.blocks if b.kind == "link"}
    assert keep["https://link.coupang.com/a/xyz"] is False
    assert keep["https://coupa.ng/abc"] is False
    assert keep["https://www.coupang.com/vp/products/123"] is False
    assert keep["https://campaign.revu.net/cp/999"] is True

    # 비협찬 상품 링크는 기존대로 텍스트 줄 제거
    p3 = build_publish_plan(draft, product_links=["https://smartstore.naver.com/x/1"])
    assert all(b.keep_url_text is False for b in p3.blocks if b.kind == "link")


def _divider_sticker_picker():
    from autoblog.publish.stickers import Sticker, StickerCatalog, StickerPicker

    cat = StickerCatalog(
        stickers=[
            Sticker(pack="ogq_d", index=7, tags=["구분선", "꽃"]),
            Sticker(pack="ogq_m", index=1, tags=["기쁨"]),
        ],
        favorites=["ogq_d:7", "ogq_m:1"],
    )
    return StickerPicker(cat)


def test_divider_sticker_not_stacked_with_native_divider():
    # LLM이 [구분선]과 구분선 스티커를 같은 전환점에 겹쳐 emit하면 스티커만 남는다
    draft = DraftResult(text="제목\n\n첫 문단.\n[구분선]\n[스티커:구분선]\n둘째 문단.")
    plan = build_publish_plan(draft, picker=_divider_sticker_picker())
    assert [b.kind for b in plan.blocks] == ["text", "sticker", "text"]
    assert plan.blocks[1].sticker_kind == "구분선"
    # 반대 순서(스티커 다음 [구분선])도 하나만
    draft2 = DraftResult(text="제목\n\n첫 문단.\n[스티커:구분선]\n[구분선]\n둘째 문단.")
    plan2 = build_publish_plan(draft2, picker=_divider_sticker_picker())
    assert [b.kind for b in plan2.blocks] == ["text", "sticker", "text"]


def test_emotion_sticker_next_to_divider_kept():
    # 감정 스티커는 구분선과 붙어 있어도 합치지 않는다(문단 끝 반응 + 화제 전환은 공존 가능)
    draft = DraftResult(text="제목\n\n정말 좋았어요.\n[스티커:기쁨]\n[구분선]\n다음 이야기.")
    plan = build_publish_plan(draft, picker=_divider_sticker_picker())
    assert [b.kind for b in plan.blocks] == ["text", "sticker", "divider", "text"]
    assert plan.blocks[1].sticker_kind == "감정"


def test_selectors_ready():
    # 라이브 분석으로 핵심 셀렉터(제목/본문/저장/발행) 확정됨
    assert selectors_ready() is True


def test_place_marker_fallback_chain():
    # [지도] 마커: place_query 없음 → 세션 마지막 수집 카드 폴백 → 그것도 없으면
    # 마커를 본문 텍스트로 남긴다(조용한 소실 방지). 이름 인자가 있으면 자립 동작.
    from autoblog.collect.fact_card import CardType, FactCard, PlaceFacts
    from autoblog.pipeline import _SCRAPE_CACHE

    draft = DraftResult(text="제목\n\n주차장이 가까워요.\n[지도]\n예약도 돼요.")

    _SCRAPE_CACHE.clear()
    plan = build_publish_plan(draft)  # 폴백 소스 전무 → 텍스트로 잔존
    assert not [b for b in plan.blocks if b.kind == "place"]
    assert any(b.kind == "text" and "[지도]" in b.text for b in plan.blocks)

    _SCRAPE_CACHE["place:https://naver.me/x"] = FactCard(
        type=CardType.place,
        place=PlaceFacts(name="바오서울 충무로", road_address="서울 중구 퇴계로27길 31"),
    )
    try:
        plan2 = build_publish_plan(draft)  # 캐시 폴백
        pb = next(b for b in plan2.blocks if b.kind == "place")
        assert pb.text == "바오서울 충무로"
        assert pb.place_address == "서울 중구 퇴계로27길 31"
    finally:
        _SCRAPE_CACHE.clear()

    draft_named = DraftResult(text="제목\n\n주차장이 가까워요.\n[지도:바오서울 충무로]\n예약도 돼요.")
    plan3 = build_publish_plan(draft_named)  # 자립 마커 — 캐시·쿼리 불필요
    assert next(b for b in plan3.blocks if b.kind == "place").text == "바오서울 충무로"


def test_rep_image_path_thumbnail_wins():
    # ★ 지정 사진이 대표 — 위치 재배치와 별개로 실행기가 저장 직전 '대표' 배지를 클릭한다
    draft = DraftResult(text="제목\n\n본문.\n[사진]\n다음.\n[사진]")
    photos = [PhotoItem(path="a.jpg", label="음식"), PhotoItem(path="b.jpg", label="외관", thumbnail=True)]
    plan = build_publish_plan(draft, photos)
    assert plan.rep_image_path == "b.jpg"


def test_rep_image_path_inplace_also_set():
    # inplace는 썸네일 '끌어올림'은 건너뛰지만 대표 지정 경로는 그대로 전달돼야 한다
    draft = DraftResult(text="제목\n\n본문.\n[사진]\n다음.\n[사진]")
    photos = [PhotoItem(path="a.jpg", label="음식"), PhotoItem(path="b.jpg", label="외관", thumbnail=True)]
    plan = build_publish_plan(draft, photos, inplace=True)
    assert plan.rep_image_path == "b.jpg"
    # 끌어올림은 없음 — 마커 순서 유지
    imgs = [b.image_path for b in plan.blocks if b.kind == "image"]
    assert imgs == ["a.jpg", "b.jpg"]


def test_rep_image_path_inplace_unmarked_thumb_inserted():
    # 초안 작성 뒤 'AI 사진 대체'로 추가된 ★ 썸네일은 마커가 없다 — inplace에서도
    # 사라지지 않고 첫 이미지 자리에 들어가 대표로 지정돼야 한다(무음 소실 회귀 방지).
    draft = DraftResult(text="제목\n\n본문.\n[사진:음식]\n다음.\n[사진:외관]")
    photos = [
        PhotoItem(path="a.jpg", label="음식"),
        PhotoItem(path="b.jpg", label="외관"),
        PhotoItem(path="ai.png", label="음식", thumbnail=True, ai_generated=True),
    ]
    plan = build_publish_plan(draft, photos, inplace=True)
    imgs = [b.image_path for b in plan.blocks if b.kind == "image"]
    assert imgs == ["ai.png", "a.jpg", "b.jpg"]
    assert plan.rep_image_path == "ai.png"
    ai_block = next(b for b in plan.blocks if b.image_path == "ai.png")
    assert ai_block.ai_generated  # 'AI 활용' 표시 대상 유지


def test_rep_image_path_excludes_sponsor_fallback_first():
    # ★ 없음 → 협찬 고지 사진은 건너뛰고 첫 일반 사진이 대표
    draft = DraftResult(text="제목\n\n본문.\n[사진:협찬]\n다음.\n[사진]")
    photos = [PhotoItem(path="banner.jpg", label="협찬"), PhotoItem(path="a.jpg", label="음식")]
    plan = build_publish_plan(draft, photos)
    assert plan.rep_image_path == "a.jpg"


def test_rep_image_path_none_without_photos():
    plan = build_publish_plan(DraftResult(text="제목\n\n본문뿐."), [])
    assert plan.rep_image_path is None


def test_structure_instruction_pins_recipe_to_postit():
    from autoblog.publish.plan import build_structure_instruction

    # 포스트잇을 안 골랐어도 레시피 안내는 포스트잇 번호(5)로 고정
    instr = build_structure_instruction(quote_keys=["default"])
    assert "레시피" in instr and "[인용구:5]" in instr
    # 포스트잇만 고른 경우엔 번호 없는 마커가 곧 포스트잇
    only = build_structure_instruction(quote_keys=["quotation_postit"])
    assert "레시피" in only and "[인용구:5]" not in only


def test_apply_photo_meta_overrides_late_thumb_swap():
    # 플랜 생성 '뒤' AI 썸네일 적용·사진 대체 — 새 이미지 삽입 + 대표 교체 + AI 표시
    from autoblog.publish.plan import apply_photo_meta_overrides

    draft = DraftResult(text="제목\n\n인트로.\n[사진]\n본문.")
    plan = build_publish_plan(draft, [PhotoItem(path="old.jpg", label="음식")])
    assert plan.rep_image_path == "old.jpg"

    apply_photo_meta_overrides(plan, {"ai.png": {"thumbnail": True, "ai_generated": True}})
    imgs = [b for b in plan.blocks if b.kind == "image"]
    assert imgs[0].image_path == "ai.png" and imgs[0].ai_generated
    assert plan.rep_image_path == "ai.png"

    # 같은 메타로 재발행(재시도) — 중복 삽입 없음
    apply_photo_meta_overrides(plan, {"ai.png": {"thumbnail": True, "ai_generated": True}})
    assert sum(1 for b in plan.blocks if b.image_path == "ai.png") == 1

    # 이미 플랜에 있는 사진에 ★만 옮긴 경우 — 삽입 없이 대표만 교체
    apply_photo_meta_overrides(plan, {"old.jpg": {"thumbnail": True}})
    assert plan.rep_image_path == "old.jpg"
    assert sum(1 for b in plan.blocks if b.image_path == "old.jpg") == 1
