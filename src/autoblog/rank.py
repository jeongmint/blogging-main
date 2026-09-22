"""키워드 순위 추적 — 게시한 글이 블로그 검색에서 몇 위에 뜨는지 실측.

블로그 검색 API(sort=sim, 상위 100위)는 블로그탭 정확도순 근사치다 —
통합검색 스마트블록 순서와 다를 수 있고 AI 브리핑 인용 여부는 알 수 없다.
목적은 글별 노출 추이(진입·등락·이탈)를 데이터로 남겨 감이 아닌 실측으로
검증하는 것. 검색 API 키(.env)를 그대로 쓴다(일 25,000회 무료).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone

import requests

from autoblog.config import DATA_DIR, load_env

_BLOG_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/blog"
_AUTOCOMPLETE_URL = "https://ac.search.naver.com/nx/ac"  # 자동완성=연관검색어, 키 불필요
_SEARCHAD_URL = "https://api.searchad.naver.com"  # 검색광고 API — 월간 검색량(키워드 도구)
_RANKS_PATH = DATA_DIR / "ranks.json"
# 게시글 URL → (blogId, logNo). 데스크톱/모바일/PostView 형식 모두 수용.
_POST_RE = re.compile(
    r"blog\.naver\.com/(?:PostView\.naver\?blogId=([\w.-]+)&logNo=(\d+)|([\w.-]+)/(\d+))"
)


def _post_key(url: str) -> tuple[str, str] | None:
    m = _POST_RE.search(url or "")
    if not m:
        return None
    return (m.group(1) or m.group(3), m.group(2) or m.group(4))


def _load() -> list[dict]:
    if _RANKS_PATH.exists():
        try:
            return json.loads(_RANKS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(entries: list[dict]) -> None:
    _RANKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RANKS_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")


def add_entry(keyword: str, url: str) -> dict:
    """추적 항목 등록. 같은 (키워드, 글) 조합은 중복 등록하지 않는다."""
    keyword = keyword.strip()
    url = url.strip()
    if not keyword:
        raise ValueError("키워드가 비어 있어요")
    if _post_key(url) is None:
        raise ValueError("네이버 블로그 글 URL이 아니에요 (blog.naver.com/아이디/글번호 형식)")
    entries = _load()
    for e in entries:
        if e["keyword"] == keyword and _post_key(e["url"]) == _post_key(url):
            return e
    entry = {
        "keyword": keyword,
        "url": url,
        "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "history": [],
    }
    entries.append(entry)
    _save(entries)
    return entry


def remove_entry(keyword: str, url: str) -> bool:
    entries = _load()
    kept = [
        e for e in entries
        if not (e["keyword"] == keyword.strip() and _post_key(e["url"]) == _post_key(url))
    ]
    if len(kept) == len(entries):
        return False
    _save(kept)
    return True


def find_rank(items: list[dict], url: str) -> int | None:
    """검색 결과 목록에서 해당 글의 순위(1부터). 100위 밖이면 None."""
    key = _post_key(url)
    if key is None:
        return None
    for i, item in enumerate(items, 1):
        if _post_key(item.get("link", "")) == key:
            return i
    return None


def _search_blog_full(keyword: str) -> dict:
    env = load_env()
    if not env.has_naver_api:
        raise RuntimeError("검색 API 키 미설정 (.env의 NAVER_CLIENT_ID/SECRET)")
    resp = requests.get(
        _BLOG_SEARCH_URL,
        params={"query": keyword, "display": 100, "sort": "sim"},
        headers={
            "X-NCP-APIGW-API-KEY-ID": env.naver_client_id or "",
            "X-NCP-APIGW-API-KEY": env.naver_client_secret or "",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _search_blog(keyword: str) -> list[dict]:
    return _search_blog_full(keyword).get("items", [])


_TAG_RE = re.compile(r"<[^>]+>")


def keyword_competition(keyword: str) -> dict:
    """발행 전 키워드 경쟁 가늠 — 블로그 문서수(경쟁량) + 현재 상위결과 + 내 글 순위.

    검색광고 API가 없어 '검색량'은 못 주고, 대신 openapi 블로그 검색으로
    '이미 쓰인 문서 수'(경쟁강도의 대리 지표)와 상위 결과 면면을 보여준다.
    공식 저경쟁 임계값은 존재하지 않으므로(리서치 검증), total은 참고용 상대 신호이고
    실제 판단은 top(상위 블로그가 대형매체·최적화 블로그로 꽉 찼는지)과 mine(내 글이
    이미 top100에 드는지)으로 눈으로 한다.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        raise ValueError("키워드가 비어 있어요")
    data = _search_blog_full(keyword)
    items = data.get("items", [])
    blog_id = (load_env().naver_blog_id or "").strip().lower()
    mine = None
    if blog_id:
        for i, it in enumerate(items, 1):
            link = (it.get("link", "") + " " + it.get("bloggerlink", "")).lower()
            if f"blog.naver.com/{blog_id}" in link or f"/{blog_id}" in link:
                mine = i
                break
    top = [
        {
            "title": _TAG_RE.sub("", it.get("title", "")).replace("&amp;", "&").strip(),
            "blogger": it.get("bloggername", ""),
            "link": it.get("link", ""),
        }
        for it in items[:5]
    ]
    # 검색량은 부가 정보 — 여기서 터지면 멀쩡한 경쟁 판정까지 통째로 날아간다(→ 칩에 판정 안 뜸)
    try:
        vol = search_volumes([keyword]).get(keyword) or {}
    except Exception:  # noqa: BLE001
        vol = {}
    return {
        "keyword": keyword, "total": data.get("total", 0), "mine": mine, "top": top,
        "volume": vol.get("volume"),  # 월간 검색수(PC+모바일) — 검색광고 키 없으면 None
        "comp_idx": vol.get("comp_idx", ""),
    }


