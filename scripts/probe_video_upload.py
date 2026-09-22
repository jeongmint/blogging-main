"""SE-ONE 동영상 업로드/컴포넌트 셀렉터 캡처용 1회성 프로브.

본문에 동영상을 삽입하려면 (1) 동영상 업로드 툴바 버튼 셀렉터, (2) 삽입 완료된
동영상 컴포넌트(인코딩 끝난 상태) 셀렉터, (3) 인코딩 진행 표식이 필요하다. 사진과
달리 동영상은 별도 업로더 + 서버 인코딩 대기가 있어 라이브 DOM에서만 확인 가능하다.

사용자가 "맨 위 임시저장 글에 영상이 들어가 있다"고 알려줬으므로, 이 프로브는
새로 업로드하지 않고 그 임시저장 글을 로드해 동영상 컴포넌트 DOM을 떠 본다. 동시에
툴바를 훑어 '동영상' 버튼 후보를 출력한다(클릭은 OS 파일창을 띄울 수 있어 기본은 안 함).

실행:
    .venv/bin/python scripts/probe_video_upload.py            # idx 0(맨 위) 임시저장 로드
    .venv/bin/python scripts/probe_video_upload.py 2          # idx 2 임시저장 로드
    .venv/bin/python scripts/probe_video_upload.py 0 --click  # 동영상 툴바 버튼 클릭 흐름까지 탐색

출력:
  1) 툴바의 '동영상' 버튼 후보(class/aria-label/data-*)
  2) 본문 동영상 컴포넌트(.se-component … video) outerHTML 앞부분 + <video>/iframe 유무
  3) (--click 시) 버튼 클릭 후 떠오른 모달/오버레이 후보

여기서 고른 셀렉터를 collect/selectors.py 의 SMART_EDITOR 에 채운다:
  video_upload_button / editor_video / (모달이면)video_file_input / 인코딩 표식
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autoblog.collect.selectors import SMART_EDITOR  # noqa: E402
from autoblog.publish.editor import BlogPublisher  # noqa: E402

# 툴바에서 '동영상/비디오' 버튼 후보를 추려내는 JS.
_TOOLBAR_JS = r"""
() => {
  const want = /(video|동영상|비디오|movie|film)/i;
  const out = [];
  const sel = 'button, li, a, [role=button], [data-name], [data-log], [class*=toolbar-item]';
  for (const el of document.querySelectorAll(sel)) {
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    const label = (el.getAttribute('aria-label') || '') + ' '
                + (el.getAttribute('title') || '') + ' '
                + (el.getAttribute('data-name') || '') + ' '
                + (el.getAttribute('data-log') || '') + ' '
                + (el.getAttribute('data-click-area') || '') + ' '
                + (el.textContent || '').trim().slice(0, 30);
    if (!want.test(cls) && !want.test(label)) continue;
    out.push({ tag: el.tagName.toLowerCase(), cls,
               aria: el.getAttribute('aria-label') || '',
               dataName: el.getAttribute('data-name') || '',
               dataLog: el.getAttribute('data-log') || '',
               clickArea: el.getAttribute('data-click-area') || '',
               text: (el.textContent || '').trim().slice(0, 30) });
  }
  return out;
}
"""

# 본문에 삽입된 동영상 컴포넌트를 찾아 DOM을 떠 오는 JS.
_VIDEO_JS = r"""
() => {
  const comps = [];
  // se-component 중 클래스에 video 가 들어가거나 내부에 <video>/iframe 이 있는 것.
  for (const el of document.querySelectorAll('.se-component, [class*=se-video], [class*=video]')) {
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    const hasVideo = !!el.querySelector('video');
    const hasIframe = !!el.querySelector('iframe');
    if (!/video/i.test(cls) && !hasVideo && !hasIframe) continue;
    const r = el.getBoundingClientRect();
    comps.push({ cls, hasVideo, hasIframe, w: Math.round(r.width), h: Math.round(r.height),
                 html: el.outerHTML.slice(0, 900) });
  }
  // 인코딩/변환 진행 표식 후보(텍스트나 클래스).
  const prog = [];
  const pw = /(인코딩|변환|업로드|로딩|loading|progress|encoding|uploading)/i;
  for (const el of document.querySelectorAll('[class*=progress], [class*=loading], [class*=encoding], [class*=upload]')) {
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (!pw.test(cls)) continue;
    prog.push({ cls, text: (el.textContent || '').trim().slice(0, 40) });
  }
  return { comps, prog };
}
"""

# --click 후 떠오른 모달/오버레이 후보.
_MODAL_JS = r"""
() => {
  const out = [];
  for (const el of document.querySelectorAll('[class*=modal], [class*=layer], [class*=popup], [role=dialog], input[type=file]')) {
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    const r = el.getBoundingClientRect();
    const isFile = el.tagName.toLowerCase() === 'input';
    if (!isFile && r.width === 0 && r.height === 0) continue;
    out.push({ tag: el.tagName.toLowerCase(), cls, isFile,
               text: (el.textContent || '').trim().slice(0, 50) });
  }
  return out;
}
"""

# 동영상 업로더(NVU) 모달 내부의 버튼/입력/iframe 정밀 덤프.
_NVU_JS = r"""
() => {
  const root = document.querySelector('.se-popup-video-upload, .nvu_wrap');
  if (!root) return { found: false, items: [], iframes: [] };
  const items = [];
  for (const el of root.querySelectorAll('button, a, input, [role=button], [class*=btn], [class*=button]')) {
    const r = el.getBoundingClientRect();
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    items.push({ tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
                 cls, id: el.id || '',
                 text: (el.textContent || '').trim().slice(0, 24),
                 vis: !(r.width === 0 && r.height === 0) });
  }
  const iframes = [...root.querySelectorAll('iframe')].map(f => ({
    cls: f.className || '', id: f.id || '', src: (f.src || '').slice(0, 80) }));
  return { found: true, items, iframes };
}
"""


# 업로드 후 모달 상태(인코딩/제목/등록 버튼)를 시간에 따라 덤프.
_UPLOAD_STATE_JS = r"""
() => {
  const root = document.querySelector('.se-popup-video-upload, .nvu_wrap');
  if (!root) return { gone: true };
  const buttons = [];
  for (const el of root.querySelectorAll('button, a, [role=button], [class*=btn]')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    const t = (el.textContent || '').trim().slice(0, 20);
    if (!t && !/btn/i.test(cls)) continue;
    buttons.push({ cls, text: t, disabled: el.disabled || el.getAttribute('aria-disabled') === 'true' });
  }
  const inputs = [];
  for (const el of root.querySelectorAll('input, textarea')) {
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    inputs.push({ tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
                  cls, ph: el.getAttribute('placeholder') || '', val: (el.value || '').slice(0, 20) });
  }
  // 진행률 표식
  const prog = [];
  for (const el of root.querySelectorAll('[class*=progress], [class*=percent], [class*=encoding], [class*=loading]')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const cls = el.className && el.className.toString ? el.className.toString() : '';
    prog.push({ cls, text: (el.textContent || '').trim().slice(0, 24) });
  }
  return { gone: false, buttons, inputs, prog, fulltext: (root.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200) };
}
"""


def _dump_upload_state(page, tag):
    st = page.evaluate(_UPLOAD_STATE_JS)
    print(f"\n----- [{tag}] 업로더 상태 -----")
    if st.get("gone"):
        print("(모달 사라짐 — 본문에 삽입됐을 가능성)")
        return True
    print(f"  text: {st['fulltext']}")
    for b in st["buttons"]:
        print(f"  btn  class={b['cls']!r} text={b['text']!r} disabled={b['disabled']}")
    for i in st["inputs"]:
        print(f"  input<{i['tag']}> type={i['type']!r} class={i['cls']!r} ph={i['ph']!r} val={i['val']!r}")
    for p in st["prog"]:
        print(f"  prog class={p['cls']!r} text={p['text']!r}")
    return False


def main() -> int:
    idx = 0
    do_click = "--click" in sys.argv
    upload_path = None
    if "--upload" in sys.argv:
        i = sys.argv.index("--upload")
        upload_path = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    for a in sys.argv[1:]:
        if a.isdigit():
            idx = int(a)

    pub = BlogPublisher().start()
    try:
        if not pub.is_logged_in():
            print("[probe] 로그인 세션 없음 — 브라우저에서 직접 로그인하세요(최대 6분 대기)…")
            if not pub.wait_for_login():
                print("[probe] 로그인 실패/시간초과")
                return 1
        pub.open_write_page()
        page = pub._page

        # 0) --upload: 새 글에 실제 업로드해 인코딩→제목→등록→본문삽입 전 과정 캡처
        if upload_path:
            page.click(SMART_EDITOR["content_component"])
            print(f"[probe] 업로드 흐름 캡처: {upload_path}")
            page.click(".se-toolbar-item-video button")
            page.wait_for_selector(".se-popup-video-upload, .nvu_wrap", timeout=5000)
            page.wait_for_timeout(800)
            with page.expect_file_chooser(timeout=5000) as fc:
                page.click(".nvu_btn_append.nvu_local")
            fc.value.set_files(upload_path)
            print("[probe] 파일 지정 완료 — 업로드 완료까지 대기…")
            # 업로드 완료 신호: 모달 텍스트에 '업로드 완료' 출현
            for sec in range(0, 60, 3):
                page.wait_for_timeout(3000)
                txt = page.evaluate(
                    "() => { const r=document.querySelector('.nvu_wrap'); return r?r.textContent:''; }"
                )
                if "업로드 완료" in (txt or ""):
                    print(f"[probe] 업로드 완료 감지 ({sec + 3}s)")
                    break
            # 제목 필수 → 입력 후 '완료' 클릭
            print("[probe] 제목 입력 + '완료' 클릭…")
            page.fill("input.nvu_inp", "테스트 동영상")
            page.wait_for_timeout(300)
            page.click(".nvu_btn_submit")
            # 본문 삽입 대기
            inserted = False
            for sec in range(0, 60, 3):
                page.wait_for_timeout(3000)
                if page.query_selector(".se-component.se-video"):
                    print(f"[probe] >>> 본문에 .se-component.se-video 삽입 확인 ({sec + 3}s)")
                    inserted = True
                    break
                if not page.query_selector(".nvu_wrap"):
                    # 모달은 닫혔는데 컴포넌트 못 찾음 → 한 번 더 확인
                    page.wait_for_timeout(1500)
                    inserted = bool(page.query_selector(".se-component.se-video"))
                    break
            if inserted:
                thumb = page.evaluate(
                    "() => { const t=document.querySelector('.se-component.se-video .se-video-thumbnail'); "
                    "return t ? (t.getAttribute('style')||'').slice(0,80) : '(썸네일 없음)'; }"
                )
                print(f"[probe] 삽입된 동영상 썸네일 style: {thumb}")
                print("[probe] ✅ 업로드→제목→완료→본문삽입 전 과정 자동화 가능 확인")
            else:
                print("[probe] ❌ 본문 미삽입 — 모달 최종 상태:")
                _dump_upload_state(page, "final")
            page.wait_for_timeout(1500)
            return 0

        # 1) 임시저장 글(idx) 로드 — 이미 영상이 들어 있는 글
        print(f"[probe] 임시저장 idx={idx} 로드 중…")
        pub._open_draft_list()
        buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
        if not buttons:
            print("[probe] 임시저장 글이 없음")
        elif idx >= len(buttons):
            print(f"[probe] idx 범위 초과: {idx} (총 {len(buttons)}건)")
        else:
            buttons[idx].click()
            page.wait_for_timeout(1500)
            confirm = page.query_selector(SMART_EDITOR["draft_load_confirm"])
            if confirm and confirm.is_visible():
                confirm.click()
            page.wait_for_timeout(2500)

        # 2) 본문 동영상 컴포넌트 덤프
        vid = page.evaluate(_VIDEO_JS)
        print("\n===== 본문 동영상 컴포넌트 =====")
        if not vid["comps"]:
            print("(동영상 컴포넌트를 못 찾음 — 이 글에 영상이 없거나 셀렉터가 다름)")
        for c in vid["comps"]:
            print(f"- class={c['cls']!r}  video={c['hasVideo']} iframe={c['hasIframe']} {c['w']}x{c['h']}")
            print(f"    html: {c['html']}")
        print("\n----- 인코딩/진행 표식 후보 -----")
        for p in vid["prog"]:
            print(f"- class={p['cls']!r}  text={p['text']!r}")
        if not vid["prog"]:
            print("(없음 — 인코딩 이미 완료 상태일 가능성)")

        # 3) 툴바 '동영상' 버튼 후보
        tb = page.evaluate(_TOOLBAR_JS)
        print("\n===== 툴바 '동영상' 버튼 후보 =====")
        if not tb:
            print("(없음 — 툴바가 접혀 있거나 클래스가 예상과 다름)")
        for h in tb:
            print(f"- <{h['tag']}> class={h['cls']!r}")
            if h["aria"]:
                print(f"    aria-label={h['aria']!r}")
            if h["dataName"] or h["dataLog"] or h["clickArea"]:
                print(f"    data-name={h['dataName']!r} data-log={h['dataLog']!r} click-area={h['clickArea']!r}")
            if h["text"]:
                print(f"    text={h['text']!r}")

        # 4) (옵션) 동영상 버튼 클릭 → 업로더 모달 내부 정밀 탐색
        if do_click:
            print("\n[probe] --click: 동영상 버튼 클릭 → 업로더 모달 탐색…")
            page.click(".se-toolbar-item-video button")
            try:
                page.wait_for_selector(".se-popup-video-upload, .nvu_wrap", timeout=5000)
            except Exception:
                print("[probe] 업로더 모달이 안 뜸")
                return 0
            page.wait_for_timeout(1200)
            nvu = page.evaluate(_NVU_JS)
            print("\n===== 동영상 업로더(NVU) 모달 내부 =====")
            for it in nvu["items"]:
                mark = "" if it["vis"] else " (hidden)"
                print(
                    f"- <{it['tag']}> type={it['type']!r} id={it['id']!r} "
                    f"class={it['cls']!r} text={it['text']!r}{mark}"
                )
            print("----- iframe -----")
            for f in nvu["iframes"]:
                print(f"- id={f['id']!r} class={f['cls']!r} src={f['src']!r}")
            if not nvu["iframes"]:
                print("(없음 — 같은 문서 내 업로더)")

            # 로컬 업로드 버튼(.nvu_btn_append.nvu_local)이 파일 다이얼로그를 여는지 확인
            print("\n[probe] '.nvu_btn_append.nvu_local' 클릭 → 파일창 여부 확인…")
            try:
                with page.expect_file_chooser(timeout=5000) as fc:
                    page.click(".nvu_btn_append.nvu_local")
                print(f"[probe] → 파일 다이얼로그 열림! multiple={fc.value.is_multiple()}")
                print("[probe] set_files 로 업로드 가능 → 이후 인코딩 대기/등록 단계 탐색 필요")
            except Exception as e:
                print(f"[probe] → 파일창 안 뜸({e!r}): 추가 단계 가능. DOM 재덤프:")
                page.wait_for_timeout(1000)
                for m in page.evaluate(_MODAL_JS):
                    print(f"    <{m['tag']}> file={m['isFile']} class={m['cls']!r} text={m['text']!r}")

        print(
            "\n[probe] 위 출력에서\n"
            "  - 동영상 툴바 버튼 → SMART_EDITOR['video_upload_button']\n"
            "  - 본문 동영상 컴포넌트 class → SMART_EDITOR['editor_video']\n"
            "  - (모달이면) input[type=file] → SMART_EDITOR['video_file_input']\n"
            "  을 골라 채우세요. (브라우저는 곧 닫힙니다)"
        )
        page.wait_for_timeout(2000)
        return 0
    finally:
        pub.close(save_session=False)


if __name__ == "__main__":
    raise SystemExit(main())
