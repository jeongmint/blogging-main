"""in-place 헤더 서식(대제목·드립) 라운드트립 프로브 — 일회용 글 생성→재작성→검증→삭제.

유저 보고 재현: 불러오기(in-place) 발행 글에서 대제목 서식(fs30·#395D73)이 드립 줄에
밀려 붙고, 대제목은 본문 기본(fs13·검정), 드립 서식(fs11·#4383BF)은 실종되는 문제.
(속초어시장·보정동 글 실측 — scripts/probe_drip_inspect_draft.py)

흐름:
  1) ZZ 제목의 일회용 임시저장 글 생성(사진 2장 포함, 일반 publish 경로)
  2) 실제 파이프라인처럼 build_publish_plan(inplace=True) + publish_inplace(save=True)
  3) 그 글을 다시 열어 헤더 문단들의 폰트/크기/색 검증(PASS/FAIL)
  4) ZZ 글 삭제(실패 시 수동 삭제 안내)

--broken: 1)에서 유저 실측과 같은 '이미 깨진' 글(헤더 텍스트 포함, 드립 줄에 대제목
서식 fs30·남색이 덮이고 대제목은 무서식)을 시드로 만든 뒤 재발행 복구를 검증한다
— 깨진 글에 다시 발행하면 정상으로 돌아오는지 + 옛 서식이 새 본문에 새는지 확인.

실행: .venv/bin/python scripts/probe_inplace_header_style.py [--keep(삭제 생략)] [--broken] [--debug]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image  # noqa: E402

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.draft.generate import DraftResult  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402
from autoblog.publish.emphasis import StyledSpan  # noqa: E402
from autoblog.publish.plan import (  # noqa: E402
    PhotoItem,
    PublishBlock,
    PublishPlan,
    build_publish_plan,
    load_structure_styles,
)

TITLE = "ZZ인플레이스 서식 프로브 글입니다 지우세요"

# 실측 재현 글과 같은 헤더 구조: 대제목 → 드립 → 태그줄 → 사진 → 본문
TEXT = f"""{TITLE}

지갑 안 아픈 테스트 찾았다
싼데 맛있으면 그건 못 참죠 테스트 ,,
#프로브 #테스트

[사진:하나]
본문 첫 문단입니다. 여기는 일반 본문이라 기본 서식이어야 해요.
본문 둘째 줄도 그냥 본문.

