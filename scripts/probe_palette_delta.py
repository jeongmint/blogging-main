"""SE 프리셋 팔레트를 캡처하고, 실제 쓰는 강조색과의 색차(ΔE)를 계산한다.

강조색을 '프리셋 스와치 1클릭'으로 바꾸면 색이 가장 가까운 프리셋으로 스냅된다.
이때 색이 얼마나 달라지는지 색당 ΔE(CIE76, Lab 거리)로 수치화한다.
  ΔE < 2   : 거의 구분 불가
  2 ~ 5    : 자세히 보면 차이
  5 ~ 10   : 눈에 띔
  > 10     : 확연히 다름

실행: .venv/bin/python scripts/probe_palette_delta.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

SCRATCH = Path("/private/tmp/claude-501/-Users-noino-dev-side-blogging/"
               "1a1bfc16-4e38-400c-9712-ef9536f4f8fe/scratchpad")

_SWATCH_DUMP_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('.se-color-palette')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const bg = getComputedStyle(el).backgroundColor;
    if (seen.has(bg)) continue; seen.add(bg);
    out.push(bg);
  }
  return out;
}
"""


def rgb_of(s: str):
    m = re.findall(r"\d+", s)
    return (int(m[0]), int(m[1]), int(m[2])) if len(m) >= 3 else None


def hex_to_rgb(h: str):
    v = h.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _srgb_to_lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb):
    r, g, b = (_srgb_to_lin(c) for c in rgb)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    x, y, z = x / 0.95047, y / 1.0, z / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(rgb1, rgb2):
    l1 = rgb_to_lab(rgb1)
    l2 = rgb_to_lab(rgb2)
    return sum((a - b) ** 2 for a, b in zip(l1, l2)) ** 0.5


def nearest(target_hex, palette_rgbs):
    t = hex_to_rgb(target_hex)
    best, best_de = None, 1e9
    for rgb in palette_rgbs:
        de = delta_e(t, rgb)
        if de < best_de:
            best, best_de = rgb, de
    return best, best_de


def used_colors():
    """emphasis.yaml의 preset_tags가 가리키는 프리셋의 실제 글자색/배경색."""
    d = json.load(open("config/power_shortcuts.json", encoding="utf-8"))
    # emphasis.yaml override + power_shortcuts 기본. 여기선 실제 사용되는 색만 모은다.
    import yaml
    em = yaml.safe_load(open("config/emphasis.yaml", encoding="utf-8"))
    used_ids = sorted(set((em.get("preset_tags") or {}).keys()))
    styles = em.get("styles") or {}
    rows = []
    for pid in used_ids:
        ov = styles.get(pid, {})
        tc = ov.get("text_color") or d.get(f"textColor{pid}") or ""
        bc = ov.get("background_color") or d.get(f"backgroundColor{pid}") or ""
        rows.append((pid, "글자색", tc))
        if bc:
            rows.append((pid, "배경색", bc))
    return [(pid, kind, c) for pid, kind, c in rows if c]


def main() -> int:
    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 세션 없음 — 중단")
            return 1
        pub.open_write_page()
        page = pub._page
        page.click(SMART_EDITOR["content_component"])
        page.keyboard.type("팔레트캡처용", delay=4)
        page.wait_for_timeout(500)
        # 글자색 팔레트
        page.click(SMART_EDITOR["toolbar_text_color"])
        page.wait_for_timeout(400)
        text_pal = page.evaluate(_SWATCH_DUMP_JS)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        # 배경색 팔레트
        page.click(SMART_EDITOR["toolbar_bg_color"])
        page.wait_for_timeout(400)
        bg_pal = page.evaluate(_SWATCH_DUMP_JS)
        page.keyboard.press("Escape")

        text_rgbs = [rgb_of(s) for s in text_pal if rgb_of(s)]
        bg_rgbs = [rgb_of(s) for s in bg_pal if rgb_of(s)]
        SCRATCH.mkdir(parents=True, exist_ok=True)
        (SCRATCH / "se_palette.json").write_text(json.dumps(
            {"text": [rgb_to_hex(r) for r in text_rgbs],
             "bg": [rgb_to_hex(r) for r in bg_rgbs]}, ensure_ascii=False, indent=2))
        print(f"SE 프리셋: 글자색 {len(text_rgbs)}색, 배경색 {len(bg_rgbs)}색 캡처\n")

        print(f"{'프리셋':<6}{'종류':<8}{'현재색':<10}{'→ 가장가까운 프리셋':<22}{'ΔE':>7}  판정")
        print("-" * 70)
        worst = 0.0
        for pid, kind, cur in used_colors():
            pal = text_rgbs if kind == "글자색" else bg_rgbs
            best, de = nearest(cur, pal)
            worst = max(worst, de)
            verdict = ("거의 동일" if de < 2 else "미세 차이" if de < 5
                       else "눈에 띔" if de < 10 else "확연히 다름")
            print(f"{pid:<6}{kind:<8}{cur.upper():<10}{rgb_to_hex(best):<22}{de:>7.1f}  {verdict}")
        print("-" * 70)
        print(f"최대 ΔE = {worst:.1f}  "
              f"({'대부분 무난' if worst < 5 else '일부 색은 확연히 달라짐 — 주의' if worst >= 10 else '약간 차이'})")
        print(f"\n[저장] SE 프리셋 팔레트 → {SCRATCH/'se_palette.json'}")
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
