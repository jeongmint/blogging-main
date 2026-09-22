"""게시 플랜 — 초안(DraftResult) → 에디터에 넣을 블록 시퀀스 (순수 변환, 테스트 가능).

본문을 [사진] 마커 기준으로 텍스트/이미지 블록으로 나누고, 강조 span을
해당 텍스트 블록에 배분한다. 이 플랜을 editor가 Smart Editor에 주입한다.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

import yaml

from autoblog.collect.fact_card import PhotoItem
from autoblog.config import CONFIG_DIR
from autoblog.draft.generate import DraftResult
from autoblog.publish.emphasis import EmphasisStyle, StyledSpan
from autoblog.publish.stickers import StickerPicker

PHOTO_MARKER = "[사진]"
# [사진] / [사진:음식] — 라벨로 어떤 사진을 그 자리에 놓을지 지정 가능
_PHOTO_RE = re.compile(r"^\[사진(?::(.+?))?\]$")
_VIDEO_RE = re.compile(r"^\[영상(?::(.+?))?\]$")  # 동영상 마커(사진과 동일 규칙, media_kind=video만 매칭)
# 협찬 고지 사진 라벨 — 이 라벨이 붙은 사진은 본문 '첫 이미지'로 끌어올린다(최상단 고지).
SPONSOR_PHOTO_LABEL = "협찬"
QUOTE_CLOSE = "[/인용구]"
# [구분선] / [구분선:2], [인용구] / [인용구:3] — 종류(variant) 선택 가능
_DIVIDER_RE = re.compile(r"^\[구분선(?::(\d+))?\]$")
_QUOTE_OPEN_RE = re.compile(r"^\[인용구(?::(\d+))?\]$")
# [스티커] / [스티커:상황] — picker가 라벨을 (팩,인덱스)로 해석
_STICKER_RE = re.compile(r"^\[스티커(?::(.+?))?\]$")
# [지도] / [지도:가게명] — SE 네이티브 '장소' 카드(주소·지도 미리보기)로 삽입.
# 이름 생략 시 build_publish_plan(place_query=)로 받은 수집된 가게명을 쓴다.
_PLACE_RE = re.compile(r"^\[지도(?::\s*(.+?))?\]$")
# 마커 인자가 URL(naver.me 단축 등)인지 — SE 장소 검색은 URL이면 결과 0건이라 이름으로 해석 필요
_PLACE_URL_RE = re.compile(r"https?://|naver\.me/|\.naver\.com/", re.I)
# 마크다운 표 — 챗봇/리스타일 출력의 `| a | b |` 행. 앞뒤 파이프가 있어야 표 행으로 본다
# (본문에 파이프 하나 섞인 산문을 표로 오인하지 않게). 구분행(|---|:--|)은 셀 없이 대시·콜론뿐.
_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")


def parse_md_table(lines: list[str]) -> list[list[str]] | None:
    """마크다운 표 행 목록 → [[셀,…],…]. 구분행(|---|)이 있어야 유효(없으면 None=표 아님)."""
    rows: list[list[str]] = []
    has_sep = False
    for ln in lines:
        s = ln.strip()
        if _TABLE_SEP_RE.match(s) and "-" in s:
            has_sep = True
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        rows.append(cells)
    if not has_sep or not rows:
        return None
    return rows

# 쿠팡파트너스 링크 도메인(link.coupang.com / coupa.ng 단축 / coupang.com 상품)
_COUPANG_HOSTS = ("coupang.com", "coupa.ng")


def _is_coupang_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _COUPANG_HOSTS)


def _resolve_place_marker_url(url: str) -> tuple[str, str | None] | None:
    """[지도:URL] 마커의 URL → (가게명, 도로명 주소). 세션 캐시 우선, 없으면 실시간 해석."""
    from autoblog.pipeline import cached_place_card  # 함수 내 임포트 - 모듈 순환 참조 회피

    card = cached_place_card(url)
    if card is not None and card.place and card.place.name:
        p = card.place
        return p.name, (p.road_address or p.address)
    from autoblog.collect.place_detail import place_name_address_from_url

    return place_name_address_from_url(url)

# 구분선/인용구 종류 메타 — value(에디터 data-value) → (variant 인덱스, 이름, 어느 상황에 쓰면 좋은지)
# 라이브 캡쳐한 모양을 보고 작성. UI에 이름·용도 노출, 초안 LLM에 상황 안내, 마커 [구분선:이름] 해석에 사용.
DIVIDER_META = {
    "default": (1, "기본 가는 선", "가장 무난한 화제 전환. 어디에나 어울림"),
    "line1": (2, "실선", "깔끔하고 또렷한 구분. 단락이 확실히 바뀔 때"),
    "line2": (3, "굵은 짧은 선", "강한 전환·소제목 느낌. 챕터를 크게 나눌 때"),
    "line3": (4, "가운데 꺾인 선", "부드러운 전환. 감성적인 흐름 사이"),
    "line4": (5, "다이아몬드 선", "장식적·포인트. 특별한 구간을 나눌 때"),
    "line5": (6, "점선", "가볍게 끊기. 부연·메모로 살짝 넘어갈 때"),
    "line6": (7, "사선", "캐주얼한 분위기 전환. 가벼운 글에"),
    "line7": (8, "세로선", "짧은 좌우 구분(드물게). 나란히 비교할 때"),
}
QUOTE_META = {
    "default": (1, "기본(큰따옴표)", "감성·감상을 담은 핵심 한마디를 큰따옴표로 가운데 크게. 강조하고 싶은 감상·메시지는 이걸 씀(밑줄형 아님)"),
    "quotation_line": (2, "왼쪽 줄", "남의 말·출처 있는 인용문을 담백하게. 내 감상 아닌 인용"),
    "quotation_bubble": (3, "말풍선", "대화체·혼잣말 코멘트. 말 거는 듯한 한마디"),
    "quotation_underline": (4, "밑줄형", "감상 아닌 정보성 요점·결론을 한 줄로 또박또박 정리(사실·포인트용, 감정 강조 아님)"),
    "quotation_postit": (5, "포스트잇", "본문 흐름 밖 곁다리 팁·꿀팁 메모. '알아두면 좋은' 정보"),
    "quotation_corner": (6, "모서리", "글을 닫는 여운 있는 마무리 멘트"),
}
# 에디터에서 가운데정렬이 기본 모양인 인용구 종류(variant 인덱스). 왼쪽줄(2)·밑줄형(4)은
# 왼쪽정렬이 기본·고정이라 가운데정렬을 주면 미리보기·에디터 둘 다 어긋난다.
_QUOTE_CENTERED_VARIANTS = {1, 3, 5, 6}


def quote_align(variant: int) -> str | None:
    """인용구 종류에 맞는 단락 정렬(가운데형은 center, 왼쪽줄·밑줄형은 None=왼쪽)."""
    return "center" if variant in _QUOTE_CENTERED_VARIANTS else None

# 초안 구조 마커: 구분선 [구분선], 인용 블록 [인용구]…[/인용구]
# (EMPHASIS_INSTRUCTION과 같은 추가 레이어. generate_draft(structure=True)에서 시스템 프롬프트에 덧붙임)
# 14b 모델은 "절제" 위주로 안내하면 마커를 아예 안 단다(라이브 측정: 0/0/0).
# "권장이 아니라 사용 + 예시 + 개수 지정"으로 바꾸니 화제전환 있는 글에서 실제로 emit됨.
def build_structure_instruction(
    divider_keys: list[str] | None = None,
    quote_keys: list[str] | None = None,
) -> str:
    """구조 마커 지시문 — 유저가 '서식'에서 고른 구분선/인용구 종류만 쓰도록 안내.

    divider_keys/quote_keys는 DIVIDER_META/QUOTE_META 키 목록(비우면 기본 한 종류).
    여러 종류를 고르면 종류별 번호·용도를 나열하고 [구분선:번호]/[인용구:번호] 로 상황에 맞게
    고르게 한다(목록 밖 종류·번호 금지). 한 종류면 번호 없이 [구분선]/[인용구] 만 쓰게 한다(종류 자동).
    """
    dkeys = [k for k in (divider_keys or ["default"]) if k in DIVIDER_META] or ["default"]
    qkeys = [k for k in (quote_keys or ["default"]) if k in QUOTE_META] or ["default"]

    def menu(keys, meta, marker):
        return "\n".join(f"  · [{marker}:{meta[k][0]}] {meta[k][1]} — {meta[k][2]}" for k in keys)

    if len(dkeys) == 1:
        divider_line = "- 화제가 바뀌는 문단 사이에 [구분선] 을 한 줄로 1~2번 넣으세요(종류는 자동).\n"
        d_open = "[구분선]"
    else:
        divider_line = (
            "- 화제가 바뀌는 문단 사이에 구분선을 한 줄로 1~2번 넣으세요. "
            "아래 고른 종류 중 상황에 맞는 걸 골라 번호까지 붙이세요(여기 없는 종류·번호는 절대 쓰지 마세요):\n"
            f"{menu(dkeys, DIVIDER_META, '구분선')}\n"
        )
        d_open = f"[구분선:{DIVIDER_META[dkeys[0]][0]}]"

    if len(qkeys) == 1:
        quote_line = (
            "- 글 전체를 관통하는 핵심 메시지·감상 '한마디'가 있을 때만 그 한 문장을 [인용구] 와 [/인용구] 로 "
            "감싸세요(없으면 넣지 마세요, 최대 1번).\n"
        )
        q_open = "[인용구]"
    else:
        quote_line = (
            "- 글 전체를 관통하는 핵심 메시지·감상 '한마디'가 있을 때만 그 한 문장을 인용구로 "
            "감싸세요(없으면 넣지 마세요, 최대 1번). 여는 줄은 아래 고른 종류 중 상황에 맞는 걸 골라 "
            "번호까지 붙이고(여기 없는 종류·번호 금지), 닫는 줄은 [/인용구] 로 두세요:\n"
            f"{menu(qkeys, QUOTE_META, '인용구')}\n"
        )
        q_open = f"[인용구:{QUOTE_META[qkeys[0]][0]}]"

    # 레시피는 서식 선택과 무관하게 포스트잇 고정 — 본문 흐름 밖 '메모' 성격이라 종류가 정해져 있다.
    postit = QUOTE_META["quotation_postit"][0]
    postit_marker = "[인용구]" if qkeys == ["quotation_postit"] else f"[인용구:{postit}]"
    recipe_line = (
        f"- 레시피·조리법·재료 분량처럼 단계나 계량을 알려주는 대목이 있으면 그 부분을 {postit_marker} 와 "
        "[/인용구] 로 감싸 포스트잇 메모로 넣으세요(본문 흐름 밖 정보라 위 '최대 1번'과 별개, 레시피 하나당 하나). "
        "재료와 순서는 각각 한 줄씩 끊어 적으세요.\n"
    )

    return (
        "[구조 마커] — 아래 마커를 본문에 실제로 넣어 글을 읽기 좋게 나누세요(권장이 아니라 사용).\n"
        f"{divider_line}"
        "  단, 번호 소제목(예: '3. 매장 내부 분위기') 바로 앞뒤에는 구분선을 넣지 마세요 — "
        "소제목이 큰 글씨라 이미 구분 역할을 해서 중복입니다. 소제목 없이 같은 섹션 안에서 "
        "화제가 크게 바뀌는 지점에만 쓰세요.\n"
        f"{quote_line}"
        f"{recipe_line}"
        "  인용구 안의 한마디도 한 줄에 짧은 절 하나씩 2~3줄로 끊어 쓰세요(본문 줄바꿈 규칙 동일).\n"
        "  음식·분위기를 묘사하는 짧은 카피성 문구(예: '겉은 바삭 속은 촉촉')는 인용구로 만들지 말고, "
        '강조하려면 본문 안에서 큰따옴표(" ")로 감싸 쓰세요.\n'
        f"예시:\n오늘 다녀온 첫 소감 문단.\n\n{d_open}\n\n"
        f"{q_open}\n두 번 세 번 와도\n안 질릴 것 같은 곳\n[/인용구]\n\n다음 문단.\n"
        "마커는 화면에 글자로 안 보이고 서식으로 바뀝니다. 문장 안에 섞지 말고 줄 단독으로 두세요."
    )


# 기본(한 종류) 지시문 — 종류 미지정 호출·프롬프트 미리보기 등에서 재사용.
STRUCTURE_INSTRUCTION = build_structure_instruction()


def build_place_instruction(place_name: str | None = None) -> str:
    """장소(지도) 마커 지시문 — 맛집 글에서 위치 안내 자리에 지도 카드를 넣게 안내.

    place_name(수집된 가게명)을 주면 [지도:가게명] 마커를 쓰게 한다 — 초안이 가게
    정보를 스스로 갖고 있어, 외부 챗봇 결과를 수집 링크 없는 탭이나 재시작 뒤에
    붙여넣어도 지도가 살아난다(세션 캐시 의존 제거)."""
    marker = f"[지도:{place_name}]" if place_name else "[지도]"
    name_rule = (
        f"- 마커는 정확히 {marker} 그대로 쓰세요(가게명을 바꾸거나 빼지 마세요).\n"
        if place_name
        else "- 가게명은 시스템이 알아서 넣으니 [지도] 만 쓰면 됩니다(이름을 직접 적지 마세요).\n"
    )
    return (
        f"{marker} 가게 위치를 안내하는 자리(보통 '상세 정보 및 위치' 섹션)에 {marker} 를 그 줄에 "
        "혼자 한 번 넣으세요(권장이 아니라 사용). 시스템이 네이버 '장소'를 검색해 지도 카드"
        "(주소·지도 미리보기)로 바꿉니다.\n"
        f"- {marker} 는 한 글에 한 번만, 위치를 설명한 문장 바로 아래 줄에 단독으로.\n"
        + name_rule
        + "- 마커는 화면에 글자로 안 보이고 지도 카드로 바뀝니다. 문장 안에 섞지 마세요."
    )


# --- 구조별 서식 템플릿 (config/structure_styles.yaml) ---
# 대제목·소제목 줄을 패턴으로 인식해 서체/크기/색을 자동 배정한다. 해시태그 줄은
# 본문에 렌더하지 않고 발행 태그칸용 plan.tags로 수집한다(자리엔 구분선만 남김).
# 마커가 아니라 패턴 인식이라, 외부 챗봇에서 받아온 글에도 동일하게 먹는다.
_STRUCTURE_STYLES_PATH = CONFIG_DIR / "structure_styles.yaml"

# "1. 가게명 후기" 소제목 / 해시태그 줄 인식. 모델이 "1)" 형태로 쓰는 경우도 받는다.
# 번호는 두 자리까지만 — 안 그러면 "2026. 7월에 방문했어요" 같은 본문 줄이 소제목으로 둔갑한다.
_SUBHEADING_RE = re.compile(r"^\d{1,2}[.)]\s+\S")


class RoleStyle(BaseModel):
    font: str | None = None
    size: int | None = None
    color: str | None = None
    align: str | None = None  # 단락 정렬: left/center/right/justify (None=기본 왼쪽)

    def to_style(self) -> EmphasisStyle:
        return EmphasisStyle(
            text_color=self.color,
            font_family=self.font,
            font_size=str(self.size) if self.size else None,
        )


class HashtagStyle(RoleStyle):
    # 태그가 본문 대신 네이버 발행 태그칸으로 들어가면서, 이 서식(font/size/color/align)은
    # 그 자리를 대신하는 '드립 한 줄'에 입힌다. per_line은 예전 설정 파일 호환용.
    per_line: int = 2
    divider: str | None = None  # 태그줄 자리(헤더 끝)에 넣을 구분선 종류(DIVIDER_META 키)


class StructureStyles(BaseModel):
    big_title: RoleStyle = Field(default_factory=RoleStyle)
    subheading: RoleStyle = Field(default_factory=RoleStyle)
    hashtags: HashtagStyle = Field(default_factory=HashtagStyle)
    # 협찬 토글 ON 시 본문 맨 위에 고정 삽입할 고지 스티커 "팩코드:인덱스" (예: ogq_a:3). 비우면 안 넣음.
    sponsor_sticker: str = ""

    def sponsor_ref(self) -> tuple[str, int] | None:
        """sponsor_sticker("팩:인덱스") → (pack, index). 형식이 어긋나면 None."""
        pack, _, idx = self.sponsor_sticker.partition(":")
        if pack and idx.isdigit():
            return pack, int(idx)
        return None


def load_structure_styles(path=None) -> StructureStyles:
    """구조별 서식 템플릿 로드(사용자 편집 파일). 없으면 빈 기본값."""
    path = path or _STRUCTURE_STYLES_PATH
    try:
        data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except FileNotFoundError:
        return StructureStyles()
    return StructureStyles(**data)


def _is_hashtag_line(s: str) -> bool:
    """해시태그가 2개 이상인 줄(헤더의 태그 묶음). 본문 속 우연한 # 한 개는 제외."""
    return sum(1 for t in s.split() if t.startswith("#")) >= 2


