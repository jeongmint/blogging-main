"""CLI 엔트리 — 백엔드 단독 실행용.

나중에 Electron 셸이 이 명령들을 자식 프로세스로 호출한다(기획서 §7.1).
"""

from __future__ import annotations

import typer

from autoblog.config import load_env, load_models_config

app = typer.Typer(add_completion=False, help="로컬 LLM 블로그 자동 작성 — 백엔드")


@app.command()
def models(tier: str = typer.Option(None, help="프리셋 키 (예: 8gb). 미지정 시 기본값")):
    """선택된 GPU 티어 프리셋의 vision/text 모델을 출력."""
    cfg = load_models_config()
    if tier:
        preset = cfg.get(tier)
        typer.echo(f"[{preset.label}]")
        typer.echo(f"  vision : {preset.vision}")
        typer.echo(f"  text   : {preset.text}")
        typer.echo(f"  동시로드: {preset.concurrent_load}")
        return
    eff = cfg.effective()
    typer.echo("[현재 적용]")
    typer.echo(f"  text   : {eff.text} ({eff.provider})")
    typer.echo(f"  vision : {eff.vision}")


@app.command()
def place(query: str = typer.Argument(..., help="가게명 + 지역 (예: '교대 김밥천국')")):
    """맛집 사실 카드 수집 (검색 API → 스크래핑)."""
    from autoblog.collect.place import collect_place

    card = collect_place(query)
    typer.echo(card.model_dump_json(indent=2, exclude_none=True))


@app.command()
def product(
    query: str = typer.Argument(..., help="상품 검색어 (예: '강아지 노즈워크 장난감')"),
    image: list[str] = typer.Option(
        None, "--image", "-i", help="상세설명 이미지 경로(반복 지정). Vision 전사/추출"
    ),
    text: str = typer.Option(
        None, "--text", "-t", help="상세설명을 텍스트로 직접 입력(Vision 불필요)"
    ),
    vision_main: bool = typer.Option(
        False, "--vision-main", help="쇼핑 API 메인 이미지도 내려받아 Vision 분석"
    ),
):
    """상품 사실 카드 수집 (쇼핑 검색 API + 상세설명 이미지/텍스트)."""
    from autoblog.collect.product import collect_product

    card = collect_product(
        query, detail_images=image or None, detail_text=text, vision_on_main=vision_main
    )
    typer.echo(card.model_dump_json(indent=2, exclude_none=True))


@app.command(name="place-url")
def place_url(
    url: str = typer.Argument(..., help="플레이스 URL (naver.me 단축링크 또는 m.place...)"),
    reviews: bool = typer.Option(True, help="방문자 리뷰(경험 키워드/본문) 수집 여부"),
    review_limit: int = typer.Option(12, help="수집할 리뷰 본문 최대 개수"),
):
    """플레이스 URL → 상세 사실 카드 (메뉴/가격/평점/좌표/영업시간 + 방문자 리뷰). 권장 경로."""
    from autoblog.collect.place import collect_place_from_url

    card = collect_place_from_url(url, with_reviews=reviews, review_limit=review_limit)
    typer.echo(card.model_dump_json(indent=2, exclude_none=True))


@app.command()
def style(
    posts: list[str] = typer.Argument(..., help="과거 글 파일 경로(2~3개)"),
    out: str = typer.Option(None, "--out", "-o", help="추출된 문체 프로파일 저장 경로"),
):
    """과거 글에서 문체 프로파일 추출 (기획서 §4.2)."""
    from autoblog.draft.style import extract_style_profile

    texts = [open(p, encoding="utf-8").read() for p in posts]
    profile = extract_style_profile(texts)
    typer.echo(profile)
    if out:
        open(out, "w", encoding="utf-8").write(profile)
        typer.echo(f"\n저장됨: {out}", err=True)


@app.command()
def classify(images: list[str] = typer.Argument(..., help="분류할 사진 경로(여러 장)")):
    """입력 사진 자동 분류 (음식/메뉴판/외관/내부/영수증/상품/기타)."""
    from autoblog.collect.fact_card import CardType, FactCard
    from autoblog.collect.photos import classify_photos_into, photo_summary

    card = classify_photos_into(FactCard(type=CardType.place), images)
    for p in card.photos:
        typer.echo(f"{p.label}\t{p.path}")
    typer.echo(f"\n요약: {photo_summary(card.photos)}", err=True)
    for w in card.warnings:
        typer.echo(f"경고: {w}", err=True)


