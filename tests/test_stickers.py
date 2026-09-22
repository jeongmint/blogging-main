from autoblog.publish.stickers import (
    Sticker,
    StickerCatalog,
    StickerPicker,
    build_sticker_instruction,
    load_sticker_catalog,
    merge_catalog,
    save_sticker_catalog,
)


def test_label_catalog_favorites_only(monkeypatch):
    import autoblog.publish.stickers as st

    monkeypatch.setattr(st, "label_sticker", lambda img, model=None: ["테스트"])
    cat = StickerCatalog(
        stickers=[
            Sticker(pack="ogq_a", index=0, image="a/0.png"),
            Sticker(pack="ogq_a", index=1, image="a/1.png"),
            Sticker(pack="ogq_a", index=2, image="a/2.png", tags=["기존"]),  # 이미 태그 → 스킵
        ],
        favorites=["ogq_a:0"],
    )
    out = st.label_catalog(cat, only_refs={"ogq_a:0"})
    by = out.by_ref()
    assert by["ogq_a:0"].tags == ["테스트"]  # 즐겨찾기만 라벨
    assert by["ogq_a:1"].tags == []  # 즐겨찾기 아님 → 안 함
    assert by["ogq_a:2"].tags == ["기존"]  # 기존 보존


def test_label_sticker_kind_assigns_class_tags(tmp_path, monkeypatch):
    """비전 kind 판정 → '헤더'/'구분선' 태그 자동 부여(다른 유저 카탈로그도 분류되게)."""
    from PIL import Image

    import autoblog.vision as vision

    img = tmp_path / "s.png"
    Image.new("RGB", (8, 8)).save(img)
    answers = iter(
        [
            '{"text":"추천 대상","mood":"중립","tags":["추천대상"],"kind":"헤더"}',
            '{"text":"","mood":"기쁨","tags":["신남"],"kind":"감정"}',
            '{"text":"","mood":"","tags":["장식"],"kind":"구분선"}',
        ]
    )
    monkeypatch.setattr(vision, "default_vision_model", lambda: "m")
    monkeypatch.setattr(vision, "vision_json", lambda *a, **k: next(answers))
    from autoblog.publish.stickers import label_sticker

    # 헤더형: mood 제외 + '헤더' 부여 → is_heading 성립
    assert label_sticker(str(img)) == ["추천대상", "헤더"]
    # 감정형: 기존 그대로(mood 먼저)
    assert label_sticker(str(img)) == ["기쁨", "신남"]
    # 구분선형: '구분선' 부여 → 구분선 지시문 분류에 걸림
    assert label_sticker(str(img)) == ["장식", "구분선"]


def test_crop_sprite_grid():
    from io import BytesIO

    from PIL import Image

    from autoblog.publish.stickers import crop_sprite

    # 324x800 스프라이트(3열 8행, 셀 108x100) 가정 — 셀 위치별로 다른 색 칠해 크롭 검증
    sprite = Image.new("RGBA", (324, 800), (255, 255, 255, 255))
    for r in range(8):
        for c in range(3):
            idx = r * 3 + c
            for x in range(c * 108, (c + 1) * 108):
                for y in range(r * 100, (r + 1) * 100):
                    sprite.putpixel((x, y), (idx, idx, idx, 255))
    buf = BytesIO()
    sprite.save(buf, format="PNG")
    raw = buf.getvalue()
    # index 4 → (col1,row1), scale=1이면 108x100, 단색 idx=4
    out = crop_sprite(raw, cols=3, count=24, index=4, scale=1)
    cell = Image.open(BytesIO(out))
    assert cell.size == (108, 100)
    assert cell.getpixel((50, 50))[0] == 4
    # scale=2면 2배
    assert Image.open(BytesIO(crop_sprite(raw, 3, 24, 0, scale=2))).size == (216, 200)


def test_sticker_instruction_lists_labels():
    instr = build_sticker_instruction(["맛있음", "기쁨", "", "기쁨"])
    assert instr is not None
    assert "맛있음" in instr and "기쁨" in instr
    assert "[스티커:상황]" in instr
    assert build_sticker_instruction([]) is None
    assert build_sticker_instruction(["  "]) is None


def _cat():
    return StickerCatalog(
        stickers=[
            Sticker(pack="ogq_a", index=0, tags=["기쁨", "좋아요"], image="data/stickers/ogq_a/0.png"),
            Sticker(pack="ogq_a", index=1, tags=["기쁨"], image="data/stickers/ogq_a/1.png"),
            Sticker(pack="ogq_b", index=0, tags=["기쁨", "감사"], image="data/stickers/ogq_b/0.png"),
            Sticker(pack="ogq_b", index=5, tags=["슬픔"], image="data/stickers/ogq_b/5.png"),
        ],
        favorites=["ogq_b:0"],
    )


