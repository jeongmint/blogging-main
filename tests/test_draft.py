from autoblog.collect.fact_card import CardType, FactCard, MenuItem, PlaceFacts
from autoblog.draft.guideline import Guidelines, check_guidelines
from autoblog.draft.prompt import build_system_prompt, build_user_prompt, render_fact_card
from autoblog.draft.prompts import load_base_prompt
from autoblog.draft.rules import CommonRules


def _place_card():
    return FactCard(
        type=CardType.place,
        place=PlaceFacts(
            name="언제나 초밥",
            category="초밥,롤",
            road_address="경기 용인시 수지구 손곡로 89",
            business_hours="매일 11:00~21:00",
            menus=[MenuItem(name="모둠초밥", price="12,900원")],
        ),
    )


def test_rules_default_and_toggle():
    default = CommonRules()
    frags = default.active_fragments()
    assert len(frags) == 4  # mobile/authenticity/structure/seo 기본 켜짐(emoji만 꺼짐)
    assert any("검색 노출" in f for f in frags)
    # emoji까지 켜면 5개, seo 끄면 3개
    assert len(CommonRules(emoji=True).active_fragments()) == 5
    assert len(CommonRules(seo=False).active_fragments()) == 3


def test_render_fact_card_place():
    text = render_fact_card(_place_card())
    assert "언제나 초밥" in text
    assert "모둠초밥(12,900원)" in text
    assert "매일 11:00~21:00" in text


def test_system_prompt_hierarchy():
    # 가이드라인은 맨 위(최우선), 그 아래 베이스 프롬프트
    base = "베이스 프롬프트 본문"
    g = Guidelines(required_keywords=["수지맛집"], min_chars=500)
    sys = build_system_prompt(base, guidelines=g)
    assert sys.index("최우선 제약") < sys.index(base)
    # 추가 문체 지시는 베이스 뒤
    from autoblog.draft.style import StyleProfile

    sys2 = build_system_prompt(base, style=StyleProfile(tone="반말로"))
    assert sys2.index(base) < sys2.index("추가 문체 지시")


def test_load_base_prompt_strips_meta():
    # 상단 메타(제목+안내, 첫 '---' 이전)는 제거되고 역할 설정부터 시작
    base = load_base_prompt()
    assert "## 역할 설정" in base
    assert "이 파일은 초안 작성" not in base  # 메타 안내 제거됨


def test_prompt_examples_follow_own_rules():
    # 프롬프트 안의 예시가 자체 규칙을 어기면 모델이 그대로 모방한다 — 회귀 방지.
    # (금지 문자 ~!, 허용 목록 밖 이모지, 특정인 필명 하드코딩)
    from autoblog.draft.prompts import (
        COMMON_STYLE_PROMPT_PATH,
        DEFAULT_PROMPT_PATH,
        PRODUCT_PROMPT_PATH,
    )
    from autoblog.draft.tones import TONES_PATH

    for path in (DEFAULT_PROMPT_PATH, PRODUCT_PROMPT_PATH, COMMON_STYLE_PROMPT_PATH, TONES_PATH):
        text = path.read_text(encoding="utf-8")
        assert "~!" not in text, path.name
        assert "🐰" not in text, path.name
        assert "노이노" not in text, path.name  # 공유 베이스에 개인 필명 금지(persona.py 원칙)


def test_user_prompt_experience_is_lead():
    user = build_user_prompt(_place_card(), "비 오는 날 들렀는데 따뜻했다")
    assert user.index("나의 경험") < user.index("참고 정보")
    assert "비 오는 날" in user
    assert "언급하거나 인용하지 마세요" in user  # 라벨 누수 방지 지시


def test_photo_prompt_advises_spreading():
    # 사진 배치 안내에 '고루 분산 / 앞에 몰지 말라'가 들어간다(근본 처방)
    from autoblog.collect.fact_card import PhotoItem

    card = _place_card()
    card.photos = [PhotoItem(path=f"{i}.jpg", label="음식") for i in range(4)]
    user = build_user_prompt(card, "맛있게 먹었다")
    assert "고루" in user and "몰아" in user


