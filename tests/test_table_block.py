"""마크다운 표 → table 블록 파싱 — 리스타일 출력의 `| a | b |`가 네이티브 표로 가는 경로."""

from autoblog.draft.generate import DraftResult
from autoblog.publish.plan import build_publish_plan, parse_md_table


def test_parse_md_table_valid():
    rows = parse_md_table(["| 메뉴 | 칼로리 |", "|---|---|", "| 아메리카노 | 5kcal |", "| 라떼 | 433kcal |"])
    assert rows == [["메뉴", "칼로리"], ["아메리카노", "5kcal"], ["라떼", "433kcal"]]


def test_parse_md_table_needs_separator():
    # 구분행(|---|)이 없으면 표가 아님 → None(본문 텍스트로 되돌림)
    assert parse_md_table(["| a | b |", "| c | d |"]) is None


def test_build_plan_emits_table_block():
    draft = DraftResult(
        text="빽다방 칼로리 정리\n\n인트로 문장입니다.\n\n| 메뉴 | 칼로리 |\n|---|---|\n| 아메리카노 | 5kcal |\n| 바닐라라떼 | 433kcal |\n\n마무리 문장이에요.",
    )
    plan = build_publish_plan(draft, photos=[])
    kinds = [b.kind for b in plan.blocks]
    assert "table" in kinds
    tbl = next(b for b in plan.blocks if b.kind == "table")
    assert tbl.table_rows[0] == ["메뉴", "칼로리"]
    assert ["바닐라라떼", "433kcal"] in tbl.table_rows
    # 표 앞뒤 문장은 텍스트로 살아 있어야 한다(표가 본문을 삼키면 안 됨)
    texts = " ".join(b.text for b in plan.blocks if b.kind == "text")
    assert "인트로" in texts and "마무리" in texts
    # 파이프 문자가 본문 텍스트로 새지 않아야 한다
    assert "|" not in texts


def test_fake_table_stays_text():
    # 구분행 없는 파이프 줄은 표로 오인하지 말고 본문 텍스트로 남긴다
    draft = DraftResult(text="제목\n\n본문이에요.\n\n| 이건 | 표가아님 |\n\n끝.")
    plan = build_publish_plan(draft, photos=[])
    assert all(b.kind != "table" for b in plan.blocks)


def test_enforce_format_keeps_table_rows():
    # 30자 줄바꿈이 표 행을 쪼개면 plan이 표로 못 읽는다 → 파이프 줄은 원형 유지
    from autoblog.draft.postprocess import enforce_format

    out = enforce_format(
        "제목입니다\n\n본문이에요.\n\n| 정보 | 내용 |\n|---|---|\n"
        "| 영업시간 | 목~화 10:30~21:00 (L.O. 20:30) |\n| 휴무일 | 매주 수요일 |\n\n끝."
    )
    assert "| 영업시간 | 목-화 10:30-21:00 (L.O. 20:30) |" in out  # ~→- 치환은 본문 규칙
    plan = build_publish_plan(DraftResult(text=out), photos=[])
    tbl = next(b for b in plan.blocks if b.kind == "table")
    assert ["휴무일", "매주 수요일"] in tbl.table_rows