def test_merge_adds_new_preserves_old_marks_stale():
    existing = StickerCatalog(
        stickers=[
            Sticker(pack="ogq_a", index=0, tags=["기쁨"], reviewed=True, image="old.png"),
            Sticker(pack="ogq_a", index=9, tags=["옛날"]),  # 스크랩에 없음 → stale
        ],
        favorites=["ogq_a:0"],
    )
    scraped = [
        Sticker(pack="ogq_a", index=0, image="new.png", animated=True),  # 기존 → 태그/검수 보존
        Sticker(pack="ogq_a", index=1, image="n1.png"),  # 신규
    ]
    merged = merge_catalog(existing, scraped)
    by = merged.by_ref()
    # 기존 검수/태그 보존 + 이미지/animated 갱신 + stale 해제
    assert by["ogq_a:0"].tags == ["기쁨"] and by["ogq_a:0"].reviewed is True
    assert by["ogq_a:0"].image == "new.png" and by["ogq_a:0"].animated is True
    assert by["ogq_a:0"].stale is False
    # 신규는 태그 비어 라벨링 대상
    assert by["ogq_a:1"].tags == []
    # 스크랩에 없던 기존은 stale(삭제 안 함)
    assert by["ogq_a:9"].stale is True
    assert merged.favorites == ["ogq_a:0"]


def test_find_prioritizes_favorites_and_skips_stale():
    cat = _cat()
    hits = cat.find("기쁨", favorites_only=False)  # 전체 후보, 즐겨쓰기 우선 정렬
    assert [s.ref for s in hits][0] == "ogq_b:0"  # 즐겨쓰기 우선
    assert {s.ref for s in hits} == {"ogq_a:0", "ogq_a:1", "ogq_b:0"}
    # stale 제외
    cat.stickers[0].stale = True
    assert "ogq_a:0" not in {s.ref for s in cat.find("기쁨", favorites_only=False)}


def test_picker_dedup_and_no_match():
    picker = StickerPicker(_cat(), favorites_only=False)  # 다중 후보 → 중복 회피 검증
    a = picker.pick("기쁨")
    b = picker.pick("기쁨")
    assert a.ref != b.ref  # 같은 라벨 반복 시 다른 스티커
    assert picker.pick("없는상황") is None


def test_picker_consistency_locks_pack():
    picker = StickerPicker(_cat(), consistent=True, favorites_only=False)
    first = picker.pick("기쁨")  # 즐겨쓰기 우선 → ogq_b:0
    assert first.pack == "ogq_b"
    # 통일성: 이후 같은 팩으로 고정. '감사'도 ogq_b에 있음
    assert picker.pick("감사").pack == "ogq_b"
    # ogq_b에 없는 라벨이면 후보가 없어 None
    assert picker.pick("슬픔").pack == "ogq_b"  # 슬픔=ogq_b:5 → 같은 팩 OK


def test_picker_empty_label_uses_favorites():
    picker = StickerPicker(_cat())
    s = picker.pick("")
    assert s.ref == "ogq_b:0"  # 즐겨쓰기


def _cat_with_heading():
    """헤더형('헤더' 태그) + 감정형이 섞인 카탈로그. '꿀팁'은 양쪽에 있는 실제 사례."""
    return StickerCatalog(
        stickers=[
            Sticker(pack="ogq_h", index=13, tags=["꿀팁", "헤더"], image="h/13.png"),
            Sticker(pack="ogq_h", index=18, tags=["추천대상", "헤더"], image="h/18.png"),
            Sticker(pack="ogq_m", index=15, tags=["꿀팁"], image="m/15.png"),
            Sticker(pack="ogq_m", index=4, tags=["좋아요"], image="m/4.png"),
        ],
        favorites=["ogq_h:13", "ogq_h:18", "ogq_m:15", "ogq_m:4"],
    )


def test_heading_stickers_hidden_from_labels():
    labels = _cat_with_heading().labels()
    # 헤더형 태그는 LLM 노출 목록에서 제외('헤더' 표시 태그 자체도)
    assert "추천대상" not in labels and "헤더" not in labels
    # 감정형의 같은 이름 태그는 유지
    assert "꿀팁" in labels and "좋아요" in labels


