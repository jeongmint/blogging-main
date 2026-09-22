"""서식/강조 로직 (기획서 §6.1).

강조 스타일을 두 방식으로 배정한다:
- 순환 풀(돌려쓰기): 여러 스타일을 묶어 핵심 문장마다 번갈아 적용 → 리듬, 단조로움 방지.
  인덱스 순환이라 연속 중복을 자연히 회피한다.
- 고정 매핑(용도별): 특정 의미(가격·가게명 등)엔 항상 같은 스타일 → 일관성.

스타일 출처:
- 파워 단축키(크롬 확장)의 JSON export를 import → 1~24번 프리셋.
- 또는 프로그램 내장 기본 스타일(확장 없이 동작).
"""

from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, Field

from autoblog.config import CONFIG_DIR


class EmphasisStyle(BaseModel):
    """글자색·배경·글꼴·크기 등 강조 스타일 한 개."""

    text_color: str | None = None  # "#E53935"
    background_color: str | None = None
    font_family: str | None = None
    font_size: str | None = None  # "16" 또는 "16px"
    bold: bool = False

    def is_empty(self) -> bool:
        return not any(
            [self.text_color, self.background_color, self.font_family, self.font_size, self.bold]
        )


# 파워 단축키 export에서 쓰일 법한 키 별칭(형식 변동 흡수)
_TEXT_KEYS = ("textColor", "text_color", "color", "fontColor")
_BG_KEYS = ("backgroundColor", "background_color", "bgColor", "bg")
_FONT_KEYS = ("fontFamily", "font_family", "font")
_SIZE_KEYS = ("fontSize", "font_size", "size")