def _find_drip_lines(lines: list[str]) -> list[int]:
    """대제목(첫 비어있지 않은 줄) 바로 아래의 '짧은 문단'(1~2줄) 인덱스들 = 드립 한 줄.

    태그줄이 없는 초안(리스타일 등)에서도 드립 줄에 해시태그 서식을 입히기 위해
    미리 찾아둔다. 드립 뒤에 태그줄이 바로 붙는 기존 헤더는 여기서 못 잡아도
    consume_tag_line 경로가 그대로 처리한다.

    모델이 '한 줄 한 절' 습관으로 드립을 두 줄로 쪼개 쓰는 경우가 실제로 있어
    (리스타일 실측) 2줄짜리 문단까지 드립으로 본다. 3줄 이상은 본문 인트로.

    마커 줄([사진:협찬] 등)은 빈 줄 취급 — 협찬 마커가 헤더 위/사이에 끼면
    드립 감지가 통째로 꺼져 해시태그 서식이 사라지던 실측 버그.

    태그줄은 빈 줄 취급하지 않는다(경계 유지) — 한때 빈 줄 취급했더니, 드립 없이
    '대제목→태그줄→인트로'로 쓴 초안에서 인트로 첫 줄이 가짜 드립(작은 파란 글씨)으로
    잡히는 회귀가 났다(우이락 실측). 태그줄 뒤에 온 드립은 본문으로 남는 게 덜 나쁘다.
    """
    lines = ["" if ln.strip().startswith("[") else ln for ln in lines]
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    if len(idx) < 2:
        return []
    big_s = lines[idx[0]].strip()
    if not (0 < len(big_s) <= 40) or big_s.startswith(("[", "|")):
        return []
    # 대제목 다음 문단 = 연속된 비어있지 않은 줄 묶음
    para = [idx[1]]
    while para[-1] + 1 < len(lines) and lines[para[-1] + 1].strip():
        para.append(para[-1] + 1)
    if len(para) > 2:
        return []  # 3줄 이상 문단은 인트로(드립 아님)
    # 2줄 드립은 뒤에 본문이 더 있을 때만 — 그 문단이 글의 전부면 인트로/본문이다
    if len(para) == 2 and not any(ln.strip() for ln in lines[para[-1] + 1 :]):
        return []
    # 마커·표·태그줄은 드립이 아니다 (ponytail: 짧은 문단 휴리스틱 — 대제목 아래
    # 짧은 인트로를 쓰는 특이 초안은 드립으로 오인될 수 있음)
    for i in para:
        s = lines[i].strip()
        if not (0 < len(s) <= 40) or s.startswith(("[", "|")) or _is_hashtag_line(s):
            return []
    return para


