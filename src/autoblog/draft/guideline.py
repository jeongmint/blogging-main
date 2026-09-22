"""가이드라인 — 선택 옵션 레이어 + 체크리스트 자동 대조 (기획서 §2, §4.1).

체험단 글은 별도 유형이 아니라 맛집/상품 글에 가이드라인을 얹은 것.
입력되면 초안 작성 시 '최우선 제약'으로 적용하고, 생성 후 자동 대조로
반려를 예방한다(킬러 기능).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

# 글자 수 세기는 네이버 카운터(공백 제외) 기준 — 줄 단독 마커는 화면에 안 보이므로 제외한다.
# [사진]/[사진:음식], [지도]/[지도:가게], [스티커:상황], [구분선], [인용구]/[/인용구] 등.
_MARKER_RE = re.compile(r"\[/?(?:사진|지도|스티커|구분선|인용구)(?::[^\]]*)?\]")


def count_chars(text: str) -> int:
    """네이버 글자 수 세기(공백 제외) 기준 순수 텍스트 길이 — 마커·공백·줄바꿈 제외."""
    body = _MARKER_RE.sub("", text)
    return len(re.sub(r"\s", "", body))


class Guidelines(BaseModel):
    """체험단 등 가이드라인 항목 (비어 있으면 무시)."""

    required_keywords: list[str] = Field(default_factory=list)
    required_hashtags: list[str] = Field(default_factory=list)
    emphasis_features: list[str] = Field(default_factory=list)  # 강조할 특징
    forbidden_expressions: list[str] = Field(default_factory=list)  # 금지 표현
    min_chars: int | None = None
    min_photos: int | None = None

    def is_empty(self) -> bool:
        return not any(
            [
                self.required_keywords,
                self.required_hashtags,
                self.emphasis_features,
                self.forbidden_expressions,
                self.min_chars,
                self.min_photos,
            ]
        )

    def as_prompt(self) -> str | None:
        """최우선 제약으로 넣을 가이드라인 지시문."""
        if self.is_empty():
            return None
        lines = ["[가이드라인 — 반드시 지켜야 하는 최우선 제약]"]
        if self.required_keywords:
            lines.append(f"- 필수 키워드(본문에 포함): {', '.join(self.required_keywords)}")
        if self.emphasis_features:
            lines.append(f"- 강조할 특징: {', '.join(self.emphasis_features)}")
        if self.required_hashtags:
            lines.append(f"- 필수 해시태그(끝에): {' '.join(self.required_hashtags)}")
        if self.forbidden_expressions:
            lines.append(f"- 금지 표현(쓰지 말 것): {', '.join(self.forbidden_expressions)}")
        if self.min_chars:
            lines.append(
                f"- 최소 글자 수: 순수 본문 텍스트만 {self.min_chars}자 이상"
                "(네이버 글자 수 세기 프로그램 기준·공백 제외). "
                "엔터(줄바꿈)와 [사진]·[지도]·[스티커]·[구분선]·[인용구] 같은 마커는 글자 수에 포함하지 마세요."
            )
        if self.min_photos:
            lines.append(f"- 사진 최소 {self.min_photos}장(본문에 사진 자리 표시)")
        return "\n".join(lines)


class CheckItem(BaseModel):
    item: str
    ok: bool
    detail: str = ""


def check_guidelines(
    draft: str, guidelines: Guidelines, photo_count: int | None = None
) -> list[CheckItem]:
    """초안을 가이드라인과 자동 대조 → 체크리스트(반려 방지)."""
    results: list[CheckItem] = []
    text = draft
    length = count_chars(draft)

    for kw in guidelines.required_keywords:
        results.append(CheckItem(item=f"키워드 '{kw}'", ok=kw in text))
    for tag in guidelines.required_hashtags:
        results.append(CheckItem(item=f"해시태그 '{tag}'", ok=tag in text))
    for feat in guidelines.emphasis_features:
        results.append(CheckItem(item=f"강조 '{feat}'", ok=feat in text))
    for bad in guidelines.forbidden_expressions:
        present = bad in text
        results.append(
            CheckItem(item=f"금지어 '{bad}' 미포함", ok=not present, detail="발견됨" if present else "")
        )
    if guidelines.min_chars:
        results.append(
            CheckItem(
                item=f"최소 {guidelines.min_chars}자",
                ok=length >= guidelines.min_chars,
                detail=f"현재 {length}자(공백 제외)",
            )
        )
    if guidelines.min_photos is not None and photo_count is not None:
        results.append(
            CheckItem(
                item=f"사진 {guidelines.min_photos}장 이상",
                ok=photo_count >= guidelines.min_photos,
                detail=f"현재 {photo_count}장",
            )
        )
    return results


def check_exposure(draft: str) -> list[CheckItem]:
    """노출 기본기 자동 체크 — 가이드라인 입력과 무관하게 항상 수행.

    기계적으로 검사 가능한 것만: 제목(첫 줄) 길이, 헤더 해시태그 개수.
    대표 검색 키워드는 LLM이 스스로 고르는 값이라 코드가 알 수 없음 —
    키워드 앞배치 검사는 자가 점검(selfcheck)과 required_keywords 입력에 맡긴다.
    """
    lines = [ln.strip() for ln in draft.strip().splitlines()]
    title = next((ln for ln in lines if ln), "")
    n = len(title)
    results = [
        CheckItem(
            item="제목 길이(검색 노출)",
            ok=20 <= n <= 55,
            detail=f"현재 {n}자 — 권장 40~50자(정보+훅 자연 융합, 최대 55자)",
        )
    ]
    n_tags = 0
    for ln in lines:
        toks = ln.split()
        cnt = sum(1 for t in toks if t.startswith("#"))
        if cnt >= 2:
            # 첫 태그만 # 없는 옛 초안도 태그로 인정("혜화맛집 #대학로맛집 …")
            # — 예전 LLM 습관. 지금은 postprocess/plan이 #을 자동 복원한다.
            all_tail_tags = all(t.startswith("#") for t in toks[1:])
            n_tags = len(toks) if (not toks[0].startswith("#") and all_tail_tags) else cnt
            break
    results.append(
        CheckItem(
            item="해시태그 5~10개(발행 태그칸)", ok=5 <= n_tags <= 10, detail=f"현재 {n_tags}개"
        )
    )
    return results
