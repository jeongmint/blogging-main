"""사진 맥락 캡션(온디맨드 AI 자동 추천) 관련 순수함수 테스트."""

from autoblog.collect.fact_card import (
    CardType,
    FactCard,
    MenuItem,
    PhotoItem,
    PlaceFacts,
    ProductFacts,
)
from autoblog.collect.photos import attach_photos
from autoblog.config import load_photo_categories
from autoblog.draft.prompt import build_user_prompt
from autoblog.pipeline import build_photo_context, caption_photos
from autoblog.vision import _parse_captions, smart_caption_photos


def test_attach_photos_uses_meta_and_skips_vision():
    card = FactCard(type=CardType.place)
    attach_photos(
        card,
        ["a.jpg", "b.jpg", "c.jpg"],
        {"a.jpg": {"label": "음식", "caption": "데미소스 돈까스"}, "b.jpg": {"caption": "간판"}},
    )
    assert card.photos[0] == PhotoItem(path="a.jpg", label="음식", caption="데미소스 돈까스")
    assert card.photos[1].label == "기타" and card.photos[1].caption == "간판"  # 라벨 없으면 기타
    assert card.photos[2] == PhotoItem(path="c.jpg", label="기타", caption="")  # 메타 없으면 기본


def test_build_photo_context_place_menu():
    card = FactCard(
        type=CardType.place,
        place=PlaceFacts(
            name="돈까스집",
            category="일식",
            description="수제 소스가 자랑",
            menus=[MenuItem(name="등심돈까스", price="9000", description="데미글라스 소스")],
        ),
    )
    ctx = build_photo_context(card, "점심에 다녀옴")
    assert "메모: 점심에 다녀옴" in ctx
    assert "돈까스집 (일식)" in ctx
    assert "등심돈까스 9000 — 데미글라스 소스" in ctx


def test_build_photo_context_product():
    card = FactCard(
        type=CardType.product,
        product=ProductFacts(name="무선 청소기", category="가전", selling_points=["가벼움", "강력 흡입"]),
    )
    ctx = build_photo_context(card, "")
    assert "무선 청소기 (가전)" in ctx
    assert "셀링포인트: 가벼움, 강력 흡입" in ctx


def test_parse_captions_validates_range_and_label():
    cats = ["음식", "외관", "기타"]
    paths = ["/a.jpg", "/b.jpg"]
    # index 범위 밖(3)·허용 외 라벨(상품)은 무시/기타 처리, 누락 사진은 기본값으로 채움
    content = (
        '{"items":[{"index":1,"label":"음식","caption":"데미소스 돈까스"},'
        '{"index":3,"label":"외관","caption":"무시"},'
        '{"index":2,"label":"상품","caption":"포장지"}]}'
    )
    out = _parse_captions(content, paths, cats)
    assert out["/a.jpg"] == {"label": "음식", "caption": "데미소스 돈까스"}
    assert out["/b.jpg"] == {"label": "기타", "caption": "포장지"}  # 허용 외 라벨→기타, 캡션 유지


def test_parse_captions_bad_json_fills_defaults():
    out = _parse_captions("이건 JSON이 아님", ["/x.jpg"], ["음식", "기타"])
    assert out["/x.jpg"] == {"label": "기타", "caption": ""}


def test_smart_caption_photos_builds_prompt_with_context(monkeypatch):
    captured = {}

    def fake_vision_chat(prompt, images, model, fmt=None):
        captured["prompt"] = prompt
        captured["n_images"] = len(images)
        captured["model"] = model
        return '{"items":[{"index":1,"label":"음식","caption":"데미소스 돈까스"}]}'

    monkeypatch.setattr("autoblog.llm.vision_chat", fake_vision_chat)
    # 다운스케일은 실제 파일을 열지 않게 대체
    monkeypatch.setattr("autoblog.vision._downscale_image", lambda p, max_dim=1024: b"img")
    out = smart_caption_photos(
        ["/a.jpg"], context="메뉴: 등심돈까스 — 데미글라스 소스", categories=["음식", "외관"], model="gemini-2.5-flash"
    )
    assert out["/a.jpg"]["caption"] == "데미소스 돈까스"
    assert captured["n_images"] == 1 and captured["model"] == "gemini-2.5-flash"
    assert "데미글라스 소스" in captured["prompt"]  # 맥락이 프롬프트에 포함
    assert "음식, 외관, 기타" in captured["prompt"]  # 기타 자동 보강


def test_caption_photos_orchestrator_no_collection(monkeypatch):
    # srcval 없으면 수집 생략, 메모 맥락만으로 진행
    monkeypatch.setattr(
        "autoblog.vision.smart_caption_photos",
        lambda paths, context, categories=None, model=None, hint=None: {
            p: {"label": "음식", "caption": f"cap-{i}"} for i, p in enumerate(paths)
        },
    )
    items = caption_photos("메모", photos=["/a.jpg", "/b.jpg"], review_type="place")
    assert items == [
        {"path": "/a.jpg", "label": "음식", "caption": "cap-0"},
        {"path": "/b.jpg", "label": "음식", "caption": "cap-1"},
    ]


def test_caption_photos_empty():
    assert caption_photos("메모", photos=[]) == []


def test_user_prompt_includes_captions():
    card = FactCard(
        type=CardType.place,
        photos=[
            PhotoItem(path="a.jpg", label="음식", caption="데미소스 돈까스"),
            PhotoItem(path="b.jpg", label="외관"),
        ],
    )
    user = build_user_prompt(card, "맛있었다")
    assert "사진 내용" in user
    assert "데미소스 돈까스 (라벨: 음식)" in user


def test_photo_categories_loaded():
    cats = load_photo_categories()
    assert "기타" in cats["place"]
    assert "언박싱" in cats["product"]
