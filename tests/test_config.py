from autoblog.config import save_env_value


def test_save_env_value_add_and_update(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\nNAVER_BLOG_ID=old\n", encoding="utf-8")

    save_env_value("NAVER_BLOG_ID", "noino0819", path=env_path)
    text = env_path.read_text(encoding="utf-8")
    assert "NAVER_BLOG_ID=noino0819" in text
    assert "NAVER_BLOG_ID=old" not in text  # 갱신됨
    assert "EXISTING=1" in text  # 기존 값 보존

    # 새 키 추가
    save_env_value("NEW_KEY", "v", path=env_path)
    assert "NEW_KEY=v" in env_path.read_text(encoding="utf-8")