# 대제목(콘셉트 한 줄)은 본문보다 큰 글씨라, 길면 모바일에서 화면 끝에서 제멋대로 접혀
# 위아래 비율이 어긋난다. 그래서 공백 제외 이 길이를 넘으면 어절 경계에서 미리 한 번
# 줄바꿈해 두 줄로 만든다(모바일 큰 글씨 기준 ~13자에서 접힘 → 10자 초과부터 선제 분할).
_BIG_TITLE_WRAP_THRESHOLD = 10


def balance_wrap(s: str, threshold: int = _BIG_TITLE_WRAP_THRESHOLD) -> str:
    """대제목이 길면 어절(띄어쓰기) 경계에서 한 번 줄바꿈해 위아래 글자 수가 최대한
    비슷한 두 줄로 만든다. 다음 경우엔 그대로 둔다:
    - 이미 줄바꿈(\\n)이 있음 — 작성자/모델이 직접 나눴으니 존중.
    - 공백 제외 길이가 threshold 이하 — 짧아서 안 접힘.
    - 띄어쓰기가 없음 — 나눌 어절 경계가 없어 단어 중간 절단은 하지 않음.
    """
    if "\n" in s:
        return s
    if len(s.replace(" ", "")) <= threshold:
        return s
    spaces = [i for i, ch in enumerate(s) if ch == " "]
    if not spaces:
        return s

    def imbalance(i: int) -> int:  # 공백 제외 글자 수 차이 — 작을수록 위아래 균형
        return abs(len(s[:i].replace(" ", "")) - len(s[i + 1 :].replace(" ", "")))

    best = min(spaces, key=imbalance)
    return s[:best] + "\n" + s[best + 1 :]


