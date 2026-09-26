"""텍스트 LLM 호출 공통 (초안 작성·문체 추출 등).

API 전용 — Claude/GPT/Gemini/NVIDIA 호스티드만 지원한다(로컬 LLM 미지원).
모델명은 config/models.yaml(프리셋 text)에서 읽는다. 비전은 vision.py 참고.
"""

from __future__ import annotations

from autoblog.config import load_env, load_models_config, provider_for_model


class LLMUnavailable(RuntimeError):
    """텍스트 모델이 연동되지 않았거나(키 미설정/패키지 미설치) 사용할 수 없을 때."""


# 공급자가 응답을 안 주면 무한 대기하지 않게 — SDK 기본값(제한 없음/10분+재시도)이면
# 웹UI가 '생성 중…'에서 영영 멈춘 것처럼 보인다. 초과하면 에러로 떨어져 안내된다.
TIMEOUT_SEC = 180

# Gemini는 thinking이 모델 기본으로 켜져 있어(3.5-flash·3.8-flash 모두 기본 medium) 초안
# 한 편에 사고 토큰이 출력의 3~4배 붙는다. 실측: 1500자 초안 요청에 medium 47초, 실제
# 프롬프트(팩트카드·사진·가이드라인)는 이보다 훨씬 무겁고 자가검수까지 켜면 같은 크기로 2회.
# 180초 마감으로는 서버가 생성 중인데 우리 마감이 먼저 끝나 504 DEADLINE_EXCEEDED가 난다.
# 구글 공식 안내도 504의 조치를 "클라이언트 데드라인을 제거하거나 늘려라"로 명시한다.
GEMINI_TIMEOUT_SEC = 600


def default_text_model() -> str:
    return load_models_config().effective().text


def provider_for(model: str) -> str:
    """모델명으로 API 제공자 판별(라우팅용)."""
    return provider_for_model(model)


def _chat_anthropic(messages: list[dict], model: str, fmt: str | None = None) -> str:
    """Claude API(공식 anthropic SDK)로 텍스트 생성. ANTHROPIC_API_KEY 필요."""
    import anthropic

    env = load_env()
    if not env.anthropic_api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY 미설정 — 설정 탭에서 API 키를 입력하세요")
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    if fmt == "json":
        system = (system + "\n\nJSON으로만 답하세요.").strip()
    conv = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m["role"] in ("user", "assistant")
    ]
    client = anthropic.Anthropic(
        api_key=env.anthropic_api_key, timeout=TIMEOUT_SEC, max_retries=1
    )
    try:
        resp = client.messages.create(
            model=model, max_tokens=16000, messages=conv, **({"system": system} if system else {})
        )
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("ANTHROPIC_API_KEY가 유효하지 않습니다") from exc
    except anthropic.APIError as exc:
        raise LLMUnavailable(f"Claude API 오류: {exc}") from exc
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def _chat_openai(
    messages: list[dict],
    model: str,
    fmt: str | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    key_name: str = "OPENAI_API_KEY",
    extra_body: dict | None = None,
) -> str:
    """OpenAI 호환 API로 텍스트 생성 — 기본은 OpenAI(GPT), base_url을 주면 호환 서비스(NVIDIA 등)."""
    try:
        from openai import APIError, AuthenticationError, OpenAI
    except ImportError as exc:
        raise LLMUnavailable("openai 패키지 미설치 — pip install openai") from exc

    env = load_env()
    key = api_key if base_url else env.openai_api_key
    if not key:
        raise LLMUnavailable(f"{key_name} 미설정 — 설정 탭에서 API 키를 입력하세요")
    msgs = list(messages)
    kwargs: dict = {}
    if extra_body:
        kwargs["extra_body"] = extra_body
    if fmt == "json":
        kwargs["response_format"] = {"type": "json_object"}
        # system은 맨 앞에 — qwen 등 일부 챗 템플릿은 중간/끝 system을 거부한다
        msgs = [{"role": "system", "content": "JSON으로만 답하세요."}] + msgs
    client = OpenAI(api_key=key, base_url=base_url, timeout=TIMEOUT_SEC, max_retries=1)
    try:
        resp = client.chat.completions.create(model=model, messages=msgs, **kwargs)
    except AuthenticationError as exc:
        raise LLMUnavailable(f"{key_name}가 유효하지 않습니다") from exc
    except APIError as exc:
        # 402=무료 크레딧 소진, 429=분당 요청 초과 — 잔여 크레딧 조회 API는 없어서 안내만
        if base_url and getattr(exc, "status_code", None) in (402, 429):
            raise LLMUnavailable(
                "NVIDIA 한도 도달 — 무료 크레딧(1,000회) 소진 또는 분당 40회 초과예요. "
                "잠시 후 재시도하거나 build.nvidia.com 로그인 후 잔여 크레딧을 확인하세요."
            ) from exc
        raise LLMUnavailable(f"{'NVIDIA' if base_url else 'OpenAI'} API 오류: {exc}") from exc
    return resp.choices[0].message.content or ""


