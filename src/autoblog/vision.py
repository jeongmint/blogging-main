"""Vision LLM 연동 (기획서 §3.2, §5).

이미지형 상품 상세설명/사진을 Vision 모델(Gemini/NVIDIA API)로 이해해 구조화한다.
일반 OCR(Tesseract) 대신 Vision LLM을 쓰는 이유: 이미지 맥락을 이해해
재질·크기·사용법·주의사항 등으로 정리하기 위함.

API 전용 — Gemini 또는 NVIDIA 호스티드 VLM(qwen3.5 등)을 지원한다(로컬 LLM 미지원).
모델명은 코드에 박지 않고 config/models.yaml(프리셋 vision)에서 읽는다.
세로로 긴 상세 이미지는 조각으로 분할해 OCR 품질을 높인 뒤 결과를 합친다.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from autoblog.collect.fact_card import ProductSpec
from autoblog.config import load_models_config


class VisionUnavailable(RuntimeError):
    """Vision 모델이 연동되지 않았거나(키 미설정/패키지 미설치) 사용할 수 없을 때."""


def default_vision_model() -> str:
    """현재 적용된 vision 모델명(독립 선택 우선)."""
    return load_models_config().effective().vision


def vision_json(prompt: str, images: list[bytes], model: str) -> str:
    """이미지+프롬프트 → 비전 호출(JSON 강제) → 응답 텍스트.

    llm.vision_chat(Gemini/NVIDIA API)을 감싸 비전 호출의 단일 진입점. 키 미설정·패키지
    미설치·미지원 모델 등은 VisionUnavailable로 변환해 호출부 계약을 유지한다.
    """
    from autoblog.llm import LLMUnavailable, vision_chat

    try:
        return vision_chat(prompt, images, model, fmt="json")
    except LLMUnavailable as exc:
        raise VisionUnavailable(str(exc)) from exc


def _split_tall_image(path: str, max_aspect: float = 2.0) -> list[bytes]:
    """세로로 긴 이미지를 가로폭 기준 조각으로 분할 → 각 조각 PNG bytes.

    상세설명 이미지는 보통 매우 길어(세로 수천 px) 모델 입력 해상도에서
    글자가 뭉개진다. height/width > max_aspect면 max_aspect 비율 높이로 자른다.
    """
    from io import BytesIO

    from PIL import Image

    img = Image.open(path).convert("RGB")
    w, h = img.size
    if h <= w * max_aspect:
        buf = BytesIO()
        img.save(buf, format="PNG")
        return [buf.getvalue()]

    tile_h = int(w * max_aspect)
    tiles: list[bytes] = []
    for top in range(0, h, tile_h):
        crop = img.crop((0, top, w, min(top + tile_h, h)))
        buf = BytesIO()
        crop.save(buf, format="PNG")
        tiles.append(buf.getvalue())
    return tiles


class ProductDetail(BaseModel):
    """상세 이미지 Vision 추출 결과."""

    text: str = ""  # 이미지에 적힌 문구 전사(마케팅 카피·후기 포함)
    selling_points: list[str] = []  # 핵심 셀링포인트/특징
    specs: list[ProductSpec] = []  # 재질/크기 등 스펙(있을 때만)


_DETAIL_PROMPT = (
    "이 상품 상세설명 이미지를 분석해 JSON으로만 답하세요. 형식:\n"
    '{"text":"이미지에 적힌 한국어 문구를 빠짐없이 그대로 전사",'
    '"selling_points":["핵심 셀링포인트/특징을 짧게"],'
    '"specs":[{"key":"재질","value":"..."}]}\n'
    "text에는 마케팅 카피·후기·문구를 그대로 옮기고, specs는 재질·크기·구성·사용법·"
    "주의사항·원산지 등 사실 스펙이 명시된 경우만 채우세요. 없으면 빈 배열. 추측 금지."
)


def _detail_prompt(context: str | None) -> str:
    if not context:
        return _DETAIL_PROMPT
    return f"참고 상품명/분류: {context}. 이 맥락에 맞춰 해석하세요.\n" + _DETAIL_PROMPT


def extract_product_detail(
    image_paths: list[str], model: str | None = None, context: str | None = None
) -> ProductDetail:
    """이미지형 상세설명 → 전사 텍스트 + 셀링포인트 + 스펙.

    context: 상품명/카테고리. 모델이 이미지를 오인식하지 않도록 함께 제공한다.
    긴 이미지는 분할해 조각별로 처리하고, 텍스트는 이어붙이고 포인트/스펙은 중복 제거 병합.
    """
    model = model or default_vision_model()
    prompt = _detail_prompt(context)
    texts: list[str] = []
    points: list[str] = []
    specs: dict[str, str] = {}
    for path in image_paths:
        for tile in _split_tall_image(path):
            detail = _parse_detail(vision_json(prompt, [tile], model))
            if detail.text:
                texts.append(detail.text)
            for pt in detail.selling_points:
                if pt and pt not in points:
                    points.append(pt)
            for spec in detail.specs:
                if spec.key not in specs:
                    specs[spec.key] = spec.value
    return ProductDetail(
        text="\n".join(texts),
        selling_points=points,
        specs=[ProductSpec(key=k, value=v) for k, v in specs.items()],
    )


def _parse_detail(content: str) -> ProductDetail:
    """모델 JSON 응답 → ProductDetail(안전 파싱)."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return ProductDetail()
    if not isinstance(data, dict):
        return ProductDetail()
    text = data.get("text")
    points = data.get("selling_points")
    return ProductDetail(
        text=str(text).strip() if isinstance(text, str) else "",
        selling_points=[str(p).strip() for p in points if p] if isinstance(points, list) else [],
        specs=_parse_specs(data.get("specs")),
    )


