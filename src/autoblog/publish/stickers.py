"""스티커 카탈로그 — 불러오기 + 비전 자동 라벨 + 유저 검수 YAML + 상황→스티커 해석.

스티커는 Smart Editor DOM에 의미(감정/상황) 라벨이 없고 (팩코드, 인덱스) 좌표뿐이라
([[smart-editor-publish]]), 다음 4단계로 "상황에 맞는 스티커"를 구현한다:
  1) pull   — 에디터에서 각 스티커를 element 스크린샷으로 떠 모은다(editor.pull_stickers).
  2) label  — 비전 모델(Gemini API)이 이미지를 보고 감정/상황 태그를 자동 생성(검수 옵션).
  3) review — 유저가 config/stickers.yaml에서 태그·즐겨쓰기를 직접 수정(자동 라벨 위 우선).
  4) resolve— 초안의 [스티커:상황] 마커를 (팩,인덱스)로 해석(StickerPicker).

(팩코드, 인덱스)를 안정 키로 **증분 동기화**한다: 다시 불러오면 새 스티커만 추가하고,
기존 태그/검수/즐겨쓰기는 보존하며, 패널에서 사라진 스티커는 stale로 표시(삭제 안 함).

스티커 분류(태그 컨벤션): '구분선'이 든 태그 → 구분선용(화제 전환 사이),
'헤더'가 든 태그 → 헤더형(소제목 라벨·고지 배너, 예: '추천대상'+'헤더').
헤더형은 LLM 감정 스티커 목록·자동 선택에서 제외되고 [스티커:태그] 수동 마커로만 쓰인다
— 제목 라벨이 감정 반응 자리(사진 옆·글 끝)에 붙는 오용 방지. 나머지는 감정 스티커.
이 태그들은 비전 자동 라벨링(label_sticker의 kind 판정)이 자동 부여한다 — 어느 유저든
자기 스티커를 불러와 태그 분석만 돌리면 분류가 되고, 틀린 건 검수(태그 칩)로 고친다.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from autoblog.config import DATA_DIR, USER_CONFIG_DIR, USER_DATA_DIR

STICKER_CONFIG_PATH = USER_CONFIG_DIR / "stickers.yaml"  # 유저가 태그/즐겨찾기 수정 → 쓰기
STICKER_DATA_DIR = DATA_DIR / "stickers"

# 네이버가 누구에게나 기본 제공하는 팩(직접 구매·추가한 게 아님) — 카탈로그 잡음이라
# UI에서 토글로 숨길 수 있게 한다(stickers 뷰의 "기본 이모티콘 숨기기").
DEFAULT_PACKS: frozenset[str] = frozenset(
    {"motion3d_02", "motion2d_01", "clip_001", "cafe_001", "cafe_002", "cafe_004", "cafe_005"}
)

# 스티커 분류(Sticker.kind 값) — UI 분류 버튼·안내 문구가 이 이름을 그대로 쓴다.
KIND_EMOTION = "감정"  # 감정·반응 문단 끝에 LLM이 자동 삽입(글당 1~3번)
KIND_DIVIDER = "구분선"  # 화제 전환 사이에 LLM이 자동 삽입(글당 0~2번)
KIND_HEADING = "헤더"  # 제목 라벨·고지 배너 — 자동 사용 제외, 수동 마커 전용
STICKER_KINDS = (KIND_EMOTION, KIND_DIVIDER, KIND_HEADING)


class Sticker(BaseModel):
    """스티커 1개. (pack, index)가 안정 식별자."""

    pack: str  # 팩 코드(예: ogq_60f7003da4337, clip_001) — 썸네일 URL에서 추출
    index: int  # 팩 내 data-index
    animated: bool = False
    image: str | None = None  # 미리보기 PNG 상대경로(예: data/stickers/<pack>/<index>.png)
    tags: list[str] = Field(default_factory=list)  # 감정/상황 라벨(비전+유저)
    reviewed: bool = False  # 유저가 손봄 → 자동 라벨링이 덮어쓰지 않음
    stale: bool = False  # 재불러오기 시 패널에 더 없음(매핑 보존 위해 남겨둠)

    @property
    def ref(self) -> str:
        return f"{self.pack}:{self.index}"

    @property
    def is_heading(self) -> bool:
        """헤더형(제목·배너) 스티커인지 — '헤더' 태그가 달려 있으면 True.

        '추천대상'·'한줄평' 같은 소제목 라벨, '내돈내산'·협찬 고지 같은 배너 스티커는
        감정 반응이 아니라서 LLM 감정 스티커 목록(labels)과 라벨 없는 자동 선택에서
        제외한다. [스티커:추천대상] 처럼 태그를 직접 지목한 마커는 계속 해석된다.
        """
        return any(_is_heading_label(t) for t in self.tags)

    @property
    def is_divider(self) -> bool:
        """구분선형 스티커인지 — '구분선'(구분/divider)이 든 태그가 있으면 True."""
        return any(_is_divider_label(t) for t in self.tags)

    @property
    def kind(self) -> str:
        """스티커 분류: '헤더' | '구분선' | '감정' (태그 마커에서 유도, 헤더 우선).

        감정=LLM이 감정·반응 문단 끝에 자동 삽입, 구분선=화제 전환 사이 자동 삽입,
        헤더=자동 사용 제외(수동 [스티커:태그] 마커 전용). UI 분류 버튼·안내의 단일 기준.
        """
        if self.is_heading:
            return KIND_HEADING
        if self.is_divider:
            return KIND_DIVIDER
        return KIND_EMOTION


class StickerCatalog(BaseModel):
    """유저의 스티커 카탈로그(= config/stickers.yaml 직렬화 대상)."""

    stickers: list[Sticker] = Field(default_factory=list)
    favorites: list[str] = Field(default_factory=list)  # 즐겨쓰기 ref("pack:index") 목록
    sponsor: str = ""  # 협찬 고지 스티커 ref("pack:index") — UI에서 카드 골라 지정(협찬 토글 시 맨 위)

    def by_ref(self) -> dict[str, Sticker]:
        return {s.ref: s for s in self.stickers}

    def labels(self, favorites_only: bool = True) -> list[str]:
        """유효(비stale) 스티커의 태그 distinct — 초안 지시문에 노출.

        favorites_only=True(기본): 즐겨찾기한 스티커의 태그만 — UI 약속("즐겨찾기한 것만
        쓰임")과 picker(find)의 동작에 맞춤. 그래야 프롬프트에 보이는 상황 목록과 실제로
        붙는 스티커가 일치한다(전체를 노출하면 즐겨찾기에 없는 라벨을 LLM이 써버린다).
        '.'·영문으로 시작하는 비정상 자동 라벨은 제외한다.
        헤더형(is_heading) 스티커의 태그는 전부 제외 — '추천대상' 같은 제목 라벨을 LLM이
        감정 스티커로 오용해 사진 옆·글 끝에 붙이는 사고 방지(수동 마커는 계속 동작).
        구분선형 스티커는 구분선 태그만 노출 — 곁태그(예: '가로')가 감정 목록에 새면
        분류가 스티커 단위로 안 지켜진다(지시문은 태그 텍스트로 감정/구분선을 나누므로).
        """
        favset = set(self.favorites)
        seen: list[str] = []
        for s in self.stickers:
            if s.stale or s.is_heading:
                continue
            if favorites_only and s.ref not in favset:
                continue
            for t in s.tags:
                t = str(t).strip()
                if not t or t[0] == "." or t[0].isascii() and t[0].isalpha():
                    continue  # '.lazy' 같은 비전 오라벨 차단(한글 상황 라벨만)
                if s.is_divider and not _is_divider_label(t):
                    continue  # 구분선형의 곁태그는 감정 목록에 새지 않게
                if t not in seen:
                    seen.append(t)
        return seen

    def find(self, label: str, favorites_only: bool = True) -> list[Sticker]:
        """태그에 label을 가진 스티커들(stale 제외). 즐겨쓰기를 앞으로.

        favorites_only=True(기본): 즐겨쓰기한 것만 후보 — UI 약속("즐겨찾기한 것만 쓰임")과 일치.
        favorites_only=False: 전체에서 찾되 즐겨쓰기를 앞으로 정렬(즐겨쓰기 소진 시 fallback).
        같은 라벨이 헤더형·감정형 양쪽에 있으면(예: '꿀팁') 감정형을 앞에 — 감정 자리에
        제목 라벨 스티커가 붙는 걸 피한다(헤더형만 매칭되면 그대로 그걸 쓴다).
        """
        favs = set(self.favorites)
        hits = [s for s in self.stickers if not s.stale and label in s.tags]
        if favorites_only:
            hits = [s for s in hits if s.ref in favs]
        hits.sort(key=lambda s: (s.ref not in favs, s.is_heading))  # 즐겨쓰기 우선(False<True)
        return hits

    def resolve_ref(self, spec: str) -> tuple[str, int] | None:
        """스티커 지정값(spec) → (pack, index). 협찬 고지 스티커 지정 등에 사용.

        spec이 'pack:index' 형식이면 그대로 해석하고, 아니면 '태그 이름'으로 보고
        그 태그를 가진 스티커(즐겨쓰기 우선, 없으면 전체)를 찾아 첫 번째를 쓴다.
        예: "파트너스" → 그 태그가 달린 스티커. 못 찾거나 비어 있으면 None.
        """
        spec = (spec or "").strip()
        if not spec:
            return None
        if ":" in spec:  # pack:index 직접 지정
            pack, _, idx = spec.partition(":")
            return (pack, int(idx)) if pack and idx.isdigit() else None
        hits = self.find(spec, favorites_only=False)  # 태그 이름으로 검색(전체에서)
        return (hits[0].pack, hits[0].index) if hits else None


def apply_kind(s: Sticker, kind: str) -> Sticker:
    """스티커 분류를 직접 지정 — 분류 마커 태그('헤더'/'구분선')를 갈아끼운다(제자리 수정).

    UI의 분류 버튼(감정/구분선/헤더)이 호출한다. 일반 상황 태그('추천대상'·'기쁨' 등)는
    보존하고 마커 태그만 정리하므로, 헤더형을 오가도 수동 마커 이름은 그대로 남는다.
    kind가 STICKER_KINDS 밖이면 아무것도 하지 않는다.
    """
    if kind not in STICKER_KINDS:
        return s
    s.tags = [t for t in s.tags if not _is_heading_label(t) and not _is_divider_label(t)]
    if kind == KIND_HEADING:
        s.tags.append("헤더")
    elif kind == KIND_DIVIDER:
        s.tags.append("구분선")
    return s


def merge_catalog(existing: StickerCatalog, scraped: list[Sticker]) -> StickerCatalog:
    """라이브 스크랩 결과를 기존 카탈로그에 증분 병합(새 객체 반환).

    - 새 (pack,index): 추가(tags 비어 → 라벨링 대상).
    - 기존: image/animated 갱신, tags/reviewed 보존, stale=False로 복구.
    - 기존에 있었는데 스크랩에 없음: stale=True(유저 매핑/검수 보존 위해 삭제 안 함).
    """
    old = existing.by_ref()
    scraped_refs = {s.ref for s in scraped}
    merged: dict[str, Sticker] = {}
    for sc in scraped:
        prev = old.get(sc.ref)
        if prev:
            merged[sc.ref] = prev.model_copy(
                update={"image": sc.image or prev.image, "animated": sc.animated, "stale": False}
            )
        else:
            merged[sc.ref] = sc
    # 스크랩에 없는 기존 것은 stale로 남긴다
    for ref, s in old.items():
        if ref not in scraped_refs:
            merged[ref] = s.model_copy(update={"stale": True})
    ordered = sorted(merged.values(), key=lambda s: (s.pack, s.index))
    # 사라진(stale) 스티커를 가리키는 즐겨쓰기는 유지(되살아날 수 있음)
    return StickerCatalog(stickers=ordered, favorites=existing.favorites)


class StickerPicker:
    """초안 마커 [스티커:label] → 스티커 해석. 한 글 내 중복 회피 + 팩 통일성 옵션.

    consistent=True면 글 전체에서 한 팩으로 고정(통일감). prefer_pack이 있으면 그 팩 우선.
    label이 빈 문자열이면 즐겨쓰기에서 고른다.
    favorites_only=True(기본): 즐겨찾기한 스티커만 사용. False면 전체 사용(즐겨찾기 우선).
    """

    def __init__(
        self,
        catalog: StickerCatalog,
        prefer_pack: str | None = None,
        consistent: bool = False,
        favorites_only: bool = True,
    ):
        self.catalog = catalog
        self.prefer_pack = prefer_pack
        self.consistent = consistent
        self.favorites_only = favorites_only
        self._locked_pack: str | None = prefer_pack
        self._used: list[str] = []  # 이미 쓴 ref(연속 중복 회피)

    def _candidates(self, label: str) -> list[Sticker]:
        if label:
            cands = self.catalog.find(label, favorites_only=self.favorites_only)
        else:  # 라벨 없는 [스티커] → 즐겨쓰기 중 감정형만(헤더=수동 전용, 구분선=전환 자리 전용)
            by_ref = self.catalog.by_ref()
            cands = [
                by_ref[r]
                for r in self.catalog.favorites
                if r in by_ref and not by_ref[r].stale and by_ref[r].kind == KIND_EMOTION
            ]
        pack = self._locked_pack
        if pack:
            same = [s for s in cands if s.pack == pack]
            if same:  # 통일성: 같은 팩 후보가 있으면 그쪽만
                cands = same
        return cands

    def pick(self, label: str) -> Sticker | None:
        """label에 맞는 스티커 1개 선택(없으면 None). 같은 글에서 반복 시 다른 스티커."""
        cands = self._candidates(label.strip())
        if not cands:
            return None
        fresh = [s for s in cands if s.ref not in self._used]
        chosen = (fresh or cands)[0]
        self._used.append(chosen.ref)
        if self.consistent and self._locked_pack is None:
            self._locked_pack = chosen.pack
        return chosen


# --- 개별 스티커 이미지(CDN 고해상도) ---
# 에디터 패널은 한 장의 스프라이트(축소 렌더 ~80px)라 캡처하면 깨진다. 대신 CDN의
# 개별 원본을 직접 받는다: ogq_ 팩은 .../ogq_<코드>/original_<N>.png 로 노출되며
# **에디터 data-index(0-based) → CDN original_{index+1}.png(1-based)**, native ~370px.
# (type=m480_480이 원본 최대; OGQ 마켓과 동일 CDN). clip/moti 등 다른 스킴 팩은 실패→스크린샷 폴백.
_CDN_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://ogqmarket.naver.com/"}


def sticker_image_url(pack: str, index: int, size: int = 480) -> str:
    return f"https://storep-phinf.pstatic.net/{pack}/original_{index + 1}.png?type=m{size}_{size}"


def download_sticker_image(pack: str, index: int, dest: Path, size: int = 480) -> bool:
    """CDN에서 개별 스티커 고해상도 PNG를 받아 dest에 저장. 성공 여부 반환(404 등 실패=False)."""
    import requests

    try:
        r = requests.get(sticker_image_url(pack, index, size), headers=_CDN_HEADERS, timeout=15)
    except requests.RequestException:
        return False
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return True


# 네이버 공식 팩(cafe_/motion3d_ 등)은 개별 파일이 없고 스프라이트(original_preview.png,
# 324x800)만 제공 → 80px 스크린샷보다 스프라이트 셀(~108px) 크롭이 선명. CDN개별 실패 시 폴백.
def sprite_png_url(pack: str) -> str:
    return f"https://storep-phinf.pstatic.net/{pack}/original_preview.png?type=p100_100"


def download_sprite(pack: str) -> bytes | None:
    import requests

    try:
        r = requests.get(sprite_png_url(pack), headers=_CDN_HEADERS, timeout=15)
    except requests.RequestException:
        return None
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
        return r.content
    return None


def crop_sprite(sprite_png: bytes, cols: int, count: int, index: int, scale: int = 2) -> bytes:
    """스프라이트에서 index 셀을 잘라 PNG bytes(행우선 격자). scale배 확대(LANCZOS)로 선명도↑."""
    import math
    from io import BytesIO

    from PIL import Image

    im = Image.open(BytesIO(sprite_png)).convert("RGBA")
    w, h = im.size
    cols = max(1, cols)
    rows = max(1, math.ceil(count / cols))
    cw, ch = w / cols, h / rows
    col, row = index % cols, index // cols
    box = (round(col * cw), round(row * ch), round((col + 1) * cw), round((row + 1) * ch))
    cell = im.crop(box)
    if scale and scale > 1:
        cell = cell.resize((cell.width * scale, cell.height * scale), Image.LANCZOS)
    buf = BytesIO()
    cell.save(buf, format="PNG")
    return buf.getvalue()


# --- 초안 지시문 (LLM이 [스티커:상황] 마커 emit) ---
def _is_divider_label(label: str) -> bool:
    """구분선 성격의 스티커 라벨인지 — 태그에 '구분선/구분/divider'가 들어가면 구분선용으로 본다."""
    low = label.replace(" ", "").casefold()
    return "구분선" in low or "구분" in low or "divider" in low


def _is_heading_label(label: str) -> bool:
    """헤더형 표시 태그인지 — '헤더'(또는 header)가 들어간 태그.

    이 태그가 하나라도 달린 스티커는 소제목 라벨('추천대상'·'한줄평')이나 고지 배너
    ('내돈내산'·협찬)로, 아래에 해당 내용이 이어져야 어울린다. 감정 반응이 아니므로
    LLM 노출 목록(labels)·라벨 없는 자동 선택에서 빠진다(Sticker.is_heading에서 사용).
    """
    low = label.replace(" ", "").casefold()
    return "헤더" in low or "header" in low


def build_sticker_instruction(labels: list[str]) -> str | None:
    """보유 스티커 상황 라벨 목록 → 초안 지시문(강조/구조 지시문과 같은 엔지니어링 패턴).

    감정 스티커(문단 끝)와 구분선 스티커(화제 전환 사이)를 나눠 안내한다 —
    '구분선'이 태그에 든 스티커는 구역 나누개로 쓰게 한다. 보유 라벨만 노출(환각 방지).
    14b급은 "절제" 안내면 0개 → "반드시 사용 + 개수 + 실제 라벨 예시"로 강하게 안내.
    """
    labels = [str(label).strip() for label in labels if str(label).strip()]
    if not labels:
        return None
    divider_labels = [label for label in labels if _is_divider_label(label)]
    mood_labels = [label for label in labels if not _is_divider_label(label)]

    parts = ["[스티커] 어울리는 자리에 [스티커:상황] 을 그 줄에 혼자 넣어 스티커를 답니다(권장이 아니라 사용)."]
    if mood_labels:
        mex = mood_labels[0]
        parts.append(
            "1) 감정 스티커 — 감정·반응이 드러나는 문단 끝 줄에 단독으로, 글 전체 1~3번.\n"
            "   사진 없이 글만 2문단 넘게 이어지는 구간(마무리 총평이 대표적)이 1순위 자리 —\n"
            "   그 구간 중간에 하나 넣어 글자만 빽빽한 화면을 깨 주세요. 글 맨 끝에만 몰지 말고.\n"
            f"   쓸 수 있는 상황(이 중에서만, 글자 그대로): {', '.join(mood_labels[:40])}\n"
            f"   예) 정말 맛있었어요.\n   [스티커:{mex}]"
        )
    if divider_labels:
        dex = divider_labels[0]
        parts.append(
            "2) 구분선 스티커 — 화제가 바뀌는 문단 사이에 단독으로 넣어 구역을 나눕니다"
            "(감정과 무관, 글 전체 0~2번).\n"
            f"   쓸 수 있는 상황(이 중에서만, 글자 그대로): {', '.join(divider_labels[:20])}\n"
            f"   예) …메뉴 이야기 끝.\n   [스티커:{dex}]\n   이제 분위기 이야기…\n"
            "   한 전환점에는 구분선 하나만 — [구분선] 마커와 같은 자리에 겹쳐 쓰지 마세요"
            "(붙여 쓰면 선이 두 줄로 보입니다)."
        )
    parts.append(
        "규칙:\n"
        "- 상황 이름은 위 목록에 있는 것만, 한 글자도 바꾸지 말고 그대로(띄어쓰기까지 동일).\n"
        "- [스티커:…] 는 반드시 그 줄에 혼자(앞뒤에 다른 글자 X).\n"
        "- 목록에 없는 상황은 절대 쓰지 마세요(없으면 그 자리엔 안 넣어도 됨)."
    )
    return "\n".join(parts)


# --- YAML IO (유저 검수 파일) ---
def load_sticker_catalog(path: Path | None = None) -> StickerCatalog:
    """카탈로그 로드(config/stickers.yaml). 없으면 빈 카탈로그."""
    path = path or STICKER_CONFIG_PATH
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return StickerCatalog()
    return StickerCatalog(**data)


def save_sticker_catalog(catalog: StickerCatalog, path: Path | None = None) -> None:
    """카탈로그를 YAML로 저장(유저가 열어 검수·수정)."""
    path = path or STICKER_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(catalog.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# --- 비전 자동 라벨링 ---
# 주의: 프롬프트에 상황 예시 목록을 넣으면 7b 모델이 내용 무시하고 그 예시를 그대로 베낀다.
# → 예시 없이 "글자 의미·표정에서 직접 유도"로 지시해야 내용 맞는 태그가 나온다(라이브 검증).
# 그래도 로컬 7b는 글자 환각·감정 오판이 잦아 자동 라벨은 초안일 뿐, config/stickers.yaml 검수가 정답.
STICKER_LABEL_PROMPT = (
    "이미지는 블로그용 스티커(이모티콘) 한 개입니다. JSON만 답하세요.\n"
    '형식: {"text":"스티커에 적힌 한글을 정확히(없으면 빈칸)","mood":"한 단어 감정",'
    '"tags":["상황"],"kind":"감정|헤더|구분선 중 하나"}\n'
    "글자를 먼저 읽고, 그 글자의 실제 뜻과 캐릭터 표정에서 감정·상황을 직접 끌어내세요. "
    "주어진 보기에서 고르지 말고 내용에 맞는 한국어 단어를 스스로 쓰세요. "
    "글자가 힘듦·피곤·짜증이면 기쁨이라 하지 마세요. tags는 2~3개.\n"
    "kind 판정: 캐릭터·표정이 주인공이고 감정이나 반응을 표현하면 '감정'. "
    "글자가 주인공인 소제목 라벨이나 안내문(고지) 배너, 말풍선 틀처럼 본문을 꾸미는 "
    "틀이면 '헤더' — 이때 tags 첫 항목은 적힌 라벨을 띄어쓰기 없이 그대로 쓰세요. "
    "구역을 나누는 가로선이나 작은 장식(꽃·별·점·리본 등)이 가로로 나란히 반복되는 "
    "띠면 '구분선' — 장식이나 캐릭터에 표정이 있어도 나란히 반복되는 배열이면 "
    "감정이 아니라 '구분선'입니다."
)

# 스티커 crop이 ~100px로 작아 한글 OCR이 뭉개짐 → 업스케일 후 비전에 전달(정확도 크게 향상).
_STICKER_UPSCALE = 3


def _upscaled_png(path: str, factor: int = _STICKER_UPSCALE) -> bytes:
    from io import BytesIO

    from PIL import Image

    im = Image.open(path).convert("RGB")
    im = im.resize((im.width * factor, im.height * factor), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def label_sticker(image_path: str, model: str | None = None) -> list[str]:
    """스티커 이미지 1개 → 감정/상황 태그 목록(비전 모델).

    작은 스티커는 업스케일해 한글 OCR 정확도를 높이고, mood+상황 태그를 합쳐 반환.
    kind 판정도 함께 받아 헤더형(제목 라벨·배너)이면 '헤더', 구분선형이면 '구분선' 태그를
    자동 부여한다 — 어느 유저의 카탈로그든 불러오기→태그 분석만으로 분류가 되게(검수로 교정).
    헤더형·구분선형은 감정이 아니므로 mood는 태그에 넣지 않는다.
    """
    from autoblog.vision import default_vision_model, vision_json

    model = model or default_vision_model()
    content = vision_json(STICKER_LABEL_PROMPT, [_upscaled_png(image_path)], model)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    kind = str(parsed.get("kind") or "").replace(" ", "")
    heading = "헤더" in kind or "제목" in kind or "배너" in kind
    divider = "구분" in kind
    out: list[str] = []
    mood = parsed.get("mood")
    if not heading and not divider and isinstance(mood, str) and mood.strip():
        out.append(mood.strip())
    tags = parsed.get("tags")
    if isinstance(tags, list):
        for t in tags:
            t = str(t).strip()
            if t and t not in out:
                out.append(t)
    if heading and not any(_is_heading_label(t) for t in out):
        out.append("헤더")
    if divider and not any(_is_divider_label(t) for t in out):
        out.append("구분선")
    return out


def _needs_label(s: Sticker, only_new: bool) -> bool:
    return not (s.stale or not s.image or (only_new and (s.tags or s.reviewed)))


def label_catalog(
    catalog: StickerCatalog,
    model: str | None = None,
    only_new: bool = True,
    on_progress=None,
    save_path: Path | None = None,
    save_every: int = 20,
    only_refs: set[str] | None = None,
) -> StickerCatalog:
    """카탈로그의 스티커들에 비전 태그 자동 부여(새 객체 반환).

    only_new=True면 태그가 비었고 검수 안 된 스티커만 라벨링(증분, 검수 보존).
    only_refs를 주면 그 ref(예: 즐겨찾기)만 라벨링 — 안 쓸 스티커까지 도는 낭비 방지.
    on_progress(done, total, sticker): 진행 콜백(선택) — 342개 등 대량일 때 진행 표시용.
    save_path 주면 save_every개마다 중간 저장(긴 작업 중 끊겨도 진행분 보존).
    """
    working = list(catalog.stickers)
    targets = [
        i
        for i, s in enumerate(working)
        if _needs_label(s, only_new) and (only_refs is None or s.ref in only_refs)
    ]
    total = len(targets)
    for done, i in enumerate(targets, 1):
        s = working[i]
        img = s.image if Path(s.image).is_absolute() else str(USER_DATA_DIR / s.image)
        try:
            tags = label_sticker(img, model)
        except Exception:  # noqa: BLE001 - 라벨링 실패해도 카탈로그는 유지
            tags = []
        working[i] = s.model_copy(update={"tags": tags or s.tags})
        if on_progress:
            on_progress(done, total, working[i])
        if save_path and done % save_every == 0:
            save_sticker_catalog(
                StickerCatalog(stickers=working, favorites=catalog.favorites), save_path
            )
    return StickerCatalog(stickers=working, favorites=catalog.favorites)
