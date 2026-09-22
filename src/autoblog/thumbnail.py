"""AI 썸네일 — 대표사진을 VLM이 읽고, FLUX.1-dev(NVIDIA API)가 손그림 감성 썸네일을 그린다.

qwen-image-edit는 NVIDIA 호스티드 미제공(다운로드 전용 NIM)이고, 호스티드 이미지
모델들은 사진 입력 자체를 막아둬서(프리셋 example_id만 허용) 2단계로 우회한다:
 1) 비전 VLM(models.yaml caption)이 사진을 보고 영어 일러스트 프롬프트를 작성
 2) flux.1-dev(텍스트→이미지)가 1:1 손그림 일러스트를 생성
 3) 한글 타이틀은 생성 모델이 못 그리므로 PIL로 유화 느낌 배경+글씨를 오버레이
드로잉 감성 규칙은 config/prompts/thumbnail.md(직접 편집 가능)에서 읽는다.
NVIDIA_API_KEY 하나로 두 호출 모두 처리.
"""

from __future__ import annotations

import base64
import colorsys
import json
import random
import sys
from io import BytesIO

from autoblog.config import CONFIG_DIR, load_env

PROMPT_PATH = CONFIG_DIR / "prompts" / "thumbnail.md"
COPY_PROMPT_PATH = CONFIG_DIR / "prompts" / "thumbnail_copy.md"  # 외부 멀티모달 모델 복사용(한글 텍스트+콜라주)

_FLUX_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"
_DIM = 1024  # 블로그 대표사진 1:1


class ThumbnailUnavailable(RuntimeError):
    """키 미설정·API 오류 등으로 썸네일을 만들 수 없을 때."""


def load_thumbnail_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_thumbnail_copy_prompt() -> str:
    """복사 버튼 → 외부 멀티모달 모델에 그대로 붙여넣는 프롬프트(FLUX용과 분리)."""
    return COPY_PROMPT_PATH.read_text(encoding="utf-8")


def _decode_image(data: dict) -> bytes:
    """응답 JSON → 이미지 bytes. native(artifacts[].base64)·OpenAI(data[].b64_json) 모두 지원."""
    items = data.get("artifacts") or data.get("data") or []
    for it in items:
        if not isinstance(it, dict):
            continue
        b64 = it.get("base64") or it.get("b64_json")
        if b64:
            return base64.b64decode(b64)
    raise ThumbnailUnavailable("응답에 이미지가 없어요: " + json.dumps(data)[:200])


def _compose_flux_prompt(photo_path: str, extra: str) -> str:
    """사진 + 드로잉 규칙 → 영어 일러스트 생성 프롬프트(VLM 작성)."""
    from autoblog.llm import LLMUnavailable, vision_chat
    from autoblog.vision import _downscale_image, default_caption_model

    rules = load_thumbnail_prompt()
    ask = (
        "아래 [드로잉 규칙]과 첨부한 사진을 참고해, 이 사진을 손그림 감성 일러스트로 "
        "재해석하는 '영어' 이미지 생성 프롬프트를 한 문단으로 작성하세요.\n"
        "- 사진 속 주인공(음식/제품)의 종류·색·구도·분위기를 구체적으로 묘사\n"
        "- 규칙의 스타일 요소를 프롬프트에 녹일 것\n"
        "- 이미지 안에 글자가 생기지 않도록 'no text, no letters, no typography'를 포함\n"
        "- 프롬프트 텍스트만 출력(설명·따옴표·코드블록 금지)\n\n"
        f"[드로잉 규칙]\n{rules}\n"
    )
    if extra:
        ask += f"\n[추가 요청 — 규칙보다 우선 반영]\n{extra}\n"
    try:
        prompt = vision_chat(ask, [_downscale_image(photo_path)], default_caption_model())
    except LLMUnavailable as exc:
        raise ThumbnailUnavailable(str(exc)) from exc
    return prompt.strip().strip('"`')[:1500]