def _parse_specs(items) -> list[ProductSpec]:
    """specs 배열 → ProductSpec 목록(값이 리스트면 콤마로 합침)."""
    if not isinstance(items, list):
        return []
    out: list[ProductSpec] = []
    for it in items:
        if isinstance(it, dict) and it.get("key") and it.get("value"):
            value = it["value"]
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            out.append(ProductSpec(key=str(it["key"]), value=str(value).strip()))
    return out


def _downscale_image(path: str, max_dim: int = 1024) -> bytes:
    """분류용 축소본 PNG bytes — 긴 변을 max_dim으로 줄여 비전 토큰을 줄인다.

    분류는 '무슨 사진인지'만 알면 되므로 풀해상도가 필요 없다. 큰 사진을 그대로 넣으면
    컨텍스트를 초과(400)하므로 한 장으로 축소해 보낸다(긴 메뉴판도 한 장으로 충분).
    """
    from io import BytesIO

    from PIL import Image

    img = Image.open(path).convert("RGB")
    img.thumbnail((max_dim, max_dim))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def classify_photos(
    image_paths: list[str], model: str | None = None
) -> dict[str, str]:
    """입력 사진 자동 분류 → {이미지경로: 분류라벨}.

    라벨 예: 음식, 메뉴판, 외관, 내부, 영수증, 상품, 기타.
    """
    model = model or default_vision_model()
    labels = ["음식", "메뉴판", "외관", "내부", "영수증", "상품", "기타"]
    prompt = (
        "이 사진을 다음 중 하나로 분류해 JSON으로만 답하세요: "
        f"{', '.join(labels)}. 형식: " + '{"label":"음식"}'
    )
    result: dict[str, str] = {}
    for path in image_paths:
        content = vision_json(prompt, [_downscale_image(path)], model)
        try:
            label = json.loads(content).get("label", "기타")
        except json.JSONDecodeError:
            label = "기타"
        result[path] = label if label in labels else "기타"
    return result


# --- 온디맨드 맥락 캡션 (멀티모달 배치) ----------------------------------------
# 사진 전부 + 메모/메뉴/가게설명을 한 번에 넣어 '데미소스 돈까스'처럼 사람처럼 유추.
# 글 1개당 호출 1번이라 저렴하고, 로컬 분류보다 훨씬 정확하다.

_DEFAULT_CAPTION_LABELS = ["음식", "메뉴판", "외관", "내부", "영수증", "상품", "기타"]


