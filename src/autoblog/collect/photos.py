"""사진 분류 연동 (기획서 §1, §3).

입력 사진을 Vision LLM으로 자동 분류(음식/메뉴판/외관/내부/영수증/상품/기타)해
FactCard.photos에 채운다. 초안 작성 시 본문 사진 배치에 활용한다.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from autoblog.collect.fact_card import FactCard, PhotoItem

# 동영상 확장자 — 이 목록이 사진/영상을 가르는 단일 기준(webui 목록·미디어 종류 판별 공용).
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".webm", ".mkv"}


def is_video(path: str) -> bool:
    """확장자로 동영상 여부 판별."""
    return Path(path).suffix.lower() in VIDEO_EXT


def media_kind_of(path: str) -> str:
    return "video" if is_video(path) else "image"


def classify_photos_into(card: FactCard, image_paths: list[str], model: str | None = None) -> FactCard:
    """사진들을 분류해 card.photos에 채운다. Vision 미연동 시 '기타'로 채우고 경고.

    영상은 Vision 분류 대상이 아니므로 라벨 '기타'로 두고, media_kind만 'video'로 표시한다.
    """
    from autoblog.vision import VisionUnavailable, classify_photos

    images = [p for p in image_paths if not is_video(p)]
    try:
        labels = classify_photos(images, model=model) if images else {}
    except VisionUnavailable as exc:
        card.warnings.append(f"사진 분류 생략(Vision 미연동): {exc}")
        labels = {p: "기타" for p in images}
    except Exception as exc:  # noqa: BLE001 - 사진 분류는 보조라 실패해도 진행
        card.warnings.append(f"사진 분류 실패: {exc}")
        labels = {p: "기타" for p in images}

    card.photos = [
        PhotoItem(path=p, label=labels.get(p, "기타"), media_kind=media_kind_of(p))
        for p in image_paths
    ]
    return card


def attach_photos(
    card: FactCard,
    image_paths: list[str],
    meta: dict[str, dict] | None = None,
) -> FactCard:
    """사진을 card.photos에 채운다(Vision 호출 없음).

    meta가 있으면 그 라벨·캡션(사용자 수동 분류 또는 AI 자동 추천 결과)을 쓰고,
    없으면 라벨 '기타'로 둔다. webui는 항상 이 경로로 채워 자동 분류를 돌리지 않는다.
    """
    meta = meta or {}
    card.photos = [
        PhotoItem(
            path=p,
            label=(meta.get(p) or {}).get("label") or "기타",
            caption=(meta.get(p) or {}).get("caption") or "",
            thumbnail=bool((meta.get(p) or {}).get("thumbnail")),
            ai_generated=bool((meta.get(p) or {}).get("ai_generated")),
            media_kind=media_kind_of(p),
        )
        for p in image_paths
    ]
    return card


def photo_summary(photos: list[PhotoItem]) -> str:
    """분류 라벨 분포 요약 (예: '음식 3, 외관 1, 메뉴판 1'). 영상은 '영상 N'으로 별도 표기."""
    counts = Counter(
        "영상" if p.media_kind == "video" else p.label for p in photos
    )
    return ", ".join(f"{label} {n}" for label, n in counts.most_common())
