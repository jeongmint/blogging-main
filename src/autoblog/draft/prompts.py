"""기본 베이스 프롬프트 로딩 (사용자 편집 가능).

config/prompts/default.md(맛집)·product.md(상품)·venue.md(숙소·전시·팝업스토어 등
체험형 장소)를 시스템 프롬프트의 베이스로 쓰고, 세 유형이 공유하는 문체 규칙
(config/prompts/common_style.md)을 그 뒤에 이어 붙인다(복붙 중복으로 파일들이
어긋나던 것을 단일 출처로 통합). 파일 상단의 메타 안내(제목 + 인용 블록, 첫 '---'
이전)는 모델에 보내지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from autoblog.config import CONFIG_DIR

DEFAULT_PROMPT_PATH = CONFIG_DIR / "prompts" / "default.md"
PRODUCT_PROMPT_PATH = CONFIG_DIR / "prompts" / "product.md"
VENUE_PROMPT_PATH = CONFIG_DIR / "prompts" / "venue.md"
COMMON_STYLE_PROMPT_PATH = CONFIG_DIR / "prompts" / "common_style.md"
RESTYLE_PROMPT_PATH = CONFIG_DIR / "prompts" / "restyle.md"


def _strip_meta(text: str) -> str:
    """파일 상단 메타 안내(제목 + 인용 블록, 첫 '---' 이전) 제거."""
    marker = "\n---\n"
    idx = text.find(marker)
    if idx != -1:
        text = text[idx + len(marker) :]
    return text.strip()


def load_base_prompt(path: str | Path | None = None, *, card=None) -> str:
    """베이스 프롬프트 텍스트 로드(상단 메타 안내 제거 + 공통 문체 규칙 연결).

    path를 명시하지 않고 card가 상품 카드(FactCard.is_product)면 product.md를 쓴다.
    상품이 아니고 체험형 장소 카드(FactCard.is_venue — 네이버 category나 유저가 적은
    '어떤 장소인지 메모'로 판별, 예: 숙소·전시·팝업스토어·테마파크)면 venue.md를 쓴다.
    둘 다 아니면 default.md로 폴백한다(맛집 공용). 공통 문체 규칙(common_style.md)은
    자동 선택 경로에서만 이어 붙인다 — path를 직접 지정한 커스텀 프롬프트
    (CLI --prompt-file 등)는 그 파일 그대로가 베이스다.
    """
    explicit_path = path is not None
    if path is None and card is not None:
        if getattr(card, "is_product", False) and PRODUCT_PROMPT_PATH.exists():
            path = PRODUCT_PROMPT_PATH
        elif getattr(card, "is_venue", False) and VENUE_PROMPT_PATH.exists():
            path = VENUE_PROMPT_PATH
    text = _strip_meta(Path(path or DEFAULT_PROMPT_PATH).read_text(encoding="utf-8"))
    if not explicit_path and COMMON_STYLE_PROMPT_PATH.exists():
        # 공통 문체 규칙(맛집·상품 공용, 단일 출처)
        common = _strip_meta(COMMON_STYLE_PROMPT_PATH.read_text(encoding="utf-8"))
        if common:
            text = f"{text}\n\n{common}"
    return text


def load_restyle_prompt() -> str:
    """리스타일 베이스(원문 구조·정보 유지, 문체만 재적용) + 공통 문체 규칙.

    외부에서 받아온 완성 초안에 내 문체·포맷을 다시 입히는 경로(webui 리스타일 모드)의
    base_prompt. 맛집/상품처럼 common_style.md를 뒤에 이어 붙여 줄바꿈·서술 규칙을 공유한다.
    """
    text = _strip_meta(RESTYLE_PROMPT_PATH.read_text(encoding="utf-8"))
    if COMMON_STYLE_PROMPT_PATH.exists():
        common = _strip_meta(COMMON_STYLE_PROMPT_PATH.read_text(encoding="utf-8"))
        if common:
            text = f"{text}\n\n{common}"
    return text


# 맛집·상품 공통 자가 점검 — 시스템 프롬프트 맨 끝에 항상 붙인다(단일 출처).
# 가장 자주 어기는 기계적 규칙만 짧게 추렸다. 외부 챗봇에 붙여넣어 쓰는 경로는
# enforce_format 후처리를 안 거치므로, 모델이 스스로 점검·수정하게 만드는 게 핵심.
# 나열 박스 예외는 상품 리뷰에만 있는 개념이라 is_product일 때만 언급한다
# (맛집 글에 예외를 언급하면 허용되는 것으로 오독할 수 있음).


def build_selfcheck_instruction(
    is_product: bool = False,
    ornaments: bool = True,
    has_photos: bool = False,
    has_stickers: bool = False,
    hashtags: bool = True,
    is_venue: bool = False,
    wishlist: bool = False,
    consumed: bool = False,
) -> str:
    """자가 점검 지시문(시스템 프롬프트 맨 끝에 붙이는 블록).

    is_product=True(상품 리뷰)면 나열 박스(1️⃣~·✅) 예외 문구를 함께 넣는다. consumed=True면
    이 예외 문구를 뺀다 — 소비리스트는 요약 박스·체크리스트 구조를 안 쓰는 목록형이라
    나열 박스 예외를 언급하면 없는 구조를 있는 것처럼 오독시킨다.
    ornaments=False(발랄체가 아닌 어투)면 어투 결합 항목(느낌표→.ᐟ 치환, 이모지 허용
    목록)을 뺀다 — 그 어투에는 해당 규칙이 없고, 기준은 [추가 문체 지시]가 정한다.
    has_photos/has_stickers면 사진 분산·이모티콘 채움 점검 항목을 추가한다
    (사진·스티커가 없는 글에 넣으면 지킬 수 없는 항목이 돼 점검 전체의 신뢰를 깎는다).
    hashtags=False(리스타일 — 태그줄을 안 쓰는 초안)면 해시태그 항목을 뺀다
    (넣으면 검수 패스가 없던 태그줄을 지어내 붙인다).
    is_venue=True(숙소·전시·팝업스토어 등 체험형 장소)면 '검색 제목'·'정보' 항목의
    메뉴/영업시간/휴무일 언어를 이용료·운영시간·볼거리 언어로 바꾼다(맛집이 아닌 글에
    '먹은 메뉴' 점검을 넣으면 지킬 수 없는 항목이 돼 점검 전체의 신뢰를 깎는다).
    wishlist=True(아직 안 산 위시리스트 상품 글)면 '경험'·'균형' 항목을 '직접 써본
    경험'·'단점'이 아니라 '갖고 싶은 이유'·'리서치 근거' 관점으로 바꾼다(안 써본 글에
    '써본 경험'·'써보니 아쉬운 점'을 점검시키면 지어내라는 지시가 되어 버린다).
    """
    box_note = " (요약 박스 1️⃣~·추천 체크리스트 ✅ 한 줄은 예외)" if (is_product and not consumed) else ""
    bullet_note = " (요약 박스·추천 체크리스트만 예외)" if (is_product and not consumed) else ""
    items = [
        "줄 길이 — 본문에 30자를 넘는 줄이 하나도 없는가? 넘으면 쉼표나 연결어미(~는데, "
        f"~거든요, ~어서 등) 뒤에서 끊어 두세 줄로 나눠.{box_note}",
        "한 줄 한 절 — 한 줄에 문장을 두 개 이어 붙이지 않았는가? 줄 중간에 마침표가 있으면 거기서 줄바꿈해.",
    ]
    if ornaments:
        items.append("느낌표 — 본문에 ! 가 하나도 없는가? 있으면 전부 .ᐟ 로 바꿔.")
    items.append(f"나열 기호 — 본문 줄 앞에 •, -, *, ▶, → 를 붙여 나열한 곳이 없는가?{bullet_note}")
    if ornaments:
        items.append("이모지 — 허용 목록 밖 이모지(💖 💕 🔥 😍 🤤 💯 등)를 쓰지 않았는가?")
    if has_photos:
        items.append(
            "사진 분산 — [사진] 마커 없이 글만 이어지는 문단이 3개 이상 연속되는 구간이 없는가? "
            "총평·꿀팁처럼 딱 맞는 사진이 없는 섹션에도 느슨하게 어울리는 남은 사진을 배치했는가? "
            "있다면 앞쪽에 몰린 사진 마커를 뒤로 옮겨 고르게 나눠."
        )
    if has_stickers:
        items.append(
            "이모티콘 — 사진이 안 붙어 글만 남은 문단에는 [스티커:상황] 을 넣어 허전함을 채웠는가? "
            "(과하지 않게 — 연속된 문단마다 붙이지는 마)"
        )
    if is_venue:
        title_check = (
            "검색 제목 — 제목이 50자 내외이고, 지역·장소명·장소 종류·실용정보(입장료·운영시간 등) "
            "같은 검색 키워드가 자연스러운 문장으로 녹아 있는가? 그 위에 호기심·감정·질문형 훅이 "
            "함께 있는가? 제목에 넣은 숫자·훅은 본문에서 실제로 다뤘는가? (불일치는 낚시로 찍힘)"
        )
    else:
        title_check = (
            "검색 제목 — 제목이 50자 내외이고, 지역·카테고리·가게/제품명·메뉴·스펙·실용정보 같은 "
            "검색 키워드가 자연스러운 문장으로 녹아 있는가? 그 위에 호기심·감정·질문형 훅이 함께 있는가? "
            "먹은 메뉴 이름이 웬만하면 전부 제목에 들어갔는가? (길이를 넘길 만큼 많을 때만 대표 메뉴 위주로) "
            "제목에 넣은 숫자·메뉴·훅은 본문에서 실제로 다뤘는가? (불일치는 낚시로 찍힘)"
        )
    items += [
        title_check,
        "드립 한 줄 — 헤더(대제목 아래)에 해시태그 나열 대신 내 말투의 드립 한 줄이 있는가? "
        '("재방문에는 다 이유가 있는법", "한번 먹고 두번 먹고 자꾸만 먹고 싶네"처럼 '
        "카톡 치듯 툭 던지는 한마디 — 반듯한 작문 티가 나면 다시 써.) "
        "줄바꿈 없이 정확히 한 줄인가? 두 줄로 쪼갰거나 한 줄로 못 줄일 만큼 길면 짧게 다시 써.",
    ]
    if hashtags:
        items.append(
            "해시태그 — 태그줄(드립 한 줄 다음 줄)에 해시태그가 5~10개 있고, 첫 태그를 포함해 모두 "
            "앞에 #이 붙어 있으며, 태그 외 다른 단어가 섞이지 않았는가? 이 줄은 네이버 발행 태그칸으로 "
            "들어가니 사람이 검색창에 칠 법한 말(#지역명맛집, #가게명, #제품명추천, #메뉴명, "
            "#지역명내돈내산)만 써 — 사진 분류명(협찬·음식·외관 같은 작업용 라벨)이나 "
            "글 성격 표시(#협찬 #광고 #후기)는 검색되지 않으니 태그로 만들지 마."
        )
    if is_venue:
        info_check = (
            "정보 — 재료에 있는 입장료·운영시간·휴무일·주차·웨이팅 같은 구체 정보가 본문에서 "
            "빠지지 않았는가? 정리 표(| 정보 | 내용 |)를 한 번 넣고 운영시간·휴무일·주차 행을 "
            "챙겼는가? 표에 전화·주소(지도 카드와 중복)나 무선 인터넷·화장실처럼 흔한 항목, "
            "재료에 없는 항목·각색한 값이 섞이지 않았는가? (재료에 없는 숫자를 지어내는 건 금지)"
        )
    else:
        info_check = (
            "정보 — 재료에 있는 가격·영업시간·휴무일·주차·웨이팅 같은 구체 정보가 본문에서 빠지지 "
            "않았는가? 맛집 글이면 정리 표(| 정보 | 내용 |)를 한 번 넣고 영업시간·휴무일·주차 행을 "
            "챙겼는가? 표에 전화·주소(지도 카드와 중복)나 무선 인터넷·화장실·신용카드처럼 흔한 항목, "
            "재료에 없는 항목·각색한 값이 섞이지 않았는가? (재료에 없는 숫자를 지어내는 건 금지)"
        )
    if wishlist:
        experience_check = (
            "경험 — 정보 나열에 그치지 않고 '이걸 왜 갖고 싶은지/어떻게 발견했는지' 1인칭 "
            "리서치 경험이 글 전체에 살아 있는가? '직접 써본/써보니' 같은 사용 경험 문구가 "
            "섞여 있지 않은가? (안 써본 글에 사용 경험을 쓰면 안 됨 — 있으면 리서치·기대 "
            "표현으로 고쳐)"
        )
        balance_check = (
            "균형 — 장점만 나열해 광고처럼 보이지 않는가? 아직 안 써봤으니 '단점'을 "
            "지어내지 말고, 대신 '가격이 부담되지만'·'고민 중인 부분' 같은 구매 전 "
            "망설임·현실적 고려를 1개 이상 솔직하게 반영했는가?"
        )
    else:
        experience_check = (
            "경험 — 정보 나열에 그치지 않고 '내가 직접 써본/다녀온' 1인칭 경험이 글 전체에 살아 있는가?"
        )
        balance_check = (
            "균형 — 재료에 아쉬운 점이 있었다면 본문에 1개 이상 솔직하게 반영했는가? (없는 단점을 지어내는 건 금지)"
        )
    items += [
        "제목 길이 — 대제목은 16자 안팎(최대 20자), 소제목은 22자 이내로 짧은가? "
        "둘 다 본문보다 큰 글씨라 길면 모바일에서 줄이 쪼개져 답답해진다. (본문 30자 규칙과 별개)",
        experience_check,
        info_check,
        "AI 검색 — 재료에 방문·구매·사용 시점이 있으면 본문에 드러냈는가? 가격·웨이팅·주차·"
        "영업시간 문장은 그 대목만 떼어 읽어도 무엇에 대한 정보인지 통하는가?",
        balance_check,
        "문체 — 모든 문장이 문체 지시의 어투(종결어미·이모티콘·꾸밈 문자 기준)를 따르는가? "
        "다른 어투의 말버릇이 섞였으면 문체 지시에 맞게 고쳐.",
        "자연스러움 — 모든 문장을 소리 내어 읽듯 하나씩 검토했는가? 어미가 이중으로 붙거나"
        '("맛있더라궁 같은 기분이더라구요"처럼 꼬인 문장), 경험 메모의 문구가 그대로 섞여 '
        "어색해진 문장이 있으면 뜻은 살리고 자연스러운 한 문장으로 다시 써.",
        "AI 티 — 실측된 AI 신호 네 가지를 점검해. 쉼표 2개 이상인 문장(줄바꿈으로 대체), "
        '첫째·둘째 같은 서수 전환, "전반적으로"·"~라고 할 수 있어요" 류 정리 멘트, '
        "길이·구조가 똑같이 반복되는 문단. 하나라도 있으면 친구한테 말하듯 리듬을 "
        "흐트러뜨려 다시 써 — 너무 매끈하고 반듯한 게 오히려 AI 티다.",
    ]
    numbered = "\n".join(f"{i}. {item}" for i, item in enumerate(items, 1))
    return f"""## 제출 전 자가 점검 (반드시 마지막에 수행)

글을 다 썼으면 제출하기 전에 아래를 한 항목씩 직접 검사하고, 어긴 곳이 있으면 그 자리에서 고친 뒤 최종본만 내보내. 이 점검을 생략하지 마.

{numbered}"""