def test_photo_labels_follow_board_order():
    # 라벨 나열 = 사진이 들어온 순서(=분류함 칸 순서). 알파벳/가나다 정렬로 뒤집히면 안 된다.
    from autoblog.collect.fact_card import PhotoItem

    card = _place_card()
    card.photos = [
        PhotoItem(path="1.jpg", label="음식"),
        PhotoItem(path="2.jpg", label="음식"),
        PhotoItem(path="3.jpg", label="외관"),
    ]
    user = build_user_prompt(card, "맛있게 먹었다")
    assert "분류명: 음식, 외관" in user
    assert "이 순서대로" in user


def test_variation_block_deterministic():
    from autoblog.draft.variation import build_variation_block

    a = build_variation_block("비 오는 날 들렀다|언제나 초밥")
    b = build_variation_block("비 오는 날 들렀다|언제나 초밥")
    assert a is not None and a == b  # 같은 재료 → 같은 변주(재생성 재현성)
    c = build_variation_block("주말에 다녀온 카페|스토리카페")
    assert c != a  # 다른 글 → 다른 조합(시드 분산)
    assert "[이번 글 스타일 변주]" in a


def test_variation_block_type_specific():
    from autoblog.draft.variation import build_variation_block

    prod = build_variation_block("메모|파우치", is_product=True)
    assert "추천 체크리스트 소제목" in prod and "🌟" in prod
    place = build_variation_block("메모|가게", is_product=False)
    assert "PICK 리스트 전환 멘트" in place
    assert "추천 체크리스트 소제목" not in place


def test_style_pool_user_override_and_sanitize(tmp_path, monkeypatch):
    # 유저 수정본이 있으면 번들 기본값 대신 그걸 쓴다(웹UI 저장 경로).
    from autoblog.draft import variation

    user = tmp_path / "style_pool.yaml"
    user.write_text("slang:\n  - {expr: 찐, meaning: 진짜, example: 찐 맛집}\n", encoding="utf-8")
    monkeypatch.setattr(variation, "STYLE_POOL_USER_PATH", user)
    assert variation.load_style_pool()["slang"][0]["expr"] == "찐"
    # 수정본이 없으면 번들 폴백
    monkeypatch.setattr(variation, "STYLE_POOL_USER_PATH", tmp_path / "없음.yaml")
    assert "kaomoji" in variation.load_style_pool()

    # sanitize: !/~ 든 카오모지 제거(보호 이모지는 유지), 깨진 유행어 제거, weight 클램프
    pool = variation.sanitize_style_pool(
        {
            "kaomoji": {"taste": ["(๑´~ˋ๑)", "(오예!)", "(물결~)", "정상"]},
            "slang": [
                {"expr": "찐", "meaning": "진짜", "example": "찐 맛집", "weight": 9},
                {"expr": "", "meaning": "빈 표현", "example": "x"},
                "평문",
            ],
            "모르는키": [1],
        }
    )
    assert pool["kaomoji"]["taste"] == ["(๑´~ˋ๑)", "정상"]
    assert pool["slang"] == [{"expr": "찐", "meaning": "진짜", "example": "찐 맛집", "weight": 3}]
    assert "모르는키" not in pool


def test_slang_weight_zero_excluded():
    # weight 0 유행어만 있으면 후보가 없어 '유행어 없이' 분기로 떨어진다.
    from autoblog.draft.variation import build_variation_block

    pool = {
        "slang": [{"expr": "찐", "meaning": "진짜", "example": "찐 맛집", "weight": 0}],
        "kaomoji": {"taste": ["(๑ᵔ⤙ᵔ๑)"]},
    }
    for seed in ("a|b", "c|d", "e|f", "g|h"):
        blk = build_variation_block(seed, pool=pool)
        assert "유행어·신조어를 쓰지 말고" in blk


def test_style_pool_broken_yaml_returns_empty(tmp_path):
    # 유저 편집 yaml의 문법 오류가 초안 생성을 죽이면 안 된다 — 빈 dict로 변주만 생략.
    from autoblog.draft.variation import build_variation_block, load_style_pool

    broken = tmp_path / "pool.yaml"
    broken.write_text("kaomoji: [unclosed", encoding="utf-8")
    assert load_style_pool(broken) == {}
    assert build_variation_block("메모|가게", pool={}) is None
    # 구조가 어긋난 풀(카테고리가 dict가 아님·slang이 평문)도 크래시 없이 동작
    weird = {"kaomoji": ["평문"], "slang": ["찐", "존맛"]}
    blk = build_variation_block("메모|가게", pool=weird)
    assert blk is not None and "카오모지를 쓰지 마" in blk


