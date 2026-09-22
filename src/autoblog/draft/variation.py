"""시드 기반 스타일 변주 — 글 간 기계 지문 제거 (config/style_pool.yaml).

전 글이 같은 카오모지 세트·같은 빈도·같은 고정 문구로 수렴하면 블로그 전체(나아가
여러 계정)에서 동일 패턴이 반복돼, 네이버 유사문서·스팸 필터가 보는 '타 문서와
중복된 표현 반복' 신호가 된다. 글 재료(경험 메모+대상 이름)로 결정적 시드를 만들어
풀에서 부분집합·개수 상한·구조 변형을 뽑아 '[이번 글 스타일 변주]' 블록으로 주입한다.
같은 재료면 같은 변주(재생성 재현성·테스트 결정성), 글이 다르면 조합이 달라진다.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

from autoblog.config import CONFIG_DIR, USER_CONFIG_DIR

STYLE_POOL_PATH = CONFIG_DIR / "style_pool.yaml"  # 번들 기본값(읽기전용 자산)
# 웹UI '스타일 풀' 편집 저장본 — 있으면 번들 기본값 대신 이걸 쓴다(전체 교체 방식).
# dev에선 USER_CONFIG_DIR == CONFIG_DIR(레포 config)라, 파일명을 달리해 번들 원본과
# 절대 같은 파일이 되지 않게 한다('기본값 복원'=수정본 삭제가 원본을 지우면 안 됨).
STYLE_POOL_USER_PATH = USER_CONFIG_DIR / "style_pool.user.yaml"

# postprocess의 !/~ 치환이 카오모지를 깨뜨리므로 풀에 못 들어가는 문자.
# (๑´~ˋ๑)만 postprocess가 예외적으로 보호한다.
_TILDE_PROTECTED = "(๑´~ˋ๑)"
_LIST_KEYS = (
    "structure_place",
    "structure_product",
    "quote_position",
    "checklist_heading",
    "summary_connector",
    "pick_transition",
    "title_format",
    "title_hook",
    "concept_tone",
    "intro_opener",
)

# 카테고리 → (표시 이름, 뽑는 개수 범위)
_KAOMOJI_PICKS = [
    ("taste", "맛·만족", (1, 2)),
    ("cheer", "응원·파이팅", (1, 2)),
    ("sad", "아쉬움", (1, 1)),
    ("angry", "불만(필요할 때만)", (0, 1)),
    ("cute", "귀여움·꾸미기", (1, 2)),
]


def _read_pool(path: str | Path) -> dict:
    """yaml 파일 하나 읽기 — 없거나 깨지면 빈 dict(변주는 부가 기능, 크래시 금지)."""
    import yaml

    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def load_style_pool(path: str | Path | None = None) -> dict:
    """변주 풀 로드 — 유저 수정본(STYLE_POOL_USER_PATH)이 있으면 우선, 없으면 번들 기본값."""
    if path is not None:
        return _read_pool(path)
    return _read_pool(STYLE_POOL_USER_PATH) or _read_pool(STYLE_POOL_PATH)


def sanitize_style_pool(pool: dict) -> dict:
    """웹UI 저장용 정규화 — 아는 키만 남기고, 깨진 항목·금지 문자(!/~) 카오모지를 걸러낸다."""
    out: dict = {}
    kao = pool.get("kaomoji")
    if isinstance(kao, dict):
        cats = {}
        for key, items in kao.items():
            if not isinstance(items, list):
                continue
            kept = []
            for it in items:
                s = str(it).strip()
                if not s or "!" in s or ("~" in s and s != _TILDE_PROTECTED):
                    continue  # postprocess 치환에 깨지는 문자는 풀에 못 들어감
                if s not in kept:
                    kept.append(s)
            cats[str(key)] = kept
        out["kaomoji"] = cats
    slang = []
    for s in pool.get("slang") or []:
        if isinstance(s, dict) and all(str(s.get(k, "")).strip() for k in ("expr", "meaning", "example")):
            item = {k: str(s[k]).strip() for k in ("expr", "meaning", "example")}
            item["weight"] = _slang_weight(s)
            slang.append(item)
    out["slang"] = slang
    for key in _LIST_KEYS:
        items = pool.get(key)
        if isinstance(items, list):
            out[key] = [str(i).strip() for i in items if str(i).strip()]
    return out


def _pick(rng: random.Random, items: list, k: int) -> list:
    """중복 없이 k개(부족하면 전부) — 순서도 시드에 따라 섞는다."""
    if not items:
        return []
    k = min(k, len(items))
    return rng.sample(list(items), k)


def _slang_weight(s: dict) -> int:
    """유행어 빈도 가중치(0~3) — 0이면 후보에서 제외, 미지정·깨진 값은 1."""
    try:
        return min(3, max(0, int(s.get("weight", 1))))
    except (TypeError, ValueError):
        return 1


def _weighted_pick(rng: random.Random, pairs: list[tuple[dict, int]], k: int) -> list[dict]:
    """가중치 비례 확률로 중복 없이 k개 뽑기(시드 결정적)."""
    pool = [(item, w) for item, w in pairs if w > 0]
    out: list[dict] = []
    while pool and len(out) < k:
        total = sum(w for _, w in pool)
        r = rng.uniform(0, total)
        acc = 0.0
        for i, (item, w) in enumerate(pool):
            acc += w
            if r <= acc:
                out.append(item)
                pool.pop(i)
                break
        else:  # 부동소수 경계 — 마지막 항목
            out.append(pool.pop()[0])
    return out


def build_variation_block(
    seed_text: str, is_product: bool = False, *, pool: dict | None = None, ornaments: bool = True
) -> str | None:
    """이번 글에만 적용할 스타일 변주 블록(시스템 프롬프트에 덧붙임).

    seed_text가 같으면 항상 같은 블록을 만든다(md5 기반 — 보안 아닌 분산 용도).
    ornaments=False(발랄체가 아닌 어투)면 어투 결합 변주(카오모지·유행어·특수문자 빈도)는
    빼고 구조 변주(섹션 흐름·핵심 한마디 위치 등)만 남긴다 — 구조 다양화(유사문서 방지)는
    모든 어투에 유효하지만, 카오모지·유행어 주입은 유저가 고른 문체를 덮어쓰기 때문.
    """
    pool = pool if pool is not None else load_style_pool()
    if not pool:
        return None
    seed = int(hashlib.md5(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)

    if ornaments:
        lines = [
            "[이번 글 스타일 변주] — 아래는 이번 글에만 적용되는 설정이야. "
            "공통 문체 규칙의 이모티콘·유행어·특수문자(〰️·문장 끝 '-') 목록/빈도와 "
            "다르면 이쪽이 우선해. (글마다 조합이 달라야 여러 글이 똑같아 보이지 않아)"
        ]
    else:
        lines = [
            "[이번 글 스타일 변주] — 아래는 이번 글에만 적용되는 구성 설정이야. "
            "(글마다 구성이 달라야 여러 글이 똑같아 보이지 않아)"
        ]

    # 표정 이모티콘: 카테고리별 부분집합 + 총 개수 상한(0이거나 뽑힌 게 없으면 카오모지 없이).
    # 시드 소비는 ornaments와 무관하게 동일하게 수행 — 같은 재료면 구조 변주도 같게(재현성).
    kaomoji = pool.get("kaomoji") if isinstance(pool.get("kaomoji"), dict) else {}
    face_quota = rng.choice([0, 2, 3, 3, 4, 4, 5, 6])
    picks: list[tuple[str, list[str]]] = []
    for key, label, (lo, hi) in _KAOMOJI_PICKS:
        items = kaomoji.get(key)
        picked = _pick(rng, list(items) if isinstance(items, list) else [], rng.randint(lo, hi))
        if picked:
            picks.append((label, picked))
    if ornaments:
        if face_quota and picks:
            lines.append(
                f"- 표정 이모티콘: 이번 글에서는 아래 것만, 글 전체 {face_quota}개 이내로 써"
                "(어울리는 곳이 없으면 덜 써도 돼):"
            )
            for label, picked in picks:
                lines.append(f"  · {label}: {' '.join(picked)}")
        else:
            lines.append(
                "- 표정 이모티콘: 이번 글에서는 카오모지를 쓰지 마"
                "(강조 이모티콘 ✨⭐️👀😎🥹👍🏻는 공통 규칙대로 사용 가능)."
            )

    # 특수문자 빈도 — 하한 없이 상한만(0이면 금지). 글마다 분포가 달라진다.
    wavy = rng.choice([0, 1, 1, 2, 2, 3])
    dash = rng.choice([0, 1, 2, 2, 3, 3])
    if ornaments:
        lines.append(
            f"- 〰️: 최대 {wavy}회" + ("(이번 글에서는 쓰지 마)" if wavy == 0 else "(안 써도 됨)")
        )
        lines.append(
            f"- 문장 끝 여운 '-': 최대 {dash}회"
            + ("(이번 글에서는 쓰지 마 — 물결표도 '-'로 대체하지 말고 그냥 빼)" if dash == 0 else "")
        )

    # 유행어: 이번 글 후보 2~4개만 노출, 사용 개수 상한(0이면 유행어 없이).
    # 후보는 weight(0~3, 유저가 풀에서 지정)에 비례한 확률로 뽑힌다 — 0은 제외.
    slang_pool = [
        (s, _slang_weight(s))
        for s in (pool.get("slang") or [])
        if isinstance(s, dict) and all(k in s for k in ("expr", "meaning", "example"))
    ]
    slang_pool = [(s, w) for s, w in slang_pool if w > 0]
    slang_quota = rng.choice([0, 1, 1, 2, 2, 3])
    # 후보 추출은 ornaments와 무관하게 수행 — 시드 소비를 동일하게 유지해, 같은 재료면
    # 어투가 달라도 아래 '구조 변주'가 같은 조합으로 나온다(재현성·테스트 결정성).
    candidates = _weighted_pick(rng, slang_pool, rng.randint(2, 4)) if slang_pool else []
    if ornaments:
        if slang_quota and candidates:
            lines.append(
                f"- 유행어: 아래 후보 중에서만, 최대 {slang_quota}개"
                "(자연스럽게 녹아들 때만 — 0개여도 됨):"
            )
            for s in candidates:
                lines.append(f"  · \"{s['expr']}\" — {s['meaning']} (예: \"{s['example']}\")")
        else:
            lines.append("- 유행어: 이번 글에서는 유행어·신조어를 쓰지 말고 담백하게 써.")

    # 글 구조 변형
    structures = pool.get("structure_product" if is_product else "structure_place") or []
    if structures:
        lines.append(f"- 섹션 흐름: {rng.choice(structures)} — 재료에 없는 섹션은 건너뛰어.")
    if not is_product:  # '핵심 한마디'는 맛집 구조 전용(상품은 요약 박스가 그 역할)
        quote_positions = pool.get("quote_position") or []
        if quote_positions:
            lines.append(f"- 핵심 한마디 위치: {rng.choice(quote_positions)}")

    if is_product:
        headings = pool.get("checklist_heading") or []
        if headings:
            lines.append(f'- 추천 체크리스트 소제목: "🌟 {rng.choice(headings)}"')
        connectors = pool.get("summary_connector") or []
        if connectors:
            conn = rng.choice(connectors)
            lines.append(f"- 핵심 요약 박스의 소제목-설명 연결 문자: '{conn}'")
    else:
        transitions = pool.get("pick_transition") or []
        if transitions:
            lines.append(
                f'- (여러 곳 소개 글일 때) PICK 리스트 전환 멘트: "{rng.choice(transitions)}" '
                "느낌으로 — 그대로 베끼지 말고 상황에 맞게 바꿔 써."
            )

    # 제목·첫 문장 변주(모든 어투 유지 — 유사문서/도배 방지). 프롬프트는 "형식을 글마다 바꿔"라고만
    # 해서 모델이 매번 같은 패턴으로 굳는다. 여기서 이번 글의 형식을 하나로 못박아
    # 강제한다(정보 키워드를 자연스러운 문장으로 녹여 넣는 원칙은 형식과 무관하게 유지).
    title_formats = pool.get("title_format") or []
    if title_formats:
        lines.append(f"- 검색 제목 형식: 이번 글은 {rng.choice(title_formats)} 형식으로만 써.")
    title_hooks = pool.get("title_hook") or []
    if title_hooks:
        lines.append(
            f"- 제목 훅: 이번 글은 {rng.choice(title_hooks)} 훅 하나를 넣어"
            " — 본문에 실제로 나오는 사실만, 과장·어그로 단어 금지."
        )
    concept_tones = pool.get("concept_tone") or []
    if concept_tones:
        lines.append(f"- 대제목(콘셉트 한 줄) 톤: 이번 글은 {rng.choice(concept_tones)}으로.")
    openers = pool.get("intro_opener") or []
    if openers:
        lines.append(
            f"- 인트로 첫 문장: {rng.choice(openers)}"
            " — 매 글 똑같은 인사말로 시작하지 마."
        )

    return "\n".join(lines)