def _first(d: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = d.get(k)
        if v:
            return str(v)
    return None


def parse_style(entry: dict) -> EmphasisStyle:
    """파워 단축키 항목 dict → EmphasisStyle (키 이름 변동에 관대)."""
    return EmphasisStyle(
        text_color=_first(entry, _TEXT_KEYS),
        background_color=_first(entry, _BG_KEYS),
        font_family=_first(entry, _FONT_KEYS),
        font_size=_first(entry, _SIZE_KEYS),
        bold=bool(entry.get("bold") or entry.get("fontWeight") == "bold"),
    )


def _is_flat_export(data) -> bool:
    """실제 파워 단축키 export(평면 suffix 형식)인지 판별."""
    return isinstance(data, dict) and any(
        k in data for k in ("hasInitialized", "textColor1", "actions1", "formatActions1")
    )


def _load_flat(data: dict, slots: int = 24) -> dict[int, EmphasisStyle]:
    """평면 형식(textColor1, actions1, editorMode1 …) → {번호: EmphasisStyle}.

    각 단축키의 활성 속성은 editorMode에 따라 formatActions/actions로 결정한다.
    값이 있어도 actions에 없으면 미적용(사용자가 끈 속성). insert 모드(인용/구분선)는 제외.
    """
    result: dict[int, EmphasisStyle] = {}
    for n in range(1, slots + 1):
        mode = data.get(f"editorMode{n}", "format")
        if mode == "insert":
            continue  # 삽입형(인용/구분선)은 텍스트 강조가 아님
        actions = set(data.get(f"formatActions{n}") or data.get(f"actions{n}") or [])
        size = data.get(f"fontSize{n}")
        style = EmphasisStyle(
            text_color=data.get(f"textColor{n}") if "textColor" in actions else None,
            background_color=(data.get(f"backgroundColor{n}") or None)
            if "backgroundColor" in actions
            else None,
            font_family=data.get(f"fontFamily{n}") if "fontFamily" in actions else None,
            font_size=str(size) if "fontSize" in actions and size else None,
        )
        if not style.is_empty():
            result[n] = style
    return result


def load_power_shortcuts(data) -> dict[int, EmphasisStyle]:
    """파워 단축키 JSON(export) → {단축키번호: EmphasisStyle}.

    실제 export는 평면 suffix 형식(textColor1, actions1, editorMode1 …).
    호환을 위해 list([{...}]) / dict({"1": {...}} / {"shortcuts": [...]}) 형식도 수용.
    """
    if _is_flat_export(data):
        return _load_flat(data)

    items: dict[int, dict] = {}
    if isinstance(data, dict) and "shortcuts" in data:
        data = data["shortcuts"]
    if isinstance(data, list):
        for i, entry in enumerate(data, start=1):
            if isinstance(entry, dict):
                num = int(entry.get("number") or entry.get("index") or i)
                items[num] = entry
    elif isinstance(data, dict):
        for k, entry in data.items():
            if isinstance(entry, dict) and str(k).isdigit():
                items[int(k)] = entry
    return {num: parse_style(entry) for num, entry in items.items()}


_POWER_SHORTCUTS_PATH = CONFIG_DIR / "power_shortcuts.json"


def load_default_power_shortcuts(path=None) -> dict[int, EmphasisStyle] | None:
    """프로젝트의 파워 단축키 프리셋(config/power_shortcuts.json) 로드 → 번호별 스타일.

    유저가 네이버 '파워 단축키' 확장에서 export한 프리셋. 있으면 강조색의 실제 색·폰트가
    이 프리셋으로 결정된다(emphasis.yaml의 번호가 이 색을 가리킴). 없으면 None → 내장 기본.
    """
    import json

    path = path or _POWER_SHORTCUTS_PATH
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except FileNotFoundError:
        return None
    return load_power_shortcuts(data) or None


# 확장 프로그램 없이 동작하는 내장 기본 스타일
DEFAULT_STYLES: dict[int, EmphasisStyle] = {
    1: EmphasisStyle(text_color="#E53935"),  # 빨강
    2: EmphasisStyle(text_color="#1E88E5"),  # 파랑
    3: EmphasisStyle(background_color="#FFF59D"),  # 노란 형광
    4: EmphasisStyle(text_color="#43A047", bold=True),  # 초록 볼드
    5: EmphasisStyle(background_color="#FFCDD2"),  # 분홍 배경
    6: EmphasisStyle(text_color="#000000", bold=True),  # 검정 볼드
    7: EmphasisStyle(text_color="#FB8C00", bold=True),  # 주황 볼드(가격용)
}


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    """'#eb7d7d' / 'eb7d7d' → (235,125,125). 형식 불량이면 None."""
    if not value:
        return None
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        return None
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except ValueError:
        return None


def nearest_palette_color(target: str, palette: list[str]) -> str | None:
    """target hex에 색거리(제곱합)상 가장 가까운 팔레트 색을 반환.

    네이티브 팔레트는 고정 프리셋만 있어, 커스텀 색을 근사 매핑한다.
    """
    tgt = _hex_to_rgb(target)
    if tgt is None or not palette:
        return None
    best, best_d = None, None
    for cand in palette:
        rgb = _hex_to_rgb(cand)
        if rgb is None:
            continue
        d = sum((a - b) ** 2 for a, b in zip(tgt, rgb))
        if best_d is None or d < best_d:
            best, best_d = cand, d
    return best


class CyclingPool:
    """순환 풀 — preset_ids를 순서대로 돌려쓰며 연속 중복을 회피."""

    def __init__(self, preset_ids: list[int]):
        self.preset_ids = list(preset_ids)
        self._idx = 0
        self._last: int | None = None

    def next(self) -> int | None:
        if not self.preset_ids:
            return None
        pid = self.preset_ids[self._idx % len(self.preset_ids)]
        self._idx += 1
        # 풀 크기가 2 이상이면 인덱스 순환만으로 연속 중복이 없지만,
        # 직전과 같으면(중복 풀 등) 한 칸 더 진행해 회피한다.
        if pid == self._last and len(set(self.preset_ids)) > 1:
            pid = self.preset_ids[self._idx % len(self.preset_ids)]
            self._idx += 1
        self._last = pid
        return pid


class EmphasisConfig(BaseModel):
    """강조 배정 규칙 (사용자 입력 가능: config/emphasis.yaml)."""

    cycling_pool: list[int] = Field(default_factory=list)  # 일반·긍정 강조 순환 풀 예: [1, 3, 5]
    negative_pool: list[int] = Field(default_factory=list)  # 부정·주의 전용 순환 풀 예: [9, 16, 24]
    fixed_map: dict[str, int] = Field(default_factory=dict)  # 예: {"price": 7, "name": 4}
    # role(강조색)별 용도 설명 — (레거시) 역할 기반 모델에서만 사용.
    role_desc: dict[str, str] = Field(default_factory=dict)  # 예: {"price": "가격·할인율", ...}
    # 프리셋(강조색)마다 태그(용도) — UI(서식 탭)에서 색마다 직접 입력. 이게 있으면 이게 우선.
    # 같은 태그를 여러 색에 주면 그 색들이 자동 순환(단조로움 방지). LLM은 <<태그:어구>>로 고른다.
    preset_tags: dict[int, str] = Field(default_factory=dict)  # 예: {7: "좋았던 점", 8: "좋았던 점", 20: "가격"}
    # 색(프리셋ID)마다 글자색·배경·굵게·폰트·크기를 UI(서식 탭)에서 직접 편집. 있으면 파워 단축키/내장보다 우선.
    styles: dict[int, EmphasisStyle] = Field(default_factory=dict)
    max_per_paragraph: int | None = None  # (옵션) 문단당 강조 개수 상한
    min_per_paragraph: int | None = None  # (옵션) 문단당 강조 개수 하한 — 프롬프트 지시로만 강제(후처리는 못 늘림)
    min_sentence_gap: int | None = None  # (옵션) 강조 간 최소 문장 간격

    def tag_pools(self) -> dict[str, list[int]]:
        """효과적인 '태그 → 프리셋ID 목록'. preset_tags가 있으면 그대로(입력 순서 유지),
        없으면 레거시(cycling_pool/negative_pool/fixed_map)에서 파생(과거 동작 유지)."""
        if self.preset_tags:
            pools: dict[str, list[int]] = {}
            for pid, tag in self.preset_tags.items():
                t = (tag or "").strip()
                if t:
                    pools.setdefault(t, []).append(int(pid))
            return pools
        pools = {}
        if self.cycling_pool:
            pools["cycle"] = list(self.cycling_pool)
        if self.negative_pool:
            pools["neg"] = list(self.negative_pool)
        for role, pid in (self.fixed_map or {}).items():
            pools.setdefault(role, []).append(pid)
        return pools

    def default_tag(self) -> str | None:
        """LLM이 목록 밖 태그를 냈을 때 폴백할 기본 태그 — 색이 가장 많은(일반·범용) 태그."""
        pools = self.tag_pools()
        return max(pools, key=lambda t: len(pools[t])) if pools else None


# 부정·주의(단점·웨이팅·아쉬운 점 등) 의미의 role 이름 — negative_pool로 배정.
# fixed_map에 같은 키가 있으면 그쪽이 우선한다(사용자 명시 오버라이드).
NEGATIVE_ROLES = frozenset({"neg", "negative", "warn", "caution"})


_EMPHASIS_CONFIG_PATH = CONFIG_DIR / "emphasis.yaml"


def load_emphasis_config(path=None) -> EmphasisConfig:
    """강조 설정 로드(사용자 편집 파일). 없으면 빈 기본값."""
    path = path or _EMPHASIS_CONFIG_PATH
    try:
        data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except FileNotFoundError:
        return EmphasisConfig()
    return EmphasisConfig(**data)


# 초안 강조 마킹: <<태그:강조할 텍스트>>  (예: <<가격:13,000원>>, <<좋았던 점:정말 좋았어요>>)
# 레거시(역할 기반) 설정에서 역할 키를 사람이 읽기 좋은 설명으로 보여줄 때 쓰는 라벨.
DEFAULT_ROLE_DESC: dict[str, str] = {
    "cycle": "좋았던 점·핵심 감상·추천 포인트(긍정/일반)",
    "neg": "아쉬웠던 점·단점·주의사항(부정)",
    "price": "가격",
    "name": "가게명/상품명",
}
# 태그 텍스트에 이 키워드가 보이면 더 어울리는 예시 어구를 메뉴에 보여준다.
_EXAMPLE_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("가격", "할인", "원", "price"), "13,000원"),
    (("단점", "주의", "아쉬", "neg", "warn"), "웨이팅이 좀 길었어요"),
    (("가게", "상품", "이름", "name", "메뉴"), "가게이름"),
]


