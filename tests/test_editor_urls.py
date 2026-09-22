"""_original_url_candidates — 에디터 축소본 src → 원본 화질 후보 순서."""

from autoblog.publish.editor import _original_url_candidates


def test_typed_thumbnail_tries_original_first():
    src = "https://postfiles.pstatic.net/MjAy/blog/banner.gif?type=w966"
    assert _original_url_candidates(src) == [
        "https://postfiles.pstatic.net/MjAy/blog/banner.gif",
        "https://postfiles.pstatic.net/MjAy/blog/banner.gif?type=w3840",
        src,
    ]


def test_no_query_src_stays_single():
    src = "https://blogfiles.pstatic.net/MjAy/blog/photo.jpg"
    cands = _original_url_candidates(src)
    assert cands[0] == src  # 이미 원본 — 그대로 1순위


def test_other_params_survive_type_removal():
    src = "https://postfiles.pstatic.net/a/b.png?abc=1&type=w773"
    assert _original_url_candidates(src)[0] == "https://postfiles.pstatic.net/a/b.png?abc=1"


# --- 예약 발행 fail-closed 가드 ---
def test_reserve_ready_reflects_selectors(monkeypatch):
    from autoblog.collect import selectors
    from autoblog.publish import editor

    # 셀렉터가 채워져 있으면(라이브 검증 완료) 예약 준비됨.
    assert editor.reserve_ready() is True
    # 하나라도 비면 미준비(fail-closed).
    monkeypatch.setitem(selectors.SMART_EDITOR, "reserve_hour_select", "")
    assert editor.reserve_ready() is False


def test_submit_reserved_fails_closed_when_not_ready(monkeypatch):
    # 예약 셀렉터가 비면(미검증 상태 시뮬레이션) 페이지를 건드리기도 전에 예외를 던져
    # '즉시 발행' 사고를 막는다(_page 접근 없이 가드가 먼저 걸린다).
    from datetime import datetime, timedelta

    from autoblog.collect import selectors
    from autoblog.publish.editor import BlogPublisher

    monkeypatch.setitem(selectors.SMART_EDITOR, "reserve_date_input", "")
    pub = BlogPublisher.__new__(BlogPublisher)  # __init__ 없이 — _page 미설정
    try:
        pub._submit_reserved(datetime.now() + timedelta(hours=1), None)
        raise AssertionError("예약 미준비인데 예외가 안 났다")
    except RuntimeError as e:
        assert "준비되지 않" in str(e)
