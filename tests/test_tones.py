"""어투 프리셋 분리 — 기본어투가 유저 문체를 덮어쓰지 않는지 검증."""

from autoblog.collect.fact_card import CardType, FactCard, PlaceFacts
from autoblog.draft import generate as gen
from autoblog.draft.style import StyleProfile
from autoblog.draft.tones import default_tone, get_tone, load_tones


def _card():
    return FactCard(type=CardType.place, place=PlaceFacts(name="언제나 초밥"))


def test_bundled_tones_load():
    tones = load_tones()
    ids = [t.id for t in tones]
    assert "playful" in ids and len(tones) >= 4
    dt = default_tone()
    assert dt is not None and dt.id == "playful" and dt.ornaments is True
    # 꾸밈 레이어(변주·.ᐟ 치환)는 발랄체만 사용
    assert all(not t.ornaments for t in tones if t.id != "playful")
    assert get_tone("calm") is not None and get_tone("없는어투") is None


def test_effective_style_defaults_to_playful_preset():
    style = gen.effective_style(gen.DraftRequest(fact_card=_card(), experience_memo="메모"))
    assert style.ornaments is True
    assert "카오모지" in (style.profile or "")  # 기본 어투(발랄체) 지시문이 채워짐


def test_effective_style_keeps_user_persona():
    req = gen.DraftRequest(
        fact_card=_card(), experience_memo="메모",
        style=StyleProfile(profile="차분한 존댓말로 쓴다"),
    )
    style = gen.effective_style(req)
    # 유저 문체가 있으면 기본 프리셋을 덧씌우지 않고, 꾸밈 레이어도 꺼진다
    assert style.profile == "차분한 존댓말로 쓴다" and style.ornaments is False


def test_tone_only_input_still_gets_default_preset():
    req = gen.DraftRequest(
        fact_card=_card(), experience_memo="메모", style=StyleProfile(tone="더 발랄하게")
    )
    style = gen.effective_style(req)
    # 톤 지시만 쓴 경우 = 문체 미선택 → 기본 어투 위에 톤이 얹힌다
    assert style.tone == "더 발랄하게" and style.profile and style.ornaments is True


def test_prompt_layers_follow_ornaments():
    # 기본(발랄체): 어투 지시 + 어투 변주(카오모지·유행어) + 느낌표 자가 점검이 모두 포함
    sys_default, _ = gen.build_prompt(gen.DraftRequest(fact_card=_card(), experience_memo="메모"))
    assert "말끝 흐림" in sys_default  # 발랄체 어투 지시(프리셋에서 온다)
    assert "- 표정 이모티콘" in sys_default  # 변주 블록의 어투 변주 항목
    assert ".ᐟ 로 바꿔" in sys_default  # 자가 점검 느낌표 항목

    # 유저 문체: 어투 변주·느낌표 점검·발랄체 어투 지시가 빠지고,
    # 구조 변주(섹션 흐름 — 유사문서 방지)는 어투와 무관하게 유지된다
    req = gen.DraftRequest(
        fact_card=_card(), experience_memo="메모",
        style=StyleProfile(profile="차분한 존댓말로 쓴다"),
    )
    sys_persona, _ = gen.build_prompt(req)
    assert "차분한 존댓말로 쓴다" in sys_persona
    assert "- 표정 이모티콘" not in sys_persona
    assert "- 유행어" not in sys_persona
    assert "- 〰️" not in sys_persona
    assert "- 섹션 흐름" in sys_persona  # 구조 변주는 유지
    assert ".ᐟ 로 바꿔" not in sys_persona
    assert "말끝 흐림" not in sys_persona  # 기본어투 미적용


def test_builtin_preset_selectable_as_style():
    calm = get_tone("calm")
    req = gen.DraftRequest(
        fact_card=_card(), experience_memo="메모",
        style=StyleProfile(profile=calm.prompt, ornaments=calm.ornaments),
    )
    sys_calm, _ = gen.build_prompt(req)
    assert "정중하고 차분한 존댓말" in sys_calm
    assert "- 표정 이모티콘" not in sys_calm  # 어투 변주 미주입


def test_enforce_format_ornaments_off_keeps_tone_chars():
    from autoblog.draft.postprocess import enforce_format

    src = "제목줄\n\n정말 맛있었다!\n좋았어요~ 😊"
    on = enforce_format(src)
    assert ".ᐟ" in on and "~" not in on and "😊" not in on
    off = enforce_format(src, ornaments=False)
    assert "맛있었다!" in off and "좋았어요~" in off and "😊" in off
    # 포맷 규칙(글머리 기호 제거·줄바꿈)은 어투와 무관하게 항상 적용
    assert "•" not in enforce_format("제목\n\n• 항목 하나", ornaments=False)


def test_selfcheck_ornaments_toggle():
    from autoblog.draft.prompts import build_selfcheck_instruction

    on = build_selfcheck_instruction()
    off = build_selfcheck_instruction(ornaments=False)
    assert "느낌표" in on and "이모지" in on
    assert "느낌표" not in off and "허용 목록 밖 이모지" not in off
    assert "줄 길이" in off and "자연스러움" in off  # 포맷·품질 항목은 유지