@app.command()
def draft(
    memo: str = typer.Argument(..., help="경험 메모(글의 중심/주연)"),
    place_url: str = typer.Option(None, "--place-url", help="맛집: 플레이스 URL로 사실 카드"),
    product: str = typer.Option(None, "--product", help="상품: 검색어로 사실 카드"),
    photo: list[str] = typer.Option(None, "--photo", "-p", help="입력 사진(분류 후 배치 안내)"),
    tone: str = typer.Option(None, "--tone", help="문체 톤 지시 (예: '친근한 반말로')"),
    style_file: str = typer.Option(
        None, "--style-file", help="문체 프로파일 파일(autoblog style로 추출)"
    ),
    prompt_file: str = typer.Option(
        None, "--prompt-file", help="베이스 프롬프트 파일 경로(기본 config/prompts/default.md)"
    ),
    model: str = typer.Option(None, "--model", help="텍스트 모델 override(기본 프리셋)"),
    emphasis: bool = typer.Option(False, "--emphasis", help="강조(서식) 배정 켜기"),
    shortcuts: str = typer.Option(
        None, "--shortcuts", help="파워 단축키 JSON 경로(미지정 시 내장 기본 스타일)"
    ),
):
    """경험 메모 + 사실 카드 → 경험 중심 블로그 초안 생성."""
    from autoblog.collect.fact_card import CardType, FactCard
    from autoblog.draft.generate import DraftRequest, generate_draft
    from autoblog.draft.prompts import load_base_prompt
    from autoblog.draft.style import StyleProfile

    if place_url:
        from autoblog.collect.place import collect_place_from_url

        card = collect_place_from_url(place_url)
    elif product:
        from autoblog.collect.product import collect_product

        card = collect_product(product)
    else:
        card = FactCard(type=CardType.place)
        typer.echo("(사실 카드 없이 경험 메모만으로 작성)", err=True)

    if photo:
        from autoblog.collect.photos import classify_photos_into

        classify_photos_into(card, photo)

    power_shortcuts = None
    if shortcuts:
        import json

        from autoblog.publish.emphasis import load_power_shortcuts

        power_shortcuts = load_power_shortcuts(json.loads(open(shortcuts, encoding="utf-8").read()))

    req = DraftRequest(
        fact_card=card,
        experience_memo=memo,
        base_prompt=load_base_prompt(prompt_file) if prompt_file else None,
        style=StyleProfile(
            tone=tone,
            profile=open(style_file, encoding="utf-8").read() if style_file else None,
        )
        if (tone or style_file)
        else None,
        emphasis=emphasis,
        power_shortcuts=power_shortcuts,
    )
    result = generate_draft(req, model=model)
    typer.echo(result.text)
    if result.emphases:
        typer.echo("\n--- 강조 배정 ---", err=True)
        for s in result.emphases:
            st = s.style
            desc = st.text_color or st.background_color or "기본"
            typer.echo(f"[{s.preset_id}] {desc}  «{s.text}»", err=True)
    if result.checklist:
        typer.echo("\n--- 자동 체크(노출 기본기·가이드라인) ---", err=True)
        for c in result.checklist:
            mark = "O" if c.ok else "X"
            typer.echo(f"[{mark}] {c.item} {c.detail}", err=True)