def _tag_example(tag: str) -> str:
    low = (tag or "").casefold()
    for keys, ex in _EXAMPLE_HINTS:
        if any(k in low for k in keys):
            return ex
    return "정말 좋았어요"


# 프롬프트 엔지니어링 노트(태그 모델):
# - 14b급 모델은 "절제하세요" 같은 약한 표현이면 마커를 0개 단다 → "반드시 사용 + 개수 지정 + 예시".
# - 태그가 유저 자유 입력(한글·공백)이라 LLM이 살짝 바꿔 적는 게 최대 리스크 → "글자 그대로 복사"를 최우선 규칙으로.
# - 같은 태그를 여러 번 써도 색이 자동 순환되므로, "반복 회피하지 말라"를 명시(순환 기능을 살림).
def _norm_tag(t: str) -> str:
    """태그 매칭 정규화 — 공백 제거 + 소문자화. LLM이 띄어쓰기·대소문자를 살짝 다르게 내도 매칭."""
    return re.sub(r"\s+", "", t or "").casefold()


# 강조 갈래(라벨) — 알아듣기 좋은 이름 + 설명. 서식 탭 드롭다운이 이 목록을 보여주고,
# 색마다 한 갈래를 고른다. LLM은 <<갈래:어구>>로 어구 성격에 맞는 갈래를 골라 쓴다.
# 사용자가 다른 이름을 preset_tags에 쓰면 그 이름도 갈래로 인정(설명은 이름 그대로).
LANE_DESC: dict[str, str] = {
    "강조": "긍정·핵심 — 그 문단에서 가장 인상적이거나 중요한 부분",
    "주의": "팁·알아두기 — 웨이팅·예약·시간대처럼 미리 알면 좋은 정보",
    "부정": "단점·아쉬운 점 — 불만이나 호불호가 갈리는 부분",
}
DEFAULT_LANES: list[str] = ["강조", "주의", "부정"]