def test_heading_sticker_manual_marker_still_resolves():
    picker = StickerPicker(_cat_with_heading())
    # [스티커:추천대상] 수동 마커 — 헤더형이어도 태그 직접 지목은 해석된다
    assert picker.pick("추천대상").ref == "ogq_h:18"


def test_shared_label_prefers_mood_over_heading():
    cat = _cat_with_heading()
    # '꿀팁'은 헤더형(ogq_h:13, 카탈로그 순서상 앞)과 감정형(ogq_m:15) 둘 다 —
    # 감정 자리에 제목 라벨이 붙지 않게 감정형이 먼저
    assert cat.find("꿀팁")[0].ref == "ogq_m:15"


def test_empty_label_pick_skips_heading():
    picker = StickerPicker(_cat_with_heading())
    # 라벨 없는 자동 선택([스티커]·빈문단 채움)은 즐겨찾기 순서상 앞인 헤더형을 건너뛴다
    assert picker.pick("").ref == "ogq_m:15"


def test_empty_label_pick_skips_divider():
    # 라벨 없는 자동 선택은 감정형만 — 구분선형은 화제 전환 자리 전용이라 건너뛴다
    cat = StickerCatalog(
        stickers=[
            Sticker(pack="p", index=0, tags=["구분선"], image="p/0.png"),
            Sticker(pack="p", index=1, tags=["기쁨"], image="p/1.png"),
        ],
        favorites=["p:0", "p:1"],
    )
    assert StickerPicker(cat).pick("").ref == "p:1"


def test_sticker_instruction_divider_no_stacking():
    # 구분선 스티커 안내에 네이티브 [구분선]과 겹치지 말라는 지시가 포함된다
    instr = build_sticker_instruction(["기쁨", "구분선"])
    assert "겹쳐 쓰지 마세요" in instr


def test_kind_property_precedence():
    from autoblog.publish.stickers import Sticker

    assert Sticker(pack="p", index=0, tags=["기쁨"]).kind == "감정"
    assert Sticker(pack="p", index=1, tags=["구분선", "가로"]).kind == "구분선"
    assert Sticker(pack="p", index=2, tags=["추천대상", "헤더"]).kind == "헤더"
    # 헤더 마커가 있으면 구분선 마커보다 우선(자동 사용 제외가 안전한 쪽)
    assert Sticker(pack="p", index=3, tags=["헤더", "구분선"]).kind == "헤더"


def test_apply_kind_swaps_markers_keeps_labels():
    from autoblog.publish.stickers import Sticker, apply_kind

    s = Sticker(pack="p", index=0, tags=["추천대상", "헤더"])
    apply_kind(s, "감정")  # 헤더 → 감정: 마커만 빠지고 상황 태그는 보존
    assert s.kind == "감정" and s.tags == ["추천대상"]
    apply_kind(s, "구분선")
    assert s.kind == "구분선" and s.tags == ["추천대상", "구분선"]
    apply_kind(s, "헤더")
    assert s.kind == "헤더" and s.tags == ["추천대상", "헤더"]
    apply_kind(s, "없는분류")  # 모르는 값은 무시
    assert s.kind == "헤더"


def test_divider_sticker_side_tags_not_exposed_as_mood():
    cat = StickerCatalog(
        stickers=[
            Sticker(pack="p", index=0, tags=["구분선", "가로"], image="p/0.png"),
            Sticker(pack="p", index=1, tags=["기쁨"], image="p/1.png"),
        ],
        favorites=["p:0", "p:1"],
    )
    labels = cat.labels()
    # 구분선형의 곁태그('가로')가 감정 목록에 새지 않는다(스티커 단위 분류 유지)
    assert "가로" not in labels
    assert "구분선" in labels and "기쁨" in labels


def test_labels_distinct_excludes_stale():
    cat = _cat()
    cat.stickers[3].stale = True  # 슬픔 제거
    # 전체 후보 기준으로 stale 제외를 검증(기본값 favorites_only=True면 즐겨찾기 태그만
    # 나와 stale 검증이 무의미해진다 — '좋아요'는 즐겨찾기 아님).
    labels = cat.labels(favorites_only=False)
    assert "기쁨" in labels and "감사" in labels and "좋아요" in labels
    assert "슬픔" not in labels


def test_yaml_round_trip(tmp_path):
    cat = _cat()
    p = tmp_path / "stickers.yaml"
    save_sticker_catalog(cat, p)
    loaded = load_sticker_catalog(p)
    assert loaded.model_dump() == cat.model_dump()
    # 없는 파일은 빈 카탈로그
    assert load_sticker_catalog(tmp_path / "none.yaml").stickers == []