@app.command()
def post(
    memo: str = typer.Argument(..., help="경험 메모(글의 중심/주연)"),
    place_url: str = typer.Option(None, "--place-url", help="맛집: 플레이스 URL로 사실 카드"),
    product: str = typer.Option(None, "--product", help="상품: 검색어로 사실 카드"),
    photo: list[str] = typer.Option(None, "--photo", "-p", help="입력 사진(분류 후 본문 배치)"),
    tone: str = typer.Option(None, "--tone", help="문체 톤 지시"),
    style_file: str = typer.Option(None, "--style-file", help="문체 프로파일 파일"),
    emphasis: bool = typer.Option(True, "--emphasis/--no-emphasis", help="강조 색상 마킹"),
    structure: bool = typer.Option(True, "--structure/--no-structure", help="구분선/인용구 마커"),
    stickers: bool = typer.Option(True, "--stickers/--no-stickers", help="스티커 마커(즐겨찾기 라벨)"),
    consistent_pack: bool = typer.Option(False, "--consistent-pack", help="스티커를 한 팩으로 통일"),
    favorites_only: bool = typer.Option(
        True, "--fav-only/--all-stickers", help="즐겨찾기한 스티커만 사용(기본). --all-stickers면 전체"
    ),
    category: str = typer.Option(None, "--category", help="발행 카테고리(유저별)"),
    model: str = typer.Option(None, "--model", help="텍스트 모델 override"),
    dry_run: bool = typer.Option(False, "--dry-run", help="브라우저 없이 초안/플랜만 출력"),
    submit: bool = typer.Option(False, "--submit", help="발행까지(기본은 임시저장만)"),
    blog_id: str = typer.Option(None, "--blog-id", help="블로그 ID(기본 .env)"),
    headless: bool = typer.Option(False, help="브라우저 숨김"),
):
    """수집→초안(강조/구분선/인용구/스티커 마커 자동)→게시까지 한 번에 (엔드투엔드).

    기본은 임시저장만(안전). --submit이면 발행. --dry-run이면 브라우저 없이 초안·플랜만 확인.
    스티커는 즐겨찾기한 것만 쓰니 미리 stickers pull→review(★)→label 해두세요.
    """
    from autoblog.draft.style import StyleProfile
    from autoblog.pipeline import run_pipeline

    style = (
        StyleProfile(
            tone=tone, profile=open(style_file, encoding="utf-8").read() if style_file else None
        )
        if (tone or style_file)
        else None
    )
    typer.echo("[1/3] 수집 + 초안 생성 중...", err=True)
    result = run_pipeline(
        memo,
        place_url=place_url,
        product=product,
        photos=photo or None,
        style=style,
        emphasis=emphasis,
        structure=structure,
        stickers=stickers,
        consistent_pack=consistent_pack,
        sticker_favorites_only=favorites_only,
        model=model,
    )
    typer.echo(result.draft.text)
    # 플랜 요약(어떤 블록으로 게시되는지)
    typer.echo("\n[2/3] 게시 플랜:", err=True)
    for b in result.plan.blocks:
        if b.kind == "sticker":
            desc = f"{b.sticker_pack}:{b.sticker_index}"
        elif b.kind == "image":
            desc = f"{b.image_label} {b.image_path}"
        elif b.kind == "text":
            desc = f"{len(b.text)}자" + (f", 강조 {len(b.emphases)}" if b.emphases else "")
        else:
            desc = f"variant {b.variant}"
        typer.echo(f"  - {b.kind}: {desc}", err=True)

    if dry_run:
        typer.echo("\n(dry-run: 게시 생략)", err=True)
        return

    typer.echo(f"\n[3/3] 에디터 주입 중... ({'발행' if submit else '임시저장'})", err=True)
    from autoblog.publish.editor import BlogPublisher

    pub = BlogPublisher(blog_id=blog_id, headless=headless)
    pub.start()
    try:
        if not pub.wait_for_login():
            typer.echo("로그인 필요 — 시간 내 로그인하지 못했습니다.")
            raise typer.Exit(1)
        pub.publish(result.plan, category=category, save=True, submit=submit)
    finally:
        pub.close()
    typer.echo("완료.", err=True)


@app.command()
def ui(
    port: int = typer.Option(8770, help="글쓰기 UI 포트"),
    open_browser: bool = typer.Option(True, help="브라우저 자동 열기"),
    reload: bool = typer.Option(
        False, "--reload", help="코드 변경 시 서버 자동 재시작(개발용)"
    ),
):
    """글쓰기 유저 화면(로컬 웹) — 메모→생성→미리보기→임시저장. 명령 한 줄로 브라우저 열림."""
    import webbrowser

    if reload:
        # 개발용: src 변경 감지 → 자식 `autoblog ui`를 죽이고 다시 띄움.
        # 자식은 포트 고정 + 브라우저/재귀 reload 끔(브라우저는 부모가 한 번만 연다).
        from watchfiles import run_process

        from autoblog.config import REPO_ROOT

        src = str(REPO_ROOT / "src")
        url = f"http://127.0.0.1:{port}/"
        typer.echo(f"[reload] {src} 감시 — 변경 시 자동 재시작 → {url}  (종료: Ctrl+C)")
        if open_browser:
            webbrowser.open(url)
        try:
            run_process(
                src,
                target=f"autoblog ui --port {port} --no-open-browser",
                target_type="command",
            )
        except KeyboardInterrupt:
            typer.echo("\n종료.")
        return

    from autoblog.webui import serve_ui

    # 로그를 파일에도 남긴다 — 에러 traceback이 터미널에만 찍히면 창이 닫히는 순간
    # 진단 근거가 사라진다(외부에서 tail로 지켜볼 수도 없다).
    import sys
    from datetime import datetime

    from autoblog.config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _log = open(DATA_DIR / "ui.log", "a", buffering=1, encoding="utf-8", errors="replace")
    _log.write(f"\n===== ui 시작 {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")

    class _Tee:
        def __init__(self, *streams):
            self._streams = streams

        def write(self, text):
            for s in self._streams:
                try:
                    s.write(text)
                except Exception:  # noqa: BLE001 - 로그가 본 동작을 죽이면 안 됨
                    pass

        def flush(self):
            for s in self._streams:
                try:
                    s.flush()
                except Exception:  # noqa: BLE001
                    pass

    sys.stdout = _Tee(sys.stdout, _log)
    sys.stderr = _Tee(sys.stderr, _log)

    server = None
    for p in range(port, port + 10):
        try:
            server = serve_ui(port=p)
            port = p
            break
        except OSError:
            continue
    if server is None:
        typer.echo("빈 포트를 찾지 못했습니다.")
        raise typer.Exit(1)
    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"글쓰기 UI 열림 → {url}  (종료: Ctrl+C)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\n종료.")
    finally:
        server.shutdown()


