"""장소 카드 검색 완화 질의·주소 대조 — '차지 강남플래그십점' 0건 사례."""

from autoblog.publish.editor import BlogPublisher


def test_branch_suffix_stripped_as_fallback():
    assert BlogPublisher._place_query_variants("차지 강남플래그십점") == ["차지 강남플래그십점", "차지"]


def test_no_branch_suffix_keeps_single_query():
    assert BlogPublisher._place_query_variants("스타벅스") == ["스타벅스"]


def test_addr_matches_ignores_sido_form_and_spaces():
    assert BlogPublisher._addr_matches("서울특별시 서초구 강남대로 407", "서울 서초구 강남대로 407")
    assert not BlogPublisher._addr_matches("서울특별시 마포구 양화로 1", "서울 서초구 강남대로 407")
    assert not BlogPublisher._addr_matches("서울 서초구 강남대로 407", None)  # 주소 없으면 대조 불가
