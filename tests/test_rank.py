from autoblog import rank


def test_post_key_formats():
    assert rank._post_key("https://blog.naver.com/foo/223456") == ("foo", "223456")
    assert rank._post_key("https://m.blog.naver.com/foo/223456") == ("foo", "223456")
    assert rank._post_key(
        "https://blog.naver.com/PostView.naver?blogId=foo&logNo=223456"
    ) == ("foo", "223456")
    assert rank._post_key("https://example.tistory.com/12") is None


def test_find_rank():
    items = [{"link": f"https://blog.naver.com/u{i}/{1000 + i}"} for i in range(5)]
    assert rank.find_rank(items, "https://m.blog.naver.com/u2/1002") == 3
    assert rank.find_rank(items, "https://blog.naver.com/nope/9") is None


def test_add_dedupe_check_history(tmp_path, monkeypatch):
    monkeypatch.setattr(rank, "_RANKS_PATH", tmp_path / "ranks.json")
    rank.add_entry("성수동 맛집", "https://blog.naver.com/me/100")
    rank.add_entry("성수동 맛집", "https://m.blog.naver.com/me/100")  # 같은 글 다른 형식
    assert len(rank.list_entries()) == 1

    monkeypatch.setattr(
        rank, "_search_blog", lambda kw: [{"link": "https://blog.naver.com/me/100"}]
    )
    rows = rank.check_all()
    assert rows[0]["rank"] == 1 and rows[0]["prev"] is None
    rows = rank.check_all()
    assert rows[0]["prev"] == 1  # 직전 이력이 prev로

    assert rank.remove_entry("성수동 맛집", "https://blog.naver.com/me/100")
    assert rank.list_entries() == []


def test_keyword_competition_survives_volume_failure(monkeypatch):
    """검색량(부가) 조회가 터져도 경쟁 판정은 나와야 한다 — 아니면 칩에 판정이 안 뜬다."""
    monkeypatch.setattr(rank, "_search_blog_full", lambda kw: {"total": 42, "items": []})
    monkeypatch.setattr(
        rank, "search_volumes", lambda kws: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    d = rank.keyword_competition("강남맛집")
    assert d["total"] == 42 and d["volume"] is None