@app.command()
def doctor():
    """환경 점검 — API 키 설정 여부 + 검색 API 라이브 호출."""
    from autoblog.collect.place import ping_search_api
    from autoblog.config import provider_for_model

    env = load_env()
    typer.echo(f"네이버 검색 API : {'설정됨' if env.has_naver_api else '미설정 (.env)'}")
    ok, msg = ping_search_api()
    typer.echo(f"검색 API 라이브 : {'OK' if ok else msg}")

    cfg = load_models_config()
    eff = cfg.effective()
    key_for = {
        "anthropic": ("ANTHROPIC_API_KEY", env.anthropic_api_key),
        "openai": ("OPENAI_API_KEY", env.openai_api_key),
        "gemini": ("GEMINI_API_KEY", env.gemini_api_key),
        "nvidia": ("NVIDIA_API_KEY", env.nvidia_api_key),
    }
    for label, model in (("텍스트 모델", eff.text), ("비전 모델", eff.vision)):
        prov = provider_for_model(model)
        env_name, val = key_for.get(prov, (None, None))
        if env_name is None:
            status = "미지원 모델 — API(claude/gpt/gemini)로 설정 필요"
        else:
            status = "OK" if val else f"키 미설정 ({env_name})"
        typer.echo(f"{label}      : {status} [{model}]")


rank_app = typer.Typer(help="키워드 순위 추적 — 게시 글의 블로그 검색 순위 실측")
app.add_typer(rank_app, name="rank")


@rank_app.command("add")
def rank_add(keyword: str, url: str):
    """추적 등록: 대표 키워드 + 게시 글 URL."""
    from autoblog.rank import add_entry

    e = add_entry(keyword, url)
    typer.echo(f"등록됨: '{e['keyword']}' ← {e['url']}")


@rank_app.command("check")
def rank_check():
    """전 항목 순위 확인(키워드당 API 1회) + 이력 저장."""
    from autoblog.rank import check_all

    rows = check_all()
    if not rows:
        typer.echo("추적 항목이 없어요 — rank add \"키워드\" <글URL> 로 등록하세요.")
        return
    for r in rows:
        cur = f"{r['rank']}위" if r["rank"] else "100위 밖"
        delta = ""
        if r["prev"] and r["rank"]:
            d = r["prev"] - r["rank"]
            delta = f" ({'▲' if d > 0 else '▼'}{abs(d)})" if d else " (—)"
        typer.echo(f"[{cur}{delta}] {r['keyword']} — {r['url']}")


@rank_app.command("rm")
def rank_rm(keyword: str, url: str):
    """추적 항목 삭제."""
    from autoblog.rank import remove_entry

    typer.echo("삭제됨" if remove_entry(keyword, url) else "해당 항목 없음")


stickers_app = typer.Typer(help="스티커 카탈로그 — 불러오기/라벨링/검수")
app.add_typer(stickers_app, name="stickers")


@stickers_app.command("pull")
def stickers_pull(
    blog_id: str = typer.Option(None, help="블로그 ID(미지정 시 .env NAVER_BLOG_ID)"),
    headless: bool = typer.Option(False, help="브라우저 숨김"),
):
    """에디터에서 보유 스티커를 전부 훑어 개별 이미지로 저장하고 카탈로그에 증분 병합.

    새 스티커만 추가하고 기존 태그/검수/즐겨쓰기는 보존(사라진 건 stale 표시).
    """
    from autoblog.publish.editor import BlogPublisher
    from autoblog.publish.stickers import (
        load_sticker_catalog,
        merge_catalog,
        save_sticker_catalog,
    )

    pub = BlogPublisher(blog_id=blog_id, headless=headless)
    pub.start()
    try:
        if not pub.wait_for_login():
            typer.echo("로그인 필요 — 시간 내 로그인하지 못했습니다.")
            raise typer.Exit(1)
        scraped = pub.pull_stickers()
    finally:
        pub.close()
    existing = load_sticker_catalog()
    merged = merge_catalog(existing, scraped)
    save_sticker_catalog(merged)
    new = sum(1 for s in merged.stickers if not s.tags and not s.stale)
    stale = sum(1 for s in merged.stickers if s.stale)
    typer.echo(
        f"불러오기 완료: 총 {len(merged.stickers)}개 "
        f"(이번에 긁음 {len(scraped)}, 라벨 필요 {new}, 사라짐 {stale})"
    )
    typer.echo("다음: autoblog stickers label  (비전 자동 라벨) → config/stickers.yaml 검수")