def build_emphasis_instruction(config: "EmphasisConfig | None" = None) -> str:
    """강조 지시문 — '판단형'. 역할(가게명·가격) 분류 대신, 문단마다 강조할 핵심을
    LLM이 직접 판단해 << >>로 감싸게 한다. 단, 어구의 성격에 맞는 '갈래'(강조/주의/부정 등)를
    골라 <<갈래:어구>>로 적는다. 색은 갈래 안에서 자동 순환(서식 탭에서 색마다 갈래 지정).

    지시문은 '색이 배정된 갈래'만 메뉴로 보여준다(색 없는 갈래는 LLM이 못 씀)."""
    config = config or EmphasisConfig()
    pools = config.tag_pools()
    lanes = [t for t in pools if pools[t]] or ["강조"]  # 색이 배정된 갈래만
    min_p = config.min_per_paragraph
    max_p = config.max_per_paragraph
    # 분량 안내 — 하한(min) 설정이 있으면 "문단마다 N개 이상"을 명시(강조가 빠진 문단이 없도록).
    if min_p and max_p:
        amount = f"한 문단에 {min_p}~{max_p}군데(문단마다 최소 {min_p}군데는 꼭)"
    elif min_p:
        amount = f"한 문단마다 최소 {min_p}군데 이상(강조가 하나도 없는 문단이 없게)"
    else:
        amount = f"한 문단에 최대 {max_p or 2}군데(강조가 없는 문단도 있을 수 있음)"
    menu = "\n".join(f"  · {t} — {LANE_DESC.get(t, t)}" for t in lanes)
    ex1 = f"<<{lanes[0]}:비주얼이 진짜 미쳤어요>>"
    neg = next((t for t in lanes if t in ("부정", "주의")), None)
    ex2 = f", <<{neg}:웨이팅이 좀 길어요>>" if neg else ""
    only = "/".join(lanes)
    return (
        "[강조 표시] 각 문단에서 독자가 주목했으면 하는 핵심 어구를 네가 직접 판단해 "
        "색을 입힙니다 — 권장이 아니라 반드시 사용하세요.\n"
        f"분량: {amount}, 글 전체에서 5군데 이상.\n"
        "방법: 강조할 짧은 어구(문장 전체 말고 핵심 한두 단어~한 구절)를 골라 << >> 로 감싸고, "
        "콜론 앞에 그 어구의 성격에 맞는 갈래를 적습니다 → <<갈래:어구>>\n"
        "갈래(어구 성격에 맞는 것 하나로):\n"
        f"{menu}\n"
        f"예) {ex1}{ex2}\n"
        "규칙:\n"
        "- 무엇을 강조할지는 네가 판단해. 가게명·가격 같은 '형식'을 따지지 말고, 그 문단에서 가장 "
        "눈에 띄어야 할 부분을 골라(정보 나열보다 감상·포인트·결정적 한마디를 우선).\n"
        f"- 갈래 이름은 위 목록({only})에 있는 것만, 한 글자도 바꾸지 말고 그대로. 목록 밖 이름은 쓰지 마.\n"
        "- 감싼 어구는 본문에 자연스럽게 읽히는 실제 표현이어야 합니다(마커 << >>는 화면엔 안 보이고 색으로 바뀜).\n"
        "- 색은 갈래 안에서 자동으로 번갈아 입혀지니 같은 갈래를 여러 번 써도 됩니다(반복을 일부러 피하지 마세요).\n"
        "- 마커를 겹치거나 중첩하지 말고, 한 마커엔 핵심 어구 하나만."
    )


