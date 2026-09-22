"""SE-ONE 강조(색) 적용 가속 프로브 v2 — 1회성, 라이브 세션(비대화형).

v1에서 확인: execCommand(foreColor/hiliteColor)는 SE에서 ok=False로 막힘.
window.SE(object) / window.SmartEditor(function) 전역은 존재. 프리셋 스와치 82개가
'더보기' 없이 1클릭으로 존재. 그래서 v2는 두 유력 경로를 정확히 측정한다:

  A+) window.SE / SmartEditor 내부 API 깊게 덤프 — 색 명령(서비스/커맨드)이 있나?
  E)  프리셋 스와치 1클릭 경로 — 우리 hex를 가장 가까운 스와치로 골라 클릭. 시간/생존 검증.
  (대조군) 현재 UI '더보기' 경로 시간/생존.

생존 판정은 '적용색이 기본 검정과 다른가 / mark 태그가 생겼나'로 정확히 본다.
시작과 끝에 PROBE_TITLE 임시저장 글을 청소한다(v1이 남긴 것 포함).

실행: .venv/bin/python scripts/probe_emphasis_speed.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

PROBE_TITLE = "ZZ_강조속도프로브_삭제대상"
TEST_TEXT = (
    "여기는 강조속도 테스트 문장입니다.\n"
    "첫번째강조 문구와 두번째강조 문구, 그리고 세번째강조 문구가 들어 있어요.\n"
    "각각 글자색과 배경색을 다르게 입혀보며 어떤 경로가 가장 빠른지 잽니다."
)
TARGET_SWATCH = "첫번째강조"   # E) 스와치 1클릭으로 색 입힐 문구
TARGET_UI = "두번째강조"       # 대조군: 현재 UI 경로
TEXT_HEX = (255, 80, 80)       # 글자색 목표 RGB(=#ff5050)
BG_HEX = (255, 242, 178)       # 배경 목표 RGB(=#fff2b2)

# ── A+) 전역 SE/SmartEditor 구조 깊게 덤프 ────────────────────────────────────
_DEEP_API_JS = r"""
() => {
  const dump = (obj, depth) => {
    const o = {};
    if (!obj || depth < 0) return o;
    let keys = [];
    try { keys = Object.keys(obj); } catch (e) { return o; }
    for (const k of keys.slice(0, 60)) {
      let v; try { v = obj[k]; } catch (e) { continue; }
      const t = typeof v;
      if (t === 'function') o[k] = 'fn';
      else if (t === 'object' && v !== null && depth > 0) o[k] = dump(v, depth - 1);
      else o[k] = t;
    }
    return o;
  };
  const out = {};
  if (window.SE) out.SE = dump(window.SE, 2);
  if (window.SmartEditor) {
    out.SmartEditor_keys = Object.keys(window.SmartEditor);
    out.SmartEditor_proto = window.SmartEditor.prototype
      ? Object.getOwnPropertyNames(window.SmartEditor.prototype).slice(0, 40) : [];
  }
  // 색/커맨드 관련 이름만 빠르게 grep
  const grep = [];
  const walk = (obj, path, d) => {
    if (!obj || d < 0) return;
    let keys = []; try { keys = Object.keys(obj); } catch (e) { return; }
    for (const k of keys) {
      if (/colo|command|format|style|service|exec|apply/i.test(k)) grep.push(path + '.' + k + ' :' + typeof obj[k]);
      let v; try { v = obj[k]; } catch (e) { continue; }
      if (typeof v === 'object' && v !== null && d > 0 && grep.length < 80) walk(v, path + '.' + k, d - 1);
    }
  };
  if (window.SE) walk(window.SE, 'SE', 2);
  out.colorCommandHits = grep;
  return out;
}
"""

# 특정 문구를 감싼 가장 가까운 요소의 적용 스타일(색)을 정확히 읽는다.
_APPLIED_STYLE_JS = r"""
(t) => {
  const roots = document.querySelectorAll('.se-component.se-text');
  for (const root of roots) {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while (n = w.nextNode()) {
      const idx = (n.textContent || '').indexOf(t);
      if (idx === -1) continue;
      let el = n.parentElement;
      // 위로 올라가며 색/배경/ mark 를 찾는다(최대 4단계).
      let color = '', bg = '', mark = false, html = '';
      let cur = el;
      for (let i = 0; i < 4 && cur; i++) {
        const cs = getComputedStyle(cur);
        if (!color && cs.color && cs.color !== 'rgb(0, 0, 0)') color = cs.color;
        if (!bg && cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)') bg = cs.backgroundColor;
        if (cur.tagName === 'MARK') mark = true;
        cur = cur.parentElement;
      }
      html = (el.outerHTML || '').slice(0, 220);
      return {color, bg, mark, html};
    }
  }
  return null;
}
"""


def _nearest_swatch_index(swatches: list[dict], target: tuple[int, int, int]) -> int:
    """bg(rgb)가 target에 가장 가까운 스와치 인덱스."""
    import re

    best_i, best_d = -1, 1e9
    for i, s in enumerate(swatches):
        m = re.findall(r"\d+", s["bg"])
        if len(m) < 3:
            continue
        r, g, b = int(m[0]), int(m[1]), int(m[2])
        d = (r - target[0]) ** 2 + (g - target[1]) ** 2 + (b - target[2]) ** 2
        if d < best_d:
            best_i, best_d = i, d
    return best_i


_SWATCH_DUMP_JS = r"""
() => {
  const out = [];
  for (const el of document.querySelectorAll('.se-color-palette')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    out.push({bg: getComputedStyle(el).backgroundColor, x: r.x + r.width/2, y: r.y + r.height/2});
  }
  return out;
}
"""


def _cleanup(pub, page):
    """PROBE_TITLE 임시저장 글을 모두 삭제(v1 잔여물 포함). 실패해도 무시."""
    try:
        if "postwrite" not in (page.url or ""):
            pub.open_write_page()
        pub._open_draft_list()
        for _ in range(8):
            items = pub._read_draft_items()
            idxs = [it["idx"] for it in items if (it.get("title") or "").strip() == PROBE_TITLE]
            if not idxs:
                return
            dels = page.query_selector_all(SMART_EDITOR["draft_item_delete"])
            if idxs[0] >= len(dels):
                return
            try:
                dels[idxs[0]].click(timeout=4000)
            except Exception:
                return
            page.wait_for_timeout(500)
            conf = page.query_selector(SMART_EDITOR["draft_delete_confirm"])
            if conf and conf.is_visible():
                conf.click()
                page.wait_for_timeout(600)
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] 경고(무시): {exc}")


def main() -> int:
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 중단.")
            return 1

        # 0) v1 잔여 글부터 청소
        print("[probe] v1 잔여 임시저장 청소 시도…")
        _cleanup(pub, pub._page)

        pub.open_write_page()
        page = pub._page
        pub._type_title(PROBE_TITLE)
        page.click(SMART_EDITOR["content_component"])
        pub._reset_text_toggles()
        page.keyboard.type(TEST_TEXT, delay=4)
        page.wait_for_timeout(800)

        # ── A+) 내부 API 깊은 덤프 ─────────────────────────────────────────
        print("\n===== A+) window.SE / SmartEditor 구조 =====")
        api = page.evaluate(_DEEP_API_JS)
        print("SmartEditor keys:", api.get("SmartEditor_keys"))
        print("SmartEditor.prototype:", api.get("SmartEditor_proto"))
        print("색/커맨드 후보(grep):")
        for h in api.get("colorCommandHits", [])[:60]:
            print("   ", h)
        if not api.get("colorCommandHits"):
            print("    (없음 — SE 내부에 노출된 색 명령 못 찾음)")
        # SE 최상위 키만 간단히
        se = api.get("SE", {})
        print("SE 최상위 키:", list(se.keys())[:30] if isinstance(se, dict) else se)

        # ── E) 프리셋 스와치 1클릭 경로 ────────────────────────────────────
        print("\n===== E) 프리셋 스와치 1클릭 (글자색) =====")
        if pub._select_body_text(TARGET_SWATCH):
            page.click(SMART_EDITOR["toolbar_text_color"])
            page.wait_for_timeout(400)
            sw = page.evaluate(_SWATCH_DUMP_JS)
            fi = _nearest_swatch_index(sw, TEXT_HEX)
            t0 = time.perf_counter()
            if fi >= 0:
                page.mouse.click(sw[fi]["x"], sw[fi]["y"])  # 스와치 직접 클릭(더보기 없음)
            page.wait_for_timeout(300)
            t1 = time.perf_counter()
            print(f"가장 가까운 글자색 스와치 bg={sw[fi]['bg'] if fi>=0 else '?'} 클릭, "
                  f"소요 {t1 - t0:.2f}s (현재 더보기 글자색 1.43s 대비)")
            applied = page.evaluate(_APPLIED_STYLE_JS, TARGET_SWATCH)
            print("적용 직후:", applied)
        else:
            print("선택 실패")

        # ── 대조군) 현재 UI '더보기' 경로 ──────────────────────────────────
        print("\n===== 대조군) 현재 UI 더보기 경로 =====")
        if pub._select_body_text(TARGET_UI):
            t0 = time.perf_counter()
            pub._apply_color(SMART_EDITOR["toolbar_text_color"], "ff5050")
            pub._apply_color(SMART_EDITOR["toolbar_bg_color"], "fff2b2")
            t1 = time.perf_counter()
            print(f"더보기 글자색+배경색 합 {t1 - t0:.2f}s/건")
            print("적용 직후:", page.evaluate(_APPLIED_STYLE_JS, TARGET_UI))

        # ── 저장→재로드 생존 검증 ──────────────────────────────────────────
        print("\n===== 저장→재로드 생존 검증 =====")
        pub.save_draft()
        pub.open_write_page()
        pub._open_draft_list()
        items = pub._read_draft_items()
        tgt = next((it["idx"] for it in items
                    if (it.get("title") or "").strip() == PROBE_TITLE), None)
        if tgt is None:
            print("재로드 실패 — 목록에서 프로브 글 못 찾음.")
        else:
            buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
            buttons[tgt].click()
            page.wait_for_timeout(1500)
            conf = page.query_selector(SMART_EDITOR["draft_load_confirm"])
            if conf and conf.is_visible():
                conf.click()
            page.wait_for_timeout(1800)
            sw_style = page.evaluate(_APPLIED_STYLE_JS, TARGET_SWATCH)
            ui_style = page.evaluate(_APPLIED_STYLE_JS, TARGET_UI)
            print(f"[E 스와치] 저장 후: {sw_style}")
            print(f"[대조군 UI] 저장 후: {ui_style}")
            sw_alive = bool(sw_style and (sw_style["color"] or sw_style["bg"] or sw_style["mark"]))
            ui_alive = bool(ui_style and (ui_style["color"] or ui_style["bg"] or ui_style["mark"]))
            print(f"\n>>> 스와치 색 생존={sw_alive}, UI 색 생존={ui_alive}")
            if sw_alive:
                print("    ✅ 스와치 1클릭이 저장까지 유지 → 더보기 대신 스와치로 교체 가능.")
            else:
                print("    ⚠️ 스와치가 저장에서 날아감 → 더보기(hex) 유지 필요. 그럼 D 대기값 축소로.")

        # 끝나면 청소
        print("\n[probe] 테스트 글 청소…")
        _cleanup(pub, page)
        print("[probe] 완료.")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
