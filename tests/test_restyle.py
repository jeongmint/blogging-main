"""리스타일 베이스 프롬프트 로딩 — 원문 보존 지침 + 공통 문체 규칙이 합쳐지는지."""

from autoblog.collect.fact_card import CardType, FactCard
from autoblog.draft.generate import DraftRequest, build_prompt
from autoblog.draft.prompts import load_base_prompt, load_restyle_prompt


def test_restyle_prompt_merges_style_and_preservation():
    text = load_restyle_prompt()
    # 리스타일 고유 지침(정보 보존)과 공통 문체 규칙(줄바꿈 포맷)이 둘 다 들어와야 한다.
    assert "정보 보존" in text
    assert "지어내지 마" in text
    assert "한 줄에 하나의 짧은 절" in text  # common_style.md 에서 이어 붙은 부분
    # 맛집 전용 구조(웨이팅 등)를 강제하지 않는 별개의 베이스여야 한다.
    assert text != load_base_prompt()


def test_build_prompt_uses_restyle_base():
    req = DraftRequest(
        fact_card=FactCard(type=CardType.place),
        experience_memo="빽다방 아메리카노는 5kcal, 바닐라라떼는 433kcal 입니다.",
        base_prompt=load_restyle_prompt(),  # webui 리스타일 모드가 넘기는 것과 동일
    )
    system, user = build_prompt(req)
    assert "정보 보존" in system  # restyle 베이스가 시스템 프롬프트에 실렸다
    assert "433kcal" in user  # 원문(=경험 메모)이 사용자 프롬프트로 전달된다