[사진:둘]
본문 셋째 문단. 마무리 문단입니다.
"""

BIG = "지갑 안 아픈 테스트 찾았다"
DRIP = "싼데 맛있으면 그건 못 참죠 테스트 ,,"
BODY1 = "본문 첫 문단입니다"

_HEAD_JS = r"""
() => {
  const out = [];
  for (const c of document.querySelectorAll('.se-component.se-text')) {
    for (const p of c.querySelectorAll('p.se-text-paragraph')) {
      const t = (p.textContent || '').trim();
      if (!t) continue;
      const span = p.querySelector('span');
      out.push({text: t.slice(0, 30), cls: span ? span.className : '',
                style: span ? (span.getAttribute('style') || '') : ''});
      if (out.length >= 8) return out;
    }
  }
  return out;
}
"""


def _mkjpg(path: Path, color: tuple[int, int, int]) -> str:
    Image.new("RGB", (640, 480), color).save(path, "JPEG")
    return str(path)


def _find(rows: list[dict], needle: str) -> dict | None:
    return next((r for r in rows if needle in r["text"]), None)


def _check(row: dict | None, name: str, want_cls: str, want_color: str) -> bool:
    if row is None:
        print(f"  ❌ {name}: 문단을 못 찾음")
        return False
    ok = want_cls in row["cls"] and want_color in row["style"].replace(" ", "")
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}: cls={row['cls']!r} style={row['style']!r} "
          f"(기대: {want_cls} + {want_color})")
    return ok


def _delete_all_by_title(pub: BlogPublisher, title: str) -> int:
    """제목 완전일치 임시저장 글을 전부 삭제(프로브 전용 — ZZ 일회용 글만 대상)."""
    deleted = 0
    for _ in range(6):
        pub.open_write_page()
        pub._open_draft_list()
        idx = pub._resolve_draft_idx(title, "")
        if idx is None:
            break
        if not pub._delete_draft_at(idx):
            break
        deleted += 1
    return deleted


def _instrument(pub: BlogPublisher):
    """--debug: 강조 적용 각 단계(rect→드래그 선택 결과→툴바 적용)를 로그로 노출."""
    import autoblog.publish.editor as ed

    orig_select = BlogPublisher._select_body_text
    orig_pick = BlogPublisher._pick_toolbar_option

    at_point_js = """
    (pt) => {
      const el = document.elementFromPoint(pt.x, pt.y);
      const path = [];
      let n = el;
      for (let i = 0; n && i < 4; i++) {
        path.push(n.tagName + '.' + (n.className || '').toString().slice(0, 50));
        n = n.parentElement;
      }
      return path;
    }
    """

    def dbg_select(self, text):
        rect = self._page.evaluate(ed._RANGE_RECT_JS, text)
        at = None
        if rect:
            at = self._page.evaluate(
                at_point_js, {"x": rect["x"] + 1, "y": rect["y"] + rect["h"] / 2}
            )
        ok = orig_select(self, text)
        sel = ""
        for fr in self._page.frames:
            try:
                sel += "|" + fr.evaluate("()=>document.getSelection().toString()")
            except Exception:  # noqa: BLE001
                pass
        print(f"   [dbg] select {text[:14]!r}: rect={rect} ok={ok} selected={sel[:40]!r}")
        print(f"   [dbg]   drag점 위 요소: {at}")
        return ok

    def dbg_pick(self, button_sel, name, value):
        got = orig_pick(self, button_sel, name, value)
        print(f"   [dbg] toolbar {name}={value}: clicked={got}")
        return got

    pub._select_body_text = dbg_select.__get__(pub)
    pub._pick_toolbar_option = dbg_pick.__get__(pub)


def main() -> int:
    keep = "--keep" in sys.argv
    debug = "--debug" in sys.argv
    scratch = Path(__file__).resolve().parents[1] / "data" / "uploads"
    a = _mkjpg(scratch / "zz_probe_a.jpg", (200, 120, 80))
    b = _mkjpg(scratch / "zz_probe_b.jpg", (80, 120, 200))

    styles = load_structure_styles()
    photos = [PhotoItem(path=a, label="하나"), PhotoItem(path=b, label="둘", thumbnail=True)]
    plan = build_publish_plan(
        DraftResult(title=TITLE, text=TEXT, emphases=[], debug={}),
        photos=photos, structure_styles=styles, inplace=True,
    )
    print("[probe] in-place 플랜 블록:")
    for blk in plan.blocks:
        spans = [(s.text[:16], s.style.font_family, s.style.font_size, s.style.text_color)
                 for s in (blk.emphases or [])]
        print(f"    {blk.kind:8s} {(blk.text or '')[:24]!r} spans={spans}")

    pub = BlogPublisher(headless=True).start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단.")
            return 1
        page = pub._page
        if debug:
            _instrument(pub)

        broken = "--broken" in sys.argv
        if broken:
            # 유저 실측(속초·보정동)과 같은 '깨진' 시드를 만든다: 헤더 텍스트가 있고
            # 대제목은 무서식(본문 크기). 드립 줄의 fs30·남색은 저장 후 직접 입힌다
            # (아래 [1b]) — 발행 경로에 맡기면 상태를 보장 못 해서 수동으로 확정한다.
            print("\n[1] '깨진' 일회용 임시저장 글 생성 …")
            seed = PublishPlan(title=TITLE, blocks=[
                PublishBlock(kind="text", text=BIG, align="center"),
                PublishBlock(kind="text", text=DRIP, align="center"),
                PublishBlock(kind="image", image_path=a),
                PublishBlock(kind="text", text="원본 본문 문단(곧 재작성될 내용)."),
                PublishBlock(kind="image", image_path=b),
                PublishBlock(kind="text", text="원본 마무리."),
            ])
        else:
            print("\n[1] 일회용 임시저장 글 생성 …")
            seed = PublishPlan(title=TITLE, blocks=[
                PublishBlock(kind="text", text="원본 인트로(곧 지워질 내용)."),
                PublishBlock(kind="image", image_path=a),
                PublishBlock(kind="text", text="원본 중간 문단."),
                PublishBlock(kind="image", image_path=b),
                PublishBlock(kind="text", text="원본 마무리."),
            ])
        pub.publish(seed, save=True, submit=False, mark_ai=False)
        page.wait_for_timeout(1200)

        if broken:
            # [1b] 저장된 시드를 다시 열어 드립 줄에 대제목 서식(fs30·남색)을 직접 덮고
            # 재저장 — 유저의 깨진 글과 동일한 '저장된 상태'를 확정한다.
            print("[1b] 드립 줄에 fs30·남색 덮고 재저장(깨진 상태 확정) …")
            pub.open_write_page()
            pub._open_draft_list()
            idx = pub._resolve_draft_idx(TITLE, "")
            assert idx is not None, "시드 글을 목록에서 못 찾음"
            pub._load_draft_into_editor(idx)
            page.wait_for_timeout(1500)
            assert pub._select_body_text(DRIP), "드립 줄 선택 실패"
            pub._apply_color(SMART_EDITOR["toolbar_text_color"], "#395D73")
            pub._apply_font("nanummaruburi")
            pub._apply_font_size(30)
            pub.save_draft()
            page.wait_for_timeout(1200)
            pub.open_write_page()
            pub._open_draft_list()
            idx = pub._resolve_draft_idx(TITLE, "")
            pub._load_draft_into_editor(idx)
            page.wait_for_timeout(1500)
            rows = page.evaluate(_HEAD_JS)
            print("   깨진 시드(저장 후 재열람) 상태:")
            for r in rows:
                print("     ", r)
            drip_row = _find(rows, DRIP[:6])
            if not (drip_row and "se-fs30" in drip_row["cls"]):
                print("   ⚠️ 드립 줄 fs30 확정 실패 — 깨진 상태 재현이 안 됨(계속 진행은 함)")

        print("[2] publish_inplace(save=True) — 실제 파이프라인 경로 …")
        warnings, infos = pub.publish_inplace(
            plan, draft_title=TITLE, photo_paths=[a, b], save=True, mark_ai=False,
        )
        if warnings:
            print("   [warn]", warnings)
        if infos:
            print("   [info]", infos)
        page.wait_for_timeout(1500)

        print("[3] 재열람 → 헤더 서식 검증 …")
        pub.open_write_page()
        pub._open_draft_list()
        idx = pub._resolve_draft_idx(TITLE, "")
        if idx is None:
            print("   ❌ 저장된 프로브 글을 못 찾음")
            return 1
        pub._load_draft_into_editor(idx)
        try:
            page.wait_for_selector(SMART_EDITOR["editor_image"], timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1500)
        rows = page.evaluate(_HEAD_JS)
        for r in rows:
            print("   ", r)

        big_size = f"se-fs{styles.big_title.size}"
        drip_size = f"se-fs{styles.hashtags.size}"
        ok = True
        ok &= _check(_find(rows, BIG[:6]), "대제목", big_size, "color:rgb(57,93,115)")
        ok &= _check(_find(rows, DRIP[:6]), "드립", drip_size, "color:rgb(67,131,191)")
        body = _find(rows, BODY1[:8])
        if body and (big_size in body["cls"] or drip_size in body["cls"]):
            print(f"  ❌ 본문에 헤더 서식이 샘: {body}")
            ok = False

        print(f"\n===== 판정: {'PASS' if ok else 'FAIL(재현됨)'} =====")

        if not keep:
            n = _delete_all_by_title(pub, TITLE)
            print(f"[4] 프로브 글 삭제: {n}건 "
                  + ("" if n else "— 'ZZ인플레이스…' 글을 직접 지워주세요"))
        return 0 if ok else 2
    finally:
        pub.close(save_session=True)


if __name__ == "__main__":
    raise SystemExit(main())
