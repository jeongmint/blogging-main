"""사용자 문체 (기획서 §4.2).

두 입력을 지원하고 조합한다:
- 과거 글 학습: 사용자 블로그 글 2~3개 → LLM이 문체 특징을 추출해 프로파일로 저장.
- 직접 설명: "친근한 반말로, 솔직담백하게" 같은 톤 지시.
프로파일(평소 문체) + 톤 지시(이번 글 조정)를 함께 시스템 프롬프트에 넣는다.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from autoblog.llm import chat


class StyleProfile(BaseModel):
    profile: str | None = None  # 평소 문체(페르소나 학습 결과 또는 어투 프리셋 지시문)
    tone: str | None = None  # 이번 글 톤 지시(직접 설명)
    # 꾸밈 레이어(발랄체 전용): 카오모지·유행어 시드 변주 + !→.ᐟ 후처리 치환을 쓸지.
    # tones.yaml 프리셋 설정에서 오고, 유저 페르소나는 False(학습된 문체 그대로).
    ornaments: bool = False

    def as_prompt(self) -> str | None:
        parts = []
        if self.profile:
            parts.append(f"[평소 문체 특징]\n{self.profile}")
        if self.tone:
            parts.append(f"[이번 글 톤 지시]\n{self.tone}")
        return "\n".join(parts) if parts else None


# 시스템: 역할과 금지선을 못 박는다. 시스템 한 줄로는 '쓰는 방식' 대신 글의
# '내용·소재'를 요약해버리기 쉬우므로, 금지 사항을 강하게 명시한다.
_EXTRACT_SYSTEM = (
    "당신은 한국어 블로그 '문체 분석가'입니다. 입력으로 한 사람이 쓴 글 여러 편을 받습니다.\n"
    "임무는 글이 '무엇에 대한 내용인지'가 아니라, 이 사람이 '어떻게 쓰는지'(문체)를 분석하는 것입니다.\n"
    "절대 금지: 글에 등장한 장소·가게·메뉴·여행지·사건 등 내용/소재를 한 번이라도 언급하면 실패입니다.\n"
    "오직 말투·어미·문장 습관만 기술하세요. 아래 사용자 메시지의 항목 형식을 그대로 채우세요."
)

# 사용자 메시지: 글모음을 구분자로 감싸고, 고정 항목 템플릿을 준다.
# 라벨이 박힌 빈칸을 채우게 하면 모델이 내용 요약으로 새지 않고 문체에 묶인다.
_EXTRACT_TEMPLATE = (
    "- 문장 길이/호흡: \n"
    "- 자주 쓰는 어미·말투: \n"
    "- 존댓말/반말: \n"
    "- 이모지·특수문자·줄임표 사용: \n"
    "- 감탄사·구어체·리듬: \n"
    "- 즐겨 쓰는 표현·말버릇: \n"
    "- 전체 톤 한 줄 요약: "
)


# 정규화용 라벨 목록 — 템플릿에서 그대로 뽑아 형식의 단일 출처를 유지한다.
_LABELS = [ln.strip("- :").strip() for ln in _EXTRACT_TEMPLATE.splitlines()]
_LABEL_RE = re.compile(
    r"^[\s>*#\-·•\d.]*(?:\*\*)?\s*("
    + "|".join(map(re.escape, _LABELS))
    + r")\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.*)$"
)


def normalize_profile(text: str) -> str:
    """LLM 출력의 서식 변주(머리말·볼드·번호·코드펜스)를 '- 라벨: 내용' 형식으로 정돈.

    기본 페르소나(personas.json)와 같은 모양이 되도록, 템플릿 라벨 순서대로 재조립한다.
    라벨이 3개 미만이면 손으로 쓴 자유형 프로파일로 보고 원문을 그대로 돌려준다.
    """
    found: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            current = None  # 빈 줄·펜스에서 섹션 종료 — 맺음말이 마지막 항목에 붙는 것 방지
            continue
        m = _LABEL_RE.match(raw)
        if m:
            current = m.group(1)
            found[current] = [m.group(2).strip()]
        elif current and line:
            found[current].append(line)  # 라벨 답이 여러 줄로 이어진 경우
    if len(found) < 3:
        return text.strip()
    return "\n".join(f"- {lb}: {' '.join(found[lb]).strip()}" for lb in _LABELS if lb in found)


def _extract_user_message(past_posts: list[str]) -> str:
    """글모음을 끼워 넣은 사용자 메시지(분석 지시 + 글 본문)."""
    joined = "\n\n=====(다음 글)=====\n\n".join(p.strip() for p in past_posts if p.strip())
    return (
        "다음은 한 사람이 쓴 블로그 글 모음입니다. 내용은 무시하고 '쓰는 방식'만 보세요.\n\n"
        f"<글모음>\n{joined}\n</글모음>\n\n"
        "아래 형식 그대로, 각 항목을 1~2문장으로 채워 답하세요. 소재·장소·메뉴는 언급 금지.\n\n"
        + _EXTRACT_TEMPLATE
    )


def extract_style_profile(past_posts: list[str], model: str | None = None) -> str:
    """과거 글들 → 문체 특징 텍스트(프로파일). 연동된 LLM으로 바로 분석한다."""
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {"role": "user", "content": _extract_user_message(past_posts)},
    ]
    return normalize_profile(chat(messages, model=model, temperature=0.2).strip())


def build_style_prompt(past_posts: list[str]) -> str:
    """과거 글들 → 아무 챗봇에 그대로 붙여넣을 '문체 분석 프롬프트' 한 덩어리.

    LLM을 호출하지 않는다. extract_style_profile과 같은 지시문(_EXTRACT_SYSTEM +
    템플릿)을 쓰되, 시스템·사용자 메시지를 한 텍스트로 합쳐 반환한다. API 키가 없을 때
    사용자가 ChatGPT·Claude 등에 직접 붙여넣어 문체 분석을 받을 수 있다.
    """
    return (
        f"{_EXTRACT_SYSTEM}\n\n{_extract_user_message(past_posts)}\n\n"
        "출력은 분석 결과만 — 인사말, 작업 설명, 마무리 코멘트 등 다른 말은 일절 쓰지 마."
    )