def test_variation_block_in_system_prompt(monkeypatch):
    # generate 경로에서 시드 변주 블록이 시스템 프롬프트에 항상 붙는다.
    from autoblog.draft import generate as gen

    captured: dict[str, str] = {}

    def fake_chat(messages, model=None):
        # 2차 자가검수 호출이 뒤따르므로 첫(생성) 호출의 시스템 프롬프트만 잡는다
        captured.setdefault("system", messages[0]["content"])
        return "제목\n\n본문"

    monkeypatch.setattr(gen, "chat", fake_chat)
    gen.generate_draft(gen.DraftRequest(fact_card=_place_card(), experience_memo="메모"))
    assert "[이번 글 스타일 변주]" in captured["system"]


def test_guideline_checklist():
    g = Guidelines(
        required_keywords=["수지맛집", "초밥"],
        required_hashtags=["#협찬"],
        forbidden_expressions=["강력추천"],
        min_chars=20,
    )
    draft = "수지맛집 초밥 다녀왔어요. 정말 좋았습니다. #협찬"
    checks = check_guidelines(draft, g)
    by_item = {c.item: c.ok for c in checks}
    assert by_item["키워드 '수지맛집'"] is True
    assert by_item["키워드 '초밥'"] is True
    assert by_item["해시태그 '#협찬'"] is True
    assert by_item["금지어 '강력추천' 미포함"] is True  # 없으므로 통과
    # 글자수 미달 케이스
    short = check_guidelines("짧음", Guidelines(min_chars=100))
    assert short[0].ok is False


def test_guidelines_empty_is_ignored():
    assert Guidelines().is_empty()
    assert Guidelines().as_prompt() is None


def test_check_exposure():
    from autoblog.draft.guideline import check_exposure

    good = (
        "[혜화맛집] 치즈철판카츠 메종아카이 내돈내산 후기\n"
        "요즘 푹 빠진 카츠 성지\n"
        "혜화맛집 #대학로맛집 #혜화내돈내산 #메종아카이 #치즈철판카츠\n\n본문"
    )
    by_item = {c.item: c for c in check_exposure(good)}
    assert by_item["제목 길이(검색 노출)"].ok is True
    assert by_item["해시태그 5~10개(발행 태그칸)"].ok is True  # 첫 태그 # 없는 헤더 관례 → 5개

    bad = "제목\n본문뿐 해시태그 없음"
    assert all(not c.ok for c in check_exposure(bad))

    # 본문 문장 속 해시태그 2개는 헤더 태그줄이 아님 — 그 줄 토큰 전체를 태그로 세지 않는다
    body_tags = "적당한 길이의 제목이라 통과하는 예시입니다\n오늘 #혜화 갔다가 #맛집 발견"
    assert {c.item: c for c in check_exposure(body_tags)}["해시태그 5~10개(발행 태그칸)"].ok is False


def test_enforce_format():
    from autoblog.draft.postprocess import enforce_format

    raw = "### 제목\n\n- 항목 하나\n맛있어요! 또 가야지~ 😊✨"
    out = enforce_format(raw)
    assert "###" not in out
    assert "\n- " not in out and not out.startswith("- ")
    assert "항목 하나" in out  # 글머리 기호만 제거, 텍스트 유지
    assert "!" not in out and ".ᐟ" in out
    assert "~" not in out
    assert "😊" not in out  # 금지 이모지 제거
    assert "✨" in out  # 허용 이모지는 유지
    # 물결표를 포함한 허용 이모지는 보호(치환되지 않음)
    assert enforce_format("맛 (๑´~ˋ๑) 좋아").count("(๑´~ˋ๑)") == 1


def test_multi_exclamation_scaled_and_capped():
    # 겹느낌표는 흥분 단계별 .ᐟ 연타로 — 최대 3개 상한(모델이 직접 쓴 .ᐟ 연타 포함)
    from autoblog.draft.postprocess import enforce_format

    out = enforce_format("제목\n\n맛있어요!! 진짜!!!!! 최고" + ".ᐟ" * 5)
    assert ".ᐟ.ᐟ 진짜" in out
    assert ".ᐟ.ᐟ.ᐟ.ᐟ" not in out
    assert ".ᐟ.ᐟ.ᐟ 최고.ᐟ.ᐟ.ᐟ" in out


