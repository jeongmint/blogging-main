"""네이버 블로그 인기글 수집 — 문체(페르소나) 학습용 (기획서 §4.2 확장).

모바일 블로그 홈 상단의 '인기글' 목록을 그대로 가져온다(공감순 랭킹).
공개 API: m.blog.naver.com/api/blogs/{blogId}/popular-post-list — 캡차 없이 동작.
각 글 본문은 모바일 PostView의 se-main-container에서 텍스트만 추출한다.
"""

from __future__ import annotations

import html as _html
import re
from urllib.parse import parse_qs, urlparse

import requests

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Safari/604.1"
)


def _headers(blog_id: str) -> dict[str, str]:
    return {
        "User-Agent": _MOBILE_UA,
        "Referer": f"https://m.blog.naver.com/{blog_id}",
        "Accept": "application/json, text/plain, */*",
    }


def parse_blog_id(text: str) -> str:
    """블로그 주소/ID 문자열 → 블로그 ID.

    허용: 'noino0819', 'blog.naver.com/noino0819[/...]',
    'm.blog.naver.com/noino0819', '...PostView.naver?blogId=...', 'naver.me/단축링크'.
    """
    s = (text or "").strip()
    if not s:
        raise ValueError("블로그 주소가 비었습니다")

    # naver.me 단축 링크는 리다이렉트를 따라가 실제 주소를 얻는다
    if "naver.me/" in s:
        try:
            resp = requests.get(
                s if s.startswith("http") else f"https://{s}",
                headers={"User-Agent": _MOBILE_UA},
                timeout=12,
                allow_redirects=True,
            )
            s = resp.url
        except requests.RequestException:
            pass  # 실패 시 아래 일반 파싱으로 진행

    if "naver.com" not in s and "/" not in s and " " not in s:
        return s  # 맨 ID만 입력한 경우

    if not s.startswith("http"):
        s = "https://" + s
    u = urlparse(s)
    qs = parse_qs(u.query)
    if qs.get("blogId"):
        return qs["blogId"][0]
    # 경로 첫 조각이 블로그 ID (blog.naver.com/{id}/{logNo} 형태)
    parts = [p for p in u.path.split("/") if p]
    if parts and parts[0].lower() not in ("postview.naver", "postlist.naver"):
        return parts[0]
    raise ValueError(f"블로그 ID를 찾지 못했습니다: {text!r}")


def fetch_popular_posts(blog_id: str, n: int = 5) -> list[dict]:
    """인기글 목록(공감순) 상위 n개 메타데이터.

    반환 항목: {logNo, title, sympathy, comments, brief, url}.
    """
    url = f"https://m.blog.naver.com/api/blogs/{blog_id}/popular-post-list"
    resp = requests.get(url, headers=_headers(blog_id), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("isSuccess"):
        raise RuntimeError(f"인기글 목록을 가져오지 못했습니다 (blogId={blog_id})")
    posts = (data.get("result") or {}).get("popularPostList") or []
    out: list[dict] = []
    for p in posts[: max(n, 0)]:
        log_no = str(p.get("logNo", "")).strip()
        if not log_no:
            continue
        out.append(
            {
                "logNo": log_no,
                "title": _html.unescape(p.get("titleWithInspectMessage") or "").strip(),
                "sympathy": int(p.get("sympathyCnt") or 0),
                "comments": int(p.get("commentCnt") or 0),
                "brief": (p.get("briefContents") or "").strip(),
                "url": f"https://blog.naver.com/{blog_id}/{log_no}",
            }
        )
    return out


def fetch_recent_posts(blog_id: str, n: int = 5) -> list[dict]:
    """최신글(전체글 발행일순) 상위 n개 메타데이터.

    공개 API: m.blog.naver.com/api/blogs/{blogId}/post-list?categoryNo=0 — 캡차 없이 동작.
    반환 항목: {logNo, title, sympathy, comments, brief, url}(인기글과 같은 형태).
    """
    url = f"https://m.blog.naver.com/api/blogs/{blog_id}/post-list"
    params = {"categoryNo": 0, "itemCount": max(n, 0), "page": 1}
    resp = requests.get(url, headers=_headers(blog_id), params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("isSuccess"):
        raise RuntimeError(f"최신글 목록을 가져오지 못했습니다 (blogId={blog_id})")
    posts = (data.get("result") or {}).get("items") or []
    out: list[dict] = []
    for p in posts[: max(n, 0)]:
        log_no = str(p.get("logNo", "")).strip()
        if not log_no:
            continue
        out.append(
            {
                "logNo": log_no,
                "title": _html.unescape(p.get("titleWithInspectMessage") or "").strip(),
                "sympathy": int(p.get("sympathyCnt") or 0),
                "comments": int(p.get("commentCnt") or 0),
                "brief": (p.get("briefContents") or "").strip(),
                "url": f"https://blog.naver.com/{blog_id}/{log_no}",
            }
        )
    return out


# 본문 끝으로 볼 수 있는 트레일러 마커(가장 먼저 나오는 곳에서 자른다)
_BODY_END_MARKERS = (
    '<div class="post_footer',
    'class="area_sympathy',
    'class="post_btn',
    'id="floating',
    "<!-- // 본문",
)


def fetch_post_text(blog_id: str, log_no: str, max_chars: int = 2500) -> str:
    """모바일 PostView 본문(se-main-container)에서 텍스트만 추출.

    스크립트·태그를 제거하고 문단 구분을 보존한 뒤 max_chars로 자른다(문체 학습엔 충분).
    """
    url = f"https://m.blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
    resp = requests.get(url, headers={"User-Agent": _MOBILE_UA}, timeout=15)
    resp.raise_for_status()
    page = resp.text
    m = re.search(r'<div class="se-main-container">(.*)', page, re.S)
    seg = m.group(1) if m else page
    cut = len(seg)
    for marker in _BODY_END_MARKERS:
        i = seg.find(marker)
        if i != -1:
            cut = min(cut, i)
    seg = seg[:cut]
    seg = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", seg, flags=re.S | re.I)
    seg = re.sub(r"<(br|/p|/div|/h\d|/li)\b[^>]*>", "\n", seg, flags=re.I)
    seg = re.sub(r"<[^>]+>", " ", seg)
    seg = _html.unescape(seg)
    seg = re.sub(r"[ \t​]+", " ", seg)
    seg = re.sub(r"\n[ \t]*", "\n", seg)
    seg = re.sub(r"\n{2,}", "\n", seg).strip()
    return seg[:max_chars]


def collect_style_samples(
    blog_id: str,
    log_nos: list[str] | None = None,
    n: int = 5,
    per_post_chars: int = 2500,
    source: str = "popular",
) -> list[dict]:
    """글 상위 n개(또는 지정한 log_nos)의 본문을 모아 문체 학습 재료로 반환.

    source: "popular"(인기글, 공감순) 또는 "recent"(최신글, 발행일순).
    반환 항목: {logNo, title, url, text}. 본문 비거나 실패한 글은 건너뛴다.
    """
    if log_nos:
        metas = [{"logNo": str(x), "title": "", "url": f"https://blog.naver.com/{blog_id}/{x}"} for x in log_nos]
    elif source == "recent":
        metas = fetch_recent_posts(blog_id, n=n)
    else:
        metas = fetch_popular_posts(blog_id, n=n)
    samples: list[dict] = []
    for meta in metas:
        try:
            text = fetch_post_text(blog_id, meta["logNo"], max_chars=per_post_chars)
        except requests.RequestException:
            continue
        if text:
            samples.append({**meta, "text": text})
    return samples
