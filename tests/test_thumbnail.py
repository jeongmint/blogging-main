"""AI 썸네일(thumbnail.py) — 네트워크 없이 응답 파싱·타이틀 오버레이 로직만 검증."""

import base64
from io import BytesIO

import pytest
from PIL import Image

from autoblog.thumbnail import ThumbnailUnavailable, _decode_image, _flux_generate, _overlay_title


def test_decode_image_both_response_shapes():
    raw = b"fake-png"
    b64 = base64.b64encode(raw).decode()
    assert _decode_image({"artifacts": [{"base64": b64}]}) == raw  # native
    assert _decode_image({"data": [{"b64_json": b64}]}) == raw  # OpenAI 호환


def test_decode_image_empty_raises():
    with pytest.raises(ThumbnailUnavailable):
        _decode_image({"artifacts": []})


def _png_bytes(size=256, color="beige"):
    buf = BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="PNG")
    return buf.getvalue()


def test_overlay_title_keeps_size_and_changes_pixels():
    src = _png_bytes()
    out = _overlay_title(src, "거제 양념게장")
    img = Image.open(BytesIO(out))
    assert img.size == (256, 256)
    assert out != src  # 글씨/배경이 실제로 그려짐


def test_overlay_empty_title_returns_image():
    out = _overlay_title(_png_bytes(), "")
    assert Image.open(BytesIO(out)).size == (256, 256)


def test_flux_quota_error_is_friendly(monkeypatch):
    class FakeResp:
        status_code = 402
        ok = False
        text = "Payment Required"

    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResp())
    with pytest.raises(ThumbnailUnavailable, match="크레딧"):
        _flux_generate("prompt", "nvapi-x")