def test_title_line_decor_stripped():
    # 제목(첫 줄)은 검색 결과에 노출되므로 장식 문자를 치환하지 않고 제거한다.
    from autoblog.draft.postprocess import enforce_format

    out = enforce_format("연남동 라멘 멘야하루 후기!\n\n본문이에요!")
    assert out.split("\n", 1)[0] == "연남동 라멘 멘야하루 후기"
    assert ".ᐟ" in out  # 본문 느낌표는 여전히 .ᐟ 치환
    # 모델이 제목에 넣은 .ᐟ·〰️도 걷어낸다
    out2 = enforce_format("성수 카페 후기 .ᐟ 〰️\n\n본문")
    assert out2.split("\n", 1)[0] == "성수 카페 후기"


def test_bracket_segments_protected_from_substitution():
    # 마커 라벨·대괄호 고유명사 속 !/~는 치환하지 않는다(매칭·표기 보호).
    from autoblog.draft.postprocess import enforce_format

    out = enforce_format("제목\n\n오늘은 [ 잇쇼우! ] 다녀왔어요\n[사진:간판!]")
    assert "[ 잇쇼우! ]" in out
    assert "[사진:간판!]" in out
    # 제목의 대괄호 구간도 본문과 같은 보호 — 표기가 본문과 어긋나지 않게
    out2 = enforce_format("[잇쇼우!] 라멘 후기\n\n본문이에요")
    assert out2.split("\n", 1)[0] == "[잇쇼우!] 라멘 후기"


def test_long_marker_line_not_wrapped():
    # 30자 넘는 마커 줄이 줄바꿈으로 쪼개지면 마커가 깨져 본문에 대괄호가 남고,
    # 그 사진이 소비되지 않아 '남은 사진 분산'으로 넘어가 배치가 통째로 틀어진다.
    from autoblog.draft.postprocess import enforce_format
    from autoblog.publish.plan import _PHOTO_RE

    marker = "[사진:겉은 아주 바삭하고 속은 정말 촉촉한 등심돈까스 클로즈업 사진]"
    out = enforce_format(f"제목\n\n{marker}\n[사진:매장 외관, 간판이 잘 보이는 사진과 주변 골목까지]\n본문")
    for line in out.split("\n"):
        if line.startswith("[사진"):
            assert _PHOTO_RE.match(line), line  # 한 줄 그대로 = plan이 마커로 인식
    assert marker in out


def test_title_detection_skips_blank_first_lines():
    # 첫 줄이 공백뿐이어도 실제 제목이 보호된다(wrap_long_lines 판정과 동일 기준).
    from autoblog.draft.postprocess import enforce_format

    out = enforce_format("   \n제목입니다!\n\n본문!")
    assert out.split("\n", 1)[0] == "제목입니다"
    assert ".ᐟ" in out  # 본문 느낌표는 치환


def test_sentinel_literals_do_not_corrupt_text():
    # 입력에 센티널 유사 리터럴이 있어도 오염되지 않는다(NUL 제거 + NUL 센티널).
    from autoblog.draft.postprocess import enforce_format

    out = enforce_format("제목\n\nTILDE_EMOJI 라는 단어와 [보호!] 구간")
    assert "TILDE_EMOJI" in out and "[보호!]" in out
    assert "(๑´~ˋ๑)" not in out


def test_forbidden_phrase_softened():
    from autoblog.draft.postprocess import enforce_format

    assert "강력 추천" not in enforce_format("여기 강력 추천 드려요")
    assert "추천" in enforce_format("여기 강력 추천 드려요")