def default_caption_model() -> str:
    """사진 자동 추천에 쓰는 멀티모달 모델명(config/models.yaml caption.model). 비면 빈 문자열."""
    return load_models_config().caption.model


def caption_available() -> bool:
    """자동 추천을 쓸 수 있는지(모델 지정 + 키 존재 여부는 호출 시 검증)."""
    return bool(default_caption_model())


def _caption_prompt(n: int, cats: list[str], context: str, hint: str = "") -> str:
    ctx = (context or "").strip()
    ctx_block = (
        "\n[참고 맥락 — 이 가게/상품의 메모·메뉴·설명. 사진이 구체적으로 무엇인지 "
        f"유추하는 데 활용하세요]\n{ctx}\n" if ctx else ""
    )
    hint = (hint or "").strip()
    hint_block = f"\n[사용자 요청사항 — 분류·설명에 반드시 반영하세요]\n{hint}\n" if hint else ""
    return (
        f"사진 {n}장을 순서대로 줄게요. 각 사진이 무엇인지 사람처럼 파악하세요."
        f"{ctx_block}{hint_block}\n"
        "각 사진마다 두 가지를 정하세요:\n"
        f"1) label: 다음 중 하나로만 분류 — {', '.join(cats)}\n"
        "2) caption: 그 사진이 구체적으로 무엇인지 한국어로 짧게. 위 맥락의 메뉴·설명과 "
        "대조해 가능한 한 구체적으로(예: '데미글라스 소스를 올린 등심돈까스', '가게 외관 간판'). "
        "맥락에서 못 찾으면 보이는 그대로 묘사하세요. 추측으로 사실을 지어내지 마세요.\n"
        "JSON으로만 답하세요. 형식: "
        '{"items":[{"index":1,"label":"음식","caption":"데미소스 돈까스"}]} — '
        f"index는 1부터 {n}까지, 준 사진 순서와 정확히 일치시키세요."
    )


def _parse_captions(
    content: str, image_paths: list[str], cats: list[str]
) -> dict[str, dict[str, str]]:
    """모델 JSON → {path: {"label","caption"}} (안전 파싱·범위 검증, 누락은 기타로 채움)."""
    out: dict[str, dict[str, str]] = {}
    items = None
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            items = data.get("items")
    except json.JSONDecodeError:
        items = None
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            idx = it.get("index")
            if not isinstance(idx, int) or not (1 <= idx <= len(image_paths)):
                continue
            label = str(it.get("label") or "").strip()
            caption = str(it.get("caption") or "").strip()
            out[image_paths[idx - 1]] = {
                "label": label if label in cats else "기타",
                "caption": caption,
            }
    for p in image_paths:
        out.setdefault(p, {"label": "기타", "caption": ""})
    return out


def smart_caption_photos(
    image_paths: list[str],
    context: str = "",
    categories: list[str] | None = None,
    model: str | None = None,
    hint: str = "",
) -> dict[str, dict[str, str]]:
    """사진들을 '한 번의 호출'로 맥락 기반 분류+캡션 → {path: {"label","caption"}}.

    context: 메모+수집 메뉴/가게/상품 정보 텍스트. categories: 허용 라벨 목록.
    Gemini/NVIDIA 멀티모달 모델 사용(llm.vision_chat). 키 미설정/패키지 미설치면 LLMUnavailable.
    """
    from autoblog.llm import vision_chat

    if not image_paths:
        return {}
    model = model or default_caption_model()
    if not model:
        from autoblog.llm import LLMUnavailable

        raise LLMUnavailable(
            "사진 자동 추천 모델 미설정 — config/models.yaml 의 caption.model 을 "
            "qwen/qwen3.5-* 또는 gemini-* 로 두세요"
        )
    cats = [c for c in (categories or []) if c] or _DEFAULT_CAPTION_LABELS
    if "기타" not in cats:
        cats = [*cats, "기타"]
    images = [_downscale_image(p) for p in image_paths]
    content = vision_chat(_caption_prompt(len(image_paths), cats, context, hint), images, model, fmt="json")
    return _parse_captions(content, image_paths, cats)
