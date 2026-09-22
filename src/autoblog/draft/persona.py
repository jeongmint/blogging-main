"""문체 페르소나 저장소 (기획서 §4.2 확장).

특정 블로거의 인기글에서 뽑아낸 '평소 문체 특징'(profile)을 이름표와 함께 저장한다.
글쓰기 화면에서 페르소나를 고르면 그 문체 프로필이 StyleProfile.profile로 들어간다.

이 저장본은 글쓰기에서 '선택했을 때만' 적용되며, 모두가 공유·편집하는 베이스 프롬프트
(config/prompts/default.md)에는 섞이지 않는다 — 한 사람의 페르소나가 베이스 프롬프트
화면에 노출되지 않도록.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from autoblog.config import CONFIG_DIR

PERSONAS_PATH = CONFIG_DIR / "personas.json"


class PersonaSource(BaseModel):
    title: str = ""
    url: str = ""


class Persona(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str  # 표시 이름(예: "내 본캐", "OO님 문체")
    blog: str = ""  # 학습에 쓴 블로그 주소/ID
    profile: str  # 추출한 평소 문체 특징(StyleProfile.profile로 투입)
    sources: list[PersonaSource] = Field(default_factory=list)  # 학습에 쓴 글 제목·링크
    created_at: str = ""

    @property
    def sample_count(self) -> int:
        return len(self.sources)


class _PersonaFile(BaseModel):
    personas: list[Persona] = Field(default_factory=list)


def load_personas() -> list[Persona]:
    """저장된 페르소나 목록(파일 없거나 깨지면 빈 목록)."""
    try:
        data = json.loads(PERSONAS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return _PersonaFile(**data).personas


def get_persona(persona_id: str) -> Persona | None:
    if not persona_id:
        return None
    return next((p for p in load_personas() if p.id == persona_id), None)


def _write(personas: list[Persona]) -> None:
    PERSONAS_PATH.write_text(
        _PersonaFile(personas=personas).model_dump_json(indent=2),
        encoding="utf-8",
    )


def save_persona(persona: Persona) -> Persona:
    """페르소나 추가 또는 갱신(같은 id면 교체). 저장한 페르소나를 반환."""
    if not persona.created_at:
        persona.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    personas = load_personas()
    for i, existing in enumerate(personas):
        if existing.id == persona.id:
            personas[i] = persona
            break
    else:
        personas.append(persona)
    _write(personas)
    return persona


def delete_persona(persona_id: str) -> bool:
    """id로 삭제. 실제로 지웠으면 True."""
    personas = load_personas()
    kept = [p for p in personas if p.id != persona_id]
    if len(kept) == len(personas):
        return False
    _write(kept)
    return True