def test_product_checklist_box_preserved():
    # 상품 리뷰(allow_checklist=True): 1️⃣~ 핵심요약·✅ 체크리스트·🌟·👉는 보존되고
    # 긴 박스 줄도 쪼개지지 않는다. 기본(맛집) 모드에서는 ✅/🌟이 제거된다.
    from autoblog.draft.postprocess import enforce_format

    raw = (
        "제목 한 줄\n인트로!\n\n"
        "1️⃣ 첫인상: 100% 재활용 가능한 폴리에틸렌이라 아주 착한 소재예요\n\n"
        "🌟 이런 분들께 추천해요\n✅ 깔끔하게 휴대하고 싶은 분\n👉 구매처: 공식 스토어"
    )
    prod = enforce_format(raw, allow_checklist=True)
    # 키캡 결합문자(⃣ U+20E3)·✅·🌟·👉가 살아 있어야 한다(변이 선택자 FE0F는 빠질 수 있음)
    assert "⃣" in prod and "✅" in prod and "🌟" in prod and "👉" in prod
    assert "!" not in prod and ".ᐟ" in prod  # 느낌표는 상품 모드에서도 치환
    # 키캡 요약 줄은 "소제목: 설명"의 콜론이 em-dash로 바뀌고 한 줄로 유지(쪼개지지 않음)
    assert "첫인상 — 100% 재활용 가능한 폴리에틸렌이라 아주 착한 소재예요" in prod
    assert "첫인상:" not in prod  # 키캡 줄 콜론 제거
    assert "👉 구매처: 공식 스토어" in prod  # 키캡 줄 아닌 곳의 콜론은 보존

    base = enforce_format(raw, allow_checklist=False)
    assert "✅" not in base and "🌟" not in base  # 맛집 모드는 기존대로 제거


def test_load_base_prompt_explicit_path_skips_common(tmp_path):
    # 명시 path(커스텀 프롬프트)는 그 파일 그대로 — 공통 문체를 덧붙이지 않는다.
    custom = tmp_path / "custom.md"
    custom.write_text("# 메타\n\n---\n나만의 프롬프트", encoding="utf-8")
    base = load_base_prompt(custom)
    assert base == "나만의 프롬프트"
    assert "문체 규칙" not in base


def test_load_base_prompt_product_card():
    # 상품 카드면 product.md(상품 리뷰 베이스)를 고른다.
    from autoblog.collect.fact_card import CardType, FactCard
    from autoblog.collect.fact_card import ProductFacts

    prod = FactCard(type=CardType.product, product=ProductFacts(name="테스트 파우치"))
    base = load_base_prompt(card=prod)
    assert "상품" in base and "역할 설정" in base
    # 카드 없음/맛집이면 기본(default.md)
    assert "맛집·카페·여행" in load_base_prompt()


def test_structure_markers_survive_postprocess():
    # [구분선]/[인용구] 마커는 postprocess(enforce_format)를 거쳐도 보존돼야
    # 게시 플랜이 블록으로 파싱할 수 있다([사진] 마커와 동일 형태).
    from autoblog.draft.postprocess import enforce_format

    raw = "첫 문단이에요\n[구분선]\n[인용구]\n인상 깊은 한마디\n[/인용구]\n마지막 문단"
    out = enforce_format(raw)
    assert "[구분선]" in out
    assert "[인용구]" in out and "[/인용구]" in out


def test_structure_flag_appends_instruction(monkeypatch):
    # generate_draft(structure=True)면 구조 마커 지시문이 시스템 프롬프트에 붙는다.
    from autoblog.draft import generate as gen
    from autoblog.publish.plan import STRUCTURE_INSTRUCTION

    captured: dict[str, str] = {}

    def fake_chat(messages, model=None):
        captured.setdefault("system", messages[0]["content"])  # 첫(생성) 호출만
        return "제목\n\n본문\n[구분선]\n끝"

    monkeypatch.setattr(gen, "chat", fake_chat)
    req = gen.DraftRequest(fact_card=_place_card(), experience_memo="메모", structure=True)
    gen.generate_draft(req)
    assert STRUCTURE_INSTRUCTION in captured["system"]

    captured.clear()
    req_off = gen.DraftRequest(fact_card=_place_card(), experience_memo="메모")
    gen.generate_draft(req_off)
    assert STRUCTURE_INSTRUCTION not in captured["system"]


