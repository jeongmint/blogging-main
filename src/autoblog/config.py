"""설정 로딩 — 모델 프리셋, 환경변수.

모델명은 코드에 박지 않고 config/models.yaml에서 읽는다(기획서 §5).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

# 레포 루트 = 이 파일 기준 ../../.. (src/autoblog/config.py → repo). dev에서만 의미.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _is_frozen() -> bool:
    """PyInstaller 등으로 묶여 실행 중인지."""
    return getattr(sys, "frozen", False)


def _user_data_dir(app: str = "autoblog") -> Path:
    """OS별 쓰기 가능한 유저 데이터 디렉터리."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / app


# 패키징 인지 경로 — 자산(읽기전용)과 유저 데이터(쓰기)를 분리한다.
#  ASSET_DIR     : 앱에 번들되는 읽기전용 자산. frozen이면 PyInstaller 추출 폴더(_MEIPASS).
#  USER_DATA_DIR : 세션/업로드/설정 등 쓰기. frozen이면 OS 유저 데이터 폴더.
# dev(비frozen)에선 둘 다 REPO_ROOT → 기존 경로와 100% 동일(개발 동작 불변).
if _is_frozen():
    ASSET_DIR = Path(getattr(sys, "_MEIPASS", REPO_ROOT))
    USER_DATA_DIR = _user_data_dir()
else:
    ASSET_DIR = REPO_ROOT
    USER_DATA_DIR = REPO_ROOT

CONFIG_DIR = ASSET_DIR / "config"            # 읽기전용 자산(프롬프트/폰트/yaml)
DATA_DIR = USER_DATA_DIR / "data"            # 쓰기: 세션/업로드/스티커
USER_CONFIG_DIR = USER_DATA_DIR / "config"   # 쓰기 설정: ui_prefs/categories
ENV_PATH = USER_DATA_DIR / ".env"

load_dotenv(ENV_PATH)


def provider_for_model(model: str) -> str:
    """모델명으로 제공자 판별. API 전용이라 그 외는 'unknown'(미지원).

    라우팅의 단일 출처 — llm.provider_for도 이걸 쓴다.
    """
    m = (model or "").lower()
    if "/" in m:  # build.nvidia.com 카탈로그 ID(org/model 형식) — 예: openai/gpt-oss-120b
        return "nvidia"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return "unknown"


class ModelPreset(BaseModel):
    label: str
    vision: str
    text: str
    note: str = ""
    concurrent_load: bool = False
    # 텍스트 생성 라우팅(API 전용): "anthropic"(Claude) | "openai"(GPT) | "gemini"(Gemini)
    #                              | "nvidia"(build.nvidia.com 호스티드 — Nemotron/GPT-OSS/Llama)
    provider: str = "gemini"


class Selection(BaseModel):
    """사용자가 실제로 고른 모델 — 텍스트/비전 독립 선택. None이면 프리셋 폴백."""

    text: str | None = None
    vision: str | None = None


class ResolvedModels(BaseModel):
    """현재 실제로 쓰이는 모델 — 선택(selection) 우선, 없으면 기본 프리셋 폴백."""

    text: str
    vision: str
    provider: str  # 텍스트 제공자(model명에서 도출)
    concurrent_load: bool = False
    note: str = ""
    label: str = ""


class CaptionConfig(BaseModel):
    """사진 '✨ AI 자동 추천'(온디맨드 맥락 캡션) 멀티모달 모델. 비우면 자동 추천 비활성."""

    model: str = ""


class ModelsConfig(BaseModel):
    presets: dict[str, ModelPreset]
    default: str
    # 텍스트/비전을 프리셋과 무관하게 독립 선택(설정 시 프리셋보다 우선)
    selection: Selection = Selection()
    # 사진 자동 추천(온디맨드)에 쓰는 멀티모달 모델 — Gemini Flash 권장
    caption: CaptionConfig = CaptionConfig()

    def get(self, tier: str | None = None) -> ModelPreset:
        key = tier or self.default
        if key not in self.presets:
            raise KeyError(f"알 수 없는 프리셋: {key!r} (가능: {list(self.presets)})")
        return self.presets[key]

    def effective(self) -> ResolvedModels:
        """실제 적용되는 텍스트/비전 모델. selection이 있으면 그게 우선."""
        base = self.presets.get(self.default)
        text = self.selection.text or (base.text if base else "")
        vision = self.selection.vision or (base.vision if base else "")
        return ResolvedModels(
            text=text,
            vision=vision,
            provider=provider_for_model(text),
            concurrent_load=base.concurrent_load if base else False,
            note=base.note if base else "",
            label=base.label if base else "",
        )