class PublishBlock(BaseModel):
    kind: str  # "text" | "image" | "video" | "divider" | "quote" | "sticker" | "place" | "link" | "table"
    text: str = ""
    table_rows: list[list[str]] = Field(default_factory=list)  # kind="table": 표의 행×셀
    link_url: str = ""  # 링크 카드(oglink) URL — 쿠팡파트너스 등
    keep_url_text: bool = False  # 협찬 링크: 카드 밑 'URL 텍스트 줄'을 지우지 말고 남김(크롤러 인식용)
    emphases: list[StyledSpan] = Field(default_factory=list)
    image_path: str | None = None
    image_label: str = ""
    image_size: str | None = None  # 이미지 표시 크기 힌트: "small"(협찬 고지 사진 등). None=기본
    ai_generated: bool = False  # AI 생성 이미지 — 게시 시 'AI 활용' 표시(네이버 자율 표기)
    variant: int = 1  # 구분선/인용구 종류(1=기본)
    sticker_pack: str | None = None  # 스티커 팩 코드(picker 해석 결과)
    sticker_index: int | None = None  # 스티커 data-index
    sticker_kind: str = ""  # 스티커 분류(감정/구분선/헤더) — 구분선 겹침 방어에 사용
    align: str | None = None  # 단락 정렬: center/right/justify (None=기본 왼쪽)
    place_address: str | None = None  # 장소 카드: 수집 도로명 주소(검색 결과 매칭용)


class PublishPlan(BaseModel):
    title: str
    blocks: list[PublishBlock] = Field(default_factory=list)
    # 네이버 발행 레이어의 '태그 입력칸'에 넣을 태그(# 제외) — 본문에는 렌더하지 않는다.
    tags: list[str] = Field(default_factory=list)
    # 대표(썸네일)로 지정할 사진 경로 — 실행기가 저장 직전 '대표' 배지를 클릭해 명시 지정한다.
    # (첫 이미지=대표라는 암묵 규칙은 in-place 삭제·재삽입, 협찬 사진 끌어올림에서 깨진다.)
    rep_image_path: str | None = None


def apply_photo_meta_overrides(plan: PublishPlan, photo_meta: dict) -> None:
    """발행 시점의 ★ 대표·AI 표시 변경을 이미 굳어 있는 플랜에 덧반영한다(제자리 수정).

    플랜은 글감 생성(또는 '받아온 글 가져오기') 시점에 서버에 굳는데, 🎨 AI 썸네일 적용과
    🔁 사진 대체는 그 '뒤'에 일어나는 게 흔하다(외부 모델에 다녀오는 동안 순서가 뒤집힘).
    그대로 발행하면 새 이미지는 본문에 안 들어가고 대표도 옛 사진으로 지정된다. 그래서
    발행 요청에 실려 온 현재 사진 메타로 ① AI 표시 플래그 갱신, ② ★ 사진이 플랜에 없으면
    첫 이미지 자리에 삽입, ③ 대표 지정 경로 교체를 수행한다.
    """
    meta = photo_meta or {}
    ai = {p for p, m in meta.items() if isinstance(m, dict) and m.get("ai_generated")}
    for b in plan.blocks:
        if b.kind == "image" and b.image_path in ai:
            b.ai_generated = True
    thumb = next(
        (p for p, m in meta.items() if isinstance(m, dict) and m.get("thumbnail")), None
    )
    if not thumb:
        return  # ★ 해제만 한 경우는 건드리지 않는다(대표=첫 이미지, 네이버 기본과 동일)
    if all(b.image_path != thumb for b in plan.blocks if b.kind == "image"):
        # ponytail: 드립 줄 아래가 아니라 '첫 이미지 자리'에 삽입 — 대표 지정은 어차피
        # rep_image_path로 명시 클릭이라 정확하고, 위치까지 맞추려면 드립 앵커 재계산이 필요
        first = next(
            (i for i, b in enumerate(plan.blocks) if b.kind == "image"), len(plan.blocks)
        )
        plan.blocks.insert(
            first, PublishBlock(kind="image", image_path=thumb, ai_generated=thumb in ai)
        )
    plan.rep_image_path = thumb


_MEDIA_KINDS = ("image", "video")


def fill_imageless_text(
    blocks: list[PublishBlock], picker: StickerPicker | None, enabled: bool = True
) -> list[PublishBlock]:
    """사진이 앞에 몰려 사진 없이 '글만 있는' 본문 문단에 이모티콘 한 개를 붙여 허전함을 채운다.

    사진 배치를 조화롭게 하는 게 우선이고 사진 3장 연속도 맥락상 괜찮지만, 사진을 앞에서
    다 쓰면 뒤쪽 문단이 텍스트만 남아 밋밋해진다. 앞뒤로 사진/영상이 붙어 있지 않은 본문
    텍스트 블록 끝에 스티커를 하나 얹는다(감정 스티커가 문단 끝에 붙는 것과 같은 자연스러움).

    - 첫 사진보다 앞(대제목·해시태그·인트로 등 헤더)은 건드리지 않는다.
    - 앞이나 뒤가 사진/영상인 문단은 이미 사진과 어울려 있으니 넘어간다.
    - 이미 스티커가 붙은 문단(감정 스티커 등)에는 겹쳐 넣지 않고, 연속으로 붙는 것도 피한다.
    - picker가 없거나(스티커 미설정) 사진이 하나도 없는 글이면 아무것도 하지 않는다.
    """
    if not enabled or picker is None:
        return blocks
    first_media = next((i for i, b in enumerate(blocks) if b.kind in _MEDIA_KINDS), None)
    if first_media is None:  # 사진이 아예 없는 글은 대상 아님
        return blocks
    n = len(blocks)
    out: list[PublishBlock] = []
    skip_next = False  # 직전 문단 뒤에 막 넣었으면 이번 문단은 건너뛰어 과밀 방지
    for i, b in enumerate(blocks):
        out.append(b)
        prev_kind = blocks[i - 1].kind if i > 0 else None
        next_kind = blocks[i + 1].kind if i + 1 < n else None
        bare = (
            b.kind == "text"
            and i > first_media  # 헤더(첫 사진 앞)는 제외
            and prev_kind not in _MEDIA_KINDS
            and next_kind not in _MEDIA_KINDS
            and prev_kind != "sticker"
            and next_kind != "sticker"
        )
        if not bare:
            skip_next = False
            continue
        if skip_next:
            skip_next = False
            continue
        chosen = picker.pick("")
        if chosen:
            out.append(
                PublishBlock(
                    kind="sticker", sticker_pack=chosen.pack, sticker_index=chosen.index,
                    sticker_kind=chosen.kind,
                )
            )
            skip_next = True
    return out