# 기본(설정 없음) 지시문 — 단순 임포트용. 실제 생성은 build_emphasis_instruction(load_emphasis_config()) 사용.
EMPHASIS_INSTRUCTION = build_emphasis_instruction()

# 꺾쇠는 2개(<<태그:text>>)가 원형이지만, 외부 챗봇이 1개(<태그:text>)로 줄여
# 출력하는 경우가 잦다. 1~2개를 모두 받아 본문 누수를 막는다.
# 태그는 한글·영문·숫자에 더해 공백·중점(·)·슬래시(/)·괄호·하이픈까지 허용(예: "좋았던 점", "가게/상품명").
_MARKUP_RE = re.compile(r"<{1,2}([\w ·/().\-]{1,40}?):(.*?)>{1,2}", re.DOTALL)


def parse_emphasis_markup(text: str) -> tuple[str, list[EmphasisRequest]]:
    """<<role:text>> 마킹 제거 → (깨끗한 본문, 강조 요청 목록).

    각 요청의 start는 깨끗한 본문에서의 시작 위치(밀도 규칙용).
    """
    requests: list[EmphasisRequest] = []
    out: list[str] = []
    idx = 0
    clean_len = 0
    for m in _MARKUP_RE.finditer(text):
        prefix = text[idx : m.start()]
        out.append(prefix)
        clean_len += len(prefix)
        inner = m.group(2)
        requests.append(EmphasisRequest(text=inner, role=m.group(1), start=clean_len))
        out.append(inner)
        clean_len += len(inner)
        idx = m.end()
    out.append(text[idx:])
    return "".join(out), requests


