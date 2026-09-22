from autoblog.collect.fact_card import CardType, FactCard, PhotoItem
from autoblog.collect.photos import classify_photos_into, photo_summary
from autoblog.draft.prompt import build_user_prompt


def test_classify_photos_into(monkeypatch):
    monkeypatch.setattr(
        "autoblog.vision.classify_photos",
        lambda paths, model=None: {"a.jpg": "음식", "b.jpg": "외관", "c.jpg": "음식"},
    )
    card = classify_photos_into(FactCard(type=CardType.place), ["a.jpg", "b.jpg", "c.jpg"])
    assert len(card.photos) == 3
    assert card.photos[0] == PhotoItem(path="a.jpg", label="음식")
    assert photo_summary(card.photos) == "음식 2, 외관 1"


def test_classify_vision_unavailable(monkeypatch):
    from autoblog.vision import VisionUnavailable

    def _fail(paths, model=None):
        raise VisionUnavailable("ollama down")

    monkeypatch.setattr("autoblog.vision.classify_photos", _fail)
    card = classify_photos_into(FactCard(type=CardType.place), ["x.jpg"])
    assert card.photos[0].label == "기타"  # 미연동 시 기타로 채움
    assert any("사진 분류" in w for w in card.warnings)


def test_user_prompt_includes_photo_summary():
    card = FactCard(
        type=CardType.place,
        photos=[PhotoItem(path="a.jpg", label="음식"), PhotoItem(path="b.jpg", label="외관")],
    )
    user = build_user_prompt(card, "맛있었다")
    assert "사진 구성" in user
    assert "음식 1, 외관 1" in user
    assert "[사진]" in user  # 사진 자리 표시 안내