def build_publish_plan(
    draft: DraftResult,
    photos: list[PhotoItem] | None = None,
    picker: StickerPicker | None = None,
    divider_variant: int = 1,
    quote_variant_default: int = 1,
    structure_styles: StructureStyles | None = None,
    place_query: str | None = None,
    place_address: str | None = None,
    sponsor: bool = False,
    sponsor_links: list[str] | None = None,
    product_links: list[str] | None = None,
    sponsor_sticker: str = "",
    sticker_catalog=None,
    inplace: bool = False,
    bare_text_sticker: bool = False,
) -> PublishPlan:
    """초안 → 게시 플랜 (줄 단위 마커 파싱).

    inplace=True(임시저장 글 in-place 편집)면 사진은 이미 글에 박혀 있어 '위치를 옮기는'
    후처리(남은 사진 분산·협찬 사진 끌어올림·대표 썸네일 끌어올림)를 모두 건너뛴다.
    이미지 블록은 마커 순서 그대로 남아 실행기가 image_path로 원본 사진 위치에 매핑한다.

    첫 비어있지 않은 줄=제목. 본문에서 마커를 블록으로 분리:
    - [사진]/[사진:라벨] → 이미지(라벨 같은 사진 우선, 없으면 남은 순서대로)
    - [구분선]    → 구분선
    - [인용구]…[/인용구] → 인용 블록
    - [스티커:상황] → picker가 (팩,인덱스)로 해석한 스티커(picker 없거나 미해석이면 무시)
    그 외 줄은 텍스트 문단으로 누적. 강조 span은 해당 텍스트 블록에 배분.

    sponsor=True면 structure_styles.sponsor_sticker(쿠팡파트너스 고지 스티커)를 본문 맨 위
    블록으로 고정 삽입한다. 지정값은 '태그 이름'(예: 파트너스) 또는 'pack:index'. 태그면
    sticker_catalog에서 찾아 해석한다(카탈로그 없으면 pack:index만 인식). 못 찾으면 건너뜀.
    sponsor_links를 주면 그 URL들을 링크 카드로 본문 텍스트 사이 고른 위치에 분산 삽입한다.
    product_links(상품 리뷰의 필수 링크)도 같은 방식으로 카드 삽입한다(협찬과 무관, 각 한 번씩).

    bare_text_sticker(기본 꺼짐)를 켜면 사진이 앞에 몰려 뒤쪽이 텍스트만 남은 문단(앞뒤로
    사진 없는 본문 블록)에 이모티콘을 하나씩 붙여 허전함을 채운다(fill_imageless_text).
    기계적 삽입이라 기본은 끄고, 사진 분산은 초안 프롬프트 안내에 맡긴다(prompt.py 사진 구성).
    """
    photos = list(photos or [])
    lines = draft.text.split("\n")

    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip():
            title = line.strip()
            body_start = i + 1
            break
    body_lines = lines[body_start:]

    blocks: list[PublishBlock] = []
    text_buf: list[str] = []
    quote_buf: list[str] = []
    table_buf: list[str] = []
    in_quote = False
    quote_variant = 1
    used = [False] * len(photos)  # 사진별 사용 여부(순서 아닌 라벨로 매칭)
    first_body_seen = False  # 대제목은 본문 첫 줄에만 부여
    header_ids: set[int] = set()  # 헤더(대제목·드립 줄) 텍스트 블록 — 남은 미디어·링크 분산에서 제외
    drip_ids: set[int] = set()  # 드립 한 줄 블록 — 대표사진을 그 바로 아래로 끌어올리는 앵커
    tags: list[str] = []  # 헤더 태그줄에서 수집한 발행 태그(네이버 태그칸 입력용)

    def take_photo(label: str | None, media_kind: str = "image") -> PhotoItem | None:
        """media_kind(사진/영상)가 같은 것 중 라벨이 같은 안 쓴 것 우선 → 캡션 매칭 → 순서대로.

        캡션 매칭: 같은 라벨 사진이 여러 장일 때 LLM이 특정 사진을 짚도록 마커에
        캡션([사진:치즈카츠 클로즈업])을 쓸 수 있다 — '사진 내용' 목록의 설명과
        부분 일치하면 그 사진을 집는다(라벨 오타·의역으로 임의 사진이 잡히는 것 완화)."""
        if label:
            for i, ph in enumerate(photos):
                if not used[i] and ph.media_kind == media_kind and ph.label == label:
                    used[i] = True
                    return ph
            if len(label) >= 2:
                for i, ph in enumerate(photos):
                    cap = (ph.caption or "").strip()
                    if (
                        not used[i]
                        and ph.media_kind == media_kind
                        and cap
                        and (label in cap or cap in label)
                    ):
                        used[i] = True
                        return ph
        for i, ph in enumerate(photos):
            if not used[i] and ph.media_kind == media_kind:
                used[i] = True
                return ph
        return None

    def media_block(ph: PhotoItem) -> PublishBlock:
        """PhotoItem → 이미지/영상 블록(media_kind로 kind 결정, 경로·라벨 필드는 공용)."""
        kind = "video" if ph.media_kind == "video" else "image"
        return PublishBlock(
            kind=kind, image_path=ph.path, image_label=ph.caption or ph.label,
            ai_generated=ph.ai_generated,
        )

    def flush_text():
        text = "\n".join(text_buf).strip()
        text_buf.clear()
        if text:
            spans = [e for e in draft.emphases if e.text and e.text in text]
            blocks.append(PublishBlock(kind="text", text=text, emphases=spans, align="center"))

    def flush_table():
        buf = table_buf[:]
        table_buf.clear()
        if not buf:
            return
        rows = parse_md_table(buf)
        if rows:  # 유효 표 → 표 블록. 실행기가 합성 paste로 네이티브 SE 표로 변환
            flush_text()  # 표 직전 텍스트를 별도 문단으로 끊고
            blocks.append(PublishBlock(kind="table", table_rows=rows))
        else:  # 구분행 없는 가짜 표 → 그냥 본문 텍스트로 되돌림(내용 소실 방지)
            text_buf.extend(buf)

    def consume_tag_line(s: str):
        """헤더의 해시태그 줄 → 본문에 렌더하지 않고 발행 태그칸용 tags로 수집.

        본문의 해시태그 자리는 프롬프트가 '드립 한 줄'로 대체했고, 태그는 네이버
        발행 레이어의 태그 입력칸으로 들어간다. 태그줄 자리에는 기존처럼 헤더
        구분선만 남긴다(structure_styles의 hashtags.divider)."""
        for t in s.split():
            t = t.lstrip("#").strip()
            if t and t not in tags:
                tags.append(t)
        # 태그줄 직전 텍스트(대제목·드립 줄 등 헤더)는 남은 미디어·링크 분산 앵커에서
        # 제외 — 안 그러면 첫 leftover가 헤더와 구분선 사이에 꽂힌다(과거 배치 사고).
        if blocks and blocks[-1].kind == "text":
            header_ids.add(id(blocks[-1]))
        if structure_styles is None:
            return
        # 드립 한 줄(태그줄 바로 위, 대제목 바로 아래) — 예전 해시태그 줄의 서식(작은
        # 파란 글씨·가운데)을 그대로 입힌다. 태그줄이 헤더 밖(본문 뒤)에 온 경우를
        # 걸러내려고 '직전 텍스트 블록이 대제목(헤더)'일 때만 적용한다. 사이에 낀
        # 마커 블록(협찬 사진 등)은 무시한다(드립 경로와 동일).
        drip = blocks[-1] if blocks and blocks[-1].kind == "text" else None
        prev_is_header = next(
            (id(b) in header_ids for b in blocks[:-1][::-1] if b.kind == "text"), False
        )
        if drip is not None and prev_is_header:
            st = structure_styles.hashtags
            drip.align = st.align or drip.align
            drip_lines = [ln.strip() for ln in drip.text.split("\n") if ln.strip()]
            if len(drip_lines) == 2:  # 두 줄 드립은 한 줄로 — 작은 글씨라 줄 나눌 이유 없음
                drip_lines = [" ".join(drip_lines)]
                drip.text = drip_lines[0]
            drip.emphases = [
                StyledSpan(text=ln, preset_id=None, style=st.to_style()) for ln in drip_lines
            ]
            drip_ids.add(id(drip))
        prev_is_divider = bool(blocks) and blocks[-1].kind == "divider"
        div = structure_styles.hashtags.divider
        if div and div in DIVIDER_META and not prev_is_divider:
            blocks.append(PublishBlock(kind="divider", variant=DIVIDER_META[div][0], align="center"))

    def emit_drip_block(s: str):
        """드립 한 줄(대제목 아래) — 태그줄이 없어도 예전 해시태그 줄 서식(작은 파란 글씨·
        가운데)과 헤더 구분선을 입힌다(리스타일 등). 뒤에 태그줄이 오면 consume_tag_line은
        직전 블록이 구분선이라 스타일·구분선을 중복 적용하지 않는다. 모델이 두 줄로 쪼갠
        드립도 호출부에서 한 줄로 합쳐 들어온다(작은 글씨라 줄 나눌 이유 없음)."""
        st = structure_styles.hashtags
        blocks.append(
            PublishBlock(
                kind="text", text=s, align=st.align or "center",
                emphases=[StyledSpan(text=s, preset_id=None, style=st.to_style())],
            )
        )
        header_ids.add(id(blocks[-1]))
        drip_ids.add(id(blocks[-1]))
        div = st.divider
        if div and div in DIVIDER_META:
            blocks.append(PublishBlock(kind="divider", variant=DIVIDER_META[div][0], align="center"))

    def classify_role(s: str) -> str | None:
        """구조별 서식이 켜져 있을 때, 이 줄이 어떤 구조 요소인지 판정(없으면 None)."""
        if structure_styles is None:
            return None
        if _SUBHEADING_RE.match(s):
            return "subheading"
        if not first_body_seen and 0 < len(s) <= 40:
            return "big_title"  # 본문 첫 줄의 짧은 콘셉트 한 줄
        return None

    def emit_role_block(role: str, s: str):
        """구조 요소 한 줄을 서식 span이 박힌 텍스트 블록으로 추가."""
        ss = structure_styles
        if role == "subheading":
            # 소제목("1. ...")은 인용구 '밑줄형'으로 렌더한다. 텍스트로 "1. "을 본문에 치면
            # 에디터가 자동 번호목록을 켜서 뒤 문단까지 번호가 번지는데, 별도 인용구 블록으로
            # 빼면 그 누수가 사라지고 소제목도 또렷하게 강조된다(variant=밑줄형).
            # 밑줄형은 왼쪽정렬이 기본·고정이라 align은 따로 주지 않는다(중앙정렬 불가).
            blocks.append(
                PublishBlock(kind="quote", text=s, variant=QUOTE_META["quotation_underline"][0])
            )
            return
        role_style = ss.big_title
        # 대제목은 큰 글씨라 길면 균형 있게 두 줄로 미리 접는다. \n을 넣으면 실행기가
        # 문단(Enter) 두 개로 치므로, 큰 글씨가 두 줄 모두 먹도록 span도 줄별로 나눈다
        # (한 span이 \n을 넘어가면 드래그 선택이 두 문단에 걸쳐 실패할 수 있음).
        wrapped = balance_wrap(s)
        spans = [
            StyledSpan(text=ln, preset_id=None, style=role_style.to_style())
            for ln in wrapped.split("\n")
        ]
        blocks.append(
            PublishBlock(
                kind="text", text=wrapped, emphases=spans, align=role_style.align or "center"
            )
        )
        header_ids.add(id(blocks[-1]))

    # 드립 한 줄 위치(대제목 아래 1~2줄 문단) — 태그줄 없는 초안(리스타일)에서도 서식 적용
    drip_idxs = _find_drip_lines(body_lines) if structure_styles is not None else []
    drip_emitted = False

    for li, line in enumerate(body_lines):
        s = line.strip()
        if in_quote:
            if s == QUOTE_CLOSE:
                in_quote = False
                qtext = "\n".join(quote_buf).strip()
                quote_buf.clear()
                if qtext:
                    blocks.append(
                        PublishBlock(
                            kind="quote",
                            text=qtext,
                            variant=quote_variant,
                            align=quote_align(quote_variant),
                        )
                    )
            else:
                quote_buf.append(line)
            continue
        # 마크다운 표 행 누적 — 연속된 `| … |` 줄을 모아 표 블록으로. 표가 아닌 줄이 오면 flush.
        if _TABLE_ROW_RE.match(s):
            table_buf.append(s)
            first_body_seen = True
            continue
        if table_buf:
            flush_table()
        div_m = _DIVIDER_RE.match(s)
        quote_m = _QUOTE_OPEN_RE.match(s)
        sticker_m = _STICKER_RE.match(s)
        photo_m = _PHOTO_RE.match(s)
        video_m = _VIDEO_RE.match(s)
        place_m = _PLACE_RE.match(s)
        if place_m:
            flush_text()
            q = (place_m.group(1) or place_query or "").strip()
            addr = place_address
            if q and _PLACE_URL_RE.search(q):
                # URL이 그대로 오면 SE 검색이 0건이라 가게명·주소로 해석. 실패하면
                # 수집된 이름 폴백, 그것도 없으면 URL 그대로 두어 에디터 단계에서
                # '지도 자동 삽입 실패' 경고로 드러나게 한다(조용히 사라지지 않게).
                resolved = _resolve_place_marker_url(q)
                if resolved:
                    q, addr = resolved
                elif place_query:
                    q, addr = place_query, place_address
            if not q:
                # 수집 링크 없이 붙여넣어도 [지도]가 조용히 사라지지 않게, 세션에서
                # 마지막으로 수집한 가게 카드로 폴백한다(미리보기에 가게명이 보임).
                # ponytail: 멀티탭에선 마지막 수집이 다른 가게일 수 있음 — 미리보기로 확인
                from autoblog.pipeline import last_cached_place  # 모듈 순환 참조 회피

                card = last_cached_place()
                if card is not None and card.place and card.place.name:
                    q = card.place.name
                    addr = card.place.road_address or card.place.address
            if q:  # 가게명(마커 인자 우선, 없으면 수집된 이름)으로 장소 카드
                blocks.append(PublishBlock(kind="place", text=q, place_address=addr))
            else:
                # 그래도 못 채우면 마커를 본문 텍스트로 남긴다 — 미리보기·에디터에서
                # 눈에 띄어 직접 조치할 수 있게(조용한 소실 방지).
                blocks.append(PublishBlock(kind="text", text=s))
        elif div_m:
            flush_text()
            blocks.append(
                PublishBlock(
                    kind="divider", variant=int(div_m.group(1) or divider_variant), align="center"
                )
            )
        elif sticker_m:
            flush_text()
            chosen = picker.pick(sticker_m.group(1) or "") if picker else None
            if chosen:  # 해석 실패(picker 없음/매칭 없음)면 마커 자체를 버림(본문 누수 방지)
                blocks.append(
                    PublishBlock(
                        kind="sticker", sticker_pack=chosen.pack, sticker_index=chosen.index,
                        sticker_kind=chosen.kind,
                    )
                )
        elif quote_m:
            flush_text()
            in_quote = True
            quote_variant = int(quote_m.group(1) or quote_variant_default)
        elif photo_m:
            flush_text()
            ph = take_photo(photo_m.group(1), media_kind="image")
            if ph is not None:
                blocks.append(media_block(ph))
        elif video_m:
            flush_text()
            ph = take_photo(video_m.group(1), media_kind="video")
            if ph is not None:
                blocks.append(media_block(ph))
        else:
            toks = s.split()
            # 태그줄: 토큰 전부가 #태그일 때만(첫 토큰의 # 누락 허용 — LLM 예시 습관).
            # 본문 단어가 섞인 줄("오늘 #혜화 갔다가 #맛집 발견")은 본문으로 남긴다.
            if _is_hashtag_line(s) and all(t.startswith("#") for t in toks[1:]):
                flush_text()
                consume_tag_line(s)
                # 태그줄은 본문에 렌더되지 않으니 '본문 시작'으로 치지 않는다 — 모델이
                # 태그줄을 대제목보다 위에 쓰면 대제목이 본문 크기로 새던 문제.
                continue
            elif (
                drip_idxs
                and li == drip_idxs[0]
                and next(
                    (id(b) in header_ids for b in reversed(blocks) if b.kind == "text"),
                    False,
                )
            ):
                # 마지막 '텍스트' 블록이 대제목(헤더)일 때만 — 대제목이 서식으로 안 잡힌
                # 초안에선 본문 취급. 사이에 낀 마커 블록(협찬 사진 등)은 무시한다.
                flush_text()
                emit_drip_block(" ".join(body_lines[i].strip() for i in drip_idxs))
                drip_emitted = True
            elif drip_emitted and li in drip_idxs[1:]:
                pass  # 드립 둘째 줄 — 위에서 드립 블록에 이미 포함(미발동 시엔 본문으로)
            else:
                role = classify_role(s)
                if role:
                    flush_text()
                    emit_role_block(role, s)
                else:
                    text_buf.append(line)
            if s:
                first_body_seen = True
    flush_table()
    flush_text()
    if in_quote and quote_buf:  # 닫힘 누락 방어
        blocks.append(
            PublishBlock(kind="quote", text="\n".join(quote_buf).strip(), variant=quote_variant)
        )

    # 구분선이 연달아 붙으면(마커 두 번·자동+마커 겹침 등) 하나로 합친다.
    # 구분선 '분류' 스티커도 구분선으로 취급 — LLM이 [구분선]과 [스티커:구분선…]을 같은
    # 전환점에 겹쳐 emit하면 선이 두 줄이 되므로, 겹칠 땐 스티커 쪽을 남긴다(장식이 더 풍부).
    def _dividerish(b: PublishBlock) -> bool:
        return b.kind == "divider" or (b.kind == "sticker" and b.sticker_kind == "구분선")

    deduped: list[PublishBlock] = []
    for b in blocks:
        if _dividerish(b) and deduped and _dividerish(deduped[-1]):
            if b.kind == "sticker" and deduped[-1].kind == "divider":
                deduped[-1] = b  # 네이티브 구분선을 스티커로 교체
            continue
        deduped.append(b)
    blocks = deduped

    # 마커로 못 채운 남은 미디어(사진·영상): 글 끝에 몰지 않고 본문 텍스트 블록 사이에 고루 분산
    # (업로드한 사진·영상은 모두 본문에 들어가되, 끝에 우르르 붙는 걸 방지)
    # inplace(불러온 글 편집)에선 사진·영상이 이미 글에 박혀 있어 '못 채운 미디어 끌어다 넣기'를
    # 하지 않는다 — 마커 안 단 미디어는 원래 자리에 그대로 두고, 실행기가 텍스트만 끼운다.
    leftover = [ph for i, ph in enumerate(photos) if not used[i]]
    if leftover and not inplace:
        # 헤더(대제목·드립 줄) 블록은 앵커에서 제외 — 안 그러면 첫 leftover가
        # 헤더와 그 뒤 구분선 사이에 꽂힌다(실제 발생했던 배치 사고).
        text_pos = [
            i for i, b in enumerate(blocks) if b.kind == "text" and id(b) not in header_ids
        ]
        # 바로 뒤에 사진/영상이 없는 문단만 후보로 — 마커 사진과 그 아래 설명 문단
        # 사이에 남은 사진이 끼어들지 않게(사진→설명 짝 보존), 사진 연속 구간도 안 만든다.
        candidates = [
            i for i in text_pos
            if i + 1 >= len(blocks) or blocks[i + 1].kind not in _MEDIA_KINDS
        ] or text_pos
        if not candidates:  # 본문 텍스트가 없으면 그대로 끝에
            for ph in leftover:
                blocks.append(media_block(ph))
        else:
            after: dict[int, list[PhotoItem]] = {}
            t = len(candidates)
            for k, ph in enumerate(leftover):
                anchor = candidates[(k * t) // len(leftover)]
                after.setdefault(anchor, []).append(ph)
            spread: list[PublishBlock] = []
            for i, b in enumerate(blocks):
                spread.append(b)
                for ph in after.get(i, []):
                    spread.append(media_block(ph))
            blocks = spread

    # 협찬 링크 카드 — 글 끝에 몰지 않고 본문 텍스트 사이 고른 '중간중간' 위치에 분산.
    # 텍스트 블록이 t개일 때 링크 i는 (i+1)/(n+1) 지점 텍스트 뒤에 — 맨 앞/맨 끝을 피해 가운데로.
    links = [u.strip() for u in [*(sponsor_links or []), *(product_links or [])] if u.strip()]
    # 협찬 링크(sponsor_links)는 카드 밑 URL 텍스트 줄을 남겨 체험단 크롤러가 잡게 한다.
    # 단, 쿠팡파트너스는 체험단과 달리 발행글에서 URL 문자열을 크롤링하지 않고
    # 카드 클릭(리다이렉트에 원본 링크 보존)으로 수익이 추적되므로 생링크를 남기지 않는다.
    # 상품리뷰 링크(product_links)는 비협찬이라 지금처럼 깔끔하게(텍스트 줄 제거).
    sponsor_set = {u.strip() for u in (sponsor_links or []) if u.strip()}

    def link_block(url: str) -> PublishBlock:
        keep = url in sponsor_set and not _is_coupang_url(url)
        return PublishBlock(kind="link", link_url=url, keep_url_text=keep)

    if links:
        text_pos = [
            i for i, b in enumerate(blocks) if b.kind == "text" and id(b) not in header_ids
        ]
        if not text_pos:  # 본문 텍스트가 없으면 그대로 끝에
            for url in links:
                blocks.append(link_block(url))
        else:
            t = len(text_pos)
            last = t - 2 if t >= 3 else t - 1  # 텍스트 블록이 3개 이상이면 마지막 문단 뒤는 피함
            after: dict[int, list[str]] = {}
            for k, url in enumerate(links):
                anchor = text_pos[min(last, ((k + 1) * t) // (len(links) + 1))]
                after.setdefault(anchor, []).append(url)
            spread: list[PublishBlock] = []
            for i, b in enumerate(blocks):
                spread.append(b)
                for url in after.get(i, []):
                    spread.append(link_block(url))
            blocks = spread

    # 협찬 고지 스티커 — 본문 맨 위에 고정 삽입(제목 칸과 별개로 본문 첫 블록).
    # 우선순위: 글쓰기 화면에서 고른 sponsor_sticker > structure_styles.yaml 수동 지정 > catalog.sponsor.
    # 지정값이 태그명이면 카탈로그로 해석, 아니면 pack:index로 해석.
    if sponsor:
        spec = sponsor_sticker or ""
        if not spec and structure_styles is not None:
            spec = structure_styles.sponsor_sticker
        if not spec and sticker_catalog is not None:
            spec = getattr(sticker_catalog, "sponsor", "")  # 예전 스티커탭 지정(하위호환)
        ref = None
        if sticker_catalog is not None:
            ref = sticker_catalog.resolve_ref(spec)
        elif structure_styles is not None:
            ref = structure_styles.sponsor_ref()
        if ref:
            blocks.insert(0, PublishBlock(kind="sticker", sticker_pack=ref[0], sticker_index=ref[1]))

    # 협찬 고지 사진 — '협찬' 라벨 사진은 본문 '내용의 가장 맨 위'(인트로·헤더보다 위, 블록 0)로
    # 끌어올리고 가장 작은 크기로 표시한다. 마커([사진:협찬])를 어디에 넣었든, 또 대표 썸네일이
    # 따로 지정됐든 항상 맨 처음에 등장하게 보장한다.
    spon_paths = {ph.path for ph in photos if ph.label == SPONSOR_PHOTO_LABEL}
    spon_blocks = [b for b in blocks if b.kind == "image" and b.image_path in spon_paths]
    for b in spon_blocks:
        b.image_size = "small"  # 협찬 고지 이미지는 가장 작게(경로 무관 — inplace도 적용)
    if spon_blocks and not inplace:  # inplace는 사진 위치를 실행기가 정함(끌어올림만 X)
        ids = {id(b) for b in spon_blocks}
        blocks = spon_blocks + [b for b in blocks if id(b) not in ids]

    # 대표 썸네일 — 지정 사진을 본문 '첫 이미지'로 끌어올린다(네이버 대표 사진=글의 첫 이미지).
    # 마커가 어디에 박히든 썸네일이 가장 먼저 등장하게 하되, 협찬 고지 사진보다는 뒤에 둔다.
    # 헤더에 드립 한 줄이 있으면 대표사진(★ 지정, 없으면 첫 비협찬 이미지)을 드립 바로 아래로
    # 올린다(헤더 직후 히어로 컷 — 유저 선호). 드립이 없는 글은 기존 '첫 이미지' 자리 유지.
    thumb_path = next((ph.path for ph in photos if ph.thumbnail and ph.path not in spon_paths), None)
    if not inplace:  # inplace는 사진 위치를 실행기가 정함(썸네일 끌어올림 X)
        img_idx = [i for i, b in enumerate(blocks) if b.kind == "image" and b.image_path not in spon_paths]
        first = img_idx[0] if img_idx else None
        cur = next((i for i in img_idx if blocks[i].image_path == thumb_path), None)
        drip_i = next((i for i, b in enumerate(blocks) if id(b) in drip_ids), None)
        if drip_i is not None and (cur is not None or first is not None):
            hero = cur if cur is not None else first  # ★ 없으면 첫 비협찬 이미지가 대표
            blocks.insert(drip_i + 1, blocks.pop(hero))
        elif thumb_path and first is not None and cur is not None and cur != first:
            blocks.insert(first, blocks.pop(cur))
    # inplace에서 ★ 썸네일이 마커로 소비되지 않은 경우(초안 작성 뒤 'AI 사진 대체'·AI 썸네일로
    # 새로 추가된 이미지가 대표적) — 남은 미디어 분산을 건너뛰는 inplace 특성상 여기서 블록을
    # 안 만들어 주면 이미지가 통째로 사라지고 대표사진도 다른 사진으로 떨어진다.
    # 첫 이미지 자리(이미지가 없으면 맨 끝)에 삽입해 본문에 들어가고 대표 지정도 되게 한다.
    if thumb_path and inplace and all(
        b.image_path != thumb_path for b in blocks if b.kind == "image"
    ):
        ph = next(ph for ph in photos if ph.path == thumb_path)
        first_img = next((i for i, b in enumerate(blocks) if b.kind == "image"), len(blocks))
        blocks.insert(first_img, media_block(ph))

    # 마지막으로, 사진이 앞에 몰려 사진 없이 글만 남은 뒤쪽 문단에 이모티콘을 채운다
    # (모든 재배치가 끝난 뒤라야 어느 문단에 사진이 붙는지 정확히 판단한다).
    blocks = fill_imageless_text(blocks, picker, enabled=bare_text_sticker)

    # 대표사진 — ★ 지정 사진(협찬 제외), 없으면 첫 비협찬 이미지, 그것도 없으면 첫 이미지.
    # 실행기가 저장 직전 '대표' 배지를 클릭해 지정한다(위치 재배치와 별개의 명시 지정).
    img_paths = [b.image_path for b in blocks if b.kind == "image" and b.image_path]
    rep = (
        (thumb_path if thumb_path in img_paths else None)
        or next((p for p in img_paths if p not in spon_paths), None)
        or (img_paths[0] if img_paths else None)
    )

    return PublishPlan(title=title, blocks=blocks, rep_image_path=rep, tags=tags)