def test_sticker_labels_append_instruction(monkeypatch):
    # sticker_labels를 주면 보유 상황 어휘가 시스템 프롬프트에 붙는다.
    from autoblog.draft import generate as gen

    captured: dict[str, str] = {}

    def fake_chat(messages, model=None):
        captured.setdefault("system", messages[0]["content"])  # 첫(생성) 호출만
        return "제목\n\n본문"

    monkeypatch.setattr(gen, "chat", fake_chat)
    req = gen.DraftRequest(
        fact_card=_place_card(), experience_memo="메모", sticker_labels=["맛있음", "기쁨"]
    )
    gen.generate_draft(req)
    assert "맛있음" in captured["system"] and "[스티커:상황]" in captured["system"]


def test_selfcheck_photo_and_sticker_items_conditional():
    # 사진/스티커가 있을 때만 분산·이모티콘 점검 항목이 붙는다
    from autoblog.draft.prompts import build_selfcheck_instruction

    plain = build_selfcheck_instruction()
    assert "사진 분산" not in plain and "[스티커:상황]" not in plain
    assert "해시태그 — " in plain  # 해시태그 점검은 사진 유무와 무관하게 항상
    both = build_selfcheck_instruction(has_photos=True, has_stickers=True)
    assert "사진 분산" in both and "[스티커:상황]" in both


def test_selfcheck_hashtag_item_off_for_restyle():
    # 리스타일(태그줄 없는 초안)은 해시태그 항목 제외 — 검수 패스가 태그줄을 지어내지 않게.
    # 드립 한 줄 항목은 리스타일에도 유지된다(restyle.md가 드립 한 줄을 지시).
    from autoblog.draft.generate import DraftRequest, _selfcheck_for
    from autoblog.draft.prompts import build_selfcheck_instruction

    off = build_selfcheck_instruction(hashtags=False)
    assert "해시태그 — " not in off and "드립 한 줄 — " in off

    req = DraftRequest(fact_card=_place_card(), experience_memo="메모", restyle=True)
    assert "해시태그 — " not in _selfcheck_for(req)


def test_selfreview_second_pass_applied(monkeypatch):
    # 생성 후 2차 자가검수 호출이 돌고, 검수 결과가 초안 텍스트로 쓰인다
    from autoblog.draft import generate as gen

    calls: list[str] = []

    def fake_chat(messages, model=None):
        calls.append(messages[0]["content"])
        if len(calls) == 1:
            return "제목 스무자 내외의 예시\n\n본문인데 느낌표가 있다!"
        return "제목 스무자 내외의 예시\n\n본문인데 느낌표가 있다.ᐟ"

    monkeypatch.setattr(gen, "chat", fake_chat)
    result = gen.generate_draft(
        gen.DraftRequest(fact_card=_place_card(), experience_memo="메모", postprocess=False)
    )
    assert len(calls) == 2
    assert "검수" in calls[1]  # 두 번째 호출은 검수 프롬프트
    assert ".ᐟ" in result.text
    assert result.debug["reviewed"]  # 고쳐진 사실이 디버그에 남는다


def test_selfreview_falls_back_on_marker_loss(monkeypatch):
    # 검수 응답이 마커를 훼손하면(개수 변화) 원본을 유지한다
    from autoblog.draft import generate as gen

    raw = "제목\n\n본문.\n[사진:음식]\n설명."

    def fake_chat(messages, model=None):
        return "제목\n\n본문.\n설명인데 사진 마커를 지워버림."

    monkeypatch.setattr(gen, "chat", fake_chat)
    req = gen.DraftRequest(fact_card=_place_card(), experience_memo="메모")
    assert gen.review_draft_text(raw, req) == raw


def test_selfreview_falls_back_on_shrunk_output(monkeypatch):
    # 검수 응답이 지나치게 짧으면(내용 소실 의심) 원본을 유지한다
    from autoblog.draft import generate as gen

    raw = "제목\n\n" + "본문 문단입니다.\n" * 20

    monkeypatch.setattr(gen, "chat", lambda messages, model=None: "짧은 응답")
    req = gen.DraftRequest(fact_card=_place_card(), experience_memo="메모")
    assert gen.review_draft_text(raw, req) == raw


def test_selfreview_skipped_for_raw_override(monkeypatch):
    # 외부 챗봇 붙여넣기(raw_override) 경로에서는 LLM 검수 호출이 없다
    from autoblog.draft import generate as gen

    def boom(messages, model=None):
        raise AssertionError("raw_override 경로에서 chat이 호출되면 안 됨")

    monkeypatch.setattr(gen, "chat", boom)
    result = gen.generate_draft(
        gen.DraftRequest(fact_card=_place_card(), experience_memo=""),
        raw_override="제목\n\n본문입니다.",
    )
    assert "본문입니다" in result.text