def _flux_generate(prompt: str, api_key: str) -> bytes:
    """flux.1-dev(텍스트→이미지) 호출 → PNG/JPEG bytes."""
    import requests

    resp = requests.post(
        _FLUX_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        json={
            "prompt": prompt,
            "width": _DIM,
            "height": _DIM,
            "steps": 30,
            "cfg_scale": 3.5,
            "seed": random.randint(0, 2**31 - 1),  # 매번 다른 그림 → '다시 생성' 가능
        },
        timeout=300,
    )
    if resp.status_code in (402, 429):  # 402=무료 크레딧 소진, 429=분당 요청 초과
        raise ThumbnailUnavailable(
            "NVIDIA 한도 도달 — 무료 크레딧(1,000회) 소진 또는 분당 40회 초과예요. "
            "잠시 후 재시도하거나 build.nvidia.com 로그인 후 잔여 크레딧을 확인하세요."
        )
    if not resp.ok:
        raise ThumbnailUnavailable(f"NVIDIA API 오류 {resp.status_code}: {resp.text[:300]}")
    return _decode_image(resp.json())


# 한글 지원 시스템 폰트 후보(위에서부터 시도). 없으면 타이틀 없이 그림만 반환.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",  # macOS
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
    "C:/Windows/Fonts/malgun.ttf",  # Windows
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",  # Linux
]


def _load_font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def _overlay_title(image: bytes, title: str) -> bytes:
    """일러스트 중앙에 타이틀 오버레이 — 두 색 유화 붓칠 느낌 배경 + 흰 테두리 글씨."""
    from PIL import Image, ImageDraw

    img = Image.open(BytesIO(image)).convert("RGB")
    w, h = img.size
    size = w // 9
    font = _load_font(size)
    if not title or font is None:
        # ponytail: 한글 폰트가 없는 환경이면 글자 없이 그림만 — 실패보다 낫다
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    draw = ImageDraw.Draw(img, "RGBA")
    while size > 12:  # 폭 80% 안에 들어올 때까지 축소
        font = _load_font(size)
        if draw.textlength(title, font=font) <= w * 0.8:
            break
        size -= 4

    # 그림의 평균 색조에서 두 톤(밝은/진한)을 뽑아 겹친 붓칠 배경
    r, g, b = img.resize((1, 1)).getpixel((0, 0))
    hue, _, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    sat = max(0.45, min(sat * 1.4, 0.85))
    band1 = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, 0.82, sat))
    band2 = tuple(int(c * 255) for c in colorsys.hls_to_rgb((hue + 0.05) % 1, 0.68, sat))
    ink = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, 0.22, 0.55))

    x0, y0, x1, y1 = draw.textbbox((0, 0), title, font=font)
    tw, th = x1 - x0, y1 - y0
    cx, cy = w // 2, h // 2
    pad = size // 2
    box = (cx - tw // 2 - pad, cy - th // 2 - pad // 2, cx + tw // 2 + pad, cy + th // 2 + pad // 2)
    radius = (box[3] - box[1]) // 3
    off = size // 8  # 두 번째 붓칠은 살짝 어긋나게 — 덧댄 유화 느낌
    draw.rounded_rectangle(
        [box[0] + off, box[1] + off, box[2] + off, box[3] + off],
        radius=radius, fill=(*band2, 235),
    )
    draw.rounded_rectangle(box, radius=radius, fill=(*band1, 235))
    draw.text(
        (cx - tw // 2 - x0, cy - th // 2 - y0), title, font=font,
        fill=ink, stroke_width=max(2, size // 14), stroke_fill=(255, 255, 255),
    )
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_thumbnail(photo_path: str, title: str = "", extra: str = "") -> tuple[bytes, str]:
    """대표사진 1장 + 타이틀 + 방향 요청(extra) → (썸네일 PNG bytes, VLM이 쓴 영어 생성 프롬프트).

    프롬프트도 함께 돌려줘서, FLUX 결과가 아쉬우면 그대로 복사해 외부 이미지 모델에 맡길 수 있게.
    """
    env = load_env()
    if not env.nvidia_api_key:
        raise ThumbnailUnavailable(
            "NVIDIA_API_KEY 미설정 — build.nvidia.com에서 발급해 모델 탭에 저장하세요"
        )
    prompt = _compose_flux_prompt(photo_path, extra)
    image = _flux_generate(prompt, env.nvidia_api_key)
    return _overlay_title(image, title.strip()), prompt


if __name__ == "__main__":  # 수동 점검: python -m autoblog.thumbnail 사진.jpg "타이틀"
    out, _ = generate_thumbnail(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "테스트")
    dest = "thumb_test.png"
    with open(dest, "wb") as f:
        f.write(out)
    print(f"저장됨: {dest} ({len(out)} bytes)")