def _searchad_headers(method: str, path: str) -> dict:
    """검색광고 API 인증 헤더 — {timestamp}.{method}.{path}를 비밀키로 HMAC-SHA256 서명."""
    env = load_env()
    ts = str(round(time.time() * 1000))
    sig = base64.b64encode(
        hmac.new(
            (env.searchad_secret or "").encode(),
            f"{ts}.{method}.{path}".encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    return {
        "X-Timestamp": ts,
        "X-API-KEY": env.searchad_api_key or "",
        "X-Customer": env.searchad_customer_id or "",
        "X-Signature": sig,
    }


def _qc(v) -> int:
    """월간 검색수 필드 파싱 — 10 미만이면 '< 10' 문자열로 오므로 5로 근사."""
    if isinstance(v, str):
        return 5 if "<" in v else int(re.sub(r"[^\d]", "", v) or 0)
    return int(v or 0)


def search_volumes(keywords: list[str]) -> dict[str, dict]:
    """키워드별 월간 검색수(PC+모바일)·광고 경쟁도. 검색광고 키 미설정이면 {}.

    keywordstool의 hintKeywords는 공백 불가·한 번에 5개까지라, 공백을 뺀 형태로
    5개씩 끊어 조회하고 응답 relKeyword(공백 없는 대문자)를 원래 키워드로 되맞춘다.
    검색량은 부가 정보라 개별 실패는 건너뛴다(경쟁도만으로도 동작해야 함).
    """
    if not load_env().has_searchad:
        return {}
    want = {}  # 정규화(공백 제거·대문자) → 원래 키워드
    for kw in keywords:
        k = (kw or "").strip()
        if k:
            want.setdefault(k.replace(" ", "").upper(), k)
    out: dict[str, dict] = {}
    hints = list(want.keys())
    for i in range(0, len(hints), 5):
        try:
            resp = requests.get(
                _SEARCHAD_URL + "/keywordstool",
                params={"hintKeywords": ",".join(hints[i : i + 5]), "showDetail": 1},
                headers=_searchad_headers("GET", "/keywordstool"),
                timeout=10,
            )
            resp.raise_for_status()
            # 응답엔 힌트 외 연관 키워드도 잔뜩 오므로, 요청한 것만 골라 담는다.
            for row in resp.json().get("keywordList", []) or []:
                orig = want.get((row.get("relKeyword") or "").replace(" ", "").upper())
                if orig and orig not in out:
                    out[orig] = {
                        "volume": _qc(row.get("monthlyPcQcCnt")) + _qc(row.get("monthlyMobileQcCnt")),
                        "comp_idx": row.get("compIdx") or "",  # 광고 입찰 경쟁도(낮음/중간/높음)
                    }
        except Exception:  # noqa: BLE001
            continue
    return out


def _searchad_related(keyword: str, limit: int) -> list[dict]:
    """keywordstool이 힌트 외에 얹어 주는 연관 키워드 — 검색량이 이미 붙어 온다.

    자동완성과 달리 광고 시장 기준 연관어라 엉뚱한 지역·주제가 섞인다. 원 키워드
    토큰을 전부 포함하는 세부 롱테일만 남기고, 검색량순 상위 limit개만 쓴다.
    """
    tokens = [t.lower() for t in keyword.split()]
    try:
        resp = requests.get(
            _SEARCHAD_URL + "/keywordstool",
            params={"hintKeywords": keyword.replace(" ", ""), "showDetail": 1},
            headers=_searchad_headers("GET", "/keywordstool"),
            timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json().get("keywordList", []) or []
    except Exception:  # noqa: BLE001 — 부가 후보라 실패해도 자동완성만으로 동작
        return []
    out = [
        {
            "keyword": t,
            "volume": _qc(row.get("monthlyPcQcCnt")) + _qc(row.get("monthlyMobileQcCnt")),
        }
        for row in rows
        if (t := (row.get("relKeyword") or "").strip())
        and all(tok in t.replace(" ", "").lower() for tok in tokens)
    ]
    out.sort(key=lambda x: x["volume"], reverse=True)
    return out[:limit]


def _related_terms(keyword: str) -> list[str]:
    """네이버 자동완성(=연관검색어) — 검색창에 뜨는 추천어. 공개 엔드포인트라 키 불필요."""
    resp = requests.get(
        _AUTOCOMPLETE_URL,
        params={"q": keyword, "st": 100, "r_format": "json", "frm": "nv", "ans": 2},
        headers={"User-Agent": "Mozilla/5.0"},  # UA 없으면 빈 응답
        timeout=6,
    )
    resp.raise_for_status()
    out: list[str] = []
    for group in resp.json().get("items", []) or []:
        for row in group or []:
            t = (row[0] if isinstance(row, list) and row else row) or ""
            t = t.strip()
            if t and t not in out:
                out.append(t)
    return out


def _total(keyword: str) -> int:
    """문서 수만 필요한 가벼운 조회(display=1) — 추천어 경쟁 정렬용."""
    env = load_env()
    resp = requests.get(
        _BLOG_SEARCH_URL,
        params={"query": keyword, "display": 1},
        headers={
            "X-NCP-APIGW-API-KEY-ID": env.naver_client_id or "",
            "X-NCP-APIGW-API-KEY": env.naver_client_secret or "",
        },
        timeout=8,
    )
    resp.raise_for_status()
    return int(resp.json().get("total", 0))


def keyword_suggest(keyword: str, limit: int = 8) -> dict:
    """연관검색어 중 '더 유리한' 키워드 추천.

    자동완성으로 실제 검색되는 연관어를 뽑고 각각 문서 수(경쟁 대리 지표)를 잰다.
    검색광고 키가 있으면 월간 검색량도 붙여 '검색량 대비 경쟁이 유리한' 순으로,
    없으면 기존대로 문서 수 오름차순으로 정렬한다.
    """
    kw = (keyword or "").strip()
    if not kw:
        raise ValueError("키워드가 비어 있어요")
    seen = {kw.replace(" ", "").lower()}

    def _fresh(t: str) -> bool:
        n = t.replace(" ", "").lower()
        if n in seen:
            return False
        seen.add(n)
        return True

    terms = [t for t in _related_terms(kw) if _fresh(t)][:limit]
    # 검색광고 연관 키워드로 후보 풀 확장 — 검색량이 응답에 이미 있어 추가 조회 불필요
    known_vol = {}
    for r in _searchad_related(kw, limit) if load_env().has_searchad else []:
        if _fresh(r["keyword"]):
            terms.append(r["keyword"])
            known_vol[r["keyword"]] = r["volume"]
    scored = []
    for t in terms:
        try:
            scored.append({"keyword": t, "total": _total(t)})
        except Exception:  # noqa: BLE001 — 개별 실패는 건너뛰고 나머지로 추천
            continue
    vols = search_volumes([s["keyword"] for s in scored if s["keyword"] not in known_vol])
    for s in scored:
        v = vols.get(s["keyword"]) or {}
        s["volume"] = known_vol.get(s["keyword"], v.get("volume"))
    has_volume = any(s["volume"] is not None for s in scored)
    if has_volume:
        # 많이 검색되는데 문서(경쟁)는 적은 키워드가 위로 오게 검색량/문서수 비로 정렬
        scored.sort(key=lambda x: (x["volume"] or 0) / (x["total"] + 1), reverse=True)
    else:
        scored.sort(key=lambda x: x["total"])
    return {"keyword": kw, "suggestions": scored, "has_volume": has_volume}


def check_all() -> list[dict]:
    """전 항목 순위 확인 → 이력 저장 → 요약 행 반환.

    반환 행: {keyword, url, rank(이번), prev(직전), added}. 같은 키워드는
    API를 한 번만 호출한다(항목 수만큼이 아니라 키워드 수만큼 과금).
    """
    entries = _load()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results_cache: dict[str, list[dict]] = {}
    rows: list[dict] = []
    for e in entries:
        kw = e["keyword"]
        if kw not in results_cache:
            results_cache[kw] = _search_blog(kw)
        rank = find_rank(results_cache[kw], e["url"])
        prev = e["history"][-1]["rank"] if e["history"] else None
        e["history"].append({"t": now, "rank": rank})
        rows.append(
            {"keyword": kw, "url": e["url"], "rank": rank, "prev": prev, "added": e["added"]}
        )
    _save(entries)
    return rows


def list_entries() -> list[dict]:
    """API 호출 없이 저장된 항목 + 마지막 확인 결과 요약."""
    rows = []
    for e in _load():
        last = e["history"][-1] if e["history"] else None
        prev = e["history"][-2] if len(e["history"]) >= 2 else None
        rows.append({
            "keyword": e["keyword"], "url": e["url"], "added": e["added"],
            "rank": last["rank"] if last else None,
            "prev": prev["rank"] if prev else None,
            "checked": last["t"] if last else None,
            "checks": len(e["history"]),
        })
    return rows