@lru_cache
def load_models_config(path: Path | None = None) -> ModelsConfig:
    path = path or CONFIG_DIR / "models.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ModelsConfig(**data)


class Env(BaseModel):
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    naver_blog_id: str | None = None  # 게시 대상 블로그 ID (한 번 받아 .env에 저장)
    anthropic_api_key: str | None = None  # Claude API 키(.env ANTHROPIC_API_KEY)
    openai_api_key: str | None = None  # OpenAI(GPT) API 키(.env OPENAI_API_KEY)
    gemini_api_key: str | None = None  # Google Gemini API 키(.env GEMINI_API_KEY)
    nvidia_api_key: str | None = None  # NVIDIA API 키(.env NVIDIA_API_KEY) — AI 썸네일 생성
    # 네이버 검색광고 API(월간 검색량 조회) — searchad.naver.com 도구>API 사용관리에서 발급
    searchad_api_key: str | None = None  # 액세스라이선스(.env NAVER_SEARCHAD_API_KEY)
    searchad_secret: str | None = None  # 비밀키(.env NAVER_SEARCHAD_SECRET)
    searchad_customer_id: str | None = None  # CUSTOMER_ID(.env NAVER_SEARCHAD_CUSTOMER_ID)

    @property
    def has_naver_api(self) -> bool:
        return bool(self.naver_client_id and self.naver_client_secret)

    @property
    def has_searchad(self) -> bool:
        return bool(self.searchad_api_key and self.searchad_secret and self.searchad_customer_id)


@lru_cache
def load_env() -> Env:
    return Env(
        naver_client_id=os.getenv("NAVER_CLIENT_ID"),
        naver_client_secret=os.getenv("NAVER_CLIENT_SECRET"),
        naver_blog_id=os.getenv("NAVER_BLOG_ID"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
        searchad_api_key=os.getenv("NAVER_SEARCHAD_API_KEY"),
        searchad_secret=os.getenv("NAVER_SEARCHAD_SECRET"),
        searchad_customer_id=os.getenv("NAVER_SEARCHAD_CUSTOMER_ID"),
    )


def save_env_value(key: str, value: str, path: Path | None = None) -> None:
    """`.env`에 키=값을 추가/갱신(한 번 받은 설정을 영속화). 캐시도 무효화."""
    path = path or ENV_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    found = False
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value
    load_env.cache_clear()


# 사진 카테고리 기본값(파일 없을 때 폴백). config/photo_categories.yaml 로 덮어쓸 수 있음.
DEFAULT_PHOTO_CATEGORIES: dict[str, list[str]] = {
    "place": ["음식", "메뉴판", "외관", "내부", "영수증", "협찬", "기타"],
    "product": ["언박싱", "제품외관", "영양성분", "제품개봉", "디테일컷", "사용샷", "협찬", "기타"],
}


@lru_cache
def load_photo_categories(path: Path | None = None) -> dict[str, list[str]]:
    """리뷰 타입별 사진 카테고리 프리셋(사용자 편집 파일). 없으면 기본값."""
    path = path or CONFIG_DIR / "photo_categories.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {k: list(v) for k, v in DEFAULT_PHOTO_CATEGORIES.items()}
    out: dict[str, list[str]] = {}
    if isinstance(data, dict):
        for key, vals in data.items():
            if isinstance(vals, list):
                out[str(key)] = [str(v).strip() for v in vals if str(v).strip()]
    return out or {k: list(v) for k, v in DEFAULT_PHOTO_CATEGORIES.items()}
