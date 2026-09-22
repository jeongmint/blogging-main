"""내장 어투 프리셋 (config/prompts/tones.yaml).

어투(말투·이모티콘·유행어·특수문자 습관)는 사람마다 달라야 하므로 베이스 프롬프트에
박지 않고 '프리셋'으로 분리한다. common_style.md에는 모든 어투가 공유하는 포맷 규칙
(줄바꿈·대괄호·서술 원칙)만 남고, 어투는 다음 중 하나가 [추가 문체 지시] 블록으로 들어간다:
  - 내장 프리셋(이 모듈) — 발랄 구어체(기본)·차분한 존댓말·친근한 반말·담백 정보형
  - 유저 페르소나(persona.py) — 블로그 글에서 학습하거나 직접 작성한 문체

ornaments(꾸밈 레이어)가 켜진 프리셋(발랄 구어체)에서만 시드 변주 블록(variation.py:
카오모지·유행어)과 후처리 어투 치환(postprocess: !→.ᐟ, ~→-)이 동작한다 — 다른 어투를
골랐는데 기본어투의 꾸밈 요소가 새어 들어가지 않도록.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from autoblog.config import CONFIG_DIR

TONES_PATH = CONFIG_DIR / "prompts" / "tones.yaml"


class TonePreset(BaseModel):
    id: str
    name: str  # UI 표시 이름(예: "발랄 구어체")
    desc: str = ""  # 한 줄 소개(셀렉트 툴팁)
    default: bool = False  # 아무것도 고르지 않았을 때 쓰는 기본 어투
    ornaments: bool = False  # 꾸밈 레이어(카오모지·유행어 변주 + !→.ᐟ 치환) 사용 여부
    prompt: str = ""  # [추가 문체 지시]로 들어가는 어투 지시문


def load_tones(path: str | Path | None = None) -> list[TonePreset]:
    """프리셋 목록 로드. 파일이 없거나 깨지면 빈 목록(초안 생성은 어투 없이 계속)."""
    try:
        data = yaml.safe_load(Path(path or TONES_PATH).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    out: list[TonePreset] = []
    for item in data.get("tones") or []:
        try:
            preset = TonePreset(**item)
        except Exception:  # noqa: BLE001 - 항목 하나가 깨져도 나머지는 살린다
            continue
        if preset.id and preset.prompt.strip():
            out.append(preset)
    return out


def get_tone(tone_id: str, path: str | Path | None = None) -> TonePreset | None:
    """id로 프리셋 찾기(없으면 None)."""
    if not tone_id:
        return None
    return next((t for t in load_tones(path) if t.id == tone_id), None)


def default_tone(path: str | Path | None = None) -> TonePreset | None:
    """기본 어투 프리셋 — default 표시가 있는 것, 없으면 첫 번째."""
    tones = load_tones(path)
    if not tones:
        return None
    return next((t for t in tones if t.default), tones[0])