def _chat_nvidia(
    messages: list[dict], model: str, fmt: str | None = None, extra_body: dict | None = None
) -> str:
    """NVIDIA 호스티드 모델(build.nvidia.com, OpenAI 호환 API). NVIDIA_API_KEY 필요."""
    return _chat_openai(
        messages,
        model,
        fmt,
        api_key=load_env().nvidia_api_key,
        base_url="https://integrate.api.nvidia.com/v1",
        key_name="NVIDIA_API_KEY",
        extra_body=extra_body,
    )


def _gemini_finish_reason(resp) -> str:
    """빈 응답의 사유를 사람이 읽을 문자열로. SDK enum에 없는 값(MALFORMED_RESPONSE 등)도 있어
    방어적으로 읽는다 — 사유를 못 읽는 것 자체가 진단을 막으면 안 된다."""
    try:
        blocked = getattr(getattr(resp, "prompt_feedback", None), "block_reason", None)
        if blocked:
            return f"prompt_blocked:{getattr(blocked, 'name', blocked)}"
        for cand in getattr(resp, "candidates", None) or []:
            fr = getattr(cand, "finish_reason", None)
            if fr:
                return str(getattr(fr, "name", fr))
    except Exception:  # noqa: BLE001 - 진단용이라 여기서 죽으면 안 된다
        pass
    return "unknown"


_GEMINI_RETRY_CODES = (429, 503)  # 429=쿼터 초과, 503=과부하 — 무료 티어는 우선순위가 낮아 특히 잦다
# 504(마감 초과)는 재시도 대상이 아니다 — 백오프해도 같은 요청은 또 느리다. _chat_gemini 참고.


def _chat_gemini(messages: list[dict], model: str, fmt: str | None = None) -> str:
    """Google Gemini API로 텍스트 생성. GEMINI_API_KEY 필요."""
    import random
    import time

    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:
        raise LLMUnavailable("google-genai 패키지 미설치 — pip install google-genai") from exc

    env = load_env()
    if not env.gemini_api_key:
        raise LLMUnavailable("GEMINI_API_KEY 미설정 — 설정 탭에서 API 키를 입력하세요")
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
        if m["role"] in ("user", "assistant")
    ]
    cfg = types.GenerateContentConfig(
        system_instruction=system or None,
        response_mime_type="application/json" if fmt == "json" else None,
    )
    client = genai.Client(
        api_key=env.gemini_api_key,
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SEC * 1000),  # ms 단위
    )
    # 503(모델 과부하)은 간헐적이다 — 2026-09-04 실측에서 gemini-3.8-flash는 시도당 성공률이
    # 약 38%였고(8회 중 3회), 실패는 요청 크기와 무관했다(1500자 성공·300자 503, 한 문장 79초).
    # 신형 모델은 대기줄이 길어 무료 티어가 특히 밀린다. 1s·2s 3회로는 76%에서 멈추므로
    # 지수 백오프 6회로 늘린다(누적 약 94%, 최악 대기 62초).
    attempts = 6
    for attempt in range(attempts):
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=cfg)
            text = resp.text or ""
            if text.strip():
                return text
            # 빈 응답을 그대로 돌려주면 '에러도 없는데 본문만 사라진 초안'이 나온다(사진·캡션만
            # 남는다). Gemini는 MALFORMED_RESPONSE·MAX_TOKENS·SAFETY 등으로 예외 없이 본문
            # 없이 끝나는 경우가 있어, 사유를 읽어 재시도하거나 사유를 밝혀 실패시킨다.
            reason = _gemini_finish_reason(resp)
            if attempt < attempts - 1:
                time.sleep(2 ** (attempt + 1) * (1 + random.random() * 0.25))
                continue
            raise LLMUnavailable(
                f"Gemini가 본문 없이 응답했습니다(finish_reason={reason}). "
                f"{attempts}회 재시도 모두 빈 응답 — 잠시 후 다시 시도하거나, 자가검수를 끄거나, "
                "config/models.yaml 에서 다른 모델로 바꿔 보세요."
            )
        except errors.APIError as exc:
            # 504는 '느려서 마감을 넘긴' 것이라 같은 요청을 다시 던져도 또 넘긴다 — 재시도로
            # 시간만 3배 태우고 실패하므로 바로 안내한다(백오프는 과부하/쿼터에만 의미가 있다).
            if exc.code == 504:
                raise LLMUnavailable(
                    f"Gemini 생성이 {GEMINI_TIMEOUT_SEC}초 안에 끝나지 않았습니다(504). "
                    "글자 수를 줄이거나, 자가검수를 끄거나, config/models.yaml 에서 "
                    "thinking_level 을 낮춘 모델로 바꿔 보세요."
                ) from exc
            if exc.code in _GEMINI_RETRY_CODES and attempt < attempts - 1:
                # 2s, 4s, 8s, 16s, 32s — 같은 순간에 몰린 요청이 같은 간격으로 재시도해
                # 다시 부딪히지 않게 지터를 섞는다.
                time.sleep(2 ** (attempt + 1) * (1 + random.random() * 0.25))
                continue
            raise LLMUnavailable(f"Gemini API 오류: {exc}") from exc
    raise AssertionError("unreachable")


