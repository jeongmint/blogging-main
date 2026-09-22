from autoblog.collect.fact_card import CardType, FactCard, PlaceFacts
from autoblog.publish.stickers import Sticker, StickerCatalog


def _card():
    return FactCard(type=CardType.place, place=PlaceFacts(name="언제나 초밥"))


def test_run_pipeline_wires_stickers(monkeypatch):
    # 초안 LLM은 모킹: 시스템 프롬프트에 스티커 라벨이 주입됐는지 + [스티커] 마커 emit
    from autoblog.draft import generate as gen
    from autoblog.pipeline import run_pipeline

    captured = {}

    def fake_chat(messages, model=None):
        captured.setdefault("system", messages[0]["content"])  # 첫(생성) 호출만
        return "초밥 후기\n\n정말 맛있었어요.\n[스티커:맛있음]\n또 갈래요."

    monkeypatch.setattr(gen, "chat", fake_chat)
    cat = StickerCatalog(
        stickers=[Sticker(pack="ogq_a", index=3, tags=["맛있음"])], favorites=["ogq_a:3"]
    )

    result = run_pipeline(
        "비 오는 날 들렀어요", card=_card(), stickers=True, sticker_catalog=cat, structure=True
    )
    # 초안에 스티커 상황 어휘 주입됨
    assert "맛있음" in captured["system"] and "[스티커:상황]" in captured["system"]
    # 구조 지시문도 주입
    assert "구조 마커" in captured["system"]
    # 플랜이 마커를 (팩,인덱스)로 해석
    st = next(b for b in result.plan.blocks if b.kind == "sticker")
    assert st.sticker_pack == "ogq_a" and st.sticker_index == 3
    assert result.plan.title == "초밥 후기"


def test_run_pipeline_no_stickers_no_marker(monkeypatch):
    # stickers=False면 라벨 주입 없고, 스티커 마커가 있어도 picker 없어 폐기
    from autoblog.draft import generate as gen
    from autoblog.pipeline import run_pipeline

    captured = {}

    def fake_chat(messages, model=None):
        captured.setdefault("system", messages[0]["content"])  # 첫(생성) 호출만
        return "제목\n\n본문\n[스티커:맛있음]\n끝"

    monkeypatch.setattr(gen, "chat", fake_chat)
    result = run_pipeline("메모", card=_card(), stickers=False)
    assert "[스티커:상황]" not in captured["system"]
    assert all(b.kind != "sticker" for b in result.plan.blocks)
    assert all("[스티커" not in b.text for b in result.plan.blocks)