def test_extract_final_draft_takes_last_section():
    from autoblog.draft.postprocess import extract_final_draft

    resp = (
        "제목\n\n초안 본문인데 느낌표가 있다!\n\n"
        "## 자가 점검\n1. 느낌표 — 어김: .ᐟ 로 교체\n\n"
        "=====최종본=====\n제목\n\n고친 본문이다.ᐟ"
    )
    assert extract_final_draft(resp) == "제목\n\n고친 본문이다.ᐟ"


def test_extract_final_draft_tolerates_decorated_marker():
    from autoblog.draft.postprocess import extract_final_draft

    resp = "초안.\n\n**=====최종본=====**\n최종 글."
    assert extract_final_draft(resp) == "최종 글."


def test_extract_final_draft_tolerates_marker_variants():
    # 모델이 ===== 대신 제목/굵게/대시로 꾸며도 최종본만 남는다
    from autoblog.draft.postprocess import extract_final_draft

    for marker in ("## 최종본", "**최종본**", "--- 최종본 ---", "최종본:", "=====최종본====="):
        resp = f"초안 본문.\n\n## 자가 점검\n1. 통과\n\n{marker}\n제목\n\n최종 글 본문이다."
        assert extract_final_draft(resp) == "제목\n\n최종 글 본문이다.", marker


def test_extract_final_draft_drops_selfcheck_without_final_marker():
    # 3단계를 빠뜨리고 초안+자가 점검만 온 응답 — 점검 목록이 본문에 섞이면 안 된다
    from autoblog.draft.postprocess import extract_final_draft

    resp = "제목\n\n초안 본문이다.\n\n## 자가 점검\n1. 줄 길이 — 통과\n2. 느낌표 — 통과"
    assert extract_final_draft(resp) == "제목\n\n초안 본문이다."


def test_extract_final_draft_ignores_stub_final():
    # "위와 동일"처럼 재출력을 생략한 최종본은 초안으로 되돌린다
    from autoblog.draft.postprocess import extract_final_draft

    resp = "제목\n\n초안 본문이 제법 길게 이어진다.\n\n## 자가 점검\n통과\n\n=====최종본=====\n위와 동일"
    assert extract_final_draft(resp) == "제목\n\n초안 본문이 제법 길게 이어진다."


def test_enforce_format_strips_chatbot_markdown_debris():
    # 코드 펜스 줄 삭제, 수평선 → [구분선], "제목:" 라벨 제거, 마커 콜론 공백 정규화
    from autoblog.draft.postprocess import enforce_format

    text = enforce_format(
        "```\n제목: 혜화 맛집 후기\n\n인트로.\n\n---\n\n[사진 : 음식]\n\n[스티커: 신남]\n\n**[ 지도 : 메종아카이 ]**\n```"
    )
    lines = text.split("\n")
    assert lines[0] == "혜화 맛집 후기"
    assert "```" not in text and "---" not in text
    assert "[구분선]" in lines
    assert "[사진:음식]" in lines
    assert "[스티커:신남]" in lines
    assert "[지도:메종아카이]" in lines


def test_extract_final_draft_passthrough_without_marker():
    from autoblog.draft.postprocess import extract_final_draft

    plain = "제목\n\n마커 없는 보통 글."
    assert extract_final_draft(plain) == plain


def test_raw_override_extracts_final_section():
    # 외부 챗봇 응답을 통째로 붙여넣어도 최종본만 초안으로 쓰인다
    from autoblog.draft import generate as gen

    resp = "제목\n\n초안 본문.\n\n## 자가 점검\n통과\n\n=====최종본=====\n제목\n\n최종 본문이다."
    result = gen.generate_draft(
        gen.DraftRequest(fact_card=_place_card(), experience_memo=""), raw_override=resp
    )
    assert "최종 본문이다" in result.text
    assert "자가 점검" not in result.text and "초안 본문" not in result.text