def _vision_gemini(prompt: str, images: list[bytes], model: str, *, fmt: str | None = None) -> str:
    """Google Gemini 멀티모달 호출 — 프롬프트 + 이미지 여러 장 한 번에. GEMINI_API_KEY 필요."""
    import time

    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:
        raise LLMUnavailable("google-genai 패키지 미설치 — pip install google-genai") from exc

    env = load_env()
    if not env.gemini_api_key:
        raise LLMUnavailable("GEMINI_API_KEY 미설정 — 설정 탭에서 API 키를 입력하세요")
    parts = [types.Part(text=prompt)]
    parts += [types.Part.from_bytes(data=b, mime_type="image/png") for b in images]
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json" if fmt == "json" else None,
    )
    client = genai.Client(
        api_key=env.gemini_api_key,
        http_options=types.HttpOptions(timeout=TIMEOUT_SEC * 1000),  # ms 단위
    )
    attempts = 3
    for attempt in range(attempts):
        try:
            resp = client.models.generate_content(
                model=model, contents=[types.Content(role="user", parts=parts)], config=cfg
            )
            return resp.text or ""
        except errors.APIError as exc:
            if exc.code in _GEMINI_RETRY_CODES and attempt < attempts - 1:
                time.sleep(2**attempt)  # 1s, 2s
                continue
            raise LLMUnavailable(f"Gemini API 오류: {exc}") from exc
    raise AssertionError("unreachable")


def _vision_nvidia(prompt: str, images: list[bytes], model: str, *, fmt: str | None = None) -> str:
    """NVIDIA 호스티드 VLM(qwen3.5 등) 멀티모달 호출 — OpenAI 호환 image_url 데이터 URL.

    thinking 모드는 끈다 — 캡션/분류엔 불필요하게 느리고, 켜면 간헐적으로
    content가 빈 응답이 온다(검증됨). 그래도 비면 재시도 후 LLMUnavailable.
    """
    import base64

    content: list[dict] = [{"type": "text", "text": prompt}]
    for b in images:
        mime = "jpeg" if b[:3] == b"\xff\xd8\xff" else "png"
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/{mime};base64,{base64.b64encode(b).decode()}"},
        })
    messages = [{"role": "user", "content": content}]
    extra = {"chat_template_kwargs": {"enable_thinking": False}}
    for _ in range(3):
        out = _chat_nvidia(messages, model, fmt=fmt, extra_body=extra)
        if out.strip():
            return out
    raise LLMUnavailable(f"NVIDIA VLM({model})이 빈 응답을 반복 — 잠시 후 다시 시도하세요")


def vision_chat(prompt: str, images: list[bytes], model: str, *, fmt: str | None = None) -> str:
    """이미지(여러 장)+프롬프트 멀티모달 호출 → 응답 텍스트.

    Gemini 또는 NVIDIA 호스티드 VLM(org/model 형식). 비전 기능 래퍼는 vision.py 참고.
    """
    provider = provider_for(model)
    if provider == "gemini":
        return _vision_gemini(prompt, images, model, fmt=fmt)
    if provider == "nvidia":
        return _vision_nvidia(prompt, images, model, fmt=fmt)
    raise LLMUnavailable(
        f"사진 분석은 Gemini/NVIDIA 모델만 지원합니다(현재 모델: {model!r}). "
        "config/models.yaml 에서 gemini-* 또는 qwen/qwen3.5-* 등으로 설정하세요."
    )


def chat(
    messages: list[dict],
    model: str | None = None,
    *,
    fmt: str | None = None,
    temperature: float = 0.7,
    timeout: int = TIMEOUT_SEC,
) -> str:
    """텍스트 LLM 호출 → 응답 텍스트.

    messages: [{"role": "system"|"user"|"assistant", "content": "..."}].
    모델명 접두사로 라우팅(claude→Claude, gpt/o*→GPT, gemini→Gemini, org/model→NVIDIA).
    API 전용 — 그 외 모델명은 미지원. fmt="json"이면 JSON 응답 강제.
    temperature는 호환을 위해 받지만 사용하지 않는다. 응답 대기는 TIMEOUT_SEC로 제한된다
    (timeout 인자는 호환용 — 공급자별 클라이언트에 TIMEOUT_SEC가 그대로 적용된다).
    """
    model = model or default_text_model()
    provider = provider_for(model)
    if provider == "anthropic":
        return _chat_anthropic(messages, model, fmt=fmt)
    if provider == "openai":
        return _chat_openai(messages, model, fmt=fmt)
    if provider == "gemini":
        return _chat_gemini(messages, model, fmt=fmt)
    if provider == "nvidia":
        return _chat_nvidia(messages, model, fmt=fmt)
    raise LLMUnavailable(
        f"텍스트 생성은 API 모델만 지원합니다(현재 model: {model!r}). "
        "config/models.yaml 의 selection.text 를 claude-*/gpt-*/gemini-*/org/model(NVIDIA) 로 설정하세요."
    )