@stickers_app.command("label")
def stickers_label(
    favorites_only: bool = typer.Option(
        True, "--favorites-only/--all-stickers", help="즐겨찾기한 것만 라벨(기본). --all-stickers면 전체"
    ),
    all_again: bool = typer.Option(False, "--all", help="검수/기존태그 무시하고 재라벨"),
):
    """비전 모델로 스티커에 감정/상황 태그 자동 부여(증분: 새 것만, 검수 보존).

    기본은 즐겨찾기한 스티커만 — 안 쓸 것까지 도는 낭비를 막는다(전체는 ~6초/개로 느림).
    먼저 autoblog stickers review 로 ★즐겨찾기를 지정하세요.
    """
    from autoblog.publish.stickers import (
        STICKER_CONFIG_PATH,
        label_catalog,
        load_sticker_catalog,
        save_sticker_catalog,
    )

    cat = load_sticker_catalog()
    if not cat.stickers:
        typer.echo("카탈로그가 비었습니다 — 먼저 autoblog stickers pull")
        raise typer.Exit(1)

    only_refs = None
    if favorites_only:
        only_refs = set(cat.favorites)
        if not only_refs:
            typer.echo("즐겨찾기한 스티커가 없습니다 — autoblog stickers review 에서 ★를 먼저 지정하세요.")
            typer.echo("(전체를 라벨하려면 --all-stickers)")
            raise typer.Exit(1)
        typer.echo(f"즐겨찾기 {len(only_refs)}개만 라벨링합니다.")

    def progress(done, total, s):
        if done == 1 or done % 10 == 0 or done == total:
            typer.echo(f"  [{done}/{total}] {s.ref}: {', '.join(s.tags) or '(태그 없음)'}")

    labeled = label_catalog(
        cat,
        only_new=not all_again,
        on_progress=progress,
        save_path=STICKER_CONFIG_PATH,
        only_refs=only_refs,
    )
    save_sticker_catalog(labeled)
    tagged = sum(1 for s in labeled.stickers if s.tags)
    typer.echo(f"라벨링 완료: 태그 {tagged}개. autoblog stickers review 로 검수하세요.")


@stickers_app.command("review")
def stickers_review(
    port: int = typer.Option(8765, help="로컬 검수 UI 포트"),
    open_browser: bool = typer.Option(True, help="브라우저 자동 열기"),
):
    """스티커를 눈으로 보며 태그 수정·즐겨찾기 지정(로컬 웹 UI, 저장 시 config/stickers.yaml).

    명령 한 줄로 서버 기동 + 브라우저 자동 오픈. (Electron 셸에선 이 화면을 그대로 창에 띄움)
    """
    import webbrowser

    from autoblog.publish.sticker_review import serve_review
    from autoblog.publish.stickers import load_sticker_catalog

    if not load_sticker_catalog().stickers:
        typer.echo("카탈로그가 비었습니다 — 먼저 autoblog stickers pull (+ label)")
        raise typer.Exit(1)
    # 포트가 쓰이면 다음 포트로
    server = None
    for p in range(port, port + 10):
        try:
            server = serve_review(port=p)
            port = p
            break
        except OSError:
            continue
    if server is None:
        typer.echo("빈 포트를 찾지 못했습니다.")
        raise typer.Exit(1)
    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"검수 UI 열림 → {url}  (종료: Ctrl+C)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\n검수 종료.")
    finally:
        server.shutdown()


@stickers_app.command("list")
def stickers_list():
    """카탈로그 요약 — 보유 상황 라벨과 스티커 수."""
    from autoblog.publish.stickers import load_sticker_catalog

    cat = load_sticker_catalog()
    active = [s for s in cat.stickers if not s.stale]
    typer.echo(f"스티커 {len(active)}개 (사라짐 {len(cat.stickers) - len(active)}), 즐겨쓰기 {len(cat.favorites)}")
    labels = cat.labels()
    typer.echo(f"상황 라벨({len(labels)}): {', '.join(labels) if labels else '(없음 — label 먼저)'}")


if __name__ == "__main__":
    app()
