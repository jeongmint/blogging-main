"""문체 프로파일 정규화(normalize_profile) — 추출·붙여넣기 결과가 기본 페르소나 형식이 되는지."""

from autoblog.draft.style import normalize_profile


def test_normalize_strips_preamble_bold_numbering_fence():
    raw = (
        "네! 문체 분석 결과입니다.\n\n"
        "```\n"
        "1. **문장 길이/호흡:** 짧게 끊어 리듬감 있게.\n"
        "2. **자주 쓰는 어미·말투**: \"~더라구요\"로 끝맺음.\n"
        "- 존댓말/반말: 존댓말 기반,\n"
        "  친근한 구어체.\n"
        "```\n"
        "도움이 되셨길 바랍니다!\n"
    )
    out = normalize_profile(raw)
    assert out.splitlines() == [
        "- 문장 길이/호흡: 짧게 끊어 리듬감 있게.",
        '- 자주 쓰는 어미·말투: "~더라구요"로 끝맺음.',
        "- 존댓말/반말: 존댓말 기반, 친근한 구어체.",
    ]


def test_normalize_reorders_to_template_order():
    raw = (
        "- 전체 톤 한 줄 요약: 다정한 후기 톤.\n"
        "- 문장 길이/호흡: 짧다.\n"
        "- 존댓말/반말: 존댓말.\n"
    )
    out = normalize_profile(raw)
    assert out.splitlines()[0] == "- 문장 길이/호흡: 짧다."
    assert out.splitlines()[-1] == "- 전체 톤 한 줄 요약: 다정한 후기 톤."


def test_normalize_keeps_freeform_profile():
    raw = "친한 언니가 조곤조곤 얘기해주는 톤. 반말 섞인 존댓말."
    assert normalize_profile(raw) == raw