def apply_density(
    clean_text: str, requests: list[EmphasisRequest], config: EmphasisConfig
) -> list[EmphasisRequest]:
    """밀도 규칙 적용 — 문단당 최대 개수 / 강조 간 최소 문장 간격으로 과한 강조 솎기.

    위치(start)가 없는 요청은 그대로 유지한다. 본문 앞쪽(먼저 나온) 강조를 우선 유지.
    """
    max_p = config.max_per_paragraph
    min_gap = config.min_sentence_gap
    if not max_p and not min_gap:
        return requests

    # 문단 경계(빈 줄 기준), 문장 끝 위치(.ᐟ . ! ? 줄바꿈)
    para_bounds: list[tuple[int, int]] = []
    s = 0
    for m in re.finditer(r"\n\s*\n", clean_text):
        para_bounds.append((s, m.start()))
        s = m.end()
    para_bounds.append((s, len(clean_text)))
    sent_ends = [m.end() for m in re.finditer(r"\.ᐟ|[.!?\n]", clean_text)]

    def para_index(pos: int) -> int:
        for i, (a, b) in enumerate(para_bounds):
            if a <= pos <= b:
                return i
        return len(para_bounds) - 1

    def sentence_index(pos: int) -> int:
        return sum(1 for e in sent_ends if e <= pos)

    per_para: dict[int, int] = {}
    last_sent: dict[int, int] = {}
    kept: list[EmphasisRequest] = []
    for r in sorted(requests, key=lambda x: x.start if x.start >= 0 else 0):
        if r.start < 0:
            kept.append(r)
            continue
        pi, si = para_index(r.start), sentence_index(r.start)
        if max_p and per_para.get(pi, 0) >= max_p:
            continue
        if min_gap and pi in last_sent and si - last_sent[pi] < min_gap:
            continue
        kept.append(r)
        per_para[pi] = per_para.get(pi, 0) + 1
        last_sent[pi] = si
    return kept


class EmphasisRequest(BaseModel):
    """초안에서 추출된 강조 대상 한 건.

    role: 'cycle'(핵심 문장·감상 → 순환 풀) 또는 고정 매핑 키('price','name' 등).
    start: 깨끗한 본문에서의 시작 위치(밀도 규칙용). 미상이면 -1.
    """

    text: str
    role: str = "cycle"
    start: int = -1


class StyledSpan(BaseModel):
    text: str
    preset_id: int | None
    style: EmphasisStyle


def assign_emphasis(
    requests: list[EmphasisRequest],
    presets: dict[int, EmphasisStyle],
    config: EmphasisConfig,
) -> list[StyledSpan]:
    """강조 요청 목록 → 스타일 배정.

    각 태그(req.role)는 그 태그가 달린 프리셋 풀에서 번갈아 배정한다.
    - 같은 태그가 여러 색이면 그 색들을 순환(단조로움 방지).
    - 태그가 한 색이면 항상 같은 색(일관성).
    - 목록 밖/오타 태그는 정규화 매칭 후, 그래도 없으면 기본 태그(가장 색 많은 태그) 풀로 폴백.
    레거시 설정(preset_tags 없음)은 cycle/neg/fixed 역할에서 파생된 풀로 동일하게 동작.
    """
    pools_ids = config.tag_pools()
    pools = {tag: CyclingPool(ids) for tag, ids in pools_ids.items()}
    by_norm = {_norm_tag(tag): tag for tag in pools}  # 정규화 키 → 실제 태그
    default = config.default_tag()
    # 태그가 하나도 없으면 전체 프리셋을 한 풀로(강조 자체는 동작하게)
    fallback = None if pools else CyclingPool(sorted(presets))
    out: list[StyledSpan] = []
    for req in requests:
        tag = by_norm.get(_norm_tag(req.role))
        cp = pools.get(tag) if tag else None
        if cp is None and default:
            cp = pools.get(default)
        if cp is None:
            cp = fallback
        pid = cp.next() if cp else None
        style = presets.get(pid, EmphasisStyle()) if pid is not None else EmphasisStyle()
        out.append(StyledSpan(text=req.text, preset_id=pid, style=style))
    return out