def test_export_prompt_includes_review_protocol():
    # 내보내기 프롬프트: 자가 점검은 속으로만, 본문은 한 번만 출력하도록 지시한다
    from autoblog.pipeline import build_export_prompt

    text = build_export_prompt("메모", card=_place_card())
    assert "자가 점검" in text
    assert "속으로만" in text
    assert "딱 한 번만" in text
    assert "=====최종본=====" not in text  # 본문 2회 출력 프로토콜 제거됨


def test_wrap_long_lines():
    from autoblog.draft.postprocess import wrap_long_lines

    line = "비가 와서 우산 들고 걸어갔는데, 다행히 막걸리가 무료라 엄마랑 좋아하며 식사를 했어요"
    # 첫 줄(제목)은 분할 대상이 아니므로 본문 줄로 보려면 제목 줄을 앞에 둔다
    wrapped = wrap_long_lines(f"제목\n\n{line}", max_len=30)
    out_lines = [ln for ln in wrapped.split("\n")[2:] if ln]  # 제목+빈 줄 제외
    assert len(out_lines) > 1  # 여러 줄로 분할
    # 짧은 어절은 안 끊으므로 약간(≤2자) 초과 허용
    assert all(len(ln) <= 32 for ln in out_lines)
    # 줄 맨 앞에 짧은 의존명사(수/것 등)가 단독으로 오지 않음
    assert not any(ln.strip() in ("수", "것", "원에", "때") for ln in out_lines)
    # 빈 줄(문단 간격)은 보존
    assert wrap_long_lines("짧은 줄\n\n다음 문단") == "짧은 줄\n\n다음 문단"
    # 숫자 안 쉼표(13,000)는 줄바꿈하지 않음
    long_num = "이 메뉴는 무려 13,000원으로 가성비가 정말 훌륭한 편이라고 생각해요"
    assert "13,000" in wrap_long_lines(f"제목\n\n{long_num}", max_len=30)


def test_wrap_keeps_title_intact():
    """첫 줄(제목)은 쉼표·길이와 무관하게 분할되지 않는다(쉼표 제목 본문 누수 방지)."""
    from autoblog.draft.postprocess import enforce_format, wrap_long_lines

    title = "서울역에서 만난 미국식 소다 아이스크림, 메종 아카이"
    text = f"{title}\n\n본문 첫 문단이에요, 이건 평소처럼 절 단위로 쪼개져야 정상입니다"
    wrapped = wrap_long_lines(text, max_len=30)
    assert wrapped.split("\n")[0] == title  # 제목은 한 줄 그대로(쉼표로 안 쪼개짐)
    # plan이 첫 줄만 제목으로 떼어내도 '메종 아카이'가 본문으로 새지 않는지
    first_line = enforce_format(text).split("\n", 1)[0]
    assert first_line == title


def test_greedy_wrap_balanced():
    """쉼표·연결어미 없는 긴 절은 균형 분할 — 초과 줄·외톨이 꼬리·매달린 수식어가 없다."""
    from autoblog.draft.postprocess import _ADV_END, wrap_long_lines

    def body(line: str) -> list[str]:
        return [ln for ln in wrap_long_lines(f"제목\n\n{line}", max_len=30).split("\n")[2:] if ln]

    # 예전엔 30자까지 꽉 채우고 7자 외톨이("부드러웠어요.")가 떨어졌다
    out = body("목에 걸고 피부에 닿았을 때 거슬림 없이 아주 부드러웠어요.")
    assert len(out) >= 2
    assert all(len(ln) <= 30 for ln in out)  # 30자 초과 줄 없음
    assert min(len(ln) for ln in out) >= 12  # 외톨이(짧은 꼬리) 없음 — 균형
    assert not any(ln.split()[-1] in _ADV_END for ln in out)  # 수식어 줄 끝 매달림 없음

    # 예전엔 35자(짧은 어절 무조건 앞줄에 붙임)까지 넘쳤다
    assert all(len(ln) <= 30 for ln in body("이런 실용적인 부분까지 사용자를 위해 세심하게 만들어진 것 같아 좋았어요 -"))

    # 1~2자 초과(≤32)는 더 잘게 쪼개지 않고 그대로 둔다
    near = "오늘 카페에서 마신 라떼가 정말 부드럽고 고소해서 좋았던"  # 31자
    assert len(near) == 31
    assert body(near) == [near]
