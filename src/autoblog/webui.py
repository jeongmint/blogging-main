"""글쓰기 유저 화면 — 로컬 웹(표준 http.server, npm/node 0).

스티커 검수에서 검증한 "로컬 서버 + 브라우저" 패턴을 앱 전체로 확장한 유저 화면.
탭: 글쓰기(메모/수집/사진/서식 → 생성 → 미리보기 → 임시저장) · 스티커(즐겨찾기 보기) · 설정(글쓰기 규칙).
`autoblog ui` 한 줄이 서버 기동 + 브라우저 자동 오픈. 최종 유저용은 이후 PyInstaller 더블클릭 앱.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from autoblog.config import CONFIG_DIR, DATA_DIR, REPO_ROOT, USER_CONFIG_DIR, USER_DATA_DIR

PHOTO_DIR = REPO_ROOT / "test"  # 유저 사진/영상 폴더(테스트용)
_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
from autoblog.collect.photos import VIDEO_EXT as _VID_EXT  # noqa: E402  영상 확장자(단일 출처)
from autoblog.collect.photos import is_video  # noqa: E402
_MEDIA_EXT = _IMG_EXT | _VID_EXT
UPLOAD_DIR = DATA_DIR / "uploads"  # 유저가 올린 사진/영상
FONTS_DIR = CONFIG_DIR / "fonts"  # 에디터 웹폰트(번들 자산, 로컬 서빙)
ASSETS_DIR = CONFIG_DIR / "assets"  # 로딩 애니메이션 등 정적 자산(로컬 서빙)
# 미리보기에서 실제 글씨체로 보이게 — 에디터와 같은 se-* 패밀리명 사용
_FONT_FAMILIES = [
    "nanumgothic", "nanummyeongjo", "nanumbarungothic", "nanumsquare",
    "nanummaruburi", "nanumdasisijaghae", "nanumbareunhipi", "nanumuriddalsongeulssi",
]


def _font_face_css() -> str:
    return "\n".join(
        f"@font-face{{font-family:'se-{f}';src:url('/font?name=se-{f}') format('woff2');font-display:swap}}"
        for f in _FONT_FAMILIES
    )

_PAGE = r"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>글쓰기</title><style>
 /*FONTFACES*/
 :root{
   --green:#03c75a;--green-d:#02b350;--green-soft:#eafaf0;
   --ink:#1f2329;--sub:#8b95a1;--line:#e8eaed;--bg:#f2f4f6;
   --red:#e5484d;--ok:#1f9d57;--blue:#3b82c4;
   --r-sm:8px;--r:12px;--r-lg:16px;--r-pill:999px;
   --fs-xs:12px;--fs-sm:13px;--fs-md:14px;--fs-lg:16px;--fs-xl:20px}
 *{box-sizing:border-box}
 input[type=checkbox]{accent-color:var(--green)}
 :where(button,.chip,.nav,summary):focus-visible{outline:2px solid #03c75a66;outline-offset:2px}
 svg.ic{width:18px;height:18px;display:inline-block;vertical-align:middle;flex:0 0 auto;stroke:currentColor}
 .btn .ic,.mx .ic{width:16px;height:16px;margin-right:6px;margin-top:-2px}
 body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Pretendard',sans-serif;
   background:var(--bg);color:var(--ink);display:flex;height:100vh;overflow:hidden}
 /* sidebar */
 .side{width:212px;flex:0 0 212px;background:#fff;border-right:1px solid var(--line);padding:18px 12px;display:flex;flex-direction:column;gap:4px}
 .brand{font-size:15px;font-weight:800;padding:8px 10px 16px;display:flex;align-items:center;gap:9px}
 .brand .ic{width:20px;height:20px;color:var(--green-d)}
 .nav{display:flex;align-items:center;gap:10px;padding:11px 12px;border-radius:var(--r-sm);cursor:pointer;color:#4b5563;font-size:var(--fs-md);font-weight:600}
 .nav:hover{background:#f6f8fa}
 .nav.on{background:var(--green-soft);color:var(--green-d)}
 .nav .ic{width:19px;height:19px;color:#9aa3ad}
 .nav.on .ic{color:var(--green-d)}
 .side .foot{margin-top:auto;font-size:11px;color:var(--sub);padding:8px 10px;line-height:1.6}
 /* main */
 main{flex:1;overflow:auto;padding:26px 30px}
 .view{display:none}.view.on{display:block}
 h2.title{font-size:20px;margin:0 0 4px}
 .desc{color:var(--sub);font-size:13px;margin:0 0 20px}
 /* write layout */
 .grid{display:grid;grid-template-columns:minmax(360px,460px) minmax(0,1fr);gap:22px;align-items:start}
 .card{background:#fff;border:1px solid var(--line);border-radius:var(--r-lg);padding:20px}
 .card h3{font-size:13px;margin:0 0 12px;color:#374151}
 label.f{display:block;font-size:12px;color:#6b7280;margin:14px 0 6px;font-weight:600}
 label.f:first-child{margin-top:0}
 /* type 없는 <input>도 text — 셀렉터에 빠지면 테두리·패딩 없는 맨 input으로 보인다(키워드 경쟁 확인·순위 추적) */
 input:where(:not([type])),input[type=text],input[type=number],input[type=url],textarea{width:100%;border:1px solid #d6dade;border-radius:10px;padding:10px 12px;font-size:13px;font-family:inherit;background:#fbfcfd}
 input:where(:not([type])):focus,input[type=text]:focus,input[type=number]:focus,input[type=url]:focus,textarea:focus{outline:2px solid #03c75a33;border-color:var(--green)}
 input[type=number]{-moz-appearance:textfield}
 input[type=number]::-webkit-outer-spin-button,input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
 textarea{min-height:130px;resize:vertical;line-height:1.6}
 /* 단계 헤더 — 글쓰기 흐름(①글감 ②스타일 ③생성 ④검토·발행)을 카드마다 번호로 표시 */
 .step{display:flex;align-items:center;gap:8px;margin:0 0 6px}
 .step .stepn{width:22px;height:22px;flex:0 0 22px;border-radius:50%;background:var(--green-soft);color:var(--green-d);font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center}
 .step .stept{font-size:14px;font-weight:800;color:var(--ink)}
 .step .steps{font-size:12px;color:var(--sub);font-weight:500}
 .req{display:inline-block;font-size:10px;font-weight:800;color:#d6453c;background:#fdecec;border-radius:5px;padding:1.5px 6px;margin-left:5px;vertical-align:1px}
 /* 세부 옵션 접기 — 저빈도 필드(문체 톤·최소 글자 수)는 기본 접힘 */
 .moreopts{margin-top:14px;border-top:1px dashed var(--line)}
 .moreopts summary{cursor:pointer;list-style:none;font-size:12px;font-weight:700;color:var(--sub);padding:10px 0 2px;user-select:none;display:flex;align-items:center;gap:6px}
 .moreopts summary::-webkit-details-marker{display:none}
 .moreopts summary .chev{font-size:9px;transition:transform .15s}
 .moreopts[open] summary .chev{transform:rotate(90deg)}
 .moreopts summary:hover{color:var(--ink)}
 /* 발행 바 — 미리보기 바로 위 카테고리+임시저장(검토한 그 자리에서 저장) */
 .pubbar{display:flex;gap:10px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:var(--r-lg);padding:13px 16px;margin-bottom:14px}
 .pubbar .step{margin:0;flex:0 0 auto}
 .pubbar .catwrap{flex:1;min-width:0}
 .pubbar #save{width:auto;flex:0 0 auto;padding:11px 22px}
 .pubbar .pubmode,.pubbar .reserveat{flex:0 0 auto;padding:9px 10px;border:1px solid var(--line);border-radius:var(--r-sm);font-size:13px;background:#fff}
 .reservehint{font-size:12.5px;color:var(--sub);margin:-6px 0 14px;padding:0 4px}
 .reservehint.warn{color:#8a6a0a}
 /* 빈 미리보기 — 진행 안내 */
 .docguide{text-align:center;color:#b0b8c1}
 .docguide .dg-ic{font-size:38px;margin-bottom:12px}
 .docguide .dg-t{font-size:14.5px;font-weight:700;color:#8b95a1;margin-bottom:18px}
 .docguide .dg-steps{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;font-size:12.5px}
 .docguide .dg-s{padding:7px 13px;border:1px solid var(--line);border-radius:999px;background:#fbfcfd;font-weight:600;color:#9aa3ad;white-space:nowrap}
 .docguide .dg-a{margin:0 8px;color:#cbd2d9}
 /* 필수 키워드 칩 입력: 컨테이너가 input처럼 보이고, 안에 칩 + 실제 입력칸이 흐른다 */
 .kwbox{display:flex;flex-wrap:wrap;gap:6px;align-items:center;border:1px solid #d6dade;border-radius:10px;padding:6px 8px;background:#fbfcfd;cursor:text}
 .kwbox:focus-within{outline:2px solid #03c75a33;border-color:var(--green)}
 .kwbox input[type=text]{flex:1;min-width:140px;width:auto;border:none;background:transparent;padding:4px 4px}
 .kwbox input[type=text]:focus{outline:none;border:none}
 .kwchip{display:inline-flex;align-items:center;gap:2px;background:#eafaf0;border:1px solid #b7e4c7;color:var(--green-d);border-radius:999px;padding:3px 5px 3px 10px;font-size:12px;line-height:1.4;font-weight:600;max-width:100%}
 .kwchip span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:240px}
 .kwchip b{font-weight:400;opacity:.5;cursor:pointer;padding:0 5px;font-size:13px;user-select:none}
 .kwchip b:hover{opacity:1;color:#c0392b}
 /* 키워드 노출 판정 — 칩 색으로 '노려볼 만한 키워드인지' 바로 표시 */
 .kwchip.jmid{background:#fdf6ec;border-color:#f0ddc0;color:#8a6a0a}
 .kwchip.jbad{background:#fdeeee;border-color:#eec2c2;color:#b03a3a}
 .kwchip.jwait{background:#f2f3f5;border-color:#e2e5ea;color:#8b93a0}
 .kwchip .jbadge{font-size:11px;margin-right:3px;flex:0 0 auto}
 .kwlegend{font-size:11.5px;color:var(--sub);margin-top:5px}
 /* 연관검색어 추천 — 경쟁 낮은(유리한) 순으로, 눌러서 바로 키워드에 추가 */
 .kwrec{margin-top:7px}
 .kwrec .kwrec-t{font-size:11.5px;color:var(--sub);margin-bottom:5px;display:flex;align-items:center;gap:4px}
 .kwrec .kwrec-re{margin-left:auto;background:none;border:none;color:var(--green-d);font-size:11px;font-weight:600;cursor:pointer;padding:2px 6px;border-radius:6px;white-space:nowrap}
 .kwrec .kwrec-re:hover{background:#eafaf0}
 .kwrec .kwrec-list{display:flex;flex-wrap:wrap;gap:6px}
 .kwrec .rc{display:inline-flex;align-items:center;gap:4px;background:#fff;border:1px dashed #cdd3da;color:#4b5563;
   border-radius:999px;padding:4px 10px 4px 8px;font-size:12px;font-weight:600;cursor:pointer;transition:.12s}
 .kwrec .rc:hover{border-style:solid;border-color:var(--green);color:var(--green-d);background:#f3fcf6;transform:translateY(-1px)}
 .kwrec .rc .rcb{font-size:11px}
 .kwrec .rc .rcplus{opacity:.4;font-weight:400;margin-left:1px}
 .kwrec .rc:hover .rcplus{opacity:.8;color:var(--green-d)}
 .seg{display:flex;gap:6px}
 .seg button{flex:1;padding:9px;font-size:12px;background:#fff;color:#6b7280;border:1px solid #d6dade;border-radius:9px;cursor:pointer;font-weight:600}
 .seg button.on{background:#eafaf0;color:var(--green-d);border-color:var(--green)}
 .chips{display:flex;flex-wrap:wrap;gap:8px}
 .chip{display:inline-flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid #d6dade;border-radius:999px;font-size:12.5px;cursor:pointer;background:#fff;user-select:none}
 .chip.on{background:var(--green);color:#fff;border-color:var(--green)}
 .chip .dot{width:7px;height:7px;border-radius:50%;background:#cbd2d9}
 .chip.on .dot{background:#fff}
 .btn{display:block;width:100%;padding:13px;border:none;border-radius:var(--r);background:var(--green);color:#fff;font-size:var(--fs-md);font-weight:700;cursor:pointer}
 .btn:hover{background:var(--green-d)}
 .btn:disabled{opacity:.45;cursor:default}
 .btn.ghost{background:#fff;color:var(--ink);border:1px solid #d6dade;font-weight:600}
 .btn.danger{background:var(--red)}
 .btn.danger:hover{background:#c93a3f}
 #status{font-size:12.5px;color:var(--sub);min-height:18px;margin-top:6px;display:flex;align-items:center;gap:8px}
 .spin{width:13px;height:13px;border:2px solid #d6dade;border-top-color:var(--green);border-radius:50%;animation:sp .7s linear infinite;display:none}
 @keyframes sp{to{transform:rotate(360deg)}}
 .loading .spin{display:inline-block}
 /* 타자기 효과: 한 글자씩 나오는 동안 깜빡이는 캐럿 표시(대기 문구용) */
 .typing::after{content:'';display:inline-block;width:2px;height:1.02em;margin-left:2px;border-radius:1px;background:currentColor;vertical-align:text-bottom;animation:cur .8s step-end infinite}
 @keyframes cur{50%{opacity:0}}
 .spincount{color:var(--sub)}
 /* 수집 종류(맛집/상품) — 크게 잘 보이게 */
 .kindseg{display:flex;gap:8px;margin-top:8px}
 .kindseg button{flex:1;padding:12px;font-size:14px;font-weight:800;background:#fff;color:#9aa3ad;border:2px solid #e0e3e7;border-radius:11px;cursor:pointer;transition:.12s}
 .kindseg button .em{font-size:17px;margin-right:5px}
 .kindseg button.on{background:var(--green);color:#fff;border-color:var(--green);box-shadow:0 3px 10px #03c75a44}
 .kindseg button.auto{outline:3px solid #03c75a33}
 /* 상단 임시저장 작업 탭바 — 백그라운드 저장을 글마다 탭으로 띄운다. 실패한 탭은 남아 다시 시도. */
 #savebar{position:fixed;top:12px;left:224px;right:16px;z-index:9998;display:flex;flex-wrap:wrap;gap:8px;pointer-events:none}
 #savebar:empty{display:none}
 .stab{display:flex;align-items:center;gap:8px;max-width:340px;background:#fff;border:1px solid var(--line);border-radius:11px;padding:8px 10px 8px 12px;font-size:12.5px;font-weight:700;color:var(--ink);box-shadow:0 8px 22px rgba(0,0,0,.14);pointer-events:auto;animation:tin .22s cubic-bezier(.2,.9,.3,1.25)}
 .stab.out{animation:tout .18s ease forwards}
 .stab .spin{display:inline-block;flex:none}
 .stab .sdot{width:15px;height:15px;flex:none;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:900;line-height:1}
 .stab .stitle{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .stab .scnt{color:var(--sub);font-weight:600;flex:none}
 .stab .sretry,.stab .sx{flex:none;display:none;align-items:center;justify-content:center;width:22px;height:22px;border:none;border-radius:7px;background:#f2f4f6;color:var(--sub);font-size:12px;cursor:pointer;line-height:1;padding:0}
 .stab .sretry:hover,.stab .sx:hover{background:#e6e9ed;color:var(--ink)}
 .stab.err{border-color:#f0b3ad;background:#fff6f5}
 .stab.err .sdot{color:#e23b2e}
 .stab.err .sretry{display:inline-flex;background:#fde5e2;color:#d0362a;font-weight:800}
 .stab.err .sretry:hover{background:#fbd3ce}
 .stab.err .sx,.stab.warn .sx{display:inline-flex}
 .stab.ok .sdot{color:var(--green-d)}
 .stab.warn{border-color:#f2d9a8;background:#fffaf0}
 .stab.warn .sdot{color:#d98a00}
 /* 멀티 탭(워크스페이스): 글마다 독립 탭. 상단 가로 바 + 새 글(+) 버튼 */
 #workbar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:0 0 16px}
 .wtab{display:flex;align-items:center;gap:6px;max-width:200px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:7px 10px;font-size:12.5px;font-weight:700;color:var(--sub);cursor:pointer;user-select:none;-webkit-user-select:none}
 .wtab:hover{border-color:#cdd3da}
 .wtab.on{color:var(--ink);border-color:var(--green);box-shadow:0 0 0 1px var(--green) inset}
 .wtab .wt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .wtab .wx{flex:none;display:none;align-items:center;justify-content:center;width:18px;height:18px;border:none;border-radius:6px;background:#f2f4f6;color:var(--sub);font-size:11px;cursor:pointer;line-height:1;padding:0}
 .wtab:hover .wx,.wtab.on .wx{display:inline-flex}
 .wtab .wx:hover{background:#e6e9ed;color:var(--ink)}
 .wtab.wadd{color:var(--sub);font-weight:900;font-size:15px;line-height:1;padding:6px 11px}
 .wtab.importing{border-color:#bfe0cf;background:var(--green-soft)}
 .wtab.importing .wt{color:var(--green-d)}
 .wtab .wspin{width:11px;height:11px;flex:none;border:2px solid #cfe9db;border-top-color:var(--green);border-radius:50%;animation:wsp .7s linear infinite;display:none}
 .wtab.importing .wspin{display:inline-block}
 @keyframes wsp{to{transform:rotate(360deg)}}
 /* 토스트 팝업 — 에러/완료를 화면 중앙 상단에 크게 */
 #toasts{position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:9999;display:flex;flex-direction:column;gap:9px;align-items:center;pointer-events:none;width:max-content;max-width:90vw}
 .toast{position:relative;pointer-events:auto;min-width:300px;max-width:560px;padding:14px 46px 14px 16px;border-radius:14px;font-size:14px;font-weight:700;color:#fff;line-height:1.45;box-shadow:0 12px 34px rgba(0,0,0,.26);display:flex;gap:11px;align-items:flex-start;animation:tin .24s cubic-bezier(.2,.9,.3,1.25)}
 .toast.out{animation:tout .18s ease forwards}
 .toast.err{background:linear-gradient(135deg,#f15a4d,#e23b2e)}
 .toast.ok{background:linear-gradient(135deg,#1ec46c,#06a94f)}
 .toast.info{background:linear-gradient(135deg,#3f99f6,#2b7fe0)}
 .toast .ic{font-size:18px;line-height:1.3;flex:none}.toast .msg{flex:1;padding-top:1px}
 .toast .x{position:absolute;top:9px;right:9px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;border-radius:50%;font-size:13px;line-height:1;opacity:.85;cursor:pointer;transition:.12s;background:rgba(255,255,255,.14)}
 .toast .x:hover{opacity:1;background:rgba(255,255,255,.32)}
 @keyframes tin{from{opacity:0;transform:translateY(-12px) scale(.97)}to{opacity:1;transform:none}}
 @keyframes tout{to{opacity:0;transform:translateY(-8px) scale(.97)}}
 /* 공용 모달 — 알림 카드와 같은 페이드+팝 등장, Esc/배경클릭으로 닫힘 */
 .modal{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9998;display:flex;align-items:center;justify-content:center;padding:24px;animation:mfade .15s ease}
 .modalbox{background:#fff;border-radius:16px;width:min(780px,94vw);max-height:88vh;display:flex;flex-direction:column;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);animation:mpop .2s cubic-bezier(.2,.9,.3,1.15)}
 @keyframes mfade{from{opacity:0}}
 @keyframes mpop{from{opacity:0;transform:translateY(10px) scale(.97)}}
 .phbox{width:min(920px,96vw)}
 .phscroll{flex:1;overflow:auto;margin-top:10px}
 .phbox .pgrid{max-height:none;margin-bottom:10px}
 .phbox .pmeta{max-height:none;border:0;padding:0}
 .modalhd{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;font-size:15.5px;font-weight:700}
 .mx{border:0;background:#eef0f2;width:32px;height:32px;border-radius:9px;cursor:pointer;font-size:14px;color:#6b7280;transition:background .12s,color .12s}
 .mx:hover{background:#e2e5ea;color:var(--ink)}
 .modalbox textarea{flex:1;min-height:360px;margin-top:10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;line-height:1.55;background:#fafbfc}
 .modalft{margin-top:14px;display:flex;gap:10px}
 /* photo grid */
 .pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(76px,1fr));gap:8px;max-height:230px;overflow:auto;padding:2px;user-select:none;-webkit-user-select:none}
 .pcell{position:relative;aspect-ratio:1;border-radius:9px;overflow:hidden;cursor:pointer;border:2px solid transparent;background:#eceff3}
 .pcell img{width:100%;height:100%;object-fit:cover;display:block}
 .vidbadge{position:absolute;bottom:4px;right:4px;background:rgba(0,0,0,.72);color:#fff;font-size:10px;font-weight:700;padding:1px 5px;border-radius:7px;pointer-events:none}
 .pcell.sel{border-color:var(--green)}
 .dropzone{border:2px dashed #cdd3da;border-radius:11px;padding:18px;text-align:center;color:var(--sub);font-size:13px;cursor:pointer;margin-bottom:10px}
 .dropzone:hover,.dropzone.drag{border-color:var(--green);background:#f3fcf6;color:var(--green-d)}
 .dropzone.compact{padding:8px 12px;font-size:12px}  /* 사진이 있으면 낮게 접어 분류 공간 확보 */
 .draftlist{border:1px solid #e3e7ec;border-radius:10px;margin-bottom:10px;max-height:220px;overflow:auto}
 #draftload.on{background:var(--green-soft);border-color:var(--green);color:var(--green-d)}
 .draftlist .ditem{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid #f0f2f5;cursor:pointer;font-size:13px}
 .draftlist .ditem:last-child{border-bottom:none}
 .draftlist .ditem:hover{background:#f3fcf6}
 .draftlist .ditem .dt{font-weight:600;color:#1f2937;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .draftlist .ditem{min-height:40px}  /* 모드 무관 고정 높이 — 체크 생겨도 안 늘어남 */
 .draftlist .ditem .dd{color:var(--sub);font-size:11px;white-space:nowrap}
 .draftlist .ditem .dt{flex:1 1 auto;min-width:0}
 /* 다중선택: 앱 기본 초록 액센트에 맞춘 둥근 사각 체크(체크 시 초록+✓).
    자리는 항상 잡아두고(단일 모드=투명) 모드 전환 시 좌우로 안 밀리게 한다. */
 .draftlist .ditem .dckbox{flex:none;width:18px;height:18px;border:2px solid #cdd3da;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:900;color:#fff;line-height:1;transition:border-color .12s,background .12s}
 .draftlist .ditem .dckbox.ghost{border-color:transparent;background:transparent}  /* 단일 모드: 공간만 유지 */
 .draftlist .ditem:hover .dckbox:not(.ghost){border-color:var(--green)}
 .draftlist .ditem.picked .dckbox{background:var(--green);border-color:var(--green)}
 .draftlist .ditem.picked .dckbox::after{content:"✓"}
 .draftlist .ditem.picked{background:var(--green-soft)}
 /* 인라인 툴바용 작은 토글 스위치(설정의 .sw 축소판) */
 .sw.sw-sm{width:34px;height:20px;flex:0 0 34px}
 .sw.sw-sm::after{width:14px;height:14px;top:3px;left:3px}
 .sw.sw-sm.on::after{left:17px}
 #draftmultiwrap{align-items:center;gap:7px;font-size:12.5px;color:var(--sub);white-space:nowrap;cursor:pointer;user-select:none}
 .minibtn{font-size:12px;padding:5px 10px;border:1px solid #cdd3da;border-radius:8px;background:#fff;cursor:pointer;color:#374151}
 .minibtn:hover{border-color:var(--green);color:var(--green-d)}
 .minibtn:disabled{opacity:.55;cursor:default}
 /* 사진 모달 단계 라벨 — ①가져오기 ②선택 ③분류 (글쓰기 탭 단계 헤더와 같은 문법) */
 .msec{display:flex;align-items:center;gap:7px;margin:0 0 8px;font-size:12.5px;font-weight:700;color:var(--ink)}
 .msec .mn{width:18px;height:18px;flex:0 0 18px;border-radius:50%;background:var(--green-soft);color:var(--green-d);font-size:10.5px;font-weight:800;display:flex;align-items:center;justify-content:center}
 .msec .mcnt{background:#eef0f2;color:#4b5563;border-radius:9px;padding:1px 7px;font-size:10.5px;font-weight:700}
 .msec .mh{font-weight:500;color:var(--sub);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .pmeta{display:none;margin-top:8px;border:1px solid #e5e7eb;border-radius:10px;padding:8px;max-height:360px;overflow:auto;user-select:none;-webkit-user-select:none}
 .pmeta.open{display:block}
 .pmhead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;font-size:12px;color:#374151}
 .pmstate.on{background:var(--green-soft);color:var(--green-d);padding:3px 9px;border-radius:7px}
 /* ✨ AI 분석 진행바 — 상태는 전역(AIPROG)이라 모달을 닫았다 열어도 이어서 보인다 */
 .aibar{flex:1;max-width:220px;height:6px;background:#eef1f4;border-radius:99px;overflow:hidden}
 .aifill{display:block;height:100%;background:linear-gradient(90deg,#03c75a,#5fe0a0);border-radius:99px;transition:width .4s ease}
 .pmboard{display:flex;flex-direction:column;gap:6px}
 .pmlane{border:1px solid #e5e7eb;border-radius:8px;padding:5px 6px;background:#fafbfc;cursor:pointer;transition:background .12s,border-color .12s}
 .pmlane.over{border-color:var(--green);background:#eafaf0;box-shadow:0 0 0 2px rgba(46,160,67,.18) inset}
 .pmlane.active{border-color:var(--green);background:#eafaf0}
 .pmlane.lmove{box-shadow:0 -3px 0 -1px var(--green)}
 .pmlanehd{font-size:11px;color:#6b7280;font-weight:600;margin-bottom:4px;display:flex;align-items:center;gap:5px}
 .pmgrip{cursor:grab;color:#c2c8d0;letter-spacing:-2px}
 .pmlane.sub{margin-left:18px;border-style:dashed;background:#fff}
 .pmtarget{margin-left:auto;background:var(--green);color:#fff;border-radius:9px;padding:0 7px;font-size:10px;font-weight:600}
 .pmsubbtn{margin-left:auto;border:0;background:#eef0f2;color:#4b5563;border-radius:7px;padding:1px 7px;font-size:10px;cursor:pointer}
 .pmsubbtn:hover{background:var(--green);color:#fff}
 .pmsubdel,.pmcatdel{border:0;background:transparent;color:#9ca3af;font-size:12px;cursor:pointer;padding:0 2px}
 .pmsubdel:hover,.pmcatdel:hover{color:#d9534f}
 .pmcount{background:#e5e7eb;color:#374151;border-radius:9px;padding:0 6px;font-size:10px}
 .pmdrop{display:flex;flex-wrap:wrap;gap:6px;min-height:44px;align-items:flex-start}
 .pmtile{position:relative;width:54px;height:54px;border-radius:6px;cursor:pointer}
 .pmtile img{width:54px;height:54px;object-fit:cover;border-radius:6px;border:1px solid #e5e7eb;background:#fff;display:block}
 .pmtile.sel img{outline:2px solid var(--green);outline-offset:1px;border-color:var(--green)}
 .pmtile img:active{cursor:grabbing}
 .pmx{position:absolute;top:-6px;right:-6px;width:18px;height:18px;border-radius:50%;border:0;background:#4b5563;color:#fff;font-size:12px;line-height:1;cursor:pointer;display:none;align-items:center;justify-content:center;padding:0}
 .pmtile:hover .pmx{display:flex}
 /* 대표 썸네일 — ★ 지정 버튼·대표 리본·강조 테두리 */
 .pmstar{position:absolute;top:-6px;left:-6px;width:18px;height:18px;border-radius:50%;border:0;background:#fff;color:#cbd2d9;font-size:12px;line-height:1;cursor:pointer;display:none;align-items:center;justify-content:center;padding:0;box-shadow:0 1px 3px #0002}
 .pmstar:hover{color:#ffb400}
 .pmstar.on{display:flex;background:#ffb400;color:#fff}
 .pmtile:hover .pmstar{display:flex}
 .pmtile.thumb img{outline:2px solid #ffb400;outline-offset:1px;border-color:#ffb400}
 .pmribbon{position:absolute;bottom:0;left:0;right:0;background:#ffb400;color:#fff;font-size:9px;font-weight:800;text-align:center;line-height:14px;border-radius:0 0 6px 6px;letter-spacing:.5px}
 .pmcap{position:absolute;bottom:-6px;right:-6px;width:18px;height:18px;border-radius:50%;border:0;background:var(--green);color:#fff;font-size:10px;line-height:1;cursor:pointer;display:none;align-items:center;justify-content:center;padding:0;box-shadow:0 1px 3px #0003;z-index:3}
 .pmtile:hover .pmcap{display:flex}
 .pmtile.hascap .pmcap{display:flex;background:var(--green)}
 .pmtile:not(.hascap) .pmcap{background:#9aa3ad}
 .pmthumbbar{display:flex;align-items:center;gap:9px;margin-bottom:9px;padding:8px 10px;border:1px solid #ffe2a6;background:#fffaf0;border-radius:9px;font-size:11.5px;color:#7a5b00}
 .pmthumbbar .pmthumblbl{font-weight:800;color:#b87b00;white-space:nowrap}
 .pmthumbbar img{width:34px;height:34px;object-fit:cover;border-radius:6px;border:1px solid #ffd47a}
 .pmthumbbar .pmempty{padding:0}
 .pmthumbbar .minibtn{margin-left:auto;white-space:nowrap}
 .pmadd{display:flex;align-items:center;justify-content:center;border:1px dashed #cdd3da;border-radius:8px;background:#fff;color:#6b7280;font-size:12px;padding:8px;cursor:pointer}
 .pmadd:hover{border-color:var(--green);color:var(--green-d)}
 .pmempty{font-size:11px;color:#9ca3af;padding:12px 4px}
 .pcell.uploading{opacity:.5}
 .pcell .num{position:absolute;top:4px;left:4px;background:var(--green);color:#fff;width:18px;height:18px;border-radius:50%;font-size:11px;display:none;align-items:center;justify-content:center;font-weight:700}
 .pcell.sel .num{display:flex}
 /* preview */
 .doc{background:#fff;border:1px solid var(--line);border-radius:16px;padding:30px 34px;min-height:300px;overflow-wrap:anywhere}
 /* 노출 순위 추적(설정 탭) */
 .rkadd{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}
 .rkadd input{flex:1;min-width:150px}
 .rkrow{display:flex;gap:10px;align-items:center;padding:7px 2px;border-bottom:1px solid var(--line);font-size:13px}
 .rkrow:last-child{border-bottom:none}
 .rkrank{min-width:80px;font-weight:700}
 .rkkw{flex:1;font-weight:600}
 .rkurl{color:var(--green);text-decoration:none}
 .rkdel{cursor:pointer;color:#b0b8c1;padding:0 4px}
 .rkdel:hover{color:#c0392b}
 /* 키워드 경쟁 확인 */
 .kwchk{display:flex;gap:6px}
 .kwchk input{flex:1;min-width:0}
 /* .btn은 기본이 block+width:100%(큰 기본 버튼) — flex 한 줄 안에서는 내용 폭으로 */
 .kwchk .btn,.rkadd .btn{width:auto;flex:0 0 auto;padding:10px 18px}
 .kwverdict{font-size:14px;font-weight:700;margin:10px 0 2px}
 .kwmeta{font-size:12.5px;color:var(--sub);margin-bottom:8px}
 .kwtop{font-size:12.5px;padding:5px 2px;border-top:1px solid var(--line);display:flex;gap:8px}
 .kwtop .n{color:#b0b8c1;min-width:16px}
 .kwtop .bl{color:var(--sub);flex:0 0 auto;max-width:38%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .kwtop .ti{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .kwtop.me{background:#eefaf3;font-weight:600}
 /* 자동 체크(노출 기본기·가이드라인 대조) — 미리보기 맨 위 */
 .ckok{font-size:12px;color:#0a8a4a;background:#eefaf3;border:1px solid #bfe8d2;border-radius:8px;padding:6px 10px;margin-bottom:14px}
 .ckbad{font-size:12px;color:#8a4a0a;background:#fdf6ec;border:1px solid #f0ddc0;border-radius:8px;padding:8px 10px;margin-bottom:14px}
 .ckbad .cki{margin-top:4px;color:#a05a1c}
 .ckbad .cki small{color:#b98a5e}
 .doc.empty{display:flex;align-items:center;justify-content:center;color:#b0b8c1;font-size:14px;min-height:420px}
 .genload{text-align:center;padding:40px 20px}
 /* 냥캣 로딩 씬: 밤하늘 + 별 + 무지개 꼬리 고양이 (외부 라이브러리 없이 인라인 SVG) */
 .nyanwrap{position:relative;width:320px;height:100px;margin:0 auto;background:linear-gradient(#0f2350,#1c3d7e);border-radius:16px;overflow:hidden}
 .nstar{position:absolute;left:0;width:3px;height:3px;border-radius:50%;background:#fff;opacity:.85;animation:nfly linear infinite}
 @keyframes nfly{from{transform:translateX(330px)}to{transform:translateX(-10px)}}
 .nlot{position:absolute;inset:0}
 .genmsg{font-size:16px;color:#374151;margin-top:14px;font-weight:700}
 .genbar{height:14px;background:#eef1f4;border-radius:99px;overflow:hidden;max-width:340px;margin:20px auto 10px}
 .genfill{height:100%;width:0;background:linear-gradient(90deg,#03c75a,#5fe0a0);border-radius:99px;transition:width .5s ease}
 .genpct{font-size:14px;color:var(--green-d);font-weight:800}
 .gensub{font-size:12px;color:var(--sub);margin-top:6px}
 .promptarea{width:100%;min-height:420px;border:1px solid #d6dade;border-radius:10px;padding:14px;font-size:13px;font-family:ui-monospace,Menlo,monospace;line-height:1.6;resize:vertical;background:#fbfcfd}
 .psec{border:1px solid var(--line);border-radius:10px;margin-bottom:8px;background:#fff;overflow:hidden}
 .psec summary{cursor:pointer;padding:10px 14px;font-weight:600;font-size:13px;user-select:none}
 .psec[open] summary{border-bottom:1px solid var(--line);background:#fbfcfd}
 .psec .psecarea{border:0;border-radius:0;min-height:100px;display:block}
 /* 문체 탭: 저장된 문체 카드 */
 .pcard{border:1px solid var(--line);border-radius:12px;margin-bottom:10px;background:#fff;overflow:hidden;transition:border-color .15s,box-shadow .15s}
 .pcard:hover{border-color:#d3dae1;box-shadow:0 1px 6px rgba(31,35,41,.05)}
 .pcard summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;padding:12px 14px;user-select:none}
 .pcard summary::-webkit-details-marker{display:none}
 .pcard[open] summary{background:#fbfcfd;border-bottom:1px solid var(--line)}
 .pava{width:38px;height:38px;border-radius:11px;background:var(--green-soft);color:var(--green-d);font-weight:800;font-size:15px;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
 .pinfo{flex:1;min-width:0}
 .pname{font-size:14px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .psub{font-size:12px;color:var(--sub);margin-top:3px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}
 .psub span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .ptag{flex:0 0 auto;display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;background:#f2f4f6;font-size:11px;font-weight:600;color:#5b6570}
 .pdel{flex:0 0 auto;border:0;background:none;color:#9aa3ad;font-size:12px;font-weight:600;cursor:pointer;padding:6px 9px;border-radius:8px}
 .pdel:hover{background:#fdeced;color:var(--red)}
 .pchev{width:16px;height:16px;color:#9aa3ad;flex:0 0 auto;transition:transform .18s}
 .pcard[open] .pchev{transform:rotate(180deg)}
 .pbody{padding:12px 14px 14px}
 .pbody .pprof{min-height:170px}
 .pempty{text-align:center;color:var(--sub);font-size:13px;padding:30px 0;line-height:1.8}
 /* 문체 만들기: 불러온 인기글 선택 목록 */
 #pf_posts:not(:empty){border:1px solid var(--line);border-radius:10px;padding:2px 12px;max-height:280px;overflow:auto}
 .pfrow{display:flex;align-items:center;gap:9px;padding:9px 2px;border-bottom:1px solid #f0f2f5;cursor:pointer}
 .pfrow:last-child{border-bottom:none}
 .pfrow:hover{background:#fbfcfd}
 .pempty b{color:#5b6570;font-size:13.5px}
 .poolchip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:8px;padding:4px 8px;margin:3px;font-size:13px;background:#fbfcfd}
 .poolchip button{border:0;background:none;cursor:pointer;color:#9aa3ad;font-size:14px;padding:0}
 .poolrow{display:flex;gap:6px;margin-bottom:6px;align-items:center}
 .poolrow input{flex:1;padding:7px 9px;border:1px solid var(--line);border-radius:8px;font-size:13px}
 .poolrow select{padding:7px 6px;border:1px solid var(--line);border-radius:8px;font-size:13px;background:#fff}
 .pooldel{border:0;background:none;cursor:pointer;color:#9aa3ad;font-size:15px}
 .pooladd{border:1px dashed var(--line);background:#fff;border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer;color:#5b6570;margin-top:2px}
 .doc h1{font-size:23px;margin:0 0 20px;line-height:1.4}
 .doc .tx{font-size:15px;line-height:2;white-space:pre-wrap;margin:0 0 6px}
 /* 구분선 — 종류(variant)별로 미리보기에서도 대략 구분되게 */
 .doc hr{border:none;border-top:1px solid #e3e6ea;width:60%;margin:22px auto}
 .doc hr.solid{border-top:1.5px solid #b8bec6;width:72%}
 .doc hr.dash{border-top:1px dashed #c4c9d0;width:60%}
 .doc hr.bar{border:none;height:3px;background:#8a929c;width:60px;border-radius:2px;margin:22px auto}
 .doc hr.vert{border:none;width:2px;height:26px;background:#8a929c;margin:20px auto}
 .doc .dv{display:flex;align-items:center;gap:14px;max-width:60%;margin:22px auto;color:#b9c0c8}
 .doc .dv::before,.doc .dv::after{content:'';flex:1;border-top:1px solid #dcdfe3}
 .doc .dv .g{font-size:12px;line-height:1}
 /* 인용구 — 에디터 종류(variant)별 모양을 미리보기에서도 구분해 보여준다 */
 .doc .q{color:#3a4250;font-size:16.5px;margin:18px 0;line-height:1.7;white-space:pre-line}
 .doc .q-quote{text-align:center;padding:4px 0}
 .doc .q-quote::before{content:'\201C';display:block;font-size:30px;color:#c4c9d0;line-height:.7}
 .doc .q-quote::after{content:'\201D';display:block;font-size:30px;color:#c4c9d0;line-height:.2;margin-top:8px}
 .doc .doctbl{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}
 .doc .doctbl th,.doc .doctbl td{border:1px solid #d3d7dd;padding:7px 10px;text-align:center}
 .doc .doctbl th{background:#f5f6f8;font-weight:700}
 .doc .q-line{border-left:3px solid #333;padding:2px 0 2px 18px;text-align:left}
 .doc .q-bubble{border:1px solid #d3d7dd;border-radius:5px;padding:18px 20px;text-align:center;position:relative;margin-bottom:28px}
 .doc .q-bubble::after{content:'';position:absolute;left:40px;bottom:-9px;width:15px;height:15px;background:#fff;border:1px solid #d3d7dd;border-top:0;border-left:0;transform:rotate(45deg)}
 .doc .q-underline{border-bottom:1px solid #333;padding:0 0 14px;text-align:left}
 .doc .q-underline::before{content:'\201C';display:block;font-size:26px;color:#c4c9d0;line-height:.9;margin-bottom:4px}
 .doc .q-postit{border:1px solid #d3d7dd;padding:18px 20px;text-align:center;position:relative}
 .doc .q-postit::after{content:'';position:absolute;right:-1px;bottom:-1px;border:9px solid #fff;border-right-color:#d3d7dd;border-bottom-color:#d3d7dd}
 .doc .q-corner{text-align:center;padding:22px 8px;position:relative}
 .doc .q-corner::before,.doc .q-corner::after{content:'';position:absolute;width:20px;height:20px;border:2px solid #333}
 .doc .q-corner::before{left:34px;top:0;border-right:0;border-bottom:0}
 .doc .q-corner::after{right:34px;bottom:0;border-left:0;border-top:0}
 .doc img.st{width:148px;height:148px;object-fit:contain;display:block;margin:10px auto}
 .doc .ph{background:#eef6ff;border:1px dashed #9ec5ff;border-radius:10px;padding:14px;color:#2f6fd6;font-size:13px;margin:10px 0}
 .doc .pvph{margin:14px 0;text-align:center}
 .doc .pvph img{max-width:100%;border-radius:10px;background:#f0f0f0;min-height:60px}
 .doc .pvph figcaption{font-size:12px;color:var(--sub);margin-top:4px}
 .pvimgtg{display:flex;align-items:center;gap:5px;font-size:12.5px;color:var(--sub);cursor:pointer;white-space:nowrap}
 em.hl{font-style:normal;border-radius:3px;padding:1px 3px}
 /* sticker / settings */
 .stgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(136px,1fr));gap:12px;margin-bottom:8px}
 .stcard{position:relative;background:#fff;border:1px solid var(--line);border-radius:14px;padding:10px;text-align:center;transition:border-color .12s,box-shadow .12s}
 .stcard:hover{border-color:#d6dade;box-shadow:0 4px 14px rgba(31,35,41,.07)}
 .stcard img{width:100%;aspect-ratio:1;object-fit:contain;background:#fafbfc;border-radius:9px}
 .stcard .tg{font-size:11px;color:var(--sub);margin-top:6px;line-height:1.4;min-height:28px}
 .tags2{display:flex;flex-wrap:wrap;gap:4px;margin-top:7px;justify-content:center;align-items:center}
 .tg2{background:#eef1f4;border-radius:6px;padding:2px 5px 2px 7px;font-size:11px;display:inline-flex;align-items:center;gap:3px;color:#374151}
 .tg2 .x{cursor:pointer;color:#aab;font-weight:700;font-size:12px}
 .tg2 .x:hover{color:#e2536a}
 .taginput{border:1px dashed #cdd3da;border-radius:6px;padding:2px 6px;font-size:11px;width:54px;text-align:center}
 .taginput:focus{outline:none;border-color:var(--green);border-style:solid}
 /* 스티커 분류(감정/구분선/헤더) — 카드 내 미니 세그먼트 + 상단 안내 */
 .kseg{display:flex;margin-top:7px;border:1px solid var(--line);border-radius:7px;overflow:hidden}
 .kseg button{flex:1;min-width:0;font-size:10.5px;padding:3.5px 0;border:0;background:#fff;color:var(--sub);cursor:pointer;white-space:nowrap;overflow:hidden}
 .kseg button+button{border-left:1px solid var(--line)}
 .kseg button.on{background:var(--green);color:#fff;font-weight:700}
 .kguide{background:#fff;border:1px solid var(--line);border-radius:12px;margin:0 0 14px;font-size:12.5px;line-height:1.65;color:#374151}
 .kguide summary{list-style:none;cursor:pointer;padding:12px 16px;font-weight:700;display:flex;align-items:center;gap:8px;user-select:none}
 .kguide summary::-webkit-details-marker{display:none}
 .kguide summary .chev{font-size:9px;color:var(--sub);transition:transform .15s}
 .kguide[open] summary .chev{transform:rotate(90deg)}
 .kguide summary:hover{color:var(--ink)}
 .kguide .kbody{display:flex;flex-direction:column;gap:9px;padding:0 16px 14px}
 .kguide b{color:var(--ink)}
 .kguide .krow{display:grid;grid-template-columns:52px 1fr;gap:10px;align-items:start}
 .kguide .kk{text-align:center;background:var(--green-soft);color:var(--green-d);border-radius:6px;font-weight:700;font-size:11.5px;padding:2.5px 4px;margin-top:1px}
 .kguide .knote{color:var(--sub);border-top:1px dashed var(--line);padding-top:9px}
 .favbtn{position:absolute;top:6px;right:6px;width:26px;height:26px;border-radius:50%;border:1px solid var(--line);
   background:#fff;color:#cbd2d9;font-size:15px;cursor:pointer;line-height:1;padding:0;display:flex;align-items:center;justify-content:center;box-shadow:0 1px 3px #0001}
 .favbtn.on{color:#ffb400;border-color:#ffe2a6;background:#fffaf0}
 .packh{font-size:13px;color:#4b5563;font-weight:700;margin:18px 0 10px}
 .packh small{color:var(--sub);font-weight:500}
 .stat{display:flex;gap:18px;margin-bottom:18px}
 .stat .b{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 18px;min-width:88px}
 .stat .b .n{font-size:22px;font-weight:800;color:var(--green-d);font-variant-numeric:tabular-nums}
 .stat .b .l{font-size:12px;color:var(--sub)}
 .setrow{display:flex;justify-content:space-between;align-items:center;padding:16px 4px;border-bottom:1px solid var(--line)}
 .setrow:last-child{border:none}
 .setrow .t{font-size:14px;font-weight:600}.setrow .d{font-size:12px;color:var(--sub);margin-top:3px;max-width:520px}
 .sw{width:44px;height:26px;border-radius:999px;background:#cdd3da;position:relative;cursor:pointer;flex:0 0 44px;transition:.15s}
 .sw.on{background:var(--green)}
 .sw::after{content:"";position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:.15s}
 .sw.on::after{left:21px}
 .muted{color:var(--sub);font-size:12.5px}
 .vgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px;margin-bottom:8px}
 .vcell{border:2px solid var(--line);border-radius:12px;padding:13px 15px;cursor:pointer;background:#fff}
 .vcell.on{border-color:var(--green);background:#f3fcf6}
 .vcell .vinfo{margin-bottom:8px}
 .vcell .vname{font-size:13.5px;font-weight:700;display:flex;align-items:center;gap:6px}
 .vcell .vck{color:var(--green-d)}
 .vcell .vdesc{font-size:11.5px;color:var(--sub);margin-top:2px;line-height:1.4}
 .vcell img{width:100%;height:auto;max-height:38px;object-fit:contain;object-position:left}
 .vcell.q img{max-height:140px;object-position:center}
 .epgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
 .eprow{display:flex;align-items:center;gap:5px;margin-top:6px;font-size:11px;color:var(--sub)}
 .eprow label{display:flex;align-items:center;gap:3px;cursor:pointer}
 .eprow input[type=color]{width:26px;height:22px;padding:0;border:1px solid #d6dade;border-radius:5px;background:#fff;cursor:pointer}
 .eprow select{padding:3px 4px;border:1px solid #d6dade;border-radius:6px;font-size:11px;background:#fff;cursor:pointer;min-width:0}
 .epsel-font{flex:1 1 auto;max-width:100%}
 .epclr-off{opacity:.35}
 .epcell{border:1px solid var(--line);border-radius:10px;padding:9px 10px;background:#fff}
 .epnum{font-size:11px;color:var(--sub);font-weight:600;margin-bottom:6px;display:flex;align-items:center}
 .epcell .sw-chip{display:inline-block;font-size:14px}
 .epmeta{font-size:11px;color:var(--sub);margin-top:5px}
 .swrap{display:flex;flex-wrap:wrap;gap:9px;align-items:center}
 .sw-chip{padding:8px 14px;border-radius:9px;font-size:14px;font-weight:600;border:1px solid var(--line);background:#fff}
 .sw-chip .pid{font-size:10px;opacity:.55;margin-left:6px;font-weight:500}
 .sub-h{font-size:12px;color:#6b7280;font-weight:700;margin:16px 0 9px}.sub-h:first-child{margin-top:4px}
 .promptbox details{border-top:1px solid var(--line);padding:4px 0}.promptbox details:first-child{border:none}
 .promptbox summary{cursor:pointer;font-size:13px;font-weight:600;padding:8px 0}
 .promptbox pre{background:#f6f8fa;border:1px solid var(--line);border-radius:10px;padding:14px;font-size:12px;line-height:1.65;white-space:pre-wrap;max-height:320px;overflow:auto;font-family:ui-monospace,Menlo,monospace;margin:4px 0 10px}
 .mcmd{background:#1f2329;color:#e8eaed;border-radius:10px;padding:14px 16px;font-size:13px;font-family:ui-monospace,Menlo,monospace;line-height:1.8;white-space:pre-wrap}
 .mgroup{font-size:12px;color:var(--sub);font-weight:700;margin:16px 0 8px;display:flex;align-items:center;gap:7px}
 .mgrid{display:flex;flex-wrap:wrap;gap:9px}
 .mcard{position:relative;border:1.5px solid #d6dade;border-radius:12px;padding:12px 16px 11px;cursor:pointer;background:#fbfcfd;min-width:150px;transition:.12s}
 .mcard:hover{border-color:#9aa5b1;background:#fff}
 .mcard.on{border-color:var(--green);background:var(--green-soft);box-shadow:0 0 0 2px #03c75a22}
 .mcard.miss{opacity:.62}
 .mc-t{font-weight:700;font-size:14px;color:var(--ink)}
 .mc-s{font-size:11.5px;color:var(--sub);margin-top:3px}
 .mc-ck{display:inline-block;margin-top:7px;font-size:11px;color:var(--green-d);font-weight:800}
 .curpill{display:inline-flex;align-items:center;gap:7px;background:var(--green-soft);color:var(--green-d);font-size:12px;font-weight:800;border-radius:999px;padding:5px 12px}
 .curpill .cdot{width:7px;height:7px;border-radius:50%;background:var(--green);flex:none}
 .keychip{font-size:10.5px;padding:1px 7px;border-radius:5px;font-weight:700}
 .keychip.ok{background:var(--green-soft);color:var(--green-d)}
 .keychip.no{background:#fdecec;color:#d6453c}
 .logflags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
 .lf{font-size:11px;padding:3px 8px;border-radius:6px;background:#eef1f4;color:#555}
 .lf.ok{background:#eafaf0;color:#02b350}.lf.no{background:#fdecef;color:#d9534f}
 .logpre{background:#f6f8fa;border:1px solid var(--line);border-radius:9px;padding:12px;font-size:11.5px;line-height:1.6;white-space:pre-wrap;max-height:300px;overflow:auto;font-family:ui-monospace,Menlo,monospace;margin:4px 0 8px}
 .logsum{cursor:pointer;font-size:12px;font-weight:600;padding:6px 0;color:#4b5563}
 /* 도움말 툴팁(ⓘ) — 긴 설명을 마우스 오버로 */
 .hint{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;border-radius:50%;
   background:#dfe3e8;color:#fff;font-size:10px;font-weight:800;cursor:help;position:relative;vertical-align:middle;margin-left:4px;font-style:normal;transition:background .12s,transform .12s}
 .hint:hover{background:var(--green);transform:translateY(-1px)}
 /* 툴팁 박스는 ⓘ 왼쪽 기준으로 오른쪽으로 펼침 — 가운데 정렬이면 왼쪽 라벨에서 main overflow에 잘려 사이드바에 가려진다 */
 /* 뜰 때 아래에서 살짝 떠올라(translateY) '올라오는' 느낌 — 그림자도 진하게 해 위로 뜬 카드처럼 */
 .hint::after{content:attr(data-tip);position:absolute;left:-10px;bottom:calc(100% + 8px);
   background:#1f2329;color:#fff;font-size:12px;font-weight:500;line-height:1.5;padding:9px 12px;border-radius:9px;
   width:max-content;max-width:260px;white-space:normal;text-align:left;box-shadow:0 12px 30px rgba(0,0,0,.30);
   opacity:0;visibility:hidden;transform:translateY(8px) scale(.96);transform-origin:left bottom;
   transition:opacity .16s ease,transform .22s cubic-bezier(.2,.85,.25,1.15),visibility .22s;z-index:50;pointer-events:none}
 .hint::before{content:"";position:absolute;left:50%;bottom:calc(100% + 2px);transform:translateX(-50%) translateY(8px);
   border:6px solid transparent;border-top-color:#1f2329;opacity:0;visibility:hidden;
   transition:opacity .16s ease,transform .22s cubic-bezier(.2,.85,.25,1.15),visibility .22s;z-index:50}
 .hint:hover::after{opacity:1;visibility:visible;transform:translateY(0) scale(1)}
 .hint:hover::before{opacity:1;visibility:visible;transform:translateX(-50%) translateY(0)}
 /* 협찬 섹션 — 토글 켤 때만 스티커 픽커·링크 펼침 */
 .togrow{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:20px;
   padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:#fbfcfd}
 .togrow .tl{font-size:13px;font-weight:700;color:#374151;display:flex;align-items:center}
 .sponbox{margin-top:10px;padding:14px;border:1px dashed #cdd3da;border-radius:12px;background:#fcfdfe}
 .sponpick{display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:8px;margin:8px 0 4px;max-height:180px;overflow:auto}
 .sponpick .spc{position:relative;aspect-ratio:1;border:2px solid transparent;border-radius:10px;overflow:hidden;cursor:pointer;background:#fafbfc}
 .sponpick .spc img{width:100%;height:100%;object-fit:contain;padding:4px}
 .sponpick .spc.sel{border-color:#7c4dff;background:#f4f0ff}
 .sponpick .spc.sel::after{content:"✓";position:absolute;top:2px;right:4px;color:#7c4dff;font-weight:800;font-size:13px}
 .prodlinkbox{margin-top:14px}
 .plrow{display:flex;gap:6px;margin-top:6px}
 .plrow .plink{flex:1;min-width:0}
 .plrow .plrm{flex:0 0 auto;width:34px;padding:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:var(--sub)}
 /* 보조 액션(복사/붙여넣기) — 한 줄에 작게 */
 .actrow{display:flex;gap:8px;margin-top:9px}
 .actrow .btn{padding:10px;font-size:12px}
 /* 카테고리 버튼 + 팝오버 */
 .catwrap{position:relative}
 .catbtn{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;padding:11px 13px;
   border:1px solid #d6dade;border-radius:11px;background:#fbfcfd;cursor:pointer;font-size:13px;color:var(--ink);font-weight:600}
 .catbtn:hover{border-color:#9aa5b1}
 .catbtn b{font-weight:700}
 .popover{position:absolute;top:calc(100% + 6px);left:0;right:0;z-index:60;background:#fff;border:1px solid var(--line);
   border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,.18);padding:12px;max-height:340px;display:flex;flex-direction:column}
 .popover .catlist{overflow:auto;margin:-2px -4px 0}
 .popover .catopt{padding:8px 10px;border-radius:8px;cursor:pointer;font-size:13px;color:#374151}
 .popover .catopt:hover{background:#f3f6f9}
 .popover .catopt.on{background:var(--green-soft);color:var(--green-d);font-weight:700}
 /* 중앙 알림(오류·확인) — 화면 가운데 카드로 */
 .alertbg{position:fixed;inset:0;background:rgba(20,24,31,.5);z-index:10000;display:flex;align-items:center;justify-content:center;padding:24px;animation:tin .16s ease}
 .alertcard{background:#fff;border-radius:18px;width:min(420px,92vw);padding:26px 26px 22px;text-align:center;box-shadow:0 24px 70px rgba(0,0,0,.32)}
 .alertcard .ai{width:56px;height:56px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:28px;margin:0 auto 14px}
 .alertcard.err .ai{background:#fdecec}.alertcard.info .ai{background:#eaf2fb}.alertcard.ok .ai{background:var(--green-soft)}
 .alertcard .at{font-size:17px;font-weight:800;color:var(--ink);margin:0 0 8px;letter-spacing:-.2px}
 .alertcard .am{font-size:14px;font-weight:600;color:#5a626c;line-height:1.6;white-space:pre-wrap}
 .alertcard .ab{margin-top:20px;display:flex;gap:10px}
 .alertcard .ab .btn{padding:12px}
 /* 임시저장 완료 — 축하 팝업 */
 .okbg{position:fixed;inset:0;background:rgba(20,24,31,.5);z-index:10001;display:flex;align-items:center;justify-content:center;padding:24px;animation:tin .18s ease}
 .okcard{position:relative;overflow:hidden;background:#fff;border-radius:22px;width:min(372px,92vw);padding:36px 28px 26px;text-align:center;box-shadow:0 28px 80px rgba(0,0,0,.34);animation:okpop .42s cubic-bezier(.18,.9,.32,1.4) both}
 @keyframes okpop{from{opacity:0;transform:translateY(10px) scale(.92)}to{opacity:1;transform:none}}
 .okcard .okring{width:88px;height:88px;margin:2px auto 18px;position:relative}
 .okcard .okring::before{content:"";position:absolute;inset:-6px;border-radius:50%;background:var(--green-soft);transform:scale(0);animation:okhalo .5s ease .05s both}
 @keyframes okhalo{to{transform:scale(1)}}
 .okcard .okring svg{position:relative;width:88px;height:88px}
 .okcard .okc{fill:none;stroke:var(--green);stroke-width:5;stroke-dasharray:252;stroke-dashoffset:252;animation:okdraw .55s ease .12s forwards}
 .okcard .okch{fill:none;stroke:var(--green);stroke-width:6;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:60;stroke-dashoffset:60;animation:okdraw .35s ease .5s forwards}
 @keyframes okdraw{to{stroke-dashoffset:0}}
 .okcard .okt{font-size:20px;font-weight:800;color:var(--ink);margin:0 0 8px;letter-spacing:-.3px}
 .okcard .okm{font-size:14px;font-weight:600;color:#5a626c;line-height:1.6}
 .okcard .oksec{margin-top:12px;display:inline-block;font-size:12px;font-weight:700;color:var(--green-d);background:var(--green-soft);padding:5px 12px;border-radius:var(--r-pill)}
 .okcard .okb{margin-top:22px}
 .okcard .okb .btn{padding:13px}
 .okcf{position:absolute;top:-12px;width:9px;height:14px;border-radius:2px;opacity:0;animation:okfall 1.15s ease-out forwards}
 @keyframes okfall{0%{opacity:0;transform:translateY(-10px) rotate(0)}12%{opacity:1}100%{opacity:0;transform:translateY(230px) rotate(420deg)}}
 @media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}}
</style></head><body><div id=toasts></div><div id=savebar></div>
<svg width=0 height=0 style="position:absolute" aria-hidden=true><defs>
 <g id=i-write fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3Z"/><path d="M13.5 6.5l3 3"/></g>
 <g id=i-sticker fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><circle cx=12 cy=12 r=9 /><path d="M8.5 14.5a4 4 0 0 0 7 0"/><circle cx=9 cy=10 r=.7 fill=currentColor stroke=none /><circle cx=15 cy=10 r=.7 fill=currentColor stroke=none /></g>
 <g id=i-format fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.9 1.8-1.9 0-.5-.2-.9-.5-1.2-.3-.3-.4-.6-.4-1 0-1 .8-1.7 1.7-1.7H17a4 4 0 0 0 4-4c0-4.4-4-8-9-8Z"/><circle cx=7.5 cy=11.5 r=.9 fill=currentColor stroke=none /><circle cx=12 cy=7.8 r=.9 fill=currentColor stroke=none /><circle cx=16.4 cy=11.5 r=.9 fill=currentColor stroke=none /></g>
 <g id=i-prompt fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v4h4"/><path d="M9 13h6M9 16.5h4"/></g>
 <g id=i-settings fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><circle cx=12 cy=12 r=3 /><path d="M19.4 13a7.6 7.6 0 0 0 0-2l2-1.5-2-3.4-2.3 1a7.6 7.6 0 0 0-1.7-1l-.4-2.5h-4l-.4 2.5a7.6 7.6 0 0 0-1.7 1l-2.3-1-2 3.4 2 1.5a7.6 7.6 0 0 0 0 2l-2 1.5 2 3.4 2.3-1a7.6 7.6 0 0 0 1.7 1l.4 2.5h4l.4-2.5a7.6 7.6 0 0 0 1.7-1l2.3 1 2-3.4-2-1.5Z"/></g>
 <g id=i-model fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><rect x=7 y=7 width=10 height=10 rx=1.5 /><path d="M10 3v2M14 3v2M10 19v2M14 19v2M3 10h2M3 14h2M19 10h2M19 14h2"/></g>
 <g id=i-copy fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><rect x=8 y=3 width=8 height=4 rx=1 /><path d="M16 5h2v16H6V5h2"/><path d="M9 12h6M9 16h4"/></g>
 <g id=i-inbox fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><path d="M4 14v5h16v-5"/><path d="M12 4v9m0 0 3.5-3.5M12 13 8.5 9.5"/></g>
 <g id=i-search fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><circle cx=11 cy=11 r=6 /><path d="m20 20-3.6-3.6"/></g>
 <g id=i-voice fill=none stroke-width=1.7 stroke-linecap=round stroke-linejoin=round><path d="M21 11.5c0 3.6-4 6.5-9 6.5-1 0-2-.1-2.9-.4L4.5 19l1.1-2.7C4 15.1 3 13.4 3 11.5 3 7.9 7 5 12 5s9 2.9 9 6.5Z"/><path d="M8.5 10.5h7M8.5 13h4.5"/></g>
</defs></svg>
<div id=pmodal class=modal style="display:none"><div class=modalbox>
  <div class=modalhd><span><svg class=ic viewBox="0 0 24 24"><use href="#i-copy"/></svg> 다른 챗봇에 붙여넣을 프롬프트</span><button class=mx id=pmclose>✕</button></div>
  <div id=ploading style="display:none"><div class=genload>
    <div id=pchar></div>
    <div class=genmsg id=pmsg>자료를 모으는 중…</div>
    <div class=genbar><div class=genfill id=pfill></div></div>
    <div class=genpct id=ppct>0%</div>
    <div class=gensub>내 프롬프트와 입력 자료를 합치고 있어요</div></div></div>
  <div id=pcontent>
    <div class=muted>내 베이스 프롬프트 + 켜둔 서식/규칙 지시문 + 입력 자료를 합친 전체 프롬프트예요. 복사해서 ChatGPT·Claude 등에 붙여넣고, <b>받은 글은 [📥 받아온 글 붙여넣기]</b>로 다시 가져오세요.</div>
    <textarea id=ptext readonly></textarea>
    <div class=modalft><button class=btn id=pcopy style="flex:1">복사하기</button><button class="btn ghost" id=pmclose2 style="flex:0 0 120px">닫기</button></div>
  </div>
</div></div>
<div id=imodal class=modal style="display:none"><div class=modalbox>
  <div class=modalhd><span><svg class=ic viewBox="0 0 24 24"><use href="#i-inbox"/></svg> 받아온 글 붙여넣기</span><button class=mx id=imclose>✕</button></div>
  <div class=muted>다른 챗봇에서 받은 글을 붙여넣으세요. 강조 &lt;&lt;…&gt;&gt; · [구분선] · [인용구] · [스티커:상황] 마커가 있으면 그대로 적용돼 미리보기로 보여줍니다. 선택한 사진도 함께 배치돼요. 응답에 자가 점검·=====최종본===== 이 섞여 있어도 <b>통째로 붙여넣으면 최종본만 자동으로 골라내요</b>.</div>
  <textarea id=itext placeholder="여기에 받아온 글을 붙여넣기"></textarea>
  <div class=modalft><button class=btn id=iapply style="flex:1">이 글로 미리보기</button><button class="btn ghost" id=imclose2 style="flex:0 0 120px">닫기</button></div>
</div></div>
<div id=phmodal class=modal style="display:none"><div class="modalbox phbox">
  <div class=modalhd><span>📷 사진 추가·분류</span><button class=mx id=phclose title=닫기>✕</button></div>
  <div class=msec style="margin-top:4px"><span class=mn>1</span>사진 가져오기<span class=mh>PC에서 올리거나 네이버 임시저장 글에서 불러와요</span></div>
  <div class=dropzone id=dropzone>📷 사진·동영상을 끌어다 놓거나 <b>클릭해서 추가</b><input type=file id=fileinput accept="image/*,video/*" multiple hidden></div>
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
    <button type=button class="btn ghost" id=draftload style="white-space:nowrap;flex:4 1 0">📥 임시저장에서 불러오기</button>
    <button type=button class="btn ghost" id=draftrefresh title="네이버에서 목록 새로고침" style="display:none;flex:1 1 0;align-self:stretch;padding:4px 8px;font-size:12px;line-height:1">🔄</button>
    <div id=draftmultiwrap style="display:none">여러 글 선택 <div class="sw sw-sm" id=draftmulti></div></div>
    <span class=muted id=draftstat></span>
  </div>
  <div class=draftlist id=draftlist style="display:none"></div>
  <div id=draftbatch style="display:none;margin-bottom:10px">
    <button type=button class="btn" id=draftbatchgo>📥 선택한 글 새 탭으로 불러오기</button>
  </div>
  <div class=phscroll>
    <div class=msec><span class=mn>2</span>분류 전 사진<span class=mcnt id=pinboxn>0</span><span class=mh>클릭=활성 칸에 담기 · Shift=여러 장 선택</span></div>
    <div class=pgrid id=pgrid></div>
    <div class=msec style="margin-top:14px"><span class=mn>3</span>분류함<span class=mh>여기 담긴 사진만 글에 들어가요 · 칸 클릭 또는 끌어놓기로 담기</span></div>
    <div class=pmeta id=pmeta></div>
  </div>
  <div class=modalft><span class=muted id=phstat style="flex:1;align-self:center"></span><button class=btn id=phdone style="flex:0 0 200px">완료</button></div>
</div></div>
<div id=catmodal class=modal style="display:none"><div class=modalbox style="width:min(420px,92vw)">
  <div class=modalhd><span id=cattitle>새 분류 추가</span><button class=mx id=catx>✕</button></div>
  <div class=muted id=catdesc></div>
  <input type=text id=catinput placeholder="예: 디저트, 음료" autocomplete=off style="margin-top:12px;padding:10px 12px;border:1px solid #cdd3da;border-radius:9px;font-size:14px;width:100%">
  <div class=modalft><button class=btn id=catok style="flex:1">추가</button><button class="btn ghost" id=catcancel style="flex:0 0 100px">취소</button></div>
</div></div>
<div id=capmodal class=modal style="display:none"><div class=modalbox style="width:min(460px,94vw)">
  <div class=modalhd><span>📝 사진 세부 설명</span><button class=mx id=capx>✕</button></div>
  <div class=muted>이 사진에 대해 글에 녹일 설명을 적어주세요. 초안 생성 때 이 내용이 그대로 반영돼요. (분류: <b id=caplabel></b>)</div>
  <div style="margin-top:10px;text-align:center"><img id=capimg style="max-width:160px;max-height:160px;border-radius:9px;border:1px solid #e5e7eb;object-fit:cover"></div>
  <textarea id=capinput placeholder="예: 가장 인상 깊었던 메뉴. 겉은 바삭하고 속은 촉촉했어요." style="min-height:110px;margin-top:10px;font-family:inherit;font-size:14px;line-height:1.5;background:#fff;border:1px solid #cdd3da;border-radius:9px;padding:10px 12px;width:100%;resize:vertical"></textarea>
  <div class=muted style="margin-top:6px;font-size:11.5px">Enter 로 저장 · Shift+Enter 줄바꿈 · 비우고 저장하면 설명이 삭제돼요</div>
  <div class=modalft><button class=btn id=capok style="flex:1">저장</button><button class="btn ghost" id=capcancel style="flex:0 0 100px">취소</button></div>
</div></div>
<div id=npmodal class=modal style="display:none"><div class=modalbox style="width:min(420px,92vw)">
  <div class=modalhd><span>✏️ 새 글 시작</span><button class=mx id=npx>✕</button></div>
  <div class=muted>지금 작성 중인 메모·사진 선택·분류가 모두 비워집니다. 새 글을 시작할까요?</div>
  <div class=modalft><button class="btn danger" id=npok style="flex:1">비우고 새 글 시작</button><button class="btn ghost" id=npcancel style="flex:0 0 100px">취소</button></div>
</div></div>
<div id=tgmodal class=modal style="display:none"><div class=modalbox style="width:min(480px,94vw)">
  <div class=modalhd><span>🎨 AI 썸네일 생성</span><button class=mx id=tgx>✕</button></div>
  <div class=muted>★ 대표사진 위에 손글씨·드로잉을 얹어 감성 썸네일을 만들어요. 사진 속 오브젝트는 그대로 유지돼요.</div>
  <div style="margin-top:10px;text-align:center"><img id=tgimg style="max-width:150px;max-height:150px;border-radius:9px;border:1px solid #e5e7eb;object-fit:cover"></div>
  <div class=muted style="margin-top:12px;font-size:12px"><b>타이틀</b> — 썸네일 중앙에 유화물감 배경으로 크게 들어갈 이름 (가게/제품/메뉴명)</div>
  <input type=text id=tgtitle placeholder="예: 거제 양념게장" autocomplete=off style="margin-top:5px;padding:10px 12px;border:1px solid #cdd3da;border-radius:9px;font-size:14px;width:100%">
  <div class=muted style="margin-top:12px;font-size:12px"><b>방향·요청</b> (선택) — 분위기, 포인트 색, 꼭 들어갈 문구 등 원하는 방향을 적어주세요</div>
  <textarea id=tgextra placeholder="예: 따뜻한 주황 포인트로, 글씨는 적게. '겉바속촉' 문구는 꼭 넣어줘." style="min-height:80px;margin-top:5px;font-family:inherit;font-size:14px;line-height:1.5;background:#fff;border:1px solid #cdd3da;border-radius:9px;padding:10px 12px;width:100%;resize:vertical"></textarea>
  <div class=muted style="margin-top:6px;font-size:11.5px">생성엔 보통 30초~1분 걸려요 · 완성되면 ★ 대표가 새 이미지로 바뀌어요</div>
  <div class=modalft><button class=btn id=tgok style="flex:1">🎨 생성 시작</button><button class="btn ghost" id=tgcancel style="flex:0 0 100px">취소</button></div>
</div></div>
<div id=tpmodal class=modal style="display:none"><div class=modalbox style="width:min(480px,94vw)">
  <div class=modalhd><span>🎨 AI 썸네일 완성</span><button class=mx id=tpx>✕</button></div>
  <div class=muted>마음에 들면 ★ 대표로 적용하세요. 적용하지 않으면 원래 대표사진이 그대로 유지돼요.</div>
  <div style="margin-top:10px;text-align:center"><img id=tpimg style="max-width:300px;max-height:300px;border-radius:9px;border:1px solid #e5e7eb"></div>
  <div class=muted style="margin-top:12px;font-size:11.5px">아쉬우면 외부 이미지 모델(Midjourney·DALL·E·nano-banana 등)에 맡겨보세요 — 프롬프트를 복사하고 원본사진을 챙겨 붙여넣으면 돼요.</div>
  <div style="display:flex;gap:8px;margin-top:6px">
    <button class="btn ghost" id=tpcopy style="flex:1">📋 프롬프트 복사</button>
    <a class="btn ghost" id=tpdl style="flex:1;text-align:center;text-decoration:none" download="원본사진.jpg">⬇ 원본사진 저장</a>
  </div>
  <div class=modalft><button class=btn id=tpok style="flex:1">★ 대표로 적용</button><button class="btn ghost" id=tpskip style="flex:0 0 110px">적용 안 함</button></div>
</div></div>
<div id=tsmodal class=modal style="display:none"><div class=modalbox style="width:min(480px,94vw)">
  <div class=modalhd><span>🔁 사진 대체</span><button class=mx id=tsx>✕</button></div>
  <div class=muted>외부 이미지 모델(ChatGPT·Midjourney·nano-banana 등)에 <b>원본사진 + 프롬프트</b>를 붙여넣어 만들고, 완성한 파일을 선택하면 ★ 대표가 바로 바뀌어요.</div>
  <div style="margin-top:10px;text-align:center"><img id=tsimg style="max-width:150px;max-height:150px;border-radius:9px;border:1px solid #e5e7eb;object-fit:cover"></div>
  <div style="display:flex;gap:8px;margin-top:10px">
    <button class="btn ghost" id=tscopyimg style="flex:1">📋 사진 복사</button>
    <a class="btn ghost" id=tsdl style="flex:1;text-align:center;text-decoration:none">⬇ 사진 저장</a>
    <button class="btn ghost" id=tscopypr style="flex:1">📋 프롬프트 복사</button>
  </div>
  <div class=modalft><button class=btn id=tsfile style="flex:1">📁 완성한 이미지 파일 선택</button><button class="btn ghost" id=tscancel style="flex:0 0 100px">취소</button></div>
</div></div>
<div id=aimodal class=modal style="display:none"><div class=modalbox style="width:min(480px,94vw)">
  <div class=modalhd><span>✨ AI 사진 분석</span><button class=mx id=aix>✕</button></div>
  <div class=muted id=aidesc></div>
  <div class=muted style="margin-top:12px;font-size:12px"><b>요청사항</b> (선택) — 분류·설명에 반영할 지시를 적어주세요</div>
  <textarea id=aihint placeholder="예: 음식 사진은 메뉴 이름을 꼭 밝혀줘. 흔들리거나 중복된 사진은 '기타'로 분류해줘." style="min-height:70px;margin-top:5px;font-family:inherit;font-size:14px;line-height:1.5;background:#fff;border:1px solid #cdd3da;border-radius:9px;padding:10px 12px;width:100%;resize:vertical"></textarea>
  <div class=muted style="margin-top:6px;font-size:11.5px">4장씩 나눠 분석하고 끝난 사진부터 바로 반영돼요 · 진행 중엔 모달을 닫아도 계속돼요</div>
  <div class=modalft><button class=btn id=aiok style="flex:1">✨ 분석 시작</button><button class="btn ghost" id=aicancel style="flex:0 0 100px">취소</button></div>
</div></div>
<div id=cfmodal class=modal style="display:none"><div class=modalbox style="width:min(420px,92vw)">
  <div class=modalhd><span id=cftitle></span><button class=mx id=cfx>✕</button></div>
  <div class=muted id=cfdesc></div>
  <div class=modalft><button class="btn danger" id=cfok style="flex:1"></button><button class="btn ghost" id=cfcancel style="flex:0 0 100px">취소</button></div>
</div></div>
<div id=alerthost></div>
<aside class=side>
  <div class=brand><svg class=ic viewBox="0 0 24 24"><use href="#i-write"/></svg> 글쓰기</div>
  <div class="nav on" data-view=write><svg class=ic viewBox="0 0 24 24"><use href="#i-write"/></svg> 글쓰기</div>
  <div class=nav data-view=stickers><svg class=ic viewBox="0 0 24 24"><use href="#i-sticker"/></svg> 스티커</div>
  <div class=nav data-view=format><svg class=ic viewBox="0 0 24 24"><use href="#i-format"/></svg> 서식</div>
  <div class=nav data-view=prompt><svg class=ic viewBox="0 0 24 24"><use href="#i-prompt"/></svg> 프롬프트</div>
  <div class=nav data-view=persona><svg class=ic viewBox="0 0 24 24"><use href="#i-voice"/></svg> 문체</div>
  <div class=nav data-view=models><svg class=ic viewBox="0 0 24 24"><use href="#i-model"/></svg> 모델</div>
  <div class=nav data-view=settings><svg class=ic viewBox="0 0 24 24"><use href="#i-settings"/></svg> 설정</div>
  <div class=foot>로컬에서 동작 · 네이버 임시저장</div>
</aside>
<main>
  <!-- 글쓰기 -->
  <section class="view write on">
    <h2 class=title>글쓰기</h2>
    <p class=desc>글감을 넣고 [초안 생성]을 누르면, 오른쪽 미리보기로 검토한 뒤 네이버에 임시저장할 수 있어요.</p>
    <div id=workbar></div>
    <div class=grid>
      <div class=col>
        <div class=card>
          <div class=step><span class=stepn>1</span><span class=stept>글감</span><span class=steps>무엇에 대해 쓸까요?</span></div>
          <label class=f style="display:flex;align-items:center;gap:8px;cursor:pointer;font-weight:600;margin-bottom:8px"><input type=checkbox id=restyleMode style="width:auto;margin:0;transform:scale(1.15)"> 리스타일 모드 <span class=hint data-tip="켜면 아래 칸에 붙여넣은 '완성된 외부 초안'(다른 AI가 쓴 글 등)에 내 문체·이모티콘을 다시 입히고 사진을 배치해요. 원문의 구조·정보·순서·수치는 그대로 두고 말투·줄바꿈만 바꿉니다 — 맛집/상품 구조를 강제하지 않아요. 수집(아래 URL)은 무시됩니다.">i</span></label>
          <label class=f id=memolabel>경험 메모<span class=req>필수</span> <span class=hint data-tip="글의 중심이 되는 실제 경험을 자유롭게 적어주세요. 이 내용을 토대로 글이 작성됩니다.">i</span></label>
          <textarea id=memo placeholder="예: 비 오는 날 들렀는데 따뜻한 우동이 정말 맛있었어요. 사장님도 친절하셨고 분위기도 아늑했어요."></textarea>
          <label class=f>수집 <span class=hint data-tip="선택 사항이에요. 맛집 플레이스 URL을 붙여넣거나 상품 검색어를 적으면 정보를 자동으로 수집합니다.">i</span></label>
          <input type=text id=srcval placeholder="맛집 플레이스 URL 붙여넣기, 또는 상품 검색어 입력">
          <div class=kindseg id=kindseg style="margin-top:8px">
            <button data-k=place class=on><span class=em>🍜</span>맛집</button>
            <button data-k=product><span class=em>🛍️</span>상품</button>
          </div>
          <div class=muted id=srchint style="margin-top:6px">링크를 붙여넣으면 알아서 맞춰져요 — 따로 안 골라도 됩니다.</div>
          <div id=placehintbox style="margin-top:10px;display:none">
            <label class=f>어떤 장소인지 메모 <span class=muted>(선택)</span> <span class=hint data-tip="가게가 아니라 호텔·전시·팝업스토어·테마파크 같은 장소면 여기 적어주세요. 네이버 카테고리로 자동 인식하지만, 애매하면 이 메모가 우선돼서 그 장소에 맞는 글 구조(운영시간·입장료·볼거리 중심)로 써줍니다.">i</span></label>
            <input type=text id=placehint placeholder="예: 팝업스토어야 / 미술관 전시 다녀왔어 / 호텔 숙박 후기야">
          </div>
          <label class=f>사진 <span class=muted id=psel></span></label>
          <button type=button class="btn ghost" id=photobtn style="width:100%;justify-content:center;gap:8px">📷 사진 추가·분류 <span class=muted id=photosum>사진 없음</span></button>
        </div>
        <div class=card style="margin-top:16px">
          <div class=step><span class=stepn>2</span><span class=stept>스타일</span><span class=steps>어떻게 쓸까요? — 모두 선택 사항</span></div>
          <label class=f>문체 <span class=hint data-tip="내장 어투(발랄 구어체·차분한 존댓말·친근한 반말·담백 정보형) 중 고르거나, [문체] 탭에서 만든 내 페르소나를 골라요. 고른 어투가 글 전체 말투가 되고, 발랄 구어체에서만 카오모지·유행어가 쓰여요.">i</span></label>
          <select id=persona style="width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-sm);font-size:var(--fs-md);background:#fff;color:#1f2937">
            <option value="">발랄 구어체 (기본)</option>
          </select>
          <label class=f>필수 키워드 <span class=hint data-tip="본문에 꼭 들어갈 키워드예요. 엔터를 치면 하나씩 태그로 추가되고, 쉼표·띄어쓰기로 이어진 여러 개를 붙여넣으면 자동으로 나뉘어 들어가요. ×로 하나씩 지울 수 있어요. 비우면 안 씁니다.">i</span></label>
          <div class=kwbox id=kwbox>
            <input type=text id=keywords placeholder="예: 강남맛집 (엔터로 추가)">
          </div>
          <div class=kwlegend>키워드를 넣으면 노출 가능성을 바로 재요 — <b style="color:var(--green-d)">✅ 노려볼 만</b> · <b style="color:#8a6a0a">△ 애매</b> · <b style="color:#b03a3a">❌ 경쟁 과다</b> <span class=muted>(칩에 마우스 올리면 문서 수)</span></div>
          <div class=muted id=kwnote style="display:none;margin-top:4px;color:#2563eb;line-height:1.4"></div>
          <div class=kwrec id=kwrec style="display:none"></div>
          <details class=moreopts id=moreopts>
            <summary><span class=chev>▶</span>세부 옵션 — 문체 톤 · 최소 글자 수</summary>
            <label class=f>문체 톤 <span class=hint data-tip="비우면 기본 톤으로 써요. 위 문체와 함께 '이번 글'만의 조정으로 쓰여요. 예: 친근한 반말로 / 담백하고 차분하게">i</span></label>
            <input type=text id=tone placeholder="예: 친근한 반말로">
            <label class=f>최소 글자 수 <span class=hint data-tip="본문이 이 글자 수(공백 제외) 이상이 되도록 써요. 비우면 1500자가 적용됩니다.">i</span></label>
            <input type=number id=minchars placeholder="1500" min=0 step=100>
          </details>
          <div class=prodlinkbox id=prodlinkbox style="display:none">
            <label class=f>상품 링크 <span class=hint data-tip="상품 리뷰에 꼭 들어가야 하는 링크예요. 본문에 카드 형태로 한 번씩 삽입됩니다. [+ 링크 추가]로 여러 개 넣을 수 있어요.">i</span></label>
            <div id=prodlinks></div>
            <button type=button class="btn ghost" id=addprodlink style="width:100%;justify-content:center;gap:6px;margin-top:6px">+ 링크 추가</button>
            <div class=togrow style="margin-top:10px">
              <div class=tl>위시리스트 <span class=hint data-tip="아직 안 사고 갖고 싶은 상품이면 켜세요. 켜면 '직접 써봤다'는 식으로 안 쓰고, '갖고 싶은 이유·리서치한 정보' 관점으로 써요. 꺼두면 상품 리뷰는 기본적으로 직접 써본 것처럼 씁니다.">i</span></div>
              <div class=sw id=wishsw></div>
            </div>
            <div class=togrow style="margin-top:10px">
              <div class=tl>소비리스트 <span class=hint data-tip="이번에 산 여러 상품을 간단히 모아 정리하는 글이면 켜세요. 경험 메모에 '1. 뭐 샀고 2. 뭐 샀고' 식으로 적으면 각 항목을 짧게 나눠서 써요. 한 제품을 깊게 파는 상세 리뷰가 아니라 목록 정리 글이에요.">i</span></div>
              <div class=sw id=consw></div>
            </div>
          </div>
          <div class=togrow>
            <div class=tl>협찬 글 <span class=hint data-tip="켜면 즐겨찾기 스티커 중 고른 고지 스티커가 본문 맨 위에 들어가고, 아래 쿠팡파트너스 링크가 본문 중간중간 카드로 분산 삽입됩니다.">i</span></div>
            <div class=sw id=sponsw></div>
          </div>
          <div class=sponbox id=sponbox style="display:none">
            <div class=muted>본문 맨 위에 넣을 <b>협찬 고지 스티커</b>를 고르세요 — 즐겨찾기 중 '협찬' 태그가 달린 것만 보입니다. (선택 안 해도 됨)</div>
            <div class=sponpick id=sponpick></div>
            <label class=f>쿠팡파트너스 링크 <span class=hint data-tip="한 줄에 하나씩. 본문 끝에 몰지 않고 중간중간 카드로 분산 삽입돼요. 보통 3개.">i</span></label>
            <textarea id=links placeholder="쿠팡파트너스 링크를 한 줄에 하나씩 붙여넣기 (보통 3개)" style="min-height:80px"></textarea>
          </div>
        </div>
        <div class=card style="margin-top:16px">
          <div class=step><span class=stepn>3</span><span class=stept>초안 생성</span><span class=steps>보통 30~60초 걸려요</span></div>
          <div style="margin-top:12px;display:flex;gap:8px"><button class=btn id=gen style="flex:1">초안 생성</button><button class="btn ghost" id=newpost style="flex:0 0 110px" title="입력·사진·분류를 비우고 새 글 시작">✏️ 새 글</button></div>
          <div class=actrow>
            <button class="btn ghost" id=export title="내 프롬프트와 입력 자료를 합쳐 복사 — 다른 챗봇에 붙여넣기"><svg class=ic viewBox="0 0 24 24"><use href="#i-copy"/></svg>프롬프트 복사</button>
            <button class="btn ghost" id=import title="다른 챗봇에서 받은 글을 붙여넣어 미리보기로"><svg class=ic viewBox="0 0 24 24"><use href="#i-inbox"/></svg>받아온 글 붙여넣기</button>
          </div>
          <div id=status></div>
        </div>
      </div>
      <div class=col>
        <div class=pubbar>
          <div class=step><span class=stepn>4</span><span class=stept>검토·발행</span></div>
          <div class=catwrap>
            <button class=catbtn id=catbtn><span>발행 카테고리: <b id=catlabel>선택 안 함</b></span><span style="color:var(--sub)">▾</span></button>
            <div class=popover id=catpop style="display:none">
              <div class=catlist id=catlist><div class=muted style="padding:8px 10px">아래 [불러오기]를 눌러주세요</div></div>
              <div style="display:flex;gap:8px;margin-top:8px;padding-top:10px;border-top:1px solid var(--line)">
                <button class="btn ghost" id=catload style="flex:1;padding:9px 13px">네이버에서 불러오기</button>
              </div>
              <div class=muted id=catstat style="margin-top:6px"></div>
            </div>
          </div>
          <label class=pvimgtg title="켜면 미리보기에 사진이 실제로 보여요"><input type=checkbox id=pvimg checked> 사진 보기</label>
          <select id=pubmode class=pubmode title="발행 방식 — 예약발행은 시간차를 둬 연속 도배를 막아요">
            <option value=draft selected>임시저장만</option>
            <option value=reserve>예약발행(시간차)</option>
          </select>
          <input type=datetime-local id=reserveat class=reserveat style="display:none">
          <button class=btn id=save disabled title="초안을 검토한 뒤 네이버 블로그에 임시저장">임시저장</button>
        </div>
        <div id=reservehint class=reservehint style="display:none"></div>
        <div class="doc empty" id=preview><div class=docguide>
          <div class=dg-ic>✍️</div>
          <div class=dg-t>초안 미리보기가 여기에 나와요</div>
          <div class=dg-steps><span class=dg-s>글감 입력</span><span class=dg-a>→</span><span class=dg-s>초안 생성</span><span class=dg-a>→</span><span class=dg-s>검토 후 임시저장</span></div>
        </div></div>
        <details id=logbox style="display:none;margin-top:14px" class=card>
          <summary style="cursor:pointer;font-weight:700;font-size:13px">🔍 이번 생성 로그 — 들어간 프롬프트 + 모델 원본 출력</summary>
          <div id=logbody style="margin-top:10px"></div>
        </details>
      </div>
    </div>
  </section>
  <!-- 스티커 -->
  <section class="view stickers">
    <h2 class=title>스티커</h2>
    <p class=desc>★를 눌러 즐겨찾기에 넣으세요. 기본은 <b>즐겨찾기한 스티커만</b> 글에 쓰입니다.</p>
    <details class=kguide>
      <summary><span class=chev>▶</span>분류 기준 — 감정·구분선·헤더 스티커는 글 어디에 쓰이나요 <span class=muted style="font-weight:500">(카드의 분류 버튼으로 바꿀 수 있어요)</span></summary>
      <div class=kbody>
      <div class=krow><span class=kk>감정</span><span>감정·반응이 드러나는 문단 끝에 AI가 자동으로 붙여요(글당 1~3번). 캐릭터 반응 스티커용.</span></div>
      <div class=krow><span class=kk>구분선</span><span>화제가 바뀌는 문단 사이에 AI가 자동으로 넣어 구역을 나눠요(글당 0~2번). 가로선·장식 띠용.</span></div>
      <div class=krow><span class=kk>헤더</span><span>제목 라벨·고지 배너용(예: '추천대상', '내돈내산'). 자동으로는 안 쓰이고,
      글감에 <b>[스티커:태그이름]</b>을 직접 적을 때만 들어가요 — 아래에 그 내용이 이어질 자리에 쓰세요.</span></div>
      <div class=knote>분류는 '태그 분석'이 자동 판정하고, 각 카드의 버튼으로 직접 바꿀 수 있어요.</div>
      </div>
    </details>
    <div style="display:flex;gap:12px;align-items:stretch;flex-wrap:wrap;margin:0 0 16px">
      <div class=stat id=ststat style="margin:0;gap:12px"></div>
      <div class=togrow style="margin:0;flex:1;min-width:280px;max-width:480px">
        <div class=tl>스티커 전체 사용 <span class=hint data-tip="끄면 즐겨찾기한 스티커만 글에 쓰입니다. 켜면 전체 스티커에서 상황에 맞게 골라 씁니다.">i</span></div>
        <div class=sw id=stickerall></div>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap">
      <div class=seg style="width:280px" id=stfilter>
        <button data-f=fav class=on>⭐ 즐겨찾기</button>
        <button data-f=all>전체 둘러보기</button>
      </div>
      <div style="position:relative;flex:1;min-width:170px;max-width:250px">
        <input type=text id=stsearch placeholder="태그·팩 이름 검색" style="padding:8px 12px 8px 31px;font-size:12.5px;border-radius:999px">
        <svg class=ic viewBox="0 0 24 24" style="position:absolute;left:11px;top:50%;transform:translateY(-50%);width:14px;height:14px;color:var(--sub)"><use href="#i-search"/></svg>
      </div>
      <button class="btn ghost" id=lblbtn style="width:auto;display:inline-flex;align-items:center;padding:8px 14px;font-size:12.5px;font-weight:600;border-radius:999px"><svg class=ic viewBox="0 0 24 24" style="margin-top:0;width:15px;height:15px"><use href="#i-search"/></svg>즐겨찾기 태그 분석</button>
      <span class="chip on" id=hidedef title="네이버 기본 제공 팩 숨기기"><span class=dot></span>기본 이모티콘 숨기기</span>
      <span class=muted id=lblstat></span>
    </div>
    <div id=stbody><div class=muted>불러오는 중…</div></div>
  </section>
  <!-- 서식 -->
  <section class="view format">
    <h2 class=title>서식</h2>
    <p class=desc>글에 들어갈 강조색·구분선·인용구를 미리 보고 고릅니다.</p>
    <div class=card><h3>강조색 <span class=muted style="font-weight:400">— 색마다 글자색·배경·폰트·크기를 직접 설정</span></h3><div id=emph><div class=muted>불러오는 중…</div></div></div>
    <div class=card style="margin-top:16px"><h3>구분선·인용구 종류 <span class=muted style="font-weight:400">— 쓸 종류를 여러 개 고르기</span></h3><div id=variants><div class=muted>불러오는 중…</div></div></div>
  </section>
  <!-- 프롬프트 -->
  <section class="view prompt">
    <h2 class=title>프롬프트</h2>
    <p class=desc>초안 생성에 쓰이는 베이스 프롬프트를 직접 수정할 수 있어요. 저장하면 다음 생성부터 반영됩니다.</p>
    <div class=card>
      <h3>베이스 프롬프트 <span class=muted id=prompthdr style="font-weight:400">— config/prompts/default.md</span></h3>
      <div class=seg id=promptkindseg style="max-width:390px;margin-bottom:10px">
        <button type=button data-k=place class=on>🍜 맛집</button>
        <button type=button data-k=product>🛍️ 상품</button>
        <button type=button data-k=venue>🏛️ 장소</button>
        <button type=button data-k=common>🧾 공통 포맷</button>
      </div>
      <p class=desc style="margin:0 0 8px">파트를 눌러 펼치고 그 부분만 고치면 돼요. 파트를 새로 만들거나 지울 땐 '원문으로 편집'을 쓰세요.</p>
      <div id=promptsections><div class=muted>불러오는 중…</div></div>
      <textarea id=promptedit class=promptarea placeholder="불러오는 중…" style="display:none"></textarea>
      <div style="margin-top:10px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <button class=btn id=promptsave style="width:auto;padding:9px 18px">저장</button>
        <button type=button id=promptmode style="padding:9px 14px;border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer;font-size:13px">원문으로 편집</button>
        <span class=muted id=promptstat></span>
      </div>
    </div>
    <div class=card style="margin-top:16px">
      <h3>스타일 풀 <span class=muted style="font-weight:400">— 유행어·표정 이모티콘·고정 문구. 글마다 일부만 뽑혀 '이번 글 스타일 변주'로 들어가요</span></h3>
      <div id=stylepool><div class=muted>불러오는 중…</div></div>
      <div style="margin-top:10px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <button class=btn id=poolsave style="width:auto;padding:9px 18px">저장</button>
        <button type=button id=poolreset style="padding:9px 14px;border:1px solid var(--line);border-radius:8px;background:#fff;cursor:pointer;font-size:13px">기본값 복원</button>
        <span class=muted id=poolstat></span>
      </div>
    </div>
    <div class=card style="margin-top:16px"><h3>자동 추가 레이어 <span class=muted style="font-weight:400">— 마커 지시문(읽기 전용, 토글 켤 때만)</span></h3><div id=promptlayers><div class=muted>불러오는 중…</div></div></div>
  </section>
  <!-- 문체 -->
  <section class="view persona">
    <h2 class=title>문체</h2>
    <p class=desc>블로거의 <b>인기글 top 5</b>에서 평소 문체를 뽑아 이름표를 붙여 저장해 두고, 글쓰기에서 골라 그 사람처럼 쓸 수 있어요. 저장한 문체는 골랐을 때만 적용되고, 모두가 공유하는 베이스 프롬프트에는 섞이지 않습니다.</p>
    <div class=card>
      <h3>새 문체 만들기</h3>
      <label class=f>블로그 주소 또는 ID <span class=hint data-tip="예: blog.naver.com/아이디, m.blog.naver.com/아이디, 또는 아이디만">i</span></label>
      <div style="display:flex;gap:8px;align-items:stretch">
        <input type=text id=pf_blog placeholder="예: blog.naver.com/아이디 또는 아이디" style="flex:1">
        <button class=btn id=pf_fetch style="flex:0 0 140px">인기글 불러오기</button>
      </div>
      <div class=muted id=pf_stat style="margin-top:8px"></div>
      <div id=pf_posts style="margin-top:10px"></div>
      <div id=pf_extractrow style="display:none;margin-top:12px;gap:8px;flex-wrap:wrap;align-items:center">
        <select id=pf_model style="padding:8px 6px;border:1px solid var(--line);border-radius:8px;font-size:13px;background:#fff" data-tip="문체 분석에 쓸 텍스트 모델 — API 키가 등록된 모델만 보여요"></select>
        <button class=btn id=pf_extract style="width:auto;padding:9px 18px">선택한 글로 문체 추출</button>
        <button class="btn ghost" id=pf_promptonly style="width:auto;padding:9px 18px" data-tip="LLM 호출 없이, 글+분석 지시를 합친 프롬프트를 복사해요. ChatGPT·Claude 등에 붙여넣어 쓰세요.">프롬프트만 복사</button>
      </div>
      <div id=pf_result style="display:none;margin-top:16px">
        <label class=f>문체 특징 <span class=muted style="font-weight:400">— 추출 결과(직접 다듬어도 됩니다)</span></label>
        <textarea id=pf_profile class=promptarea style="min-height:150px"></textarea>
        <label class=f>이름</label>
        <input type=text id=pf_name placeholder="예: 내 본캐 문체">
        <div style="margin-top:10px;display:flex;align-items:center;gap:12px">
          <button class=btn id=pf_save style="width:auto;padding:9px 18px">문체 저장</button>
          <span class=muted id=pf_savestat></span>
        </div>
      </div>
    </div>
    <div class=card style="margin-top:16px">
      <h3>저장된 문체</h3>
      <div id=personalist><div class=muted>불러오는 중…</div></div>
    </div>
  </section>
  <!-- 모델 -->
  <section class="view models">
    <h2 class=title>모델</h2>
    <p class=desc>초안 작성에 쓸 모델을 고릅니다 — 내 컴퓨터(GPU)에서 돌리는 내장 모델, 또는 외부 API(Claude·GPT·Gemini).</p>
    <div class=card id=models><h3>모델</h3><div class=muted>불러오는 중…</div></div>
  </section>
  <!-- 설정 -->
  <section class="view settings">
    <h2 class=title>설정</h2>
    <p class=desc>글쓰기 규칙과 임시저장 동작을 관리합니다.</p>
    <div class=card><h3>글쓰기 규칙 <span class=muted style="font-weight:400">— 초안 생성 때 켠 것만 반영돼요</span></h3><div id=rules></div></div>
    <div class=card style="margin-top:16px"><h3>임시저장</h3><div id=draftset></div><div id=cleanimp></div><div id=aimark></div><div id=savedebug></div></div>
    <div class=card style="margin-top:16px"><h3>키워드 경쟁 확인 <span class=muted style="font-weight:400">— 발행 전에 이 키워드로 노출 가능성이 있는지 가늠해요</span></h3>
      <div class=kwchk>
        <input id=kwq placeholder="예: 회현역 카페 주차" autocomplete=off>
        <button class=btn id=kwbtn>확인</button>
      </div>
      <div id=kwres><div class=muted style="margin-top:8px">키워드를 넣으면 <b>이미 쓰인 블로그 글 수(경쟁)</b>·<b>현재 상위 글</b>·<b>내 글 순위</b>를 보여줘요. 문서 수가 적고 상위가 대형 블로그로 꽉 차 있지 않을수록 노려볼 만해요.</div></div>
      <div id=kwad style="margin-top:10px;padding-top:10px;border-top:1px dashed var(--line)"></div>
    </div>
    <div class=card style="margin-top:16px"><h3>노출 순위 추적 <span class=muted style="font-weight:400">— 블로그 검색 상위 100위(정확도순 근사) 실측</span></h3><div id=ranktrk><div class=muted>불러오는 중…</div></div></div>
  </section>
</main>
<script src="/asset?name=lottie.min.js"></script>
<script>
// 프런트 JS 에러를 서버 로그(ui.log)에 남긴다 — '하얗게 뜸' 같은 화면 깨짐이 재발했을 때
// 유저 브라우저 콘솔을 못 보는 상태에서도 원인(스택)을 사후 추적할 수 있게.
addEventListener('error',e=>{try{navigator.sendBeacon('/api/client-error',
  (e.message||'')+' @'+(e.filename||'').split('/').pop()+':'+e.lineno+'\n'+(e.error&&e.error.stack||''));}catch(_){}});
addEventListener('unhandledrejection',e=>{try{navigator.sendBeacon('/api/client-error',
  'unhandled: '+(e.reason&&(e.reason.stack||e.reason.message)||e.reason));}catch(_){}});
// fetch 래퍼: 네트워크 단절(서버 꺼짐/재시작)을 'TypeError: Failed to fetch' 대신 친절한 메시지로
const _fetch=window.fetch.bind(window);
window.fetch=async(...a)=>{try{return await _fetch(...a);}
  catch(e){const m='서버에 연결할 수 없어요. 앱(서버)이 꺼졌거나 재시작 중일 수 있어요 — 잠시 후 새로고침하거나 다시 시도하세요.';toast(m,'err');throw new Error(m);}};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const EMPTY_DOC=$('#preview').innerHTML;  // 빈 미리보기 안내 — 새 탭(blankWS) 초기 상태로 재사용
let PHOTOS=[], SELP=[], PLAN=null;
let PERSONAS=[], TONES=[], PERSONA_ID='', PF={};  // 문체: 페르소나 목록 / 내장 어투 프리셋 / 선택 id / 작성 임시상태
// 알림: 오류(err)는 화면 가운데 카드로 크게, 완료/안내(ok/info)는 상단 토스트로 가볍게.
function toast(msg,kind='err',ms){
  if(kind==='err'){centerAlert(msg,'err');return;}
  if(ms==null)ms=kind==='ok'?3500:6000;
  const t=document.createElement('div');t.className='toast '+kind;
  const ic=kind==='ok'?'✅':kind==='info'?'ℹ️':'⚠️';
  t.innerHTML='<span class=ic>'+ic+'</span><span class=msg>'+String(msg).replace(/</g,'&lt;')+'</span><span class=x title="닫기">✕</span>';
  const close=()=>{if(t._gone)return;t._gone=true;t.classList.add('out');setTimeout(()=>t.remove(),180);};
  t.querySelector('.x').onclick=close;$('#toasts').appendChild(t);setTimeout(close,ms);}
// 화면 중앙 알림 카드(오류·확인). 유저가 직접 닫아야 함(꼭 봐야 하는 알림용).
function centerAlert(msg,kind='err'){
  const ic=kind==='ok'?'✅':kind==='info'?'ℹ️':'⚠️';
  const title=kind==='ok'?'완료됐어요':kind==='info'?'알려드려요':'문제가 발생했어요';
  const bg=document.createElement('div');bg.className='alertbg';
  bg.innerHTML=`<div class="alertcard ${kind}"><div class=ai>${ic}</div>
    <div class=at>${title}</div>
    <div class=am>${String(msg).replace(/</g,'&lt;')}</div>
    <div class=ab><button class=btn>확인</button></div></div>`;
  const close=()=>bg.remove();
  bg.querySelector('.btn').onclick=close;
  bg.onclick=e=>{if(e.target===bg)close();};
  document.addEventListener('keydown',function esc(e){if(e.key==='Escape'){close();document.removeEventListener('keydown',esc);}});
  $('#alerthost').appendChild(bg);bg.querySelector('.btn').focus();}
// 자동 삽입 실패 항목 목록을 꼭 봐야 하는 모달로 표시(유저가 직접 닫아야 함).
function warnModal(title, items){
  const lis=(items||[]).map(s=>'<li>'+String(s).replace(/</g,'&lt;')+'</li>').join('');
  const bg=document.createElement('div');bg.className='alertbg';
  bg.innerHTML=`<div class="alertcard info"><div class=ai>⚠️</div>
    <div class=at>${title}</div>
    <ul class=am style="text-align:left;margin:6px 0;padding-left:20px;line-height:1.6">${lis}</ul>
    <div class=ab><button class=btn>확인</button></div></div>`;
  const close=()=>bg.remove();
  bg.querySelector('.btn').onclick=close;
  bg.onclick=e=>{if(e.target===bg)close();};
  document.addEventListener('keydown',function esc(e){if(e.key==='Escape'){close();document.removeEventListener('keydown',esc);}});
  $('#alerthost').appendChild(bg);bg.querySelector('.btn').focus();}
// '확인 필요' 기록 — 모달을 실수로 닫아도 다시 볼 수 있게 localStorage에 쌓아둔다.
// 탭바의 ⚠ 칩을 누르면 전체 기록 모달. '기록 비우기'로만 지워진다.
const WARNLOG_KEY='autoblog.warnlog';
function warnLogAll(){try{return JSON.parse(localStorage.getItem(WARNLOG_KEY))||[]}catch(e){return[]}}
function warnLogAdd(title, items){
  const log=warnLogAll(); log.unshift({t:title,w:items,at:Date.now()});
  try{localStorage.setItem(WARNLOG_KEY,JSON.stringify(log.slice(0,30)))}catch(e){}  // ponytail: 최근 30건만 보관
  renderWarnChip();
}
function renderWarnChip(){
  const n=warnLogAll().length; let el=$('#warnchip');
  if(!n){ if(el)el.remove(); return; }
  if(!el){
    el=document.createElement('div'); el.id='warnchip'; el.className='stab warn'; el.style.cursor='pointer';
    el.title='실수로 닫은 확인 필요 안내를 다시 봅니다';
    el.innerHTML='<span class=sdot style="color:#d98a00">⚠</span><span class=stitle></span>';
    el.onclick=warnLogModal; $('#savebar').prepend(el);
  }
  el.querySelector('.stitle').textContent=`확인 필요 기록 ${n}건`;
}
function warnLogModal(){
  const esc=s=>String(s).replace(/</g,'&lt;');
  const secs=warnLogAll().map(e=>{
    const d=new Date(e.at);
    const ts=`${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    return `<div style="margin:0 0 12px"><b style="color:var(--ink)">${esc(e.t)}</b> <span style="font-weight:600;font-size:12px">· ${ts}</span>
      <ul style="margin:4px 0 0;padding-left:20px">${(e.w||[]).map(s=>'<li>'+esc(s)+'</li>').join('')}</ul></div>`;
  }).join('');
  const bg=document.createElement('div');bg.className='alertbg';
  bg.innerHTML=`<div class="alertcard info"><div class=ai>⚠️</div>
    <div class=at>확인 필요 기록</div>
    <div class=am style="text-align:left;max-height:55vh;overflow:auto">${secs}</div>
    <div class=ab style="justify-content:center">
      <button class="btn ghost" data-clear style="width:auto;padding:9px 16px">기록 비우기</button>
      <button class=btn data-close style="width:auto;padding:9px 16px">닫기</button></div></div>`;
  const close=()=>bg.remove();
  bg.querySelector('[data-close]').onclick=close;
  bg.querySelector('[data-clear]').onclick=()=>{try{localStorage.removeItem(WARNLOG_KEY)}catch(e){} renderWarnChip(); close();};
  bg.onclick=e=>{if(e.target===bg)close();};
  document.addEventListener('keydown',function esc2(e){if(e.key==='Escape'){close();document.removeEventListener('keydown',esc2);}});
  $('#alerthost').appendChild(bg);
}
renderWarnChip();  // 새로고침해도 지난 기록 칩이 되살아남
// 예/아니오 확인 모달(최초 1회 안내 등). onYes/onNo 콜백. 배경/Esc는 '아니오'로 닫힘.
function confirmModal(title, desc, yesLabel, noLabel, onYes, onNo, icon){
  const bg=document.createElement('div');bg.className='alertbg';
  bg.innerHTML=`<div class="alertcard info"><div class=ai>${icon||'🗑️'}</div>
    <div class=at>${title}</div>
    <div class=am style="text-align:left;margin:6px 0;line-height:1.6;color:var(--sub);font-size:13px">${desc}</div>
    <div class=ab style="display:flex;gap:8px;justify-content:center">
      <button class="btn ghost" data-no style="width:auto;padding:9px 16px">${noLabel}</button>
      <button class=btn data-yes style="width:auto;padding:9px 16px">${yesLabel}</button></div></div>`;
  let done=false;
  const fin=(fn)=>{if(done)return;done=true;bg.remove();if(fn)fn();};
  bg.querySelector('[data-yes]').onclick=()=>fin(onYes);
  bg.querySelector('[data-no]').onclick=()=>fin(onNo);
  bg.onclick=e=>{if(e.target===bg)fin(onNo);};
  document.addEventListener('keydown',function esc(e){if(e.key==='Escape'){document.removeEventListener('keydown',esc);fin(onNo);}});
  $('#alerthost').appendChild(bg);bg.querySelector('[data-yes]').focus();
}
// NVIDIA 한도(402/429) 에러는 모달로 안내(확인 경로 포함), 그 외 에러는 기존 토스트.
function errNotice(prefix, msg){
  msg=String(msg||'알 수 없는 오류');
  if(msg.includes('한도 도달')){
    confirmModal('NVIDIA 무료 한도에 걸렸어요',
      msg+'<br><br>분당 40회 제한이면 <b>1분쯤 뒤</b> 다시 시도하면 돼요. 크레딧(1,000회)이 소진됐다면 build.nvidia.com에서 잔여량 확인·추가 요청(무료)이 가능해요.',
      '잔여 크레딧 확인 ↗','닫기',()=>window.open('https://build.nvidia.com','_blank','noopener'),null,'⏳');
  } else toast(prefix+' — '+msg,'err');
}
// 브라우저(크롬) 알림 — 유저가 다른 탭/창에 가 있어도 결과를 알린다. 권한은 저장 클릭 시 요청.
function ensureNotify(){try{if('Notification'in window&&Notification.permission==='default')Notification.requestPermission();}catch(e){}}
function notify(title, body){
  try{
    if(!('Notification'in window)||Notification.permission!=='granted')return;
    const n=new Notification(title,{body:body||'',tag:'autoblog-publish',renotify:true});
    n.onclick=()=>{window.focus();n.close();};
  }catch(e){}
}
// 임시저장 완료 — 체크마크가 그려지고 색종이가 흩날리는 축하 팝업.
function successModal(title, msg, badge){
  const bg=document.createElement('div');bg.className='okbg';
  const cols=['#03c75a','#ffd23f','#ff7a9c','#4f9dff','#9b6cff'];
  let cf='';
  for(let i=0;i<14;i++){
    const c=cols[i%cols.length], left=6+Math.random()*88, delay=(Math.random()*.35).toFixed(2), dur=(.9+Math.random()*.5).toFixed(2);
    cf+=`<span class=okcf style="left:${left}%;background:${c};animation-delay:${delay}s;animation-duration:${dur}s"></span>`;
  }
  bg.innerHTML=`<div class=okcard>${cf}
    <div class=okring><svg viewBox="0 0 88 88"><circle class=okc cx=44 cy=44 r=40 /><path class=okch d="M27 45l11 11 23-25" /></svg></div>
    <div class=okt>${String(title).replace(/</g,'&lt;')}</div>
    <div class=okm>${msg}</div>
    ${badge?`<div class=oksec>${String(badge).replace(/</g,'&lt;')}</div>`:''}
    <div class=okb><button class=btn>확인</button></div></div>`;
  const close=()=>bg.remove();
  bg.querySelector('.btn').onclick=close;
  bg.onclick=e=>{if(e.target===bg)close();};
  document.addEventListener('keydown',function esc(e){if(e.key==='Escape'){close();document.removeEventListener('keydown',esc);}});
  $('#alerthost').appendChild(bg);bg.querySelector('.btn').focus();
}
// 실측 경과시간 카운터 — 가짜 %가 아니라 '진짜로 얼마나 걸리는지'를 보여줌.
// requestAnimationFrame으로 0.1초 단위 표시가 바뀔 때만 갱신해 숫자가 자연스럽게 올라가고,
// 글자만 바꾸므로 스피너 회전이 끊기지 않는다. render(plainText, sec)로 갱신, stop()은 멈추고 총 초(소수1).
// 타자기 효과: 문구를 한 글자씩 출력(대기 화면 공통). 같은 문구면 무시해 깜빡임 방지.
function typeText(el, text){
  if(!el) return;
  text=text||'';
  if(el._ttTarget===text) return;            // 인터벌이 같은 문구로 반복 호출해도 재시작 안 함
  el._ttTarget=text;
  if(el._ttTimer){clearInterval(el._ttTimer); el._ttTimer=null;}
  el.classList.add('typing'); el.textContent=''; let i=0;
  const step=()=>{ i++; el.textContent=text.slice(0,i);
    if(i>=text.length){ clearInterval(el._ttTimer); el._ttTimer=null; el.classList.remove('typing'); } };
  step(); el._ttTimer=setInterval(step, 26);  // 첫 글자 즉시, 이후 26ms 간격
}
function elapsed(label, render){
  const t0=Date.now();
  const fmt=s=>s<10?s.toFixed(1):Math.round(s);
  let raf, last=null;
  const tick=()=>{
    const s=(Date.now()-t0)/1000, shown=fmt(s);
    if(shown!==last){ last=shown; render(label, `${shown}초 경과…`, s); }
    raf=requestAnimationFrame(tick);
  };
  tick();
  return {stop(){if(raf)cancelAnimationFrame(raf); return +((Date.now()-t0)/1000).toFixed(1);}};
}
// 스피너 + 타자기 라벨 + 경과시간 카운터. 라벨은 처음 한 번만 한 글자씩 출력하고,
// 타이핑이 끝난 뒤에야 카운터가 따라붙는다(타이핑 중엔 카운터 숨김).
function spinRow(el){
  el.innerHTML='<span class=loading><span class=spin></span></span> <span class=spintext></span><span class=spincount></span>';
  const txt=el.querySelector('.spintext'), cnt=el.querySelector('.spincount');
  let typed=false;
  return (label, counter)=>{
    if(!typed){ typed=true; typeText(txt, label); }
    cnt.textContent = txt._ttTimer ? '' : (counter ? (' '+counter) : '');
  };
}
// 수집 종류: 'place'(맛집·기본) | 'product'(상품). 입력으로 자동 추정하되 직접 고르면 고정.
let SRCKIND='place', KINDMANUAL=false;
function autoKind(v){v=(v||'').trim().toLowerCase(); if(!v)return 'place';
  // 쇼핑 링크 → 상품, 그 외 URL/플레이스 → 맛집, 그냥 글자 → 상품(검색어)
  if(/smartstore\.|shopping\.naver|brand\.naver|coupang\.|11st\.|gmarket\.|ssg\.com/.test(v))return 'product';
  if(/^https?:\/\//.test(v)||/naver\.me|place|map\.naver/.test(v))return 'place';
  return 'product';}
function setKind(k,manual){SRCKIND=k; if(manual)KINDMANUAL=true;
  $$('#kindseg button').forEach(b=>{b.classList.toggle('on',b.dataset.k===k);
    b.classList.toggle('auto',!KINDMANUAL&&b.dataset.k===k);});
  {const pb=$('#prodlinkbox'); if(pb)pb.style.display=(k==='product')?'block':'none';}
  {const ph=$('#placehintbox'); if(ph)ph.style.display=(k==='place')?'block':'none';}
  $('#srchint').innerHTML=KINDMANUAL
    ?('<b>'+(k==='place'?'맛집':'상품')+'</b>으로 수집합니다.')
    :('입력을 보고 <b>'+(k==='place'?'맛집':'상품')+'</b>으로 자동 인식했어요. 직접 골라도 돼요.');}
// 강조색·구분선/인용구·스티커는 항상 켜둠(즐겨찾기/설정이 없으면 자동으로 안 들어감) — 토글 UI 제거.
const FMT={emphasis:true,structure:true,stickers:true,stickerAll:false,sponsored:false,sponsorSticker:'',wishlist:false,consumed:false,hideDefault:true};
let CATEGORY='';
// 예약 발행 준비 여부(예약 시간피커 셀렉터가 라이브 검증돼 채워졌는지) — 서버가 주입.
const RESERVE_READY = ("/*RESERVE_READY*/"==="true");
const LINKS=()=>($('#links').value||'').split('\n').map(s=>s.trim()).filter(Boolean);
// 상품 링크 — 상품 리뷰에 꼭 넣을 링크. 카드로 한 번씩 삽입. 기본 1행 + [+ 링크 추가].
function prodLinkRow(val){
  const row=document.createElement('div'); row.className='plrow';
  const inp=document.createElement('input'); inp.type='url'; inp.className='plink'; inp.placeholder='https:// 상품 링크 붙여넣기'; inp.value=val||'';
  const rm=document.createElement('button'); rm.type='button'; rm.className='btn ghost plrm'; rm.title='삭제'; rm.textContent='✕';
  rm.onclick=()=>{const box=$('#prodlinks'); if(box.children.length>1)row.remove(); else inp.value='';};
  row.append(inp,rm); return row;}
function addProdLink(val){$('#prodlinks').appendChild(prodLinkRow(val)); return $('#prodlinks').lastElementChild;}
function resetProdLinks(){$('#prodlinks').innerHTML=''; addProdLink('');}
const PRODLINKS=()=>SRCKIND==='product'?$$('#prodlinks .plink').map(i=>i.value.trim()).filter(Boolean):[];
const RULES={mobile_friendly:true,authenticity:true,structure_guide:true,seo:true,emoji:false};
let PRUNE=true;  // 임시저장 시 같은 제목 이전 글 자동 정리(설정 토글)
let IMPORTED_DRAFT=null;  // 사진을 가져온 원본 임시저장 글 {title,date} — 저장 완료 후 삭제 대상
let SAVEDBG=false;  // 디버그: 임시저장 시 브라우저를 화면에 띄워 작업 과정을 직접 본다(headful)
let CLEANIMP=true;  // 불러오기(in-place): 원본 글의 기존 스티커·지도 등 장식 삭제 후 작성(설정 토글)
let MARKAI=true;  // AI 생성 이미지(FLUX 썸네일 등)에 네이버 'AI 활용' 표시(설정 토글, 기본 켬)
const RULE_META=[
 ['mobile_friendly','모바일 친화','문단을 짧게 끊고 여백 넉넉히(네이버 트래픽 대부분 모바일)'],
 ['authenticity','진정성','과장·상투구·AI식 표현 피하고 솔직·담백하게(단점도 자연스럽게)'],
 ['structure_guide','구조 가이드','방문/구매 동기 → 경험 → 평가 흐름, 소제목으로 구간 나누기'],
 ['seo','검색 노출(SEO)','대표 키워드를 인트로·소제목·본문에 자연스럽게(문장마다 반복은 저품질)'],
 ['emoji','이모지','분위기에 맞는 이모지 적절히 사용'],
];

// nav
$$('.nav').forEach(n=>n.onclick=()=>{
  $$('.nav').forEach(x=>x.classList.remove('on')); n.classList.add('on');
  $$('.view').forEach(v=>v.classList.remove('on')); $('.view.'+n.dataset.view).classList.add('on');
  if(n.dataset.view==='stickers') loadStickers();
  if(n.dataset.view==='persona') loadPersonas();
  if(n.dataset.view==='settings'){ loadRanks(); bindKwCheck(); loadKwAd(); }
});
// 키워드 경쟁 확인 — 발행 전에 '노려볼 만한 키워드인지' 가늠(설정 탭)
function bindKwCheck(){
  const btn=$('#kwbtn'), inp=$('#kwq'); if(!btn||!inp)return;
  const run=async()=>{
    const q=inp.value.trim(); if(!q){toast('키워드를 입력하세요','info');return;}
    const res=$('#kwres'); res.innerHTML='<div class=muted style="margin-top:8px">확인 중…</div>';
    try{
      const r=await fetch('/api/keyword-check?q='+encodeURIComponent(q));
      const d=await r.json();
      if(!r.ok){ res.innerHTML=`<div class=ckbad style="margin-top:8px">${esc(d.error||'확인 실패')}</div>`; return; }
      renderKwCheck(d);
    }catch(e){ res.innerHTML=`<div class=ckbad style="margin-top:8px">확인 실패 — ${esc(e.message)}</div>`; }
  };
  btn.onclick=run;
  inp.onkeydown=e=>{ if(e.key==='Enter')run(); };
}
// 검색광고 API 키 등록(월간 검색량) — 키워드 경쟁 확인 카드 하단(설정 탭)
async function loadKwAd(){
  const box=$('#kwad'); if(!box)return;
  let set=false; try{ set=!!(await (await fetch('/api/searchad-key')).json()).set; }catch(e){}
  const inpSt='padding:8px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px;background:#fff';
  box.innerHTML=`<div class=muted style="font-size:12px">${set
    ?'🔑 <b>검색광고 API 연결됨</b> — 키워드 판정·추천에 월간 검색량(PC+모바일)이 함께 나와요. <a href=# id=kwadedit>키 변경</a>'
    :'월간 <b>검색량</b>까지 보려면 <a href="https://searchad.naver.com" target=_blank rel=noopener>네이버 검색광고</a>(무료 가입) → 도구 → API 사용관리에서 키를 발급받아 등록하세요. 등록하면 추천이 \'검색량 대비 경쟁 유리한 순\'으로 똑똑해져요.'}</div>
  <div id=kwadform style="display:${set?'none':'flex'};gap:6px;flex-wrap:wrap;margin-top:8px">
    <input id=kwadkey placeholder="액세스라이선스(API 키)" autocomplete=off style="flex:2 1 200px;${inpSt}">
    <input id=kwadsec type=password placeholder="비밀키" autocomplete=off style="flex:2 1 160px;${inpSt}">
    <input id=kwadcid placeholder="CUSTOMER_ID" autocomplete=off style="flex:1 1 110px;${inpSt}">
    <button class="btn ghost" id=kwadsave>저장</button>
  </div>`;
  const ed=$('#kwadedit'); if(ed) ed.onclick=e=>{ e.preventDefault(); $('#kwadform').style.display='flex'; };
  $('#kwadsave').onclick=async()=>{
    const k=$('#kwadkey').value.trim(), s=$('#kwadsec').value.trim(), c=$('#kwadcid').value.trim();
    if(!k||!s||!c){ toast('액세스라이선스·비밀키·CUSTOMER_ID를 모두 입력하세요','info'); return; }
    const sv=$('#kwadsave'); sv.disabled=true;
    try{
      const r=await fetch('/api/searchad-key',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({api_key:k,secret:s,customer_id:c})});
      if(!r.ok) throw new Error((await r.json().catch(()=>({}))).error||'저장 실패');
      toast('검색광고 API 키 저장됨 ✓ — 이제 검색량이 함께 나와요','ok'); loadKwAd();
    }catch(e){ toast('저장 실패 — '+e.message,'err'); }
    finally{ const x=$('#kwadsave'); if(x)x.disabled=false; }
  };
}
// 문서수는 절대 기준이 아니라 상대 신호 — 대략의 밴드만 보여주고 판단은 상위결과로.
function renderKwCheck(d){
  const res=$('#kwres'); const n=d.total||0;
  let band, color;
  if(n<1000){ band='경쟁 적음 — 노려볼 만해요'; color='#0a8a4a'; }
  else if(n<20000){ band='경쟁 보통 — 상위 글이 대형 블로그로 꽉 찼는지 보고 판단'; color='#8a6a0a'; }
  else{ band='경쟁 치열 — 지금 체급으론 묻히기 쉬워요'; color='#c0392b'; }
  const mine = d.mine ? `<b style="color:#0a8a4a">내 글이 이미 ${d.mine}위</b>` : '내 글은 상위 100위 밖';
  const vol = d.volume!=null
    ? `월간 검색 <b>${(d.volume||0).toLocaleString()}회</b>(PC+모바일)${d.comp_idx?` · 광고 경쟁 ${esc(d.comp_idx)}`:''} · ` : '';
  let html=`<div class=kwverdict style="color:${color}">${esc(band)}</div>`
    +`<div class=kwmeta>${vol}이미 쓰인 블로그 글 <b>${n.toLocaleString()}개</b> · ${mine} <span class=muted>(문서 수는 절대 기준이 아니라 상대 신호예요)</span></div>`;
  (d.top||[]).forEach((t,i)=>{
    const me = d.mine===i+1 ? ' me' : '';
    html+=`<div class="kwtop${me}"><span class=n>${i+1}</span><span class=bl>${esc(t.blogger||'')}</span>`
      +`<a class=ti href="${esc(t.link)}" target=_blank rel=noopener style="color:inherit;text-decoration:none">${esc(t.title||'')}</a></div>`;
  });
  res.innerHTML=html;
}
// 노출 순위 추적 — 등록한 (키워드, 글)의 블로그 검색 순위를 실측(설정 탭)
async function loadRanks(){
  const box=$('#ranktrk'); if(!box)return;
  try{const d=await (await fetch('/api/ranks')).json(); renderRanks(d.rows||[]);}catch(e){}
}
function rankRow(r){
  const cur=r.rank?`${r.rank}위`:(r.checked?'100위 밖':'미확인');
  let delta='';
  if(r.prev&&r.rank){const d=r.prev-r.rank;
    delta=d?` <b style="color:${d>0?'#0a8a4a':'#c0392b'}">${d>0?'▲':'▼'}${Math.abs(d)}</b>`:' <span class=muted>—</span>';}
  const when=r.checked?new Date(r.checked).toLocaleDateString():'';
  return `<div class=rkrow><span class=rkrank>${cur}${delta}</span><span class=rkkw>${esc(r.keyword)}</span>
    <a class=rkurl href="${esc(r.url)}" target=_blank rel=noopener>글 보기</a><span class=muted>${when}</span>
    <span class=rkdel data-kw="${esc(r.keyword)}" data-url="${esc(r.url)}" title="추적 삭제">✕</span></div>`;
}
function renderRanks(rows){
  const box=$('#ranktrk');
  box.innerHTML=`<div class=rkadd><input id=rkkw placeholder="대표 키워드 (예: 성수동 맛집)">
    <input id=rkurl placeholder="게시 글 URL (blog.naver.com/아이디/글번호)">
    <button class="btn ghost" id=rkaddbtn>추가</button>
    <button class=btn id=rkchk ${rows.length?'':'disabled'}>지금 순위 확인</button></div>`
    +(rows.length?rows.map(rankRow).join('')
      :'<div class=muted style="margin-top:8px">게시한 글의 대표 키워드와 URL을 등록하면 검색 순위 추이를 기록해요 — 프롬프트 수정 전후 노출을 데이터로 비교할 수 있어요.</div>');
  $('#rkaddbtn').onclick=async()=>{
    const kw=$('#rkkw').value.trim(), url=$('#rkurl').value.trim();
    if(!kw||!url){toast('키워드와 글 URL을 모두 입력하세요','info');return;}
    const r=await fetch('/api/ranks',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({keyword:kw,url})});
    if(!r.ok){const d=await r.json().catch(()=>({}));toast('등록 실패 — '+(d.error||'입력을 확인하세요'),'err');return;}
    toast('등록했어요. [지금 순위 확인]으로 첫 순위를 재보세요.','ok'); loadRanks();
  };
  $('#rkchk').onclick=async()=>{
    $('#rkchk').disabled=true; $('#rkchk').textContent='확인 중…';
    try{const r=await fetch('/api/ranks/check',{method:'POST'});
      const d=await r.json(); if(!r.ok)throw new Error(d.error||'서버 오류');
      const now=new Date().toISOString();
      renderRanks((d.rows||[]).map(x=>({...x,checked:now})));
      toast('순위 확인 완료 — 이력에 저장했어요.','ok');
    }catch(e){toast('순위 확인 실패 — '+e.message,'err'); loadRanks();}
  };
  $$('#ranktrk .rkdel').forEach(x=>x.onclick=async()=>{
    await fetch('/api/ranks',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({delete:true,keyword:x.dataset.kw,url:x.dataset.url})});
    loadRanks();
  });
}
// 수집 종류: 직접 클릭 → 고정, 안 골랐으면 입력으로 자동 추정
$$('#kindseg button').forEach(b=>b.onclick=()=>setKind(b.dataset.k,true));
$('#srcval').oninput=()=>{if(!KINDMANUAL)setKind(autoKind($('#srcval').value),false);};
// 맛집 URL은 붙여넣는 즉시(또는 포커스가 떠날 때) 미리 수집해 서버 캐시를 데워둔다
// — '프롬프트 만들기'에서 수집 대기가 사라진다. 상품은 검색어 타이핑 중 오발동이 잦아 제외.
let PREFETCHED='';
async function prefetchCard(){
  const v=$('#srcval').value.trim();
  if(!v||v===PREFETCHED||SRCKIND!=='place'||!(/^https?:\/\//.test(v)||v.includes('naver.me')))return;
  PREFETCHED=v;
  const hint=$('#srchint'), esc=s=>String(s).replace(/</g,'&lt;');
  hint.innerHTML='🍜 가게 정보를 미리 수집하는 중…';
  try{
    const r=await(await fetch('/api/prefetch-card',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({srcval:v,kind:SRCKIND})})).json();
    if($('#srcval').value.trim()!==v)return; // 그 사이 입력이 바뀌었으면 힌트 안 덮음
    hint.innerHTML=r.ok?('🍜 <b>'+esc(r.name||'가게')+'</b> 정보 수집 완료 — 프롬프트에 자동으로 들어가요')
      :'가게 정보를 못 가져왔어요 — 링크 확인해 주세요 (프롬프트 만들기 때 자동 재시도)';
  }catch(e){}
}
$('#srcval').addEventListener('change',prefetchCard);
$('#srcval').addEventListener('paste',()=>setTimeout(prefetchCard,0));
// 협찬 토글 — 켜면 고지 스티커 픽커·쿠팡 링크 입력을 펼침
$('#sponsw').onclick=function(){FMT.sponsored=!FMT.sponsored;
  this.classList.toggle('on',FMT.sponsored);
  $('#sponbox').style.display=FMT.sponsored?'block':'none';
  if(FMT.sponsored)loadSponPicker();
  savePrefs();};
// 위시리스트·소비리스트는 서로 배타적 관점(안 산 것 vs 이미 산 것들) — 하나를 켜면 다른
// 쪽을 자동으로 끈다. 글마다 다를 수 있어 prefs에 저장하지 않고 매번 명시적으로 켠다(기본 꺼짐).
$('#wishsw').onclick=function(){FMT.wishlist=!FMT.wishlist;
  this.classList.toggle('on',FMT.wishlist);
  if(FMT.wishlist){FMT.consumed=false; $('#consw').classList.remove('on');}};
$('#consw').onclick=function(){FMT.consumed=!FMT.consumed;
  this.classList.toggle('on',FMT.consumed);
  if(FMT.consumed){FMT.wishlist=false; $('#wishsw').classList.remove('on');}};
// 협찬 고지 스티커 픽커 — 즐겨찾기한 스티커를 불러와 하나 고름(다시 누르면 해제)
async function loadSponPicker(){
  const box=$('#sponpick');
  try{const c=await (await fetch('/api/catalog')).json();
    const favset=new Set(c.favorites);
    const favs=c.stickers.filter(s=>favset.has(s.ref)&&(s.tags||[]).some(t=>String(t).includes('협찬')));
    if(!favs.length){box.innerHTML='<div class=muted>\'협찬\' 태그가 달린 즐겨찾기 스티커가 없어요. [스티커] 탭에서 ★ 추가 후 태그에 \'협찬\'을 넣으세요.</div>';return;}
    box.innerHTML=favs.map(s=>`<div class="spc${s.ref===FMT.sponsorSticker?' sel':''}" data-ref="${s.ref}"><img loading=lazy src="/img?ref=${encodeURIComponent(s.ref)}"></div>`).join('');
  }catch(e){box.innerHTML='<div class=muted>스티커 로드 실패</div>';}
}
$('#sponpick').onclick=e=>{const c=e.target.closest('.spc'); if(!c)return;
  const ref=c.dataset.ref;
  FMT.sponsorSticker=(FMT.sponsorSticker===ref)?'':ref;
  $$('#sponpick .spc').forEach(x=>x.classList.toggle('sel',x.dataset.ref===FMT.sponsorSticker));
  savePrefs();};

function st(m,loading){const s=$('#status'); s.innerHTML=(loading?'<span class=spin></span>':'')+m;
  s.parentElement.classList.toggle('loading',!!loading);}

// 사진: PHOTOS=업로드 전체, SELP=분류함(보드)에 넣은 사진. 그리드(위)=아직 분류 안 한 더미(=PHOTOS−SELP).
function inboxPhotos(){ return PHOTOS.filter(p=>!SELP.includes(p)); }
function isVid(path){ return /\.(mp4|mov|m4v|avi|webm|mkv)$/i.test(path||''); }  // 확장자로 영상 판별
function gridCell(path){
  const d=document.createElement('div'); d.className='pcell'+(PMSEL.has(path)?' sel':''); d.dataset.path=path;
  const badge = isVid(path) ? '<span class=vidbadge>▶ 영상</span>' : '';
  d.innerHTML=`<img loading=lazy src="/photo?path=${encodeURIComponent(path)}">${badge}`;
  d.onclick=(e)=>photoSel(path,e);
  d.onmousedown=(e)=>{ if(e.shiftKey) e.preventDefault(); };  // Shift+클릭 시 텍스트선택 방지
  return d;
}
function renderGrid(){
  const g=$('#pgrid'); if(!g)return; g.innerHTML='';
  const inbox=inboxPhotos();
  const cnt=$('#pinboxn'); if(cnt)cnt.textContent=inbox.length;
  const dz=$('#dropzone'); if(dz)dz.classList.toggle('compact',PHOTOS.length>0);
  if(!inbox.length) g.innerHTML='<div class=muted style="grid-column:1/-1;padding:6px 2px">분류할 사진이 없어요. 위에서 추가하거나 아래 분류함에서 ×로 다시 꺼낼 수 있어요.</div>';
  else inbox.forEach(p=>g.appendChild(gridCell(p)));
  updatePhotoSummary();
}
async function loadPhotos(){
  try{ const ps=await (await fetch('/api/photos')).json();
    const pool=ps.map(p=>p.path);
    // 서버 사진 풀(dev용 test/ 폴더)이 비어 있으면(=프로덕션 업로드 모델) 기존 업로드 사진을
    // 절대 덮어쓰지 않는다. 이게 새로고침·새 탭 때 사진이 통째로 사라지던 원인이었다.
    if(pool.length){ PHOTOS=pool; renderGrid(); }
  }catch(e){}
}
function setupUpload(){const dz=$('#dropzone'), fi=$('#fileinput');
  dz.onclick=()=>fi.click(); fi.onchange=()=>handleFiles(fi.files);
  dz.ondragover=e=>{e.preventDefault();dz.classList.add('drag');};
  dz.ondragleave=()=>dz.classList.remove('drag');
  dz.ondrop=e=>{e.preventDefault();dz.classList.remove('drag');handleFiles(e.dataTransfer.files);};}
async function handleFiles(files){
  for(const f of files){ if(!f.type.startsWith('image/') && !f.type.startsWith('video/') && !isVid(f.name))continue;
    const dataurl=await new Promise(r=>{const fr=new FileReader();fr.onload=()=>r(fr.result);fr.readAsDataURL(f);});
    try{const res=await fetch('/api/upload',{method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify({filename:f.name,data:dataurl.split(',')[1]})});
      const d=await res.json(); if(d.path && !PHOTOS.includes(d.path)) PHOTOS.push(d.path); renderGrid();
    }catch(e){}
  }
  renderGrid();
  persistWS();  // 업로드 직후 저장 — 다시 올리기 아까운 작업이라 바로 남긴다
}
async function handleFilesForBucket(files, bucketKey){
  await handleFiles(files);
  // 업로드된 파일들을 자동으로 해당 칸에 담기
  const newly=PHOTOS.slice(-[...files].filter(f=>f.type.startsWith('image/')||f.type.startsWith('video/')||isVid(f.name)).length);
  newly.forEach(p=>{ if(!SELP.includes(p)){ SELP.push(p); pmAssign(p,bucketKey); } });
  renderPmeta();
}

// 네이버 임시저장 글에서 사진 불러오기: 목록 조회 → 글 선택 → 본문 사진 다운로드 → PHOTOS에 추가
// DRAFTS=한 번 조회한 목록 캐시. 📥 버튼은 이 캐시를 펼침/접음만(재조회 X), 🔄로만 네이버 재조회.
let DRAFTBUSY=false, DRAFTS=null;
let DRAFTMULTI=false;            // '여러 글 선택' 모드
const DRAFTSEL=new Set();        // 선택된 글 idx(문자열) 집합
// 목록 펼침/접힘 + 📥 버튼 모양을 함께 토글 — 열려 있으면 '다시 누르면 접힌다'가 보이게.
function setDraftListOpen(open){
  $('#draftlist').style.display=open?'block':'none';
  if(!open) $('#draftbatch').style.display='none';
  const btn=$('#draftload');
  btn.classList.toggle('on',open);
  btn.textContent=open?'▲ 목록 접기':'📥 임시저장에서 불러오기';
}
// 캐시된 목록을 #draftlist에 렌더(데이터만; 표시 여부는 호출부에서 토글).
function renderDraftList(){
  const list=$('#draftlist'); list.innerHTML='';
  (DRAFTS||[]).forEach(dr=>{
    const key=String(dr.idx);
    const row=document.createElement('div'); row.className='ditem'+(DRAFTMULTI&&DRAFTSEL.has(key)?' picked':'');
    // 체크 자리는 항상 두고, 단일 모드에선 ghost(투명)로 — 모드 전환 시 좌우 밀림 없음.
    const ck = `<span class="dckbox${DRAFTMULTI?'':' ghost'}"></span>`;
    row.innerHTML=`${ck}<span class=dt>${(dr.title||'(제목 없음)')}</span><span class=dd>${dr.date||''}</span>`;
    if(DRAFTMULTI){
      row.onclick=()=>toggleDraftSel(key);  // 다중선택 모드: 행 클릭=체크 토글
    }else{
      row.onclick=()=>importDraft(dr.idx, dr.title, dr.date);  // 단일: 지금 탭에 바로 불러오기
    }
    list.appendChild(row);
  });
  updateDraftBatchBtn();
}
function toggleDraftSel(key){
  if(DRAFTSEL.has(key)) DRAFTSEL.delete(key); else DRAFTSEL.add(key);
  renderDraftList();
}
function updateDraftBatchBtn(){
  const wrap=$('#draftbatch'), btn=$('#draftbatchgo');
  if(!wrap) return;
  const n=DRAFTSEL.size;
  wrap.style.display=(DRAFTMULTI&&n>0)?'block':'none';
  if(btn) btn.textContent=`📥 선택한 ${n}개 글 새 탭으로 불러오기`;
}
// 네이버에서 목록을 새로 가져와 캐시에 채운다. 성공 시 목록을 펼쳐 보여준다.
async function fetchDrafts(){
  if(DRAFTBUSY) return; DRAFTBUSY=true;
  const list=$('#draftlist'), stat=$('#draftstat');
  const el=elapsed('네이버에서 목록 불러오는 중…', spinRow(stat));
  try{
    const r=await fetch('/api/drafts',{method:'POST'});
    const d=await r.json();
    if(!r.ok){ throw new Error(d.error||'목록을 불러오지 못했어요'); }
    const sec=el.stop();
    DRAFTS=d.drafts||[];
    $('#draftrefresh').style.display='inline-block';  // 한 번 조회하면 새로고침 버튼 노출
    if(!DRAFTS.length){ stat.textContent=`임시저장된 글이 없어요. (${sec}초)`; setDraftListOpen(false); DRAFTBUSY=false; return; }
    stat.textContent=`${DRAFTS.length}건 (${sec}초) — 사진을 가져올 글을 선택하세요`;
    renderDraftList(); setDraftListOpen(true); $('#draftmultiwrap').style.display='inline-flex';
  }catch(e){ el.stop(); stat.textContent='불러오기 실패'; toast('임시저장 목록을 못 불러왔어요 — '+e.message,'err'); }
  DRAFTBUSY=false;
}
function setupDraftImport(){
  const btn=$('#draftload'); if(!btn) return;
  btn.onclick=async()=>{
    const list=$('#draftlist');
    if(list.style.display==='block'){ setDraftListOpen(false); return; }  // 펼쳐져 있으면 접기
    if(DRAFTS!==null){  // 캐시가 있으면 재조회 없이 즉시 펼침(글 불러온 뒤에도 그대로 유지)
      if(DRAFTS.length){ renderDraftList(); setDraftListOpen(true); $('#draftmultiwrap').style.display='inline-flex'; }
      else { $('#draftstat').textContent='임시저장된 글이 없어요. (🔄로 새로고침)'; }
      return;
    }
    await fetchDrafts();  // 첫 조회만 네이버 호출
  };
  const ref=$('#draftrefresh'); if(ref) ref.onclick=()=>fetchDrafts();
  const mc=$('#draftmulti'); if(mc) mc.onclick=()=>{ DRAFTMULTI=!DRAFTMULTI; mc.classList.toggle('on',DRAFTMULTI); if(!DRAFTMULTI)DRAFTSEL.clear(); renderDraftList(); };
  const bg=$('#draftbatchgo'); if(bg) bg.onclick=()=>batchImport();
}
async function importDraft(idx, title, date){
  if(DRAFTBUSY) return; DRAFTBUSY=true;
  const stat=$('#draftstat');
  const el=elapsed(`"${title}" 사진 가져오는 중…`, spinRow(stat));
  try{
    const r=await fetch('/api/drafts/import',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({idx})});
    const d=await r.json();
    if(!r.ok){ throw new Error(d.error||'가져오기 실패'); }
    const sec=el.stop();
    // 미디어를 문서 순서대로(사진+영상). 하위호환: media 없으면 paths를 이미지로 간주.
    const media=d.media||((d.paths||[]).map(p=>({kind:'image',path:p})));
    const paths=media.map(m=>m.path).filter(Boolean);  // 사진+영상 경로(순서 유지)
    const nImg=media.filter(m=>m.kind==='image').length;
    const nVid=media.filter(m=>m.kind==='video').length;
    // 불러온 미디어를 기존 사진에 추가(중복 제외). 분류·메타는 유지.
    const added=[]; paths.forEach(p=>{ if(!PHOTOS.includes(p)){ PHOTOS.push(p); added.push(p); } });
    SELP=[]; THUMB=null; AISET=new Set();
    PMACTIVE=undefined; PMSEL=new Set(); PMANCHOR=null; SUBCATS={}; XCATS=[]; PMDRAG=null;
    renderGrid(); renderPmeta(); updatePhotoSummary();
    // 글을 고르면 목록을 자동으로 접는다(캐시는 유지 — 📥로 다시 펼치면 재조회 없이 바로 뜸).
    setDraftListOpen(false);
    const vidNote = nVid? ` · 영상 ${nVid}개(▶ 타일에 무슨 영상인지 꼭 캡션하세요)` : '';
    stat.textContent = paths.length? `사진 ${nImg}장${vidNote} 불러옴 (${sec}초) — 아래에서 분류하세요` : '가져올 미디어가 없는 글이에요';
    if(paths.length) toast(nVid? `사진 ${nImg}장·영상 ${nVid}개 불러왔어요 — 영상 캡션 잊지 마세요`:`${nImg}장 추가됐어요 — PC에서 더 올릴 수도 있어요`,'ok');
    // 사진 불러오기 성공 + 불러온 글에 제목이 있으면 → 그 제목을 필수 키워드에 자동으로 넣어줌
    if(paths.length) applyDraftTitleKeyword(title);
    // 이 원본 글을 저장 완료 후 삭제 대상으로 기억(제목+저장일시로 식별).
    if(paths.length) IMPORTED_DRAFT={title:(title||''), date:(date||'')};
    renderTabs();  // 불러온 글 제목이 탭에 반영되게
  }catch(e){ el.stop(); stat.textContent='가져오기 실패'; toast('사진을 못 가져왔어요 — '+e.message,'err'); }
  DRAFTBUSY=false;
}
// ── 필수 키워드 칩 입력 ──────────────────────────────────────────
// KW가 확정된 키워드 배열. 탭 스냅샷·서버 전송은 기존과 같은 '쉼표 문자열'(kwGet/kwSet)로
// 오가므로 서버 파싱·배경 탭 상태(fillStateFromMedia) 등 문자열 흐름과 그대로 호환된다.
let KW=[];
// 키워드별 노출 판정 캐시(소문자 키 → {cls,badge,tip}). 칩을 넣는 순간 /api/keyword-check로
// 경쟁강도(문서수)를 재서, 지금 체급으로 '노려볼 만한 키워드인지'를 칩 색으로 바로 보여준다.
const KWJUDGE={};
function classifyKw(d){
  const n=d.total||0;
  const mine = d.mine ? ` · 내 글 ${d.mine}위` : '';
  const vol = d.volume!=null ? ` · 월 검색 ${fmtVol(d.volume)}회` : '';  // 검색광고 키 있을 때만
  const docs = `문서 ${n.toLocaleString()}개`;
  if(n<1000)  return {cls:'',     badge:'✅', tip:`노려볼 만해요 · ${docs}${vol}${mine}`};
  if(n<20000) return {cls:'jmid', badge:'△',  tip:`애매 — 상위 글이 대형 블로그로 꽉 찼는지 보고 판단 · ${docs}${vol}${mine}`};
  return              {cls:'jbad', badge:'❌', tip:`경쟁 과다 — 지금 체급엔 묻히기 쉬워요 · ${docs}${vol}${mine}`};
}
// 검색량 짧은 표기: 12345 → 1.2만
function fmtVol(v){ v=v||0; return v>=10000 ? ((v/10000).toFixed(v%10000?1:0))+'만' : v.toLocaleString(); }
async function judgeKeyword(kw){
  const key=kw.toLowerCase();
  if(KWJUDGE[key]&&!KWJUDGE[key].fail) return;   // 캐시 — 재조회 안 함(실패는 다음 기회에 다시)
  KWJUDGE[key]={cls:'jwait',badge:'⏳',tip:'노출 가능성 확인 중…'}; kwRender();
  // 실패도 ⚠️로 보이게 — 빈 칩이면 '판정을 아예 안 해준다'로 보인다
  const bad=m=>({cls:'jwait',badge:'⚠️',tip:'노출 판정 실패 — '+m,fail:true});
  try{
    const r=await fetch('/api/keyword-check?q='+encodeURIComponent(kw));
    const d=await r.json();
    KWJUDGE[key]= r.ok ? classifyKw(d) : bad(d.error||'키 설정 확인');
  }catch(e){ KWJUDGE[key]=bad(e.message||'네트워크'); }
  kwRender();
}
function kwHas(t){ return KW.some(k=>k.toLowerCase()===t.toLowerCase()); }
function kwRender(){
  const box=$('#kwbox'), inp=$('#keywords'); if(!box||!inp) return;
  box.querySelectorAll('.kwchip').forEach(c=>c.remove());
  KW.forEach((k,i)=>{
    const j=KWJUDGE[k.toLowerCase()];
    const c=document.createElement('span'); c.className='kwchip'+(j&&j.cls?(' '+j.cls):'');
    if(j&&j.tip) c.title=j.tip;
    if(j&&j.badge){ const bd=document.createElement('span'); bd.className='jbadge'; bd.textContent=j.badge; c.append(bd); }
    const tx=document.createElement('span'); tx.textContent=k;
    const x=document.createElement('b'); x.textContent='×'; x.title='이 키워드 빼기';
    // mousedown: 입력칸 blur(=커밋·재렌더)보다 먼저 지워지도록
    x.onmousedown=e=>{ e.preventDefault(); e.stopPropagation(); KW.splice(i,1); kwRender(); kwRecRender(); };
    c.append(tx,x); box.insertBefore(c,inp);
  });
  inp.placeholder=KW.length?'':'예: 강남맛집 (엔터로 추가)';
}
// fromSuggest=true(추천칩 클릭)면 씨앗 안 바꿈 — 손으로 새로 넣은 키워드면 그걸 씨앗 삼아 다시 검색.
function kwAddMany(parts,fromSuggest){ let n=0,last=null; parts.forEach(p=>{ p=(p||'').trim(); if(p&&!kwHas(p)){KW.push(p);n++;judgeKeyword(p);last=p;} }); if(n){kwRender(); kwRecRender(); if(last&&!fromSuggest)suggestKeywords(last);} return n; }
// 입력칸에 쓰다 만 텍스트를 칩으로 확정(쉼표 기준 — 띄어쓰기 포함 키워드는 통째로 유지)
function kwCommit(){ const inp=$('#keywords'); if(!inp)return; const v=inp.value; inp.value=''; if(v.trim()) kwAddMany(v.split(',')); }
// 직렬화: 칩 + 아직 확정 안 한 입력 중 텍스트까지 합쳐 쉼표 문자열로
function kwGet(){
  const inp=$('#keywords'), all=KW.slice();
  ((inp&&inp.value)||'').split(',').map(s=>s.trim()).filter(Boolean)
    .forEach(p=>{ if(!all.some(k=>k.toLowerCase()===p.toLowerCase())) all.push(p); });
  return all.join(', ');
}
function kwSet(str){
  const seen=[]; (str||'').split(',').map(s=>s.trim()).filter(Boolean)
    .forEach(p=>{ if(!seen.some(k=>k.toLowerCase()===p.toLowerCase())) seen.push(p); });
  KW=seen; const inp=$('#keywords'); if(inp)inp.value=''; kwRecReset(); kwRender();
  KW.forEach(k=>judgeKeyword(k));        // 배치 불러오기·탭 복원으로 들어온 키워드도 판정(캐시되면 재조회 없음)
  if(KW.length) suggestKeywords(KW[0]);  // 첫 키워드(=주제 씨앗)로 연관 추천도 살림
}
// 연관검색어 추천 — 넣은 키워드(첫 키워드=주제 씨앗)로 '경쟁 낮은 유리한' 연관어를 눌러 담게.
const KWREC={}; let KWREC_SEED='';
// 캐시(KWREC)는 남긴다 — 탭을 오갈 때마다 kwSet이 추천을 다시 살리는데, 지우면 매번 네이버 재조회.
function kwRecReset(){ KWREC_SEED=''; const b=$('#kwrec'); if(b){b.style.display='none';b.innerHTML='';} }
function kwRecRender(){
  const box=$('#kwrec'); if(!box) return;
  const list=KWREC[KWREC_SEED];
  if(!Array.isArray(list)){ box.style.display='none'; box.innerHTML=''; return; }
  // 이미 넣은 키워드는 빼고, ❌(경쟁 과다)도 빼 '유리한' 것만 남긴다.
  const items=list.map(s=>({kw:s.keyword,vol:s.volume,j:classifyKw({total:s.total,volume:s.volume})}))
    .filter(s=>!kwHas(s.kw)&&s.j.badge!=='❌');
  const hasVol=items.some(s=>s.vol!=null);
  box.style.display='block'; box.innerHTML='';
  // 헤더 + '🔄 다시 추천'(넣은 키워드를 돌아가며 새 연관어를 뽑아줌 — 첫 단어에 안 묶임)
  const head=document.createElement('div'); head.className='kwrec-t';
  head.append(document.createTextNode('💡 이 키워드는 어때요? '));
  const m=document.createElement('span'); m.className='muted';
  m.textContent=hasVol?`'${KWREC_SEED}' 연관검색어 중 검색량 대비 경쟁 유리한 순`:`'${KWREC_SEED}' 연관검색어 중 경쟁 낮은 순`;
  head.append(m);
  const rb=document.createElement('button'); rb.type='button'; rb.className='kwrec-re'; rb.textContent='🔄 다시 추천';
  rb.title='넣은 키워드를 돌아가며 다른 연관어를 추천해요'; rb.onclick=reSuggest; head.append(rb);
  box.append(head);
  if(!items.length){
    const e=document.createElement('div'); e.className='muted'; e.style.fontSize='11.5px';
    e.textContent='이 키워드로는 더 추천할 게 없어요. 🔄로 다른 키워드에서 찾아보세요.'; box.append(e); return;
  }
  const wrap=document.createElement('div'); wrap.className='kwrec-list';
  items.forEach(s=>{ const b=document.createElement('button'); b.type='button'; b.className='rc'; b.title=s.j.tip;
    const bd=document.createElement('span'); bd.className='rcb'; bd.textContent=s.j.badge;
    const tx=document.createTextNode(s.kw);
    b.append(bd,tx);
    if(s.vol!=null){ const vv=document.createElement('span'); vv.className='muted';
      vv.style.cssText='font-size:10.5px;margin-left:4px'; vv.textContent=`월 ${fmtVol(s.vol)}`; b.append(vv); }
    const pl=document.createElement('span'); pl.className='rcplus'; pl.textContent='+';
    b.append(pl); b.onclick=()=>{ kwAddMany([s.kw],true); }; wrap.append(b); });  // true=추천 클릭 → 씨앗 안 바꿈
  box.append(wrap);
}
// '🔄 다시 추천' — 넣은 키워드를 순서대로 돌며(첫 단어만이 아니라) 캐시를 비우고 새로 뽑는다.
function reSuggest(){
  if(!KW.length) return;
  const i=KW.findIndex(k=>k.toLowerCase()===(KWREC_SEED||'').toLowerCase());
  const next=KW[(i+1)%KW.length]||KW[0];
  delete KWREC[next];              // 캐시 비워 강제 재조회
  suggestKeywords(next);
}
async function suggestKeywords(seed){
  seed=(seed||'').trim(); if(!seed) return;
  KWREC_SEED=seed;
  if(KWREC[seed]!==undefined){ kwRecRender(); return; }   // 캐시 or 진행 중 — 재요청 안 함
  KWREC[seed]=null;
  const box=$('#kwrec'); if(box){ box.style.display='block'; box.innerHTML='<div class=kwrec-t><span class=muted>유리한 연관 키워드 찾는 중…</span></div>'; }
  try{ const r=await fetch('/api/keyword-suggest?q='+encodeURIComponent(seed)); const d=await r.json();
       KWREC[seed]=(r.ok&&Array.isArray(d.suggestions))?d.suggestions:[]; }
  catch(e){ KWREC[seed]=[]; }
  kwRecRender();
}
(()=>{ const inp=$('#keywords'), box=$('#kwbox'); if(!inp||!box) return;
  box.onclick=e=>{ if(e.target===box) inp.focus(); };
  inp.onkeydown=e=>{
    // 한글 IME 조합 중 keydown(keyCode 229)은 무시 — 조합 확정 Enter를 커밋으로 오인해 마지막 글자가 칩으로 따로 들어가던 버그
    if(e.isComposing||e.keyCode===229) return;
    if(e.key==='Enter'||e.key===','){ e.preventDefault(); kwCommit(); }
    else if(e.key==='Backspace'&&!inp.value){ if(KW.length){ KW.pop(); kwRender(); } }
  };
  // 붙여넣기: "필수키워드" 같은 라벨 줄/접두어는 걷어내고, 쉼표·줄바꿈이 있으면 그 기준으로만
  // 나눠 "프랑스 소금"처럼 띄어쓰기 포함 키워드를 통째로 유지. 없으면 기존대로 띄어쓰기로 나눔.
  inp.onpaste=e=>{ const t=(e.clipboardData||window.clipboardData).getData('text'); if(!t)return;
    e.preventDefault(); kwCommit();
    const body=t.replace(/(^|\n)[ \t]*(필수[ \t]*)?키워드[ \t]*(?:[::][ \t]*|(?=\n)|$)/g,'$1');
    kwAddMany(body.split(/[,\n]/.test(body)?/[,\n]+/:/\s+/)); };
  inp.onblur=()=>kwCommit();
})();
// 불러온 글 제목을 필수 키워드 맨 앞에 넣어줌(중복이면 그대로). 노트로 사용자에게 알려줌.
function applyDraftTitleKeyword(title){
  const t=(title||'').trim(); if(!t||t==='(제목 없음)') return;
  const note=$('#kwnote'); if(!$('#kwbox')) return;
  kwCommit();
  const dup=kwHas(t);
  if(!dup){ KW.unshift(t); kwRender(); }
  judgeKeyword(t); suggestKeywords(t);  // 손으로 넣을 때와 똑같이 노출 판정·연관 추천을 돌린다
  if(note){
    note.textContent = dup
      ? `📥 불러온 글 제목 "${t}"은(는) 이미 키워드에 있어요.`
      : `📥 불러온 글 제목 "${t}"을(를) 필수 키워드에 자동으로 넣었어요. 필요 없으면 지워도 돼요.`;
    note.style.display='block';
  }
}
// 불러온 미디어를 '상태 객체(WS.state)'에 반영한다(현재 탭이 아닌 배경 탭에 채울 때 씀).
// 반환: 사진+영상 경로 배열. 활성 탭이면 호출부가 applyWS로 화면에 반영한다.
function fillStateFromMedia(s, media, title, date){
  const paths=media.map(m=>m.path).filter(Boolean);
  s.PHOTOS=paths.slice(); s.SELP=[]; s.PHOTOMETA={}; s.THUMB=null; s.AISET=new Set();
  s.PMACTIVE=undefined; s.PMSEL=new Set(); s.PMANCHOR=null; s.SUBCATS={}; s.XCATS=[];
  if(paths.length){
    s.IMPORTED_DRAFT={title:(title||''), date:(date||'')};  // 저장 후 원본 삭제 식별용
    const t=(title||'').trim();
    if(t&&t!=='(제목 없음)'){  // 제목을 필수 키워드 맨 앞에(단일 불러오기와 동일 규칙)
      const cur=(s.keywords||'').split(',').map(x=>x.trim()).filter(Boolean);
      if(!cur.some(k=>k.toLowerCase()===t.toLowerCase())){ cur.unshift(t); s.keywords=cur.join(', '); }
    }
  }
  return paths;
}
// 손 안 댄 빈 '새 글' 탭인지 — 인박스 사진(서버 풀 자동 로드)은 작업으로 안 침.
function wsIsBlank(s){
  return !s.PLAN && !s.IMPORTED_DRAFT && !(s.SELP&&s.SELP.length)
    && !((s.memo||'').trim()) && !((s.srcval||'').trim()) && !((s.keywords||'').trim()) && !((s.itext||'').trim())
    && !((s.links||'').trim()) && !(s.prod||[]).some(v=>(v||'').trim())
    && (s.previewClass||'').includes('empty');
}
// 배치 불러오기: 선택된 글을 각각 '새 탭'으로 연다. 네이버 접속은 서버 락이 하나씩 처리하므로,
// N개를 한꺼번에 쏴도 세션 충돌 없이 순서대로 채워진다(끝난 탭부터 사진이 들어옴).
async function batchImport(){
  const keys=[...DRAFTSEL]; if(!keys.length) return;
  const picks=keys.map(k=>DRAFTS.find(d=>String(d.idx)===String(k))).filter(Boolean);
  if(!picks.length) return;
  stashCur();  // 현재 탭 상태 보존
  // 선택 수만큼 '불러오는 중' 탭 생성(전환은 첫 탭만). 제목은 임시로 원본 글 제목.
  // 단, 현재 탭이 손 안 댄 빈 '새 글'이면 첫 글은 새 탭 대신 그 탭에 담는다(빈 탭 안 남게).
  const cur=findWS(CURWS);
  const tabs=picks.map((dr,i)=>{ const w=(i===0&&cur&&wsIsBlank(cur.state))?cur:pushWS(blankWS()); w.status='importing';
    w.state.IMPORTED_DRAFT={title:(dr.title||''), date:(dr.date||'')}; return {w,dr}; });
  CURWS=tabs[0].w.id; applyWS(tabs[0].w.state); renderTabs();
  closePhotoModal(); DRAFTSEL.clear(); updateDraftBatchBtn();
  toast(`${tabs.length}개 글을 새 탭으로 불러오는 중… 뒤에서 하나씩 처리돼요. 다른 탭 작업하셔도 돼요.`,'ok');
  for(const {w,dr} of tabs){
    fetch('/api/drafts/import',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({idx:dr.idx})})
      .then(async res=>{ const d=await res.json().catch(()=>({})); if(!res.ok) throw new Error(d.error||'가져오기 실패');
        const media=d.media||((d.paths||[]).map(p=>({kind:'image',path:p})));
        const paths=fillStateFromMedia(w.state, media, dr.title, dr.date);
        w.status='edit';
        if(w.id===CURWS) applyWS(w.state);  // 그 탭을 보고 있으면 즉시 화면 반영
        renderTabs();
        const nVid=media.filter(m=>m.kind==='video').length;
        toast(`'${dr.title||'글'}' ${paths.length}장${nVid?` · 영상 ${nVid}개`:''} 불러옴 ✓`,'ok');
      })
      .catch(e=>{ w.status='edit'; renderTabs(); toast(`'${dr.title||'글'}' 불러오기 실패 — ${e.message}`,'err'); });
  }
}

// 사진 분류·캡션 (수동 + ✨ AI 자동 추천). 결과는 PHOTOMETA(경로→{label,caption})에 저장.
let PHOTOMETA={}, PHOTO_CATS={}, THUMB=null;  // THUMB=대표 썸네일 경로(글 맨 위 첫 사진, 최대 1장)
let AISET=new Set();  // AI로 만든 이미지 경로(FLUX 썸네일·외부 AI 대체) — 게시 시 'AI 활용' 표시
let AIPROG=null;  // ✨ AI 분석 진행 상태 {wsid,done,total} — 전역이라 모달을 닫았다 열어도, 탭을 바꿔도 표시가 이어진다
async function loadPhotoCats(){ try{PHOTO_CATS=await (await fetch('/api/photo_categories')).json();}catch(e){} }
function curCats(){ return PHOTO_CATS[SRCKIND]||PHOTO_CATS.place||['외관','내부','메뉴판','음식','영수증','기타']; }
function photoMetaForSel(){ const o={}; SELP.forEach(p=>{const m=PHOTOMETA[p]||{}; const e={};
  if(m.label)e.label=m.label; if(m.caption)e.caption=m.caption; if(p===THUMB)e.thumbnail=true;
  if(AISET.has(p))e.ai_generated=true;
  if(e.label||e.caption||e.thumbnail||e.ai_generated)o[p]=e; }); return o; }
function setThumb(path){ THUMB=(THUMB===path?null:path); renderGrid(); renderPmeta(); updatePhotoSummary(); }
function updatePhotoSummary(){
  const n=SELP.length, inbox=inboxPhotos().length;
  const ai=AIPROG&&AIPROG.wsid===CURWS;  // 모달 밖(사진 버튼 옆)에서도 분석 진행이 보이게
  const ps=$('#psel'); if(ps) ps.textContent = n? `${n}장` : '';
  const su=$('#photosum'); if(su) su.textContent = ai? `✨ AI 분석 중 ${AIPROG.done}/${AIPROG.total}장…` : (n? `${n}장 선택됨` : '사진 없음');
  const stt=$('#phstat'); if(stt) stt.textContent = (n||inbox)? `글에 담김 ${n}장 · 분류 전 ${inbox}장` : '';
}
function openPhotoModal(){
  const m=$('#phmodal'); if(!m)return;
  m.style.display='flex';
  const box=$('#pmeta'); if(box){ box.classList.add('open'); }
  renderGrid(); renderPmeta();
}
function closePhotoModal(){ const m=$('#phmodal'); if(m)m.style.display='none'; updatePhotoSummary(); }
// PMACTIVE: 활성 칸(undefined=초기→첫칸 외관, 문자열=활성, null=해제). PMSEL=보이는 선택(더미·보드 공통). SUBCATS=세션 세부분류.
let PMDRAG=null, PMSEL=new Set(), PMANCHOR=null, PMACTIVE=undefined, SUBCATS={}, XCATS=[], CATCB=null;
let LANEDRAG=null, CATORDER=[];  // LANEDRAG=끌고 있는 칸, CATORDER=드래그로 정한 칸 순서(비면 프리셋 순서)
// 프리셋(config) + 이 글에만 추가한 분류(XCATS). '기타' 앞에 끼워 넣어 기타를 맨 뒤로 유지.
// CATORDER가 있으면 그 순서로 재배열(목록에 없는 분류는 원래 자리 뒤에 남는다).
function baseCats(){ const c=curCats().slice(), i=c.indexOf('기타'); c.splice(i<0?c.length:i, 0, ...XCATS.filter(x=>!c.includes(x)));
  if(!CATORDER.length) return c;
  return c.map((n,idx)=>{const k=CATORDER.indexOf(n); return {n, k:k<0?1e6+idx:k};}).sort((a,b)=>a.k-b.k).map(o=>o.n); }
// 칸 순서 바꾸기 — src를 dst 자리로(아래로 끌면 dst 뒤, 위로 끌면 dst 앞).
function laneMove(src,dst){
  if(!src||!dst||src===dst) return;
  const c=baseCats(), i=c.indexOf(src), d=c.indexOf(dst);
  if(i<0||d<0) return;
  const down=i<d; c.splice(i,1);
  const j=c.indexOf(dst); c.splice(down?j+1:j, 0, src);
  CATORDER=c; renderPmeta();
}
// 초안에 보낼 사진 순서 = 칸 순서(= 글의 사진 배치 순서). 같은 칸 안에서는 담은 순서 유지.
// 영상은 불러온 글에서 위치를 못 바꾸므로 원래 순서 그대로 뒤에 붙인다(백엔드가 따로 다룸).
function orderedSel(){
  const ord=pmBuckets().map(b=>b.key), k=p=>{const i=ord.indexOf(pmBucketOf(p)); return i<0?999:i;};
  const imgs=SELP.filter(p=>!isVid(p)), vids=SELP.filter(isVid);
  return imgs.map((p,i)=>[p,k(p),i]).sort((a,b)=>a[1]-b[1]||a[2]-b[2]).map(a=>a[0]).concat(vids);
}
function allCats(){ const o=[]; baseCats().forEach(c=>{ o.push(c); (SUBCATS[c]||[]).forEach(s=>{ if(!o.includes(s))o.push(s); }); }); return o; }
function pmBuckets(){ const o=[]; baseCats().forEach(c=>{ o.push({key:c,name:c,sub:false}); (SUBCATS[c]||[]).forEach(s=>o.push({key:s,name:s,sub:true,parent:c})); }); return o; }
function pmBucketOf(path){ const cats=allCats(), lb=(PHOTOMETA[path]||{}).label||''; return cats.includes(lb)?lb:(baseCats()[0]||''); }
function pmAssign(path,key){ (PHOTOMETA[path]=PHOTOMETA[path]||{}).label=key; }
function pmEnsureDefaults(){ const def=baseCats()[0]||''; SELP.forEach(p=>{const m=(PHOTOMETA[p]=PHOTOMETA[p]||{}); if(!m.label)m.label=def;}); }
// 사진 클릭(더미·보드 공통): 단일=활성 칸으로 즉시 / Shift=보이는 범위 선택(이동X, 업로드 순서) / ⌘·Ctrl=개별 토글
function photoSel(path,ev){
  if(ev.shiftKey){  // Shift는 항상 '선택'만(즉시 이동 안 함). 시작점도 Shift로 가능.
    if(PMANCHOR){
      const a=PHOTOS.indexOf(PMANCHOR), b=PHOTOS.indexOf(path);
      if(a>=0&&b>=0){ const lo=Math.min(a,b),hi=Math.max(a,b), remove=PMSEL.has(path);
        for(let i=lo;i<=hi;i++){ const p=PHOTOS[i]; if(!p)continue; if(remove)PMSEL.delete(p); else PMSEL.add(p); } }
      else PMSEL.add(path);
    } else PMSEL.add(path);
    PMANCHOR=path;
  } else if(ev.metaKey||ev.ctrlKey){ if(PMSEL.has(path))PMSEL.delete(path); else PMSEL.add(path); PMANCHOR=path; }
  else {
    if(PMACTIVE!=null){ if(!SELP.includes(path))SELP.push(path); pmAssign(path,PMACTIVE); PMSEL.clear(); }
    else PMSEL=new Set([path]);
    PMANCHOR=path;
  }
  renderGrid(); renderPmeta();
}
function laneClick(key){  // 칸 클릭: 선택한 사진 있으면 그 칸으로 이동, 없으면 활성 토글
  if(PMSEL.size){
    const moved=[...PMSEL];
    moved.forEach(p=>{ if(!SELP.includes(p))SELP.push(p); pmAssign(p,key); });
    PMSEL=new Set(); PMANCHOR=null; PMACTIVE=key;
    if(moved.length>1){  // 시프트로 여러 장 담았으면 → 다음 더미 사진을 자동 선택해 이어서 처리
      const lastIdx=Math.max(...moved.map(p=>PHOTOS.indexOf(p)));
      const nxt=PHOTOS.find((p,i)=>i>lastIdx && !SELP.includes(p));
      if(nxt){ PMSEL.add(nxt); PMANCHOR=nxt; }
    }
  } else PMACTIVE=(PMACTIVE===key?null:key);
  renderGrid(); renderPmeta();
}
function openCatModal(title,desc,cb){
  CATCB=cb; $('#cattitle').textContent=title; $('#catdesc').textContent=desc||'';
  const inp=$('#catinput'); inp.value=''; $('#catmodal').style.display='flex'; setTimeout(()=>inp.focus(),30);
}
function closeCatModal(){ $('#catmodal').style.display='none'; CATCB=null; }
function catSubmit(){ const v=$('#catinput').value.trim(); if(!v){toast('이름을 입력하세요.','info');return;} const cb=CATCB; closeCatModal(); if(cb)cb(v); }
let CAPPATH=null;  // 세부 설명 편집 중인 사진 경로(보드 타일 더블클릭)
function openCapModal(path){
  CAPPATH=path; const m=PHOTOMETA[path]||{};
  $('#caplabel').textContent = m.label || '미분류';
  $('#capimg').src = '/photo?path='+encodeURIComponent(path);
  const inp=$('#capinput'); inp.value=m.caption||'';
  $('#capmodal').style.display='flex'; setTimeout(()=>{inp.focus(); inp.select();},30);
}
function closeCapModal(){ $('#capmodal').style.display='none'; CAPPATH=null; }
function capSubmit(){
  if(CAPPATH){ const v=$('#capinput').value.trim();
    (PHOTOMETA[CAPPATH]=PHOTOMETA[CAPPATH]||{}).caption=v; }
  closeCapModal(); renderGrid(); renderPmeta();
  toast('세부 설명을 저장했어요.','ok');
}
function addCategory(){  // 분류 추가(이 글에만 — 다른 글·다음 글엔 안 번짐)
  openCatModal('새 분류 추가','이번 글에만 쓰는 분류예요(다른 글엔 안 생겨요). 계속 쓸 분류는 config/photo_categories.yaml에 적어두세요.', name=>{
    if(allCats().includes(name)){ toast('이미 있는 분류예요.','info'); return; }
    XCATS.push(name); PMACTIVE=name; renderPmeta(); toast('"'+name+'" 분류 추가(이 글에만)','ok');
  });
}
function removeCat(name){
  XCATS=XCATS.filter(c=>c!==name);
  (SUBCATS[name]||[]).forEach(s=>removeSub(name,s));  // 딸린 세부분류 먼저 접기
  delete SUBCATS[name];
  const def=baseCats()[0]||'';
  SELP.forEach(p=>{ if((PHOTOMETA[p]||{}).label===name) pmAssign(p,def); });
  if(PMACTIVE===name)PMACTIVE=def; renderPmeta();
}
function addSub(parent){  // 세부분류 추가(이 글에만, 저장 안 함)
  openCatModal('세부분류 추가', "'"+parent+"' 아래 세부분류 — 이번 글에만(새 글 시작하면 사라짐)", name=>{
    if(allCats().includes(name)){ toast('이미 있는 분류예요.','info'); return; }
    (SUBCATS[parent]=SUBCATS[parent]||[]).push(name); PMACTIVE=name; renderPmeta(); toast('세부분류 "'+name+'" 추가(이 글에만)','ok');
  });
}
function removeSub(parent,sub){
  SUBCATS[parent]=(SUBCATS[parent]||[]).filter(s=>s!==sub);
  SELP.forEach(p=>{ if((PHOTOMETA[p]||{}).label===sub) pmAssign(p,parent); });  // 그 세부 사진은 부모 칸으로
  if(PMACTIVE===sub)PMACTIVE=parent; renderPmeta();
}
function pmTile(path){
  const isT=path===THUMB;
  const hasCap=!!((PHOTOMETA[path]||{}).caption||'').trim();
  return `<div class="pmtile${PMSEL.has(path)?' sel':''}${isT?' thumb':''}${hasCap?' hascap':''}" data-path="${esc(path)}">`
    +`<img draggable=true src="/photo?path=${encodeURIComponent(path)}">`
    +`<button type=button class="pmstar${isT?' on':''}" title="${isT?'대표 썸네일 해제':'대표 썸네일로 지정 — 글 맨 위 첫 사진'}">★</button>`
    +(isT?'<span class=pmribbon>대표</span>':'')
    +`<button type=button class=pmcap title="${hasCap?'세부 설명 편집 (더블클릭)':'세부 설명 추가 (더블클릭)'}">📝</button>`
    +`<button type=button class=pmx title="분류함에서 빼기(다시 더미로)">×</button></div>`;
}
function renderPmeta(){
  if(PMACTIVE===undefined) PMACTIVE = baseCats()[0]||null;
  if(PMACTIVE!=null && !allCats().includes(PMACTIVE)) PMACTIVE=null;
  pmEnsureDefaults();
  [...PMSEL].forEach(p=>{ if(!PHOTOS.includes(p))PMSEL.delete(p); });
  if(THUMB && !SELP.includes(THUMB)) THUMB=null;  // 분류함에서 빠진 사진은 썸네일 해제
  const tbody = (THUMB)
    ? `<img src="/photo?path=${encodeURIComponent(THUMB)}"><span>이 사진이 글 맨 위 <b>첫 사진</b>으로 들어가요</span><button type=button class=minibtn id=thumbgen title="대표사진을 손그림 감성 썸네일로 (Qwen-Image-Edit)">🎨 AI 썸네일</button><button type=button class=minibtn id=thumbswap title="내가 만든 이미지 파일로 대표를 교체 — 외부 AI로 만든 썸네일 등">🔁 사진 대체</button><button type=button class=minibtn id=thumbclr>해제</button>`
    : `<span class=pmempty>사진의 <b>★</b>를 눌러 <b>대표 썸네일</b>을 정하세요 — 글 맨 위 첫 사진이 됩니다</span>`;
  let h=`<div class=pmthumbbar><span class=pmthumblbl>⭐ 대표 썸네일</span>${tbody}</div>`;
  if(AIPROG&&AIPROG.wsid===CURWS){  // 분석 중엔 상태줄이 진행바로 바뀜 — 모달을 닫았다 열어도 그대로
    const pct=AIPROG.total?Math.round(AIPROG.done/AIPROG.total*100):0;
    h+=`<div class=pmhead><span class="pmstate on">✨ AI 분석 중 · <b>${AIPROG.done}/${AIPROG.total}장</b> <span id=aisec></span></span><span class=aibar><span class=aifill style="width:${pct}%"></span></span></div>`;
  }else{
    h+='<div class=pmhead><span class="pmstate'+(PMSEL.size?' on':'')+'">'
    + (PMSEL.size
        ? `<b>${PMSEL.size}장</b> 선택됨 — 담을 칸을 클릭(또는 드래그)`
        : (PMACTIVE!=null
            ? `<b>${esc(PMACTIVE)}</b> 칸 활성 — 사진 클릭하면 담겨요 · Shift로 여러 장 선택 후 칸 클릭`
            : '사진 클릭/Shift로 선택 → 담을 칸 클릭. (칸을 클릭하면 활성=클릭으로 담기)'))
    + `</span><button type=button class=minibtn id=aibtn title="분류함에 담긴 사진을 AI가 알맞은 칸으로 분류하고 세부 설명을 달아줘요">✨ AI 자동 분류·설명${SELP.length?` (${SELP.length}장)`:''}</button></div>`;
  }
  h+='<div class=pmboard>'+pmBuckets().map(b=>{
    const items=SELP.filter(p=>pmBucketOf(p)===b.key);
    const inner=items.length?items.map(pmTile).join(''):'<span class=pmempty>여기로 끌어다 놓기</span>';
    const act=(b.key===PMACTIVE)?' active':'';
    const badge=`<span class=pmcount>${items.length}</span>${act?'<span class=pmtarget>담는 중</span>':''}`;
    const hd = b.sub
      ? `<div class=pmlanehd>↳ ${esc(b.name)} ${badge}<button type=button class=pmsubdel data-parent="${esc(b.parent)}" data-sub="${esc(b.name)}" title="세부분류 삭제">×</button></div>`
      : `<div class=pmlanehd draggable=true title="끌어서 글쓰기 순서 바꾸기"><span class=pmgrip>⠿</span>${esc(b.name)} ${badge}<button type=button class=pmsubbtn data-cat="${esc(b.key)}" title="세부분류 추가(이 글에만)">+세부</button>`
        + (XCATS.includes(b.key)?`<button type=button class=pmcatdel data-cat="${esc(b.key)}" title="이 글에서 추가한 분류 삭제">×</button>`:'') + `</div>`;
    return `<div class="pmlane${b.sub?' sub':''}${act}" data-key="${esc(b.key)}"${b.sub?` data-parent="${esc(b.parent)}"`:''}>${hd}<div class=pmdrop>${inner}</div></div>`;
  }).join('')
   + '<button type=button class=pmadd id=pmadd>+ 새 분류 추가</button>'
   + '</div>';
  const box=$('#pmeta'); box.innerHTML=h;
  const ab=$('#aibtn'); if(ab)ab.onclick=openAiModal;  // 분석 중엔 버튼 대신 진행바라 없을 수 있음
  $('#pmadd').onclick=addCategory;
  $$('#pmeta .pmsubbtn').forEach(btn=>{ btn.onclick=e=>{ e.stopPropagation(); addSub(btn.dataset.cat); }; });
  $$('#pmeta .pmsubdel').forEach(btn=>{ btn.onclick=e=>{ e.stopPropagation(); removeSub(btn.dataset.parent,btn.dataset.sub); }; });
  $$('#pmeta .pmcatdel').forEach(btn=>{ btn.onclick=e=>{ e.stopPropagation(); removeCat(btn.dataset.cat); }; });
  $$('#pmeta .pmlane:not(.sub) > .pmlanehd').forEach(hd=>{  // 칸 머리 = 순서 바꾸기 손잡이
    const key=hd.parentElement.dataset.key;
    hd.ondragstart=e=>{ e.stopPropagation(); LANEDRAG=key; e.dataTransfer.effectAllowed='move';
      try{e.dataTransfer.setData('text/plain','lane:'+key);}catch(_){}};
    hd.ondragend=()=>{ LANEDRAG=null; $$('#pmeta .pmlane').forEach(l=>l.classList.remove('lmove')); };
  });
  $$('#pmeta .pmlane[data-key]').forEach(l=>{
    const top=()=>l.dataset.parent||l.dataset.key;  // 세부칸에 떨어뜨리면 그 부모 자리로
    l.onclick=()=>laneClick(l.dataset.key);
    l.ondragover=e=>{e.preventDefault(); e.dataTransfer.dropEffect='move';
      l.classList.add(LANEDRAG?'lmove':'over');};
    l.ondragleave=()=>l.classList.remove('over','lmove');
    l.ondrop=async e=>{e.preventDefault(); l.classList.remove('over','lmove');
      if(LANEDRAG){ laneMove(LANEDRAG, top()); LANEDRAG=null; return; }  // 칸 순서 바꾸기
      // 파일 드롭 처리
      if(e.dataTransfer.files.length){ await handleFilesForBucket(e.dataTransfer.files, l.dataset.key); return; }
      // 사진 이동 처리
      const set=(PMDRAG&&PMDRAG.length)?PMDRAG:[]; PMDRAG=null;
      if(!set.length)return;
      set.forEach(p=>{ if(!SELP.includes(p))SELP.push(p); pmAssign(p,l.dataset.key); }); PMSEL=new Set(); PMANCHOR=null;
      renderGrid(); renderPmeta();
    };
  });
  $$('#pmeta .pmtile img').forEach(img=>{
    const path=img.closest('.pmtile').dataset.path;
    let clickT=null;  // 단일클릭은 살짝 지연 — 더블클릭(세부 설명)이면 취소
    img.onmousedown=e=>{ if(e.shiftKey) e.preventDefault(); };
    img.onclick=e=>{ e.stopPropagation();
      const mods={shiftKey:e.shiftKey,metaKey:e.metaKey,ctrlKey:e.ctrlKey};
      if(clickT)clearTimeout(clickT);
      clickT=setTimeout(()=>{ clickT=null; photoSel(path,mods); }, 230);
    };
    img.ondblclick=e=>{ e.stopPropagation(); if(clickT){clearTimeout(clickT);clickT=null;} openCapModal(path); };
    img.ondragstart=e=>{ if(clickT){clearTimeout(clickT);clickT=null;} PMDRAG=(PMSEL.has(path)&&PMSEL.size)?[...PMSEL]:[path];
      e.dataTransfer.effectAllowed='move'; try{e.dataTransfer.setData('text/plain',path);}catch(_){}};
    img.ondragend=()=>{PMDRAG=null; $$('#pmeta .pmlane').forEach(l=>l.classList.remove('over'));};
  });
  $$('#pmeta .pmtile .pmcap').forEach(c=>{
    c.onclick=e=>{ e.stopPropagation(); openCapModal(c.closest('.pmtile').dataset.path); };
  });
  $$('#pmeta .pmtile .pmx').forEach(x=>{
    x.onclick=e=>{ e.stopPropagation();
      const path=x.closest('.pmtile').dataset.path, i=SELP.indexOf(path);
      if(i>=0)SELP.splice(i,1); PMSEL.delete(path); if(THUMB===path)THUMB=null;
      renderGrid(); renderPmeta();
    };
  });
  $$('#pmeta .pmtile .pmstar').forEach(s=>{
    s.onclick=e=>{ e.stopPropagation(); setThumb(s.closest('.pmtile').dataset.path); };
  });
  const tc=$('#thumbclr'); if(tc) tc.onclick=()=>{ THUMB=null; renderGrid(); renderPmeta(); };
  const tg=$('#thumbgen'); if(tg) tg.onclick=openThumbModal;
  const ts=$('#thumbswap'); if(ts) ts.onclick=openSwapModal;
}
// ===== 멀티 탭(워크스페이스) =====
// 글마다 독립 탭. 흩어진 전역·입력값을 '한 글치 상태 객체'로 캡처/복원해, 탭을 바꿔도
// 서로 안 섞이게 한다. 네이버 접속(불러오기·게시)은 여전히 서버 락으로 한 번에 하나씩.
let WS=[];        // [{id, status, state}]  status: 'edit' | 'importing'
let CURWS=null;   // 현재 활성 탭 id
let WSSEQ=0;      // '새 글 N' 번호 매기기용
function newWSId(){ return (window.crypto&&crypto.randomUUID)?crypto.randomUUID():('w'+Date.now()+'-'+Math.round(Math.random()*1e6)); }
function findWS(id){ return WS.find(w=>w.id===id); }
// 화면·전역의 'per-draft' 상태 전부를 평범한 객체로 캡처(탭에 보관용).
function captureWS(){
  return {
    PHOTOS:PHOTOS.slice(), SELP:SELP.slice(), PLAN,
    PHOTOMETA:JSON.parse(JSON.stringify(PHOTOMETA||{})), THUMB, AISET:new Set(AISET||[]),
    PMACTIVE, PMSEL:new Set(PMSEL||[]), PMANCHOR, SUBCATS:JSON.parse(JSON.stringify(SUBCATS||{})), XCATS:XCATS.slice(), CATORDER:CATORDER.slice(),
    SRCKIND, KINDMANUAL, IMPORTED_DRAFT,
    memo:$('#memo').value, srcval:$('#srcval').value, placehint:$('#placehint')?$('#placehint').value:'', keywords:kwGet(), itext:$('#itext').value,
    kwnote:$('#kwnote')?$('#kwnote').textContent:'', kwnoteShow:$('#kwnote')?$('#kwnote').style.display:'none',
    links:$('#links')?$('#links').value:'', prod:$$('#prodlinks .plink').map(i=>i.value),
    previewHTML:$('#preview').innerHTML, previewClass:$('#preview').className,
    saveDisabled:$('#save')?$('#save').disabled:true,
  };
}
// 빈 상태(새 글 탭).
function blankWS(){
  return {PHOTOS:[],SELP:[],PLAN:null,PHOTOMETA:{},THUMB:null,AISET:new Set(),PMACTIVE:undefined,PMSEL:new Set(),PMANCHOR:null,SUBCATS:{},XCATS:[],CATORDER:[],
    SRCKIND:'place',KINDMANUAL:false,IMPORTED_DRAFT:null,
    memo:'',srcval:'',placehint:'',keywords:'',itext:'',kwnote:'',kwnoteShow:'none',links:'',prod:[''],
    previewHTML:EMPTY_DOC,previewClass:'doc empty',saveDisabled:true};
}
// 캡처된 상태를 화면·전역으로 되돌린다(+재렌더).
function applyWS(s){
  PHOTOS=(s.PHOTOS||[]).slice(); SELP=(s.SELP||[]).slice(); PLAN=s.PLAN||null;
  PHOTOMETA=JSON.parse(JSON.stringify(s.PHOTOMETA||{})); THUMB=s.THUMB||null; AISET=new Set(s.AISET||[]);
  PMACTIVE=s.PMACTIVE; PMSEL=new Set(s.PMSEL||[]); PMANCHOR=s.PMANCHOR||null; SUBCATS=JSON.parse(JSON.stringify(s.SUBCATS||{})); XCATS=(s.XCATS||[]).slice(); CATORDER=(s.CATORDER||[]).slice(); PMDRAG=null; LANEDRAG=null;
  IMPORTED_DRAFT=s.IMPORTED_DRAFT||null;
  $('#memo').value=s.memo||''; $('#srcval').value=s.srcval||''; if($('#placehint'))$('#placehint').value=s.placehint||''; kwSet(s.keywords||''); $('#itext').value=s.itext||'';
  if($('#kwnote')){ $('#kwnote').textContent=s.kwnote||''; $('#kwnote').style.display=s.kwnoteShow||'none'; }
  if($('#links')) $('#links').value=s.links||'';
  $('#prodlinks').innerHTML=''; ((s.prod&&s.prod.length)?s.prod:['']).forEach(v=>addProdLink(v));
  $('#preview').innerHTML=s.previewHTML||''; $('#preview').className=s.previewClass||'doc empty';
  if(PLAN)renderPreview(PLAN);  // 스냅샷 HTML은 당시 '사진 보기' 설정으로 그린 것 — 현재 설정으로 다시 그린다
  if($('#save')) $('#save').disabled=(s.saveDisabled!==false);
  setKind(s.SRCKIND||'place', s.KINDMANUAL);  // kind UI + 상품링크칸 표시 동기화
  renderGrid(); renderPmeta(); updatePhotoSummary();
}
// 탭 제목: 초안 제목 > 메모 첫 줄 > 불러온 원본 제목 > '새 글 N'.
// 활성 탭은 아직 stash 전이므로 live 값(전역/DOM)을 읽어 실시간 반영한다.
function wsTitle(w){
  const live=(w.id===CURWS), s=w.state;
  const plan=live?PLAN:s.PLAN;
  const memo=live?($('#memo')?$('#memo').value:''):s.memo;
  const imp=live?IMPORTED_DRAFT:s.IMPORTED_DRAFT;
  if(plan&&plan.title) return plan.title;
  const m=(memo||'').trim().split('\n')[0]; if(m) return m.slice(0,20);
  if(imp&&imp.title) return imp.title;
  return '새 글 '+(w.seq||'');
}
function renderTabs(){
  const bar=$('#workbar'); if(!bar) return; bar.innerHTML='';
  WS.forEach(w=>{
    const t=document.createElement('div');
    t.className='wtab'+(w.id===CURWS?' on':'')+(w.status==='importing'?' importing':'');
    t.innerHTML='<span class=wspin></span><span class=wt></span>'+(WS.length>1?'<button class=wx title="탭 닫기">✕</button>':'');
    t.querySelector('.wt').textContent=wsTitle(w);
    t.onclick=e=>{ if(e.target.closest('.wx'))return; switchWS(w.id); };
    const x=t.querySelector('.wx'); if(x) x.onclick=e=>{ e.stopPropagation(); closeWS(w.id); };
    bar.appendChild(t);
  });
  const add=document.createElement('button'); add.type='button'; add.className='wtab wadd'; add.title='새 글 탭 열기'; add.textContent='+';
  add.onclick=()=>newWS(); bar.appendChild(add);
}
// 현재 탭 상태를 저장해두는 헬퍼(전환·새탭·닫기 전에 호출).
function stashCur(){ const c=findWS(CURWS); if(c) c.state=captureWS(); }

// 탭 작업 상태를 localStorage에 저장/복원 — 새로고침·크래시·서버 재시작으로 사진·순서·분류가
// 통째로 날아가던 문제를 막는다. 사진은 경로(작은 문자열)라 50장이어도 용량 문제 없음.
// PMSEL(Set)만 배열로 직렬화(그 외 전역은 JSON 안전).
const WS_KEY='autoblog_ws_v1';
function serWS(w){ return {id:w.id, seq:w.seq, status:w.status,
  state:{...w.state, PMSEL:[...(w.state.PMSEL||[])], AISET:[...(w.state.AISET||[])]}}; }
function persistWS(){
  try{
    const c=findWS(CURWS); if(c) c.state=captureWS();   // 현재 탭의 라이브 상태 반영 후 저장
    try{ localStorage.setItem(WS_KEY, JSON.stringify({CURWS, WS:WS.map(serWS)})); }
    catch(e){ // 용량 초과 시 미리보기 HTML만 빼고 재시도(사진·순서·분류는 보존)
      localStorage.setItem(WS_KEY, JSON.stringify({CURWS,
        WS:WS.map(w=>{ const x=serWS(w); x.state.previewHTML=''; return x; })}));
    }
  }catch(e){}
}
function restoreWS(){
  try{
    const raw=localStorage.getItem(WS_KEY); if(!raw) return false;
    const d=JSON.parse(raw); if(!d||!Array.isArray(d.WS)||!d.WS.length) return false;
    WS=d.WS.map(w=>({id:w.id, seq:w.seq||0, status:w.status||'edit', state:w.state}));
    WSSEQ=Math.max(0, ...WS.map(w=>w.seq||0));
    CURWS=(d.CURWS && findWS(d.CURWS)) ? d.CURWS : WS[0].id;
    applyWS(findWS(CURWS).state); renderTabs();
    dropMissingPhotos();  // 복원된 경로 중 파일이 없어진 것 정리(타일이 깨진 아이콘으로 남지 않게)
    return true;
  }catch(e){ return false; }
}
// 복원 상태엔 이제 없는 사진 경로가 섞일 수 있다(앱 이동·데이터 폴더 변경·파일 삭제).
// 그대로 두면 모든 타일이 이유 없이 깨져 보이므로, 서버에 한 번 물어보고 전 탭에서 걷어낸다.
async function dropMissingPhotos(){
  const all=[...new Set(WS.flatMap(w=>(w.state.PHOTOS||[])))]; if(!all.length) return;
  let miss;
  try{ const r=await fetch('/api/photos/missing',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({paths:all})});
       miss=new Set((await r.json()).missing||[]); }catch(e){ return; }  // 서버가 못 답하면 그냥 둔다
  if(!miss.size) return;
  WS.forEach(w=>{ const s=w.state;
    s.PHOTOS=(s.PHOTOS||[]).filter(p=>!miss.has(p));
    s.SELP=(s.SELP||[]).filter(p=>!miss.has(p));
    (s.PMSEL instanceof Set) && [...s.PMSEL].forEach(p=>miss.has(p)&&s.PMSEL.delete(p));
    if(s.PHOTOMETA) miss.forEach(p=>delete s.PHOTOMETA[p]);
    if(miss.has(s.THUMB)) s.THUMB=null;
    Object.keys(s.SUBCATS||{}).forEach(k=>{ s.SUBCATS[k]=(s.SUBCATS[k]||[]).filter(p=>!miss.has(p)); });
  });
  applyWS(findWS(CURWS).state); persistWS();
  toast(`사진 ${miss.size}장이 파일이 없어져 목록에서 빠졌어요 — 임시저장에서 다시 불러오거나 업로드하세요.`,'err');
}
function switchWS(id){
  if(id===CURWS) return;
  const t=findWS(id); if(!t) return;
  stashCur(); CURWS=id; applyWS(t.state); renderTabs();
}
// 전환 없이 새 탭을 목록에 추가만 한다(배치 불러오기가 여러 개를 한꺼번에 만들 때).
function pushWS(state){ const w={id:newWSId(), seq:++WSSEQ, status:'edit', state:state||blankWS()}; WS.push(w); return w; }
function newWS(){
  stashCur();
  const w=pushWS(blankWS()); CURWS=w.id; applyWS(w.state); renderTabs();
  return w;
}
function closeWS(id){
  const i=WS.findIndex(w=>w.id===id); if(i<0) return;
  const wasCur=(id===CURWS);
  WS.splice(i,1);
  if(!WS.length){ const w={id:newWSId(), seq:++WSSEQ, status:'edit', state:blankWS()}; WS.push(w); }
  if(wasCur){ CURWS=WS[Math.min(i,WS.length-1)].id; applyWS(findWS(CURWS).state); }
  renderTabs();
}
// 초기 탭 1개를 지금 화면 상태로 만든다(init 끝에서 호출).
function initWorkspaces(){
  const w={id:newWSId(), seq:++WSSEQ, status:'edit', state:captureWS()};
  WS=[w]; CURWS=w.id; renderTabs();
}

function newPost(){ $('#npmodal').style.display='flex'; }  // 새 글 시작 확인 모달
function closeNP(){ $('#npmodal').style.display='none'; }
function doNewPost(){  // 새 글: 현재 탭은 그대로 두고, 새 빈 탭을 연다
  closeNP();
  newWS();
  loadPhotos();  // 새 탭의 사진 인박스를 서버 풀에서 채움(기존 새글 동작 유지)
  toast('새 글 탭을 열었어요.','ok');
}
// 🎨 AI 썸네일 — ★ 대표사진을 Qwen-Image-Edit로 손그림 감성 썸네일로 만들어 대표로 교체
function openThumbModal(){
  if(!THUMB){toast('먼저 사진의 ★를 눌러 대표 썸네일을 정하세요.','info');return;}
  $('#tgimg').src='/photo?path='+encodeURIComponent(THUMB);
  $('#tgtitle').value=kwGet()[0]||'';
  $('#tgextra').value='';
  $('#tgmodal').style.display='flex'; setTimeout(()=>$('#tgtitle').focus(),30);
}
function closeTG(){ $('#tgmodal').style.display='none'; }
let PENDTHUMB=null;  // 생성 완료 후 적용 대기 중인 썸네일 {path,src}
async function runThumbGen(title,extra){
  const src=THUMB, btn=$('#thumbgen'); if(btn)btn.disabled=true;
  const el=elapsed('썸네일 생성 중…',(label,counter)=>{if(btn)btn.textContent=label+(counter?' '+counter:'');});
  try{
    const r=await fetch('/api/thumbnail',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({photo:src,title:title||'',extra:extra||''})});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||'알 수 없는 오류');
    const sec=el.stop();
    renderPmeta();  // 🎨 버튼 복구
    PENDTHUMB={path:d.path,src,prompt:d.prompt||''};
    $('#tpimg').src='/photo?path='+encodeURIComponent(d.path);
    const dl=$('#tpdl'); dl.href='/photo?path='+encodeURIComponent(src)+'&full=1';  // 외부 모델에 넘길 원본(화질 그대로)
    dl.download=src.split(/[\\/]/).pop()||'원본사진';  // 실제 확장자 그대로
    $('#tpmodal').style.display='flex';
    toast(`AI 썸네일 완성! (${sec}초) 미리보기에서 적용 여부를 정하세요.`,'ok');
  }catch(e){el.stop(); renderPmeta(); errNotice('썸네일 생성 실패', e.message);}
}
// ponytail: '적용 안 함'은 그냥 버림 — 파일은 uploads에 남지만 목록엔 안 뜸, 용량이 문제되면 삭제 API 추가
function closeTP(){ $('#tpmodal').style.display='none'; PENDTHUMB=null; }
function applyPendThumb(){
  const t=PENDTHUMB; closeTP(); if(!t)return;
  adoptThumb(t.path, t.src);
}
// 새 이미지를 원본과 같은 칸에 담고 ★ 대표로 교체 — AI 썸네일 적용·사진 대체 공용
function adoptThumb(path, src){
  if(!PHOTOS.includes(path))PHOTOS.push(path);
  if(!SELP.includes(path))SELP.push(path);
  pmAssign(path, pmBucketOf(src));
  AISET.add(path);  // AI 썸네일·외부 AI 대체 둘 다 여기로 온다 → 'AI 활용' 표시 대상
  THUMB=path;
  renderGrid(); renderPmeta();
  // 미리보기도 발행 결과와 맞춘다 — 서버 apply_photo_meta_overrides(plan.py)와 같은 규칙:
  // 플랜에 없는 새 이미지는 첫 이미지 자리에 삽입.
  if(PLAN&&!PLAN.blocks.some(b=>b.kind==='image'&&b.image_path===path)){
    const i=PLAN.blocks.findIndex(b=>b.kind==='image');
    PLAN.blocks.splice(i<0?PLAN.blocks.length:i,0,{kind:'image',image_path:path,image_label:'★ 대표(AI)',ai_generated:true});
    renderPreview(PLAN);
  }
  toast('새 이미지를 ★ 대표로 지정했어요.','ok');
}
// 🔁 사진 대체 — 원본사진·프롬프트를 챙겨 외부 이미지 모델에서 만들고, 완성 파일로 ★ 대표를 교체
let TSPROMPT=null;  // 썸네일 복사용 프롬프트 캐시(config/prompts/thumbnail_copy.md) — 외부 모델에 그대로 붙여넣기
async function thumbPrompt(){
  if(TSPROMPT===null){
    try{const d=await (await fetch('/api/thumbprompt')).json();
      TSPROMPT=d.prompt;}catch(e){}
  }
  return TSPROMPT;
}
function openSwapModal(){
  const src=THUMB; if(!src)return;
  $('#tsimg').src='/photo?path='+encodeURIComponent(src);
  const dl=$('#tsdl'); dl.href='/photo?path='+encodeURIComponent(src)+'&full=1';
  dl.download=src.split(/[\\/]/).pop()||'원본사진';
  $('#tsmodal').style.display='flex';
  thumbPrompt();  // 캐시만 미리 채움 — 자동 복사하면 [사진 복사]와 클립보드가 충돌해서 제거
}
function closeTS(){ $('#tsmodal').style.display='none'; }
function swapThumbFile(){
  const src=THUMB; if(!src)return;
  const fi=document.createElement('input'); fi.type='file'; fi.accept='image/*';
  fi.onchange=async()=>{
    const f=fi.files[0]; if(!f)return;
    if(!f.type.startsWith('image/')){toast('이미지 파일만 대표로 쓸 수 있어요.','info');return;}
    try{
      const dataurl=await new Promise(r=>{const fr=new FileReader();fr.onload=()=>r(fr.result);fr.readAsDataURL(f);});
      const res=await fetch('/api/upload',{method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify({filename:f.name,data:dataurl.split(',')[1]})});
      const d=await res.json();
      if(!res.ok||!d.path)throw new Error(d.error||'업로드 실패');
      closeTS();
      adoptThumb(d.path, src);
    }catch(e){errNotice('사진 대체 실패', e.message);}
  };
  fi.click();
}
// ✨ AI 분석 시작 전 모달 — 대상(분류함에 담긴 사진)을 명시하고, 선택 요청사항(hint)을 받는다.
function aiTargets(){ return SELP.filter(p=>!isVid(p)); }  // 영상은 비전 모델이 못 읽으니 제외
function openAiModal(){
  const n=aiTargets().length, inbox=inboxPhotos().filter(p=>!isVid(p)).length;
  if(!n){toast('분류함에 담긴 사진이 없어요 — 먼저 글에 쓸 사진을 칸에 담아주세요.','info');return;}
  if(AIPROG){toast('이미 AI 분석이 진행 중이에요.','info');return;}
  $('#aidesc').innerHTML=`분류함에 담긴 <b>${n}장</b>을 분석해 알맞은 칸으로 분류하고, 글에 녹일 세부 설명을 달아줘요.`
    +(inbox?`<br><span style="font-size:12px">분류 전 사진 ${inbox}장은 대상이 아니에요 — 글에 쓸 사진만 먼저 담아주세요.</span>`:'');
  $('#aimodal').style.display='flex'; setTimeout(()=>$('#aihint').focus(),30);
}
function closeAI(){ $('#aimodal').style.display='none'; }
// 분석 결과 반영 — 시작한 탭(wsid)의 상태에 쓴다. 탭을 바꿨으면 그 탭의 스냅샷에 기록.
function aiApply(wsid, items){
  const st = wsid===CURWS ? null : (findWS(wsid)||{}).state;
  const meta = st? st.PHOTOMETA : PHOTOMETA;
  if(!meta) return;
  (items||[]).forEach(p=>{meta[p.path]={label:p.label||'',caption:p.caption||''};});
}
const AIBATCH=4;  // ponytail: 4장씩 순차 배치 — 실제 진행도 표시 + 실패 시 끝난 배치까지 반영
async function runAiCaption(paths, hint, ctx){
  if(AIPROG)return;
  const targets=(paths||[]).filter(p=>!isVid(p));
  if(!targets.length){toast('분석할 사진이 없어요.','info');return;}
  const wsid=CURWS;  // 탭을 바꾸거나 모달을 닫아도 이어지도록 시작 시점의 탭·입력을 붙잡아 둔다
  ctx=ctx||{memo:$('#memo').value,srcval:$('#srcval').value,kind:SRCKIND};
  AIPROG={wsid,done:0,total:targets.length};
  renderPmeta(); updatePhotoSummary();
  const t0=Date.now();
  const tick=setInterval(()=>{const s=$('#aisec'); if(s)s.textContent=Math.round((Date.now()-t0)/1000)+'초';},1000);
  let done=0, fail=null;
  try{
    for(let i=0;i<targets.length;i+=AIBATCH){
      if(wsid!==CURWS && !findWS(wsid)) break;  // 시작한 탭이 닫혔으면 중단
      const chunk=targets.slice(i,i+AIBATCH);
      const r=await fetch('/api/photos/caption',{method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify({memo:ctx.memo,srcval:ctx.srcval,kind:ctx.kind,reviewType:ctx.kind,photos:chunk,hint:hint||''})});
      const d=await r.json().catch(()=>({}));
      if(!r.ok)throw new Error(d.error||'알 수 없는 오류');
      aiApply(wsid,d.photos);
      done+=chunk.length; AIPROG.done=done;
      if(wsid===CURWS){renderPmeta(); updatePhotoSummary();}
    }
  }catch(e){fail=e;}
  clearInterval(tick); AIPROG=null;
  if(wsid===CURWS){renderPmeta(); updatePhotoSummary();}
  const sec=((Date.now()-t0)/1000).toFixed(1);
  if(!fail){ if(done)toast(`사진 ${done}장 자동 분석 완료! (${sec}초) 검토·수정 후 생성하세요.`,'ok'); return; }
  // 실패해도 끝난 배치까지는 이미 반영됨 — 몇 장까지 됐는지 알리고 '이어서 분석'을 제안
  const remaining=targets.slice(done);
  if(String(fail.message).includes('한도 도달')){
    errNotice('사진 자동 분석', fail.message);
    if(done)toast(`${done}/${targets.length}장까지는 분류·설명이 반영됐어요.`,'info');
  }else{
    confirmModal('사진 분석이 중간에 멈췄어요',
      (done?`<b>${done}/${targets.length}장</b>까지는 분류·설명이 반영됐어요.<br>`:'')
      +`남은 <b>${remaining.length}장</b>을 이어서 분석할까요?<br><br><span style="font-size:12px;color:#8b95a1">${String(fail.message).replace(/</g,'&lt;')}</span>`,
      '이어서 분석','나중에',()=>runAiCaption(remaining,hint,ctx),null,'🤖');
  }
}

let GENTIMER=null, GENT0=0;
// 냥캣 로딩 씬: 밤하늘 별 + 냥캣 Lottie(LottieFiles 무료 애니메이션, /asset으로 로컬 서빙)
const NYAN=`<div class=nyanwrap>
  <i class=nstar style="top:14%;animation-duration:1.1s"></i>
  <i class=nstar style="top:32%;animation-duration:1.8s;animation-delay:.5s"></i>
  <i class=nstar style="top:52%;animation-duration:1.3s;animation-delay:.9s"></i>
  <i class=nstar style="top:70%;animation-duration:2.1s;animation-delay:.2s"></i>
  <i class=nstar style="top:85%;animation-duration:1.5s;animation-delay:1.2s"></i>
  <div class=nlot></div></div>`;
$('#pchar').innerHTML=NYAN;
function nyanMount(rootSel){ // 씬 주입 후 호출 — lottie가 없으면 밤하늘+별만 남음
  if(!window.lottie)return null;
  const el=document.querySelector(rootSel+' .nlot'); if(!el)return null;
  return lottie.loadAnimation({container:el,renderer:'svg',loop:true,autoplay:true,
    rendererSettings:{preserveAspectRatio:'xMidYMid slice'},path:'/asset?name=nyan_cat.json'});
}
function nyanKill(a){try{a&&a.destroy()}catch(e){}}
let GENANIM=null, EXPANIM=null;
const GENMSGS=[[0,'메모를 읽는 중…'],[18,'글을 쓰는 중…'],[50,'문장을 다듬는 중…'],[78,'강조·서식 입히는 중…'],[92,'거의 다 됐어요!']];
function genLoading(){
  const who=TEXT_MODEL?`${nicer(TEXT_MODEL)} 모델이 글을 써요`:'AI가 글을 써요';  // 적용 중인 텍스트 모델명 표시
  $('#preview').classList.add('empty');
  $('#preview').innerHTML=`<div class=genload>${NYAN}
    <div class=genmsg id=genmsg></div>
    <div class=genbar><div class=genfill id=genfill></div></div>
    <div class=genpct id=genpct>0%</div>
    <div class=gensub id=gensub>${who} · 보통 30~60초</div></div>`;
  nyanKill(GENANIM); GENANIM=nyanMount('#preview');
  typeText($('#genmsg'), '메모를 읽는 중…');  // 첫 문구도 한 글자씩
  let pct=0; GENT0=Date.now();
  GENTIMER=setInterval(()=>{
    pct+=Math.max(0.4,(96-pct)*0.035); if(pct>96)pct=96;
    const fl=$('#genfill'); if(!fl){clearInterval(GENTIMER);return;}
    fl.style.width=pct+'%'; $('#genpct').textContent=Math.floor(pct)+'%';
    const m=GENMSGS.filter(x=>pct>=x[0]).pop(); if(m)typeText($('#genmsg'), m[1]);
    const sb=$('#gensub'); if(sb)sb.textContent=`${who} · ${Math.round((Date.now()-GENT0)/1000)}초 경과`;
  },700);
}
function genDone(ok){ if(GENTIMER)clearInterval(GENTIMER);
  setTimeout(()=>{nyanKill(GENANIM); GENANIM=null;},400);  // renderPreview(350ms)로 교체된 뒤 정리
  const sec=GENT0?((Date.now()-GENT0)/1000).toFixed(1):null;
  if(ok){const fl=$('#genfill'); if(fl){fl.style.width='100%'; $('#genpct').textContent='100%';}
    const sb=$('#gensub'); if(sb&&sec)sb.textContent=`완성! ${sec}초 걸렸어요`;} }
// 생성 중에는 같은 버튼이 [취소]가 된다 — 서버가 늦게 답해도 언제든 빠져나올 수 있게.
let GENABORT=null;
const genLabel=()=>$('#restyleMode').checked?'내 문체로 변환':'초안 생성';
$('#gen').onclick=async()=>{
  if(GENABORT){GENABORT.abort(); return;}
  if(!$('#memo').value.trim()){st('경험 메모를 입력하세요.');return;}
  GENABORT=new AbortController(); $('#gen').textContent='✕ 취소';
  $('#save').disabled=true; st('생성 중…',true); genLoading();
  try{
    const body={memo:$('#memo').value,srcval:$('#srcval').value,kind:SRCKIND,placeHint:$('#placehint').value,photos:orderedSel(),photoMeta:photoMetaForSel(),tone:$('#tone').value,personaId:PERSONA_ID,keywords:kwGet(),minChars:$('#minchars').value,
      emphasis:FMT.emphasis,structure:FMT.structure,stickers:FMT.stickers,stickerAll:FMT.stickerAll,sponsored:FMT.sponsored,sponsorSticker:FMT.sponsorSticker,wishlist:FMT.wishlist,consumed:FMT.consumed,links:LINKS(),productLinks:PRODLINKS(),rules:RULES,
      draftId:CURWS,  // 이 탭의 글로 서버에 보관(게시 때 이 id로 '그 탭 글'을 정확히 저장)
      restyle:$('#restyleMode').checked,  // 켜면 외부 초안에 내 문체만 재적용(맛집/상품 구조 강제 안 함)
      inplace:!!IMPORTED_DRAFT};  // 불러온 글이면 in-place 편집(새 글용 사진 재정렬 휴리스틱 끔)
    const r=await fetch('/api/generate',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),signal:GENABORT.signal});
    const d=await r.json();
    if(!r.ok){genDone(false); $('#preview').innerHTML='<div class=genload><div style="font-size:40px">😢</div><div class=genmsg>생성 실패</div><div class=gensub>'+(d.error||'')+'</div></div>'; st('실패'); errNotice('초안 생성 실패', d.error); return;}
    genDone(true); PLAN=d; setTimeout(()=>renderPreview(d),350); st('생성 완료. 검토 후 임시저장하세요.'); toast('초안 생성 완료! 오른쪽 미리보기를 확인하세요.','ok'); $('#save').disabled=false; renderTabs();
    if(d.debug)showLog(d.debug);
  }catch(e){genDone(false);
    if(e.name==='AbortError'){$('#preview').innerHTML='<div class=genload><div style="font-size:40px">✋</div><div class=genmsg>생성을 취소했어요</div><div class=gensub>다시 [초안 생성]을 누르면 새로 시작해요</div></div>'; st('취소했어요'); toast('초안 생성을 취소했어요','ok');}
    else{st('오류: '+e); toast('초안 생성 오류: '+e,'err');}
  }finally{GENABORT=null; $('#gen').disabled=false; $('#gen').textContent=genLabel();}
};
// 리스타일 모드 토글 — 메모칸을 '외부 초안 붙여넣기'로 바꾸고 버튼 문구도 전환(백엔드 분기는 restyle 플래그)
$('#restyleMode').onchange=e=>{
  const on=e.target.checked;
  $('#memo').placeholder = on ? '여기에 완성된 외부 초안을 통째로 붙여넣으세요 (예: 다른 AI가 쓴 빽다방 칼로리 글 전체)' : '예: 비 오는 날 들렀는데 따뜻한 우동이 정말 맛있었어요. 사장님도 친절하셨고 분위기도 아늑했어요.';
  const lab=$('#memolabel'); if(lab&&lab.childNodes[0])lab.childNodes[0].nodeValue = on ? '외부 초안 붙여넣기' : '경험 메모';
  const gb=$('#gen'); if(gb&&!GENABORT)gb.textContent=genLabel();  // 생성 중이면 [취소] 유지
};
// 프롬프트 내보내기: 모달 안에서 진행바 + 실제 단계 메시지 보여주고, 합쳐진 프롬프트 표시·복사
let EXPTIMER=null;
function expLoading(on){
  $('#ploading').style.display=on?'block':'none'; $('#pcontent').style.display=on?'none':'block';
  if(EXPTIMER){clearInterval(EXPTIMER);EXPTIMER=null;}
  if(on){$('#pmodal').style.display='flex'; let pct=0;
    nyanKill(EXPANIM); EXPANIM=nyanMount('#ploading');
    $('#pfill').style.width='0%'; $('#ppct').textContent='0%'; typeText($('#pmsg'),'자료를 준비하는 중…');
    // 진행바·스피너만 부드럽게 굴리고, 문구는 서버가 보내는 실제 단계로 갱신(expStage)
    EXPTIMER=setInterval(()=>{pct+=Math.max(1,(96-pct)*0.08); if(pct>96)pct=96;
      const fl=$('#pfill'); if(!fl){clearInterval(EXPTIMER);return;}
      fl.style.width=pct+'%'; $('#ppct').textContent=Math.floor(pct)+'%';},650);
  }else{const fl=$('#pfill'); if(fl)fl.style.width='100%'; $('#ppct').textContent='100%';
    nyanKill(EXPANIM); EXPANIM=null;}
}
function expStage(msg){if(msg)typeText($('#pmsg'), msg);}
$('#export').onclick=async()=>{
  if(!$('#memo').value.trim()){toast('경험 메모를 먼저 입력하세요.','info');return;}
  $('#export').disabled=true; st('프롬프트를 만드는 중…',true);
  try{
    const body={memo:$('#memo').value,srcval:$('#srcval').value,kind:SRCKIND,placeHint:$('#placehint').value,photos:orderedSel(),photoMeta:photoMetaForSel(),tone:$('#tone').value,personaId:PERSONA_ID,keywords:kwGet(),minChars:$('#minchars').value,
      emphasis:FMT.emphasis,structure:FMT.structure,stickers:FMT.stickers,stickerAll:FMT.stickerAll,sponsored:FMT.sponsored,sponsorSticker:FMT.sponsorSticker,wishlist:FMT.wishlist,consumed:FMT.consumed,links:LINKS(),rules:RULES,
      restyle:$('#restyleMode').checked,  // 켜면 export도 restyle.md 사용(원문 표·나열 보존)
      inplace:!!IMPORTED_DRAFT};  // 불러온 글이면 [영상] 순서 고정 지시를 프롬프트에 포함
    const r=await fetch('/api/export-prompt',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    if(!r.body){st(''); toast('프롬프트 생성 실패','err');return;}
    // NDJSON 스트림: {stage} 단계 갱신, 마지막에 {prompt} 또는 {error}
    const reader=r.body.getReader(), dec=new TextDecoder(); let buf='', prompt=null, err=null;
    for(;;){const {value,done}=await reader.read();
      if(value){buf+=dec.decode(value,{stream:true}); let nl;
        while((nl=buf.indexOf('\n'))>=0){const line=buf.slice(0,nl).trim(); buf=buf.slice(nl+1);
          if(!line)continue; let ev; try{ev=JSON.parse(line);}catch(_){continue;}
          if(ev.stage)st(ev.stage,true); if(ev.prompt!=null)prompt=ev.prompt; if(ev.error)err=ev.error;}}
      if(done)break;}
    if(err){st(''); errNotice('프롬프트 생성 실패', err);return;}
    if(prompt==null){st(''); toast('프롬프트 생성 실패','err');return;}
    // 모달 없이 바로 클립보드로. 브라우저가 클립보드를 막은 경우에만 기존 모달로 폴백.
    try{await navigator.clipboard.writeText(prompt); st('프롬프트를 복사했어요.'); toast('프롬프트를 복사했어요! 다른 챗봇에 붙여넣으세요.','ok');}
    catch(_){$('#ptext').value=prompt; expLoading(false); $('#pmodal').style.display='flex'; st('');}
  }catch(e){st(''); toast('프롬프트 오류: '+e,'err');}finally{$('#export').disabled=false;}
};
$('#pcopy').onclick=async()=>{const t=$('#ptext');
  try{await navigator.clipboard.writeText(t.value);}catch(e){t.select();document.execCommand('copy');}
  toast('복사했어요! 다른 챗봇에 붙여넣으세요.','ok');};
function closePM(){$('#pmodal').style.display='none'; if(EXPTIMER){clearInterval(EXPTIMER);EXPTIMER=null;}}
$('#pmclose').onclick=closePM; $('#pmclose2').onclick=closePM;
$('#pmodal').onclick=e=>{if(e.target===$('#pmodal'))closePM();};
// 받아온 글 붙여넣기: 외부 챗봇 결과 → 마커 파싱 → 미리보기(생성과 동일 경로)
function closeIM(){$('#imodal').style.display='none';}
$('#import').onclick=()=>{$('#imodal').style.display='flex'; $('#itext').focus();};
$('#imclose').onclick=closeIM; $('#imclose2').onclick=closeIM;
$('#imodal').onclick=e=>{if(e.target===$('#imodal'))closeIM();};
$('#iapply').onclick=async()=>{
  const text=$('#itext').value.trim();
  if(!text){toast('붙여넣은 글이 비어 있어요.','info');return;}
  $('#iapply').disabled=true;
  try{
    const body={text,srcval:$('#srcval').value,kind:SRCKIND,photos:orderedSel(),photoMeta:photoMetaForSel(),emphasis:FMT.emphasis,structure:FMT.structure,stickers:FMT.stickers,stickerAll:FMT.stickerAll,sponsored:FMT.sponsored,sponsorSticker:FMT.sponsorSticker,links:LINKS(),productLinks:PRODLINKS()};
    const r=await fetch('/api/import-draft',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok){toast('가져오기 실패: '+(d.error||''),'err');return;}
    closeIM(); PLAN=d; renderPreview(d); st('받아온 글을 미리보기에 반영했어요. 검토 후 임시저장하세요.'); toast('받아온 글을 가져왔어요! 검토 후 임시저장하세요.','ok'); $('#save').disabled=false;
    if(d.debug)showLog(d.debug);
  }catch(e){toast('가져오기 오류: '+e,'err');}finally{$('#iapply').disabled=false;}
};
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
// 단락 정렬(left/center/right/justify) — 에디터에 실제 적용되는 align을 미리보기에도 반영
function alignStyle(b){return b&&b.align&&b.align!=='left'?`text-align:${b.align};`:'';}
// 강조 span의 실제 서식(색·배경·글씨체·크기·굵기)을 미리보기 인라인 스타일로 — 에디터와 최대한 같게
function emStyle(e){let s='';
  if(e.text_color)s+=`color:${e.text_color};`;
  if(e.background_color)s+=`background:${e.background_color};`;
  if(e.font_family)s+=`font-family:'se-${e.font_family}',inherit;`;
  if(e.font_size)s+=`font-size:${e.font_size}px;`;
  if(e.bold)s+='font-weight:700;';
  return s;}
// 구분선 종류(1~8) → 미리보기 모양. DIVIDER_META 순서와 맞춤(가는선/실선/굵은짧은선/꺾인선/다이아몬드/점선/사선/세로선)
function dividerHTML(b){const v=b.variant||1;
  if(v===2)return '<hr class=solid>';
  if(v===3)return '<hr class=bar>';
  if(v===6)return '<hr class=dash>';
  if(v===8)return '<hr class=vert>';
  const g={4:'﹀',5:'◆',7:'╱'}[v];  // ﹀ ◆ ╱
  if(g)return `<div class=dv><span class=g>${g}</span></div>`;
  return '<hr>';}  // v1 기본 가는 선
function renderText(b){let h=esc(b.text);
  (b.emphases||[]).forEach(e=>{
    h=h.replace(esc(e.text),`<em class=hl style="${emStyle(e)}">${esc(e.text)}</em>`);});
  return `<p class=tx style="${alignStyle(b)}">${h}</p>`;}
function checklistHTML(cl){
  if(!cl||!cl.length)return '';
  const bad=cl.filter(c=>!c.ok);
  if(!bad.length)return `<div class=ckok>✓ 자동 체크 ${cl.length}건 통과</div>`;
  return `<div class=ckbad><b>자동 체크 미충족 ${bad.length}건</b> — 게시 전 확인하세요`+
    bad.map(c=>`<div class=cki>✗ ${esc(c.item)}${c.detail?` <small>${esc(c.detail)}</small>`:''}</div>`).join('')+`</div>`;
}
function renderPreview(d){
  let h=checklistHTML(d.checklist)+`<h1>${esc(d.title)||'(제목 없음)'}</h1>`;
  // 발행 태그는 본문이 아니라 네이버 발행 창의 태그칸으로 들어가 눈에 안 보인다 —
  // 뭐가 들어가는지 항상 맨 위에서 보이게 하고, 비었거나 마음에 안 들면 여기서 직접 고친다.
  h+=`<div class=ph>🏷 발행 태그(태그칸 자동 입력 — 직접 수정 가능)
    <input id=tagedit value="${esc((d.tags||[]).map(t=>'#'+t).join(' ')).replace(/"/g,'&quot;')}"
      placeholder="#태그 #띄어쓰기로 #구분 — 비우면 태그칸에 아무것도 안 넣어요" spellcheck=false
      style="display:block;width:100%;margin-top:6px;padding:2px 0;border:none;border-bottom:1px dashed #9ec5ff;background:transparent;font:inherit;color:inherit;outline:none"></div>`;
  for(const b of d.blocks){
    if(b.kind==='text')h+=renderText(b);
    else if(b.kind==='divider')h+=dividerHTML(b);
    else if(b.kind==='quote'){const qc={1:'q-quote',2:'q-line',3:'q-bubble',4:'q-underline',5:'q-postit',6:'q-corner'}[b.variant]||'q-quote';
      h+=`<div class="q ${qc}" style="${alignStyle(b)}">${esc(b.text)}</div>`;}
    else if(b.kind==='sticker')h+=`<img class=st src="/img?ref=${encodeURIComponent(b.sticker_ref)}">`;
    else if(b.kind==='image')h+=PVIMG
      ?`<figure class=pvph><img loading=lazy src="/photo?path=${encodeURIComponent(b.image_path)}"><figcaption>🖼 ${esc(b.image_label)}</figcaption></figure>`
      :`<div class=ph>🖼 ${esc(b.image_label)} <small>${esc(b.image_path)}</small></div>`;
    else if(b.kind==='video')h+=`<div class=ph>🎬 동영상 ${esc(b.image_label)} <small>${esc(b.image_path)}</small></div>`;
    else if(b.kind==='link')h+=`<div class=ph>🔗 링크 카드 <small>${esc(b.link_url)}</small></div>`;
    else if(b.kind==='place')h+=`<div class=ph>📍 지도(장소) <small>${esc(b.text)}</small></div>`;
    else if(b.kind==='table')h+=tableHTML(b);
  }
  const p=$('#preview'); p.classList.remove('empty'); p.innerHTML=h;
}
// 발행 태그 직접 수정: 입력값 → PLAN.tags(발행 요청에 실어 서버 플랜에 덮어씀).
// setAttribute로 value '속성'도 갱신 — 탭 전환은 innerHTML 스냅샷이라 속성에 남아야 복원된다.
function parseTags(v){const out=[];for(const t of v.split(/[#,\s]+/)){const c=t.trim();if(c&&!out.includes(c))out.push(c);}return out.slice(0,30);} // ponytail: 네이버 태그칸 상한 30개
// 미리보기 사진 표시 온오프 — 기본 켬, 전 탭 공통(localStorage). 끄면 경로 플레이스홀더로.
let PVIMG=localStorage.getItem('pvimg')!=='0';
$('#pvimg').checked=PVIMG;
$('#pvimg').onchange=e=>{PVIMG=e.target.checked;localStorage.setItem('pvimg',PVIMG?'1':'0');if(PLAN)renderPreview(PLAN);};
$('#preview').addEventListener('input',e=>{
  if(e.target.id!=='tagedit')return;
  e.target.setAttribute('value',e.target.value);
  if(PLAN)PLAN.tags=parseTags(e.target.value);
});
function tableHTML(b){
  const rows=b.table_rows||[]; if(!rows.length)return '';
  const tr=rows.map((r,i)=>'<tr>'+r.map(c=>`<${i?'td':'th'}>${esc(c)}</${i?'td':'th'}>`).join('')+'</tr>').join('');
  return `<table class=doctbl>${tr}</table>`;
}
function showLog(dbg){
  const raw=dbg.raw||'';
  const cnt=(re)=>(raw.match(re)||[]).length;
  const flags=`<div class=logflags>
    <span class="lf ${raw.includes('<<')?'ok':'no'}">강조마킹 &lt;&lt; ${raw.includes('<<')?'있음':'없음'}</span>
    <span class="lf ${cnt(/\[구분선/g)?'ok':'no'}">구분선 ${cnt(/\[구분선/g)}</span>
    <span class="lf ${cnt(/\[인용구\]/g)?'ok':'no'}">인용구 ${cnt(/\[인용구\]/g)}</span>
    <span class="lf ${cnt(/\[스티커/g)?'ok':'no'}">스티커 ${cnt(/\[스티커/g)}</span>
    <span class=lf>줄바꿈 ${cnt(/\n/g)}</span>
    <span class=lf>모델 ${dbg.model||'기본'}</span></div>`;
  $('#logbody').innerHTML=flags
    +'<div class=sub-h>모델 원본 출력 (후처리 전)</div><pre class=logpre>'+esc(raw)+'</pre>'
    +'<details><summary class=logsum>시스템 프롬프트 전체 보기</summary><pre class=logpre>'+esc(dbg.system||'')+'</pre></details>'
    +'<details><summary class=logsum>유저 프롬프트(재료) 보기</summary><pre class=logpre>'+esc(dbg.user||'')+'</pre></details>';
  $('#logbox').style.display='block';
}
// 카테고리: 자리 차지 않게 작은 버튼+팝오버. 고른 값(CATEGORY)은 기억(prefs).
function setCategory(name){CATEGORY=name||'';
  $('#catlabel').textContent=CATEGORY||'선택 안 함';}
function fillCategories(cats){
  const opts='<div class="catopt'+(CATEGORY?'':' on')+'" data-v="">— 선택 안 함 —</div>'+cats.map(c=>
    `<div class="catopt${c.name===CATEGORY?' on':''}" data-v="${esc(c.name)}">${'　'.repeat(c.depth||0)}${c.depth?'└ ':''}${esc(c.name)}</div>`).join('');
  $('#catlist').innerHTML=opts;}
async function loadCategories(){try{const d=await (await fetch('/api/categories')).json();
  if(d.categories&&d.categories.length){fillCategories(d.categories); $('#catstat').textContent=`저장된 ${d.categories.length}개 · 갱신하려면 [네이버에서 불러오기]`;}
}catch(e){}}
function catpopOpen(on){$('#catpop').style.display=on?'flex':'none';}
$('#catbtn').onclick=e=>{e.stopPropagation(); catpopOpen($('#catpop').style.display==='none');};
$('#catpop').onclick=e=>e.stopPropagation();
document.addEventListener('click',()=>catpopOpen(false));
$('#catlist').onclick=e=>{const o=e.target.closest('.catopt'); if(!o)return;
  setCategory(o.dataset.v);
  $$('#catlist .catopt').forEach(x=>x.classList.toggle('on',x===o));
  catpopOpen(false); savePrefs();};
$('#catload').onclick=async()=>{
  $('#catload').disabled=true;
  const el=elapsed('네이버에서 카테고리 불러오는 중…', spinRow($('#catstat')));
  try{const r=await fetch('/api/categories',{method:'POST'}); const d=await r.json();
    if(!r.ok){throw new Error(d.error||'알 수 없는 오류');}
    const sec=el.stop();
    fillCategories(d.categories); $('#catstat').textContent=`카테고리 ${d.categories.length}개 불러와 저장됨 (${sec}초)`; toast(`카테고리 ${d.categories.length}개를 불러와 저장했어요.`,'ok');
  }catch(e){el.stop(); $('#catstat').textContent='실패'; toast('카테고리 불러오기 실패 — '+e.message,'err');}finally{$('#catload').disabled=false;}
};
// 임시저장은 '쏘고 넘어가는' 방식 — 누르면 상단 탭바에 '작업 탭'을 만들어 백그라운드로 보내고,
// 바로 새 글로 갈지 묻는다. 연속으로 눌러도 막지 않고 탭이 쌓이며, 서버가 한 건씩 순서대로
// 처리한다(대기열). 저장이 실패하면 그 탭이 빨갛게 남아 ↻로 다시 시도할 수 있다 — 이미 다음
// 글로 넘어갔어도 서버가 그 글의 스냅샷을 들고 있어 '그 글'을 다시 저장한다.
let SAVE_QUEUE=0;  // 진행 중/대기 중인 임시저장 건수
function updateSaveHint(){
  if(SAVE_QUEUE>0) st(`백그라운드 임시저장 ${SAVE_QUEUE}건 진행 중… 다른 작업 계속하셔도 돼요.`);
}
const SAVES={};  // 작업 탭: id → {id,title,el,timer,serverId,body}
function makeSaveTab(id,title){
  const el=document.createElement('div'); el.className='stab run'; el.dataset.id=id;
  el.innerHTML='<span class=sdot><span class=spin></span></span>'
    +'<span class=stitle></span><span class=scnt></span>'
    +'<button class=sretry title="다시 시도">↻</button>'
    +'<button class=sx title="닫기">✕</button>';
  el.querySelector('.stitle').textContent="'"+title+"' 임시저장";
  el.querySelector('.sretry').onclick=()=>retrySave(id);
  el.querySelector('.sx').onclick=()=>removeSave(id);
  $('#savebar').appendChild(el);
  return el;
}
function removeSave(id){const r=SAVES[id]; if(!r)return;
  if(r.timer){r.timer.stop(); r.timer=null;}
  if(r.el){r.el.classList.add('out'); setTimeout(()=>r.el.remove(),200);}
  delete SAVES[id];}
// 탭 상태 전환. run이면 스피너, 그 외엔 상태 글자(✓ / ⚠ / !).
function tabSetState(r,cls,dot){
  r.el.className='stab '+cls;
  r.el.querySelector('.sdot').innerHTML = cls==='run' ? '<span class=spin></span>' : dot;
}
function retrySave(id){const r=SAVES[id]; if(!r)return;
  if(!r.serverId){ toast('이 글은 다시 시도할 수 없어요 — 글을 다시 열어 저장해 주세요.','err'); return; }
  runSave(r, r.serverId);}
// 실제 저장 요청. retryId가 있으면 서버가 그 작업의 스냅샷을 그대로 다시 저장한다.
function runSave(r, retryId){
  tabSetState(r,'run','');
  const cntEl=r.el.querySelector('.scnt'); cntEl.textContent='';
  if(r.timer)r.timer.stop();
  r.timer=elapsed('', (lbl,counter,s)=>{ cntEl.textContent=(s<10?s.toFixed(1):Math.round(s))+'초'; });
  SAVE_QUEUE++; updateSaveHint();
  const body = retryId ? {retryJob:retryId} : r.body;
  fetch('/api/publish',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)})
    .then(async res=>{
      const d=await res.json().catch(()=>({}));
      if(d && d.jobId) r.serverId=d.jobId;         // 실패 응답에도 jobId가 실려와 재시도가 가능
      if(!res.ok) throw new Error(d.error||'알 수 없는 오류');
      const sec=r.timer?r.timer.stop():0; r.timer=null;
      const warns=d.warnings||[], infos=d.infos||[];  // infos=정상 동작 안내(확인 불필요)
      if(warns.length){
        tabSetState(r,'warn','⚠'); cntEl.textContent='확인 필요';
        const wTitle=`'${r.title}' 임시저장됨 — 일부 항목 확인 필요`;
        const wItems=warns.concat(['네이버 글쓰기 › 저장 목록에서 글을 열어 직접 보완해 주세요.']);
        warnModal(wTitle, wItems);
        warnLogAdd(r.title, wItems);  // 실수로 닫아도 ⚠ 기록 칩에서 다시 봄
        // ⚠ 탭 자체를 눌러도 그 글의 안내를 다시 띄운다(✕·↻ 버튼 제외).
        r.el.style.cursor='pointer';
        r.el.onclick=e=>{ if(e.target.closest('button'))return; warnModal(wTitle, wItems); };
        notify('임시저장 완료 — 확인 필요', warns.join('\n'));
      }else{
        tabSetState(r,'ok','✓'); cntEl.textContent=`${sec}초`;
        toast(`'${r.title}' 임시저장 완료 ✓ (${sec}초) — 네이버 글쓰기 › 저장 목록`,'ok');
        notify('임시저장 완료 ✓', `'${r.title}' — 네이버 글쓰기 › 저장 목록`);
        setTimeout(()=>removeSave(r.id), 4000);    // 성공 탭은 잠깐 ✓ 후 사라짐
      }
      if(infos.length) infos.forEach(m=>toast(m,'info'));
    })
    .catch(e=>{ if(r.timer){r.timer.stop(); r.timer=null;}
      tabSetState(r,'err','!'); cntEl.textContent='실패';
      toast(`'${r.title}' 임시저장 실패 — ${e.message}`,'err'); notify('임시저장 실패', e.message||''); })
    .finally(()=>{ SAVE_QUEUE--; updateSaveHint(); if(SAVE_QUEUE===0) st('임시저장 대기열이 모두 끝났어요 ✓'); });
}
// 한 건을 백그라운드로 게시. 지금 화면 상태와 무관하게 '누른 그 글'을 저장한다
// (제목·카테고리·불러온 원본은 클릭 시점 값으로 고정해 넘긴다).
// --- 발행 방식(임시저장만 / 예약발행) ---
// 예약발행은 시간차를 둬 연속 도배를 막는다(네이버 네이티브 예약 사용). 기본 예약 시각은
// '마지막 예약 + 2시간'(없으면 지금 + 1시간)으로 자동 벌려 준다 — 유저는 바꿔도 됨.
function pad2(n){return String(n).padStart(2,'0');}
function toLocalInput(d){return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;}
function nextReserveDefault(){
  const now=Date.now();
  const last=parseInt(localStorage.getItem('lastReservedAt')||'0',10)||0;
  let t=Math.max(now+60*60*1000, last+2*60*60*1000);  // 지금+1h 또는 마지막예약+2h 중 뒤
  const d=new Date(t); d.setMinutes(Math.ceil(d.getMinutes()/10)*10,0,0);  // 10분 단위 올림
  return d;
}
function pubModeChanged(){
  const mode=$('#pubmode').value, at=$('#reserveat'), hint=$('#reservehint'), btn=$('#save');
  if(mode==='reserve'){
    at.style.display=''; hint.style.display='';
    if(!at.value) at.value=toLocalInput(nextReserveDefault());
    at.min=toLocalInput(new Date(Date.now()+5*60*1000));
    btn.textContent='예약발행';
    if(RESERVE_READY){ hint.className='reservehint'; hint.textContent='설정한 시각에 네이버가 발행해요. 글마다 시간을 벌리면 연속 도배를 막을 수 있어요.'; }
    else{ hint.className='reservehint warn'; hint.textContent='⚠ 예약발행은 최초 1회 설정이 필요해요 — 지금 누르면 임시저장만 되고 예약은 건너뛰어요. (셋업 전까지는 임시저장 후 네이버에서 직접 예약)'; }
  }else{
    at.style.display='none'; hint.style.display='none'; btn.textContent='임시저장';
  }
}
$('#pubmode').onchange=pubModeChanged;
function fireSave(title, category){
  const id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
           : ('s'+Date.now()+'-'+Math.round(Math.random()*1e6));
  // 불러온 글이면 그 글을 'in-place'로 갱신(원본 삭제 X, 사진 재업로드 X, 영상 보존).
  // 일반 새 글이면 importedDraft 없음 → 기존 방식(새 글 저장). 값은 지금 시점으로 고정.
  const inplace=!!IMPORTED_DRAFT, inplaceDraft=IMPORTED_DRAFT;
  // 예약발행이면 예약 시각(로컬 naive)을 실어 보낸다. 예약은 in-place가 아닌 새 글에만.
  let reserveAt=null;
  if($('#pubmode').value==='reserve' && !inplace){
    reserveAt=($('#reserveat').value||'').trim()||null;
    if(reserveAt) localStorage.setItem('lastReservedAt', String(new Date(reserveAt).getTime()));
  }
  const r=SAVES[id]={id,title,el:makeSaveTab(id,title),timer:null,serverId:null,reserved:!!reserveAt,
    // draftId=지금 탭 → 서버가 '그 탭 글'을 저장. photoMeta=지금 시점 ★ 대표·AI 표시 —
    // 플랜 생성 뒤 AI 썸네일 적용·사진 대체를 해도 발행에 반영되게 서버가 플랜에 덧입힌다.
    body:{category,inplace,inplaceDraft,draftId:CURWS,reserveAt,photoMeta:photoMetaForSel(),
      tags:(PLAN&&PLAN.tags||[]).slice()}};  // 미리보기에서 고친 발행 태그(클릭 시점 값 고정)
  runSave(r, null);
}
$('#save').onclick=()=>{
  if(!PLAN)return;
  ensureNotify();  // 유저 클릭(제스처) 시점에 알림 권한 요청 — 자리 비워도 결과 알림 받게
  const title=PLAN.title||'제목 없음';
  const reserve=$('#pubmode').value==='reserve' && !IMPORTED_DRAFT;
  if(reserve){
    const v=($('#reserveat').value||'').trim();
    if(!v){ toast('예약 시각을 선택하세요','info'); return; }
    if(new Date(v).getTime() <= Date.now()){ toast('예약 시각은 미래여야 해요','info'); return; }
  }
  // 1) 저장을 즉시 백그라운드 대기열로 보낸다(기다리지 않음).
  fireSave(title, CATEGORY);
  // 2) 같은 글 중복 저장 방지 — 다음 [초안 생성]/[받아온 글]에서 다시 활성화된다.
  $('#save').disabled=true;
  // 3) 바로 "새 글 쓸까요?" 확인 — 확인하면 새 탭을 연다(이 글 탭은 그대로 남음).
  const startMsg=reserve?'예약발행을 시작했어요':'임시저장을 시작했어요';
  confirmModal(startMsg,
    '저장은 뒤에서 진행돼요. 새 글을 작성할까요?<br><span style="color:var(--sub)">새 탭이 열려요 · 이 글 탭은 그대로 남습니다.</span>',
    '새 글 작성', '이 글 유지', doNewPost, null, '📝');
};

// 스티커 탭
let CAT=null, ST_FILTER='fav', ST_Q='', ST_QT=null;
async function loadStickers(force){
  if(CAT && !force){renderStickers();return;}
  try{CAT=await (await fetch('/api/catalog')).json(); renderStickers();}
  catch(e){$('#stbody').innerHTML='<div class=muted>스티커 로드 실패</div>';}
}
function updateStat(){if(!CAT)return;
  $('#ststat').innerHTML=`<div class=b><div class=n>${CAT.total}</div><div class=l>전체</div></div>
    <div class=b><div class=n>${CAT.favorites.length}</div><div class=l>⭐ 즐겨찾기</div></div>
    <div class=b><div class=n>${CAT.label_count}</div><div class=l>상황 라벨</div></div>`;}
function renderStickers(){
  if(!CAT)return;
  updateStat();
  $('#hidedef').classList.toggle('on',!!FMT.hideDefault);
  $('#stickerall').classList.toggle('on',!!FMT.stickerAll);
  const favset=new Set(CAT.favorites);
  const defset=new Set(CAT.default_packs||[]);
  let list=CAT.stickers;
  if(ST_FILTER==='fav') list=list.filter(s=>favset.has(s.ref));
  if(FMT.hideDefault) list=list.filter(s=>!defset.has(s.pack)||favset.has(s.ref));
  if(ST_Q) list=list.filter(s=>(s.pack||'').toLowerCase().includes(ST_Q)||(s.tags||[]).some(t=>(t||'').toLowerCase().includes(ST_Q)));
  const body=$('#stbody');
  if(!list.length){body.innerHTML=`<div class=muted>${ST_Q?'검색에 맞는 스티커가 없어요 — 다른 태그·팩 이름으로 찾아보세요.':ST_FILTER==='fav'?'아직 즐겨찾기가 없어요. [전체 둘러보기]에서 ★를 눌러 추가하세요.':'스티커가 없어요. 터미널에서 autoblog stickers pull'}</div>`;return;}
  const packs={};
  list.forEach(s=>{(packs[s.pack]=packs[s.pack]||[]).push(s);});
  let h='';
  for(const pack of Object.keys(packs)){
    h+=`<div class=packh>${pack} <small>(${packs[pack].length})</small></div><div class=stgrid>`;
    for(const s of packs[pack]){const on=favset.has(s.ref);
      h+=`<div class=stcard><button class="favbtn${on?' on':''}" data-ref="${s.ref}" title="즐겨찾기">★</button>
        <img loading=lazy src="/img?ref=${encodeURIComponent(s.ref)}">
        ${ksegHtml(s)}${tagsHtml(s)}</div>`;}
    h+='</div>';
  }
  body.innerHTML=h;
}
function tagsHtml(s){return `<div class=tags2 data-ref="${s.ref}">`
  +(s.tags||[]).map(t=>`<span class=tg2>${esc(t)}<span class=x data-t="${esc(t)}">×</span></span>`).join('')
  +`<input class=taginput placeholder="+태그"></div>`;}
// 분류 세그먼트(감정/구분선/헤더) — 상단 안내(kguide)의 동작 설명과 짝
function ksegHtml(s){return `<div class=kseg data-ref="${s.ref}" title="스티커 분류">`
  +['감정','구분선','헤더'].map(k=>`<button class="${s.kind===k?'on':''}" data-k="${k}">${k}</button>`).join('')
  +`</div>`;}
function stickerOf(ref){return CAT.stickers.find(z=>z.ref===ref);}
async function saveTags(s){try{const r=await (await fetch('/api/sticker-tags',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({ref:s.ref,tags:s.tags})})).json();
  if(r&&r.kind){s.kind=r.kind; redrawKseg(s);}  // 태그 편집(예: '헤더' 칩 삭제)이 분류를 바꿀 수 있음
  }catch(e){}}
function redrawTags(wrap){const s=stickerOf(wrap.dataset.ref); if(s)wrap.outerHTML=tagsHtml(s);}
function redrawKseg(s){const w=document.querySelector(`.kseg[data-ref="${CSS.escape(s.ref)}"]`);
  if(w)w.querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.k===s.kind));}
$('#stfilter').onclick=e=>{const b=e.target.closest('button'); if(!b)return;
  $$('#stfilter button').forEach(x=>x.classList.remove('on')); b.classList.add('on');
  ST_FILTER=b.dataset.f; renderStickers();};
// 기본(네이버 제공) 이모티콘 숨기기 토글
$('#hidedef').onclick=function(){FMT.hideDefault=!FMT.hideDefault;
  this.classList.toggle('on',FMT.hideDefault); savePrefs(); renderStickers();};
// 태그·팩 이름 검색(150ms 디바운스 — 타자마다 그리드 전체를 다시 그리지 않게)
$('#stsearch').oninput=e=>{clearTimeout(ST_QT);
  ST_QT=setTimeout(()=>{ST_Q=e.target.value.trim().toLowerCase(); renderStickers();},150);};
// 태그 칩 삭제(×)
$('#stbody').addEventListener('click', e=>{const x=e.target.closest('.x'); if(!x)return;
  const wrap=x.closest('.tags2'); const s=stickerOf(wrap.dataset.ref); if(!s)return;
  s.tags=(s.tags||[]).filter(t=>t!==x.dataset.t); redrawTags(wrap); saveTags(s);});
// 분류 버튼(감정/구분선/헤더) — 서버가 태그 마커('헤더'/'구분선')를 갈아끼우고 결과를 돌려준다
$('#stbody').addEventListener('click', async e=>{
  const b=e.target.closest('.kseg button'); if(!b)return;
  const s=stickerOf(b.closest('.kseg').dataset.ref); if(!s||s.kind===b.dataset.k)return;
  try{
    const r=await (await fetch('/api/sticker-kind',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({ref:s.ref,kind:b.dataset.k})})).json();
    if(!r.ok)return;
    s.kind=r.kind; s.tags=r.tags; redrawKseg(s);
    const tw=document.querySelector(`.tags2[data-ref="${CSS.escape(s.ref)}"]`); if(tw)redrawTags(tw);
  }catch(err){}
});
// 태그 추가(엔터)
$('#stbody').addEventListener('keydown', e=>{
  if(!e.target.classList.contains('taginput')||e.key!=='Enter'||e.isComposing||e.keyCode===229)return;
  e.preventDefault(); const wrap=e.target.closest('.tags2'); const s=stickerOf(wrap.dataset.ref);
  const v=e.target.value.trim(); if(!s||!v)return;
  if(!(s.tags||[]).includes(v)){s.tags=(s.tags||[]).concat(v);} redrawTags(wrap);
  const ni=wrap.querySelector('.taginput'); if(ni)ni.focus(); saveTags(s);});
// 태그 분석(즐겨찾기만, 백그라운드 진행)
$('#lblbtn').onclick=async()=>{
  $('#lblbtn').disabled=true; $('#lblstat').textContent='시작 중…';
  try{
    const d=await (await fetch('/api/label',{method:'POST'})).json();
    if(!d.total){$('#lblstat').textContent='분석할 새 즐겨찾기가 없어요(이미 태그 있음).'; $('#lblbtn').disabled=false; return;}
    pollLabel();
  }catch(e){$('#lblstat').textContent='오류: '+e; $('#lblbtn').disabled=false;}
};
async function pollLabel(){
  const s=await (await fetch('/api/label/status')).json();
  $('#lblstat').textContent=`분석 중… ${s.done}/${s.total} (스티커당 수 초)`;
  if(s.running){setTimeout(pollLabel,1500);}
  else{$('#lblstat').textContent=`완료 ✓ 태그 ${s.done}개 분석`; $('#lblbtn').disabled=false; await loadStickers(true);}
}
$('#stbody').onclick=async e=>{const b=e.target.closest('.favbtn'); if(!b)return;
  const ref=b.dataset.ref, on=!b.classList.contains('on');
  b.classList.toggle('on',on);
  CAT.favorites=CAT.favorites.filter(r=>r!==ref); if(on)CAT.favorites.push(ref);
  updateStat();
  if(ST_FILTER==='fav' && !on) b.closest('.stcard').remove();  // 즐겨찾기 보기에선 해제 시 사라짐
  try{await fetch('/api/favorite',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({ref,on})});}
  catch(e){}
};
// 스티커 전체 사용 토글(끄면 즐겨찾기만) — 글쓰기에서 쓰던 걸 스티커 탭에서 관리
$('#stickerall').onclick=function(){FMT.stickerAll=!FMT.stickerAll;
  this.classList.toggle('on',FMT.stickerAll); savePrefs();};

// 글쓰기 설정(규칙·협찬·톤·카테고리) 서버 저장/복원 — 새로고침해도 유지
// personaId는 '고른 적 없음'(빈값)과 '기본 어투를 직접 고름'('default')을 구분해 저장 —
// 고른 적 없는 사용자만 내 문체 자동 선택 대상이 된다.
let PREFS_LOADED=false, PERSONA_PICKED=false;
async function savePrefs(){try{await fetch('/api/prefs',{method:'POST',headers:{'content-type':'application/json'},
  body:JSON.stringify({rules:RULES,fmt:FMT,tone:$('#tone').value,personaId:PERSONA_PICKED?(PERSONA_ID||'default'):PERSONA_ID,minChars:$('#minchars').value,category:CATEGORY,pruneDrafts:PRUNE,saveDebug:SAVEDBG,cleanImported:CLEANIMP,markAiImages:MARKAI})});}catch(e){}}
// 내 문체가 있는데 아직 아무 문체도 고른 적 없으면 첫 번째 내 문체를 기본 선택
function autoPickPersona(){
  if(!PREFS_LOADED||PERSONA_PICKED||PERSONA_ID||!PERSONAS.length)return;
  PERSONA_ID=PERSONAS[0].id; PERSONA_PICKED=true;
  const sel=$('#persona'); if(sel)sel.value=PERSONA_ID;
  savePrefs();
}
async function loadPrefs(){
  let asked=true;
  try{const p=await (await fetch('/api/prefs')).json();
    if(p.rules)Object.assign(RULES,p.rules);
    if(p.fmt)Object.assign(FMT,p.fmt);
    if(typeof p.tone==='string')$('#tone').value=p.tone;
    if(typeof p.personaId==='string'){PERSONA_PICKED=(p.personaId!=='');
      PERSONA_ID=(p.personaId==='default')?'':p.personaId;
      const sel=$('#persona'); if(sel)sel.value=PERSONA_ID;}
    if(p.minChars!=null)$('#minchars').value=p.minChars;
    if($('#tone').value||$('#minchars').value)$('#moreopts').open=true;  // 저장된 값이 있으면 접힌 세부 옵션을 펼쳐 보여줌
    if(typeof p.category==='string')setCategory(p.category);
    if(typeof p.pruneDrafts==='boolean')PRUNE=p.pruneDrafts;
    if(typeof p.saveDebug==='boolean')SAVEDBG=p.saveDebug;
    if(typeof p.cleanImported==='boolean')CLEANIMP=p.cleanImported;
    if(typeof p.markAiImages==='boolean')MARKAI=p.markAiImages;
    asked=!!p.pruneDraftsAsked;
  }catch(e){}
  PREFS_LOADED=true; autoPickPersona();  // 문체 목록이 먼저 로드돼 있으면 여기서 자동 선택
  renderRules(); renderDraftSet(); renderCleanImp(); renderAiMark(); renderSaveDebug(); applyFmtState();
  if(!asked)askPrune();  // 최초 1회만: 자동 정리 켤지 물어봄
}
// 저장된 협찬/스티커 상태를 토글 UI에 반영(서식 칩은 제거됨)
function applyFmtState(){
  $('#sponsw').classList.toggle('on',!!FMT.sponsored);
  $('#sponbox').style.display=FMT.sponsored?'block':'none';
  if(FMT.sponsored)loadSponPicker();
  $('#stickerall').classList.toggle('on',!!FMT.stickerAll);
}

// 설정
function renderRules(){const c=$('#rules'); c.innerHTML='';
  RULE_META.forEach(([k,t,d])=>{const row=document.createElement('div'); row.className='setrow';
    row.innerHTML=`<div><div class=t>${t}</div><div class=d>${d}</div></div><div class="sw ${RULES[k]?'on':''}"></div>`;
    row.querySelector('.sw').onclick=function(){RULES[k]=!RULES[k]; this.classList.toggle('on',RULES[k]); savePrefs();};
    c.appendChild(row);});
}
// 임시저장 정리 토글(설정)
function renderDraftSet(){const c=$('#draftset'); if(!c)return; c.innerHTML='';
  const row=document.createElement('div'); row.className='setrow';
  row.innerHTML=`<div><div class=t>이전 임시저장 자동 정리</div>
    <div class=d>새 글을 임시저장하면 <b>같은 제목</b>의 이전 임시저장 글을 삭제해 최신 1건만 남겨요. (네이버 임시저장 삭제는 복구 불가)</div></div>
    <div class="sw ${PRUNE?'on':''}"></div>`;
  row.querySelector('.sw').onclick=function(){PRUNE=!PRUNE; this.classList.toggle('on',PRUNE); savePrefs();};
  c.appendChild(row);
}
// 불러오기(in-place): 기존 글의 제목·본문·장식을 비우고 새로 작성(설정)
function renderCleanImp(){const c=$('#cleanimp'); if(!c)return; c.innerHTML='';
  const row=document.createElement('div'); row.className='setrow';
  row.innerHTML=`<div><div class=t>불러온 글 비우고 새로 쓰기</div>
    <div class=d>글을 <b>불러와</b> 이어 쓸 때, 기존 <b>제목·본문 글·스티커·지도·링크카드</b>는 지우고 새 내용으로 다시 써요. <b>사진·동영상은 그대로</b> 두고요. 끄면 기존 본문·장식을 남긴 채 사진 사이에 본문만 끼워 넣어요.</div></div>
    <div class="sw ${CLEANIMP?'on':''}"></div>`;
  row.querySelector('.sw').onclick=function(){CLEANIMP=!CLEANIMP; this.classList.toggle('on',CLEANIMP); savePrefs();
    toast(CLEANIMP?'불러온 글의 기존 제목·본문·장식은 지우고 새로 작성할게요.':'불러온 글의 기존 본문·장식을 그대로 두고 작성할게요.','info');};
  c.appendChild(row);
}
// AI 활용 표시: AI로 만든 이미지(FLUX 썸네일 등)에 네이버 'AI 활용' 아이콘을 켠다(자율 표기)
function renderAiMark(){const c=$('#aimark'); if(!c)return; c.innerHTML='';
  const row=document.createElement('div'); row.className='setrow';
  row.innerHTML=`<div><div class=t>AI 이미지에 'AI 활용' 표시</div>
    <div class=d><b>AI로 만든 이미지</b>(🎨 AI 썸네일·🔁 외부 AI 대체)에 네이버 <b>'AI 활용'</b> 아이콘을 자동으로 켜요. 지금은 <b>자율 표기</b>라 안 켜도 노출 불이익은 없지만, 나중 AI 탐지 강화 대비 보험이에요. 실사진은 대상이 아니에요.</div></div>
    <div class="sw ${MARKAI?'on':''}"></div>`;
  row.querySelector('.sw').onclick=function(){MARKAI=!MARKAI; this.classList.toggle('on',MARKAI); savePrefs();
    toast(MARKAI?"AI로 만든 이미지에 'AI 활용' 표시를 켤게요.":"'AI 활용' 표시를 끌게요.",'info');};
  c.appendChild(row);
}
// 디버그: 임시저장 과정을 화면에 띄워 직접 본다(headful 브라우저)
function renderSaveDebug(){const c=$('#savedebug'); if(!c)return; c.innerHTML='';
  const row=document.createElement('div'); row.className='setrow';
  row.innerHTML=`<div><div class=t>임시저장 과정 직접 보기 <span class=muted style="font-weight:400">(디버그)</span></div>
    <div class=d>임시저장 시 브라우저 창을 <b>화면에 띄워</b> 입력·저장 과정을 눈으로 봐요. 평소엔 꺼두면 백그라운드(숨김)로 조용히 처리돼요.</div></div>
    <div class="sw ${SAVEDBG?'on':''}"></div>`;
  row.querySelector('.sw').onclick=function(){SAVEDBG=!SAVEDBG; this.classList.toggle('on',SAVEDBG); savePrefs();
    toast(SAVEDBG?'다음 임시저장부터 브라우저 창을 띄워 보여줄게요.':'임시저장을 다시 백그라운드(숨김)로 처리할게요.','info');};
  c.appendChild(row);
}
// 최초 1회: 자동 정리를 켤지 물어본다(기본 켬). 어떤 선택이든 asked=true로 다시 안 묻는다.
function askPrune(){
  const apply=(on)=>{PRUNE=on; renderDraftSet();
    fetch('/api/prefs',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({pruneDrafts:on,pruneDraftsAsked:true})}).catch(()=>{});
    toast(on?'이전 임시저장 자동 정리를 켰어요. (설정에서 끌 수 있어요)':'자동 정리는 꺼둘게요. (설정에서 켤 수 있어요)','ok');};
  confirmModal('이전 임시저장 글을 자동으로 정리할까요?',
    '앞으로 새 글을 임시저장할 때마다, <b>같은 제목</b>의 이전 임시저장 글을 삭제해 최신 1건만 남겨둬요.<br>서로 다른 글은 건드리지 않고, 삭제는 복구되지 않아요. 설정에서 언제든 끌 수 있어요.',
    '네, 자동 정리','아니요',()=>apply(true),()=>apply(false));
}
// provider별 메타: 라벨·키 발급처·플레이스홀더
const PROV={
  anthropic:{name:'Claude API',short:'Claude',color:'#7b61ff',ph:'sk-ant-...',issuer:'console.anthropic.com › API Keys'},
  openai:{name:'OpenAI API',short:'OpenAI',color:'#10a37f',ph:'sk-...',issuer:'platform.openai.com › API keys'},
  gemini:{name:'Gemini API',short:'Gemini',color:'#1a73e8',ph:'AQ... 또는 AIza...',issuer:'aistudio.google.com › API keys'},
  nvidia:{name:'NVIDIA API',short:'NVIDIA',color:'#76b900',ph:'nvapi-...',issuer:'build.nvidia.com › API Keys',free:'https://build.nvidia.com/qwen/qwen3.5-397b-a17b'},
};
// 모델 표시명 — 코드명 대신 사람이 읽기 좋게(없으면 원본)
const MODELNAME={'claude-opus-4-8':'Opus 4.8','claude-sonnet-4-6':'Sonnet 4.6','gpt-4o':'GPT-4o','gemini-3.5-flash':'3.5 Flash',
  'nvidia/nemotron-3-super-120b-a12b':'Nemotron 3 Super','openai/gpt-oss-120b':'GPT-OSS 120B','meta/llama-3.3-70b-instruct':'Llama 3.3 70B'};
const nicer=v=>MODELNAME[v]||v;
// 선택 카드 한 장
function mcard(val,title,sub,active,miss){
  return `<div class="mcard${active?' on':''}${miss?' miss':''}" data-model="${val}">
    <div class=mc-t>${title}</div>${sub?`<div class=mc-s>${sub}</div>`:''}
    ${active?'<div class=mc-ck>✓ 사용 중</div>':''}</div>`;}
let MODEL_KEYS={}, API_TEXT=[], TEXT_MODEL='';  // 키 보유 여부/등록 텍스트 모델 — 문체 추출 모델 선택에도 씀
function provOf(model){const s=(model||'').toLowerCase();
  if(s.startsWith('claude'))return 'anthropic';
  if(s.startsWith('gemini'))return 'gemini';
  if(s.startsWith('gpt')||/^o[134]/.test(s))return 'openai';
  return 'unknown';}
// 모델 적용(텍스트/비전 독립) — 적용 후 새로고침해 '적용 중' 갱신
async function applyModel(payload, okmsg, btn){
  if(btn)btn.disabled=true;
  try{const r=await fetch('/api/models',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});
    if(r.ok){toast(okmsg,'ok'); await loadModels();} else toast('적용 실패','err');
  }catch(e){toast('적용 오류: '+e,'err');}finally{if(btn)btn.disabled=false;}}
// API 키 입력 박스(텍스트가 외부 API일 때)
function apiKeyBox(provider){
  const pv=PROV[provider]; const has=!!MODEL_KEYS[provider];
  return `<div class=sub-h style="margin-top:16px">${pv.short} API 키</div>
    <div class=muted style="margin-bottom:8px">${has?`등록됨 ✓ — 다시 입력하면 교체돼요.`:`이 모델을 쓰려면 키가 필요해요. <b>${pv.issuer}</b>에서 발급 → .env에 저장됩니다.`}${!has&&pv.free?` <a href="${pv.free}" target=_blank rel=noopener>여기서 무료로 발급받을 수 있어요 ↗</a>`:''}</div>
    <div style="display:flex;gap:8px">
      <input type=password id=apikey placeholder="${has?'키 등록됨 ✓ (교체하려면 입력)':pv.ph}" style="flex:1;border:1px solid #d6dade;border-radius:8px;padding:9px;font-size:13px">
      <button class=btn id=apikeysave data-prov="${provider}" style="width:auto;padding:9px 16px">저장</button>
    </div>`;
}
async function loadModels(){try{const m=await (await fetch('/api/models')).json();
  MODEL_KEYS=m.keys||{}; API_TEXT=m.api_text||[]; TEXT_MODEL=m.text||'';
  // ── 텍스트: 외부 API 카드(공급자별 묶음) ──
  const byProv={}; (m.api_text||[]).forEach(a=>{(byProv[a.provider]=byProv[a.provider]||[]).push(a);});
  const apiCards=Object.entries(byProv).map(([prov,list])=>{const pv=PROV[prov]||{short:prov}; const key=!!MODEL_KEYS[prov];
    return `<div class=mgroup>${pv.short} <span class="keychip ${key?'ok':'no'}">${key?'키 있음':'키 필요'}</span></div>
      <div class=mgrid>${list.map(a=>mcard(a.model, nicer(a.model), pv.short, a.model===m.text)).join('')}</div>`;}).join('');

  $('#models').innerHTML=`
    <h3>텍스트 모델 <span class=muted style="font-weight:400">— 초안 글 작성</span></h3>
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
      <span class=curpill><span class=cdot></span>적용 중 · ${m.text?nicer(m.text):'-'}${(PROV[m.text_provider]||{}).short?' ('+PROV[m.text_provider].short+')':''}</span>
      <span class=muted>카드를 누르면 바로 적용돼요.</span>
    </div>
    <div id=txtsection>${apiCards}</div>
    <div id=txtnote></div>
    <div id=apikeybox></div>

    <h3 style="margin-top:26px;padding-top:22px;border-top:1px solid var(--line)">비전 모델 <span class=muted style="font-weight:400">— 사진·상품 이미지 분석</span></h3>
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span class=curpill><span class=cdot></span>적용 중 · ${m.vision?nicer(m.vision):'-'}</span>
      <span class=muted>qwen3.5(NVIDIA)는 <b>NVIDIA_API_KEY</b>, gemini-*는 <b>GEMINI_API_KEY</b>가 필요해요.</span>
    </div>

    <h3 style="margin-top:26px;padding-top:22px;border-top:1px solid var(--line)">썸네일 모델 <span class=muted style="font-weight:400">— 🎨 AI 썸네일 (대표사진 → 손그림 감성)</span></h3>
    <div class=muted>비전 모델이 사진을 읽고 FLUX.1-dev(NVIDIA API)가 그려요. ${MODEL_KEYS.nvidia?'<b style="color:var(--green)">키 등록됨 ✓</b>':'<b>NVIDIA_API_KEY</b>가 필요해요 — <a href="https://build.nvidia.com/qwen/qwen3.5-397b-a17b" target=_blank rel=noopener>build.nvidia.com에서 무료 발급 ↗</a> 후 아래 저장.'}</div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <input type=password id=nvkey placeholder="${MODEL_KEYS.nvidia?'키 등록됨 ✓ (교체하려면 입력)':'nvapi-...'}" style="flex:1;border:1px solid #d6dade;border-radius:8px;padding:9px;font-size:13px">
      <button class=btn id=nvkeysave style="width:auto;padding:9px 16px">저장</button>
    </div>`;

  // 텍스트 적용 중 안내(API 키)
  function txtNote(){const prov=m.text_provider;
    $('#apikeybox').innerHTML = apiKeyBox(prov);
    const sv=$('#apikeysave'); if(sv)sv.onclick=()=>saveKey(prov);}
  txtNote();
  $('#nvkeysave').onclick=async()=>{const v=$('#nvkey').value.trim(); if(!v){toast('키를 입력하세요.','info');return;}
    const b=$('#nvkeysave'); b.disabled=true;
    try{const r=await fetch('/api/llm-key',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({provider:'nvidia',key:v})});
      if(r.ok){toast('NVIDIA 키 저장됨 ✓','ok'); await loadModels();} else toast('API 키 저장 실패','err');
    }catch(e){toast('API 키 오류: '+e,'err');}finally{const x=$('#nvkeysave'); if(x)x.disabled=false;}};
  $$('#txtsection [data-model]').forEach(c=>c.onclick=()=>{const v=c.dataset.model;
    if(v===m.text){toast('이미 쓰는 모델이에요.','info');return;}
    applyModel({text:v}, '텍스트 모델 적용됨 ✓');});
}catch(e){$('#models').innerHTML='<div class=muted>로드 실패</div>';}}
async function saveKey(provider){const v=$('#apikey').value.trim(); if(!v){toast('키를 입력하세요.','info');return;}
  const b=$('#apikeysave'); if(b)b.disabled=true;
  try{const r=await fetch('/api/llm-key',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({provider,key:v})});
    if(r.ok){MODEL_KEYS[provider]=true; toast(`${(PROV[provider]||{}).name||provider} 키 저장됨 ✓`,'ok'); await loadModels();}
    else toast('API 키 저장 실패','err');
  }catch(e){toast('API 키 오류: '+e,'err');}finally{const x=$('#apikeysave'); if(x)x.disabled=false;}}

function renderEmphasis(e){
  // 색마다 글자색·배경·폰트·크기를 직접 편집 + 드롭다운으로 갈래 선택(안 씀 / 강조 / 주의 …).
  const lanes=(e.lanes&&e.lanes.length?e.lanes:[{name:'강조'},{name:'주의'},{name:'부정'}]);
  const fonts=e.fonts||[{value:'',name:'기본'}], sizes=e.sizes||[];
  const card=s=>{
    const tc=s.text_color||'', bg=s.background_color||'';
    const hasStyle=tc||bg||s.font||s.size||s.bold;
    const stl=hasStyle?((tc?`color:${tc};`:'')+(bg?`background:${bg};`:'')+(s.bold?'font-weight:800;':'')+(s.font?`font-family:'se-${s.font}';`:'')+(s.size?`font-size:${s.size}px;`:'')):'color:#9aa5b1';
    const lane=s.tag||'';
    const box=lane?'border-color:var(--green);background:#f3fbf6':'border-color:#e3e8ee;background:#fff';
    const laneOpts='<option value="">안 씀</option>'+lanes.map(L=>`<option value="${esc(L.name)}"${L.name===lane?' selected':''}>${esc(L.name)}</option>`).join('');
    const fontOpts=fonts.map(f=>`<option value="${esc(f.value)}"${(f.value||'')===(s.font||'')?' selected':''}>${esc(f.name)}</option>`).join('');
    const sizeOpts='<option value="">크기</option>'+sizes.map(z=>`<option value="${z}"${String(z)===String(s.size||'')?' selected':''}>${z}</option>`).join('');
    return `<div class=epcell data-id="${s.id}" style="border:1.5px solid;border-radius:11px;padding:9px;${box}">
      <div class=epnum>#${s.id}${s.edited?' <span style="color:var(--green)">· 내가 설정함</span>':''}</div>
      <div style="text-align:center"><span class="sw-chip" style="${stl}">${hasStyle?'강조 텍스트':'(서식 없음)'}</span></div>
      <div class=eprow>
        <label><input type=checkbox class=epclr-on data-clr=text ${tc?'checked':''}>글자</label>
        <input type=color class="epclr${tc?'':' epclr-off'}" data-clr=text value="${tc||'#e53935'}">
        <label><input type=checkbox class=epclr-on data-clr=bg ${bg?'checked':''}>배경</label>
        <input type=color class="epclr${bg?'':' epclr-off'}" data-clr=bg value="${bg||'#fff59d'}"></div>
      <div class=eprow>
        <select class=epstyle data-key=font title=폰트>${fontOpts}</select>
        <select class=epstyle data-key=size title=글씨크기>${sizeOpts}</select>
        <label><input type=checkbox class=epstyle data-key=bold ${s.bold?'checked':''}>굵게</label></div>
      <select class=eplane data-id="${s.id}" style="width:100%;margin-top:7px;padding:5px 7px;border:1px solid #d6dade;border-radius:7px;font-size:12px;background:#fff;cursor:pointer">${laneOpts}</select></div>`;};
  const laneHelp=lanes.map(L=>`<b>${esc(L.name)}</b>`).join(' · ');
  let h=`<div class=muted style="margin-bottom:10px">색마다 <b>글자색·배경·폰트·크기</b>를 직접 정하고, <b>갈래</b>를 고르세요 — ${laneHelp}. 같은 갈래에 여러 색을 주면 글에서 <b>번갈아</b> 쓰입니다. <b>안 씀</b>이면 그 색은 사용 안 함. (현재: <b>${esc(e.source||'')}</b>)</div>`;
  h+='<div class=epgrid>'+(e.all||[]).map(card).join('')+'</div>';
  const cfg = e.config || {};
  h += `<div style="margin-top:18px;padding:14px;border:1px solid #e7edf3;border-radius:14px;background:#fcfdff">
    <div class=sub-h style="margin-bottom:10px">강조 밀도</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
      <div><div style="font-weight:700;margin-bottom:4px;font-size:13px">문단당 최소 강조</div><input class=epconf data-key="min_per_paragraph" value="${esc(cfg.min_per_paragraph||'')}" placeholder="0" style="width:100%;padding:9px 11px;border:1px solid #d6dade;border-radius:10px;background:#fff"></div>
      <div><div style="font-weight:700;margin-bottom:4px;font-size:13px">문단당 최대 강조</div><input class=epconf data-key="max_per_paragraph" value="${esc(cfg.max_per_paragraph||'')}" placeholder="2" style="width:100%;padding:9px 11px;border:1px solid #d6dade;border-radius:10px;background:#fff"></div>
      <div><div style="font-weight:700;margin-bottom:4px;font-size:13px">최소 문장 간격</div><input class=epconf data-key="min_sentence_gap" value="${esc(cfg.min_sentence_gap||'')}" placeholder="1" style="width:100%;padding:9px 11px;border:1px solid #d6dade;border-radius:10px;background:#fff"></div>
    </div>
    <div class=muted style="margin-top:8px;font-size:12px">문단당 최소 강조를 1 이상으로 두면 <b>모든 문단에 강조를 그만큼 넣으라고</b> LLM에게 안내돼요(아래 안내문에 반영). 최대만 두면 강조 없는 문단도 허용돼요.</div>
    <div style="margin-top:12px"><button class=btn data-action="save-emphasis-config" style="width:auto;padding:9px 16px">저장</button></div>
  </div>`;
  // 가시성 — LLM에게 실제로 들어가는 강조 지시문(펼쳐야 보이게 접어둠)
  h+=`<details class=psec style="margin-top:16px"><summary>✍️ 생성 시 LLM에게 들어가는 강조 안내문 보기</summary>
    <pre style="white-space:pre-wrap;background:#f7f9fb;border:0;padding:12px 14px;font-size:12px;line-height:1.6;margin:0;max-height:320px;overflow:auto">${esc(e.instruction||'')}</pre></details>`;
  $('#emph').innerHTML=h;
}
async function loadEmphasis(){try{renderEmphasis(await (await fetch('/api/emphasis')).json());
}catch(e){$('#emph').innerHTML='<div class=muted>로드 실패</div>';}}
// 색 칸의 글자색·배경·폰트·크기·굵게 → emphasis.yaml styles에 저장
function collectStyle(cell){
  const on=c=>cell.querySelector(`.epclr-on[data-clr=${c}]`).checked;
  const v=sel=>cell.querySelector(sel).value;
  return {
    text_color: on('text')?v('.epclr[data-clr=text]'):'',
    background_color: on('bg')?v('.epclr[data-clr=bg]'):'',
    font: v('[data-key=font]'),
    size: v('[data-key=size]'),
    bold: cell.querySelector('[data-key=bold]').checked,
  };}
$('#emph').addEventListener('change',async e=>{
  // 갈래(태그) 선택
  const sel=e.target.closest('.eplane');
  if(sel){try{const r=await fetch('/api/emphasis',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:+sel.dataset.id,tag:sel.value})});
    if(r.ok){renderEmphasis(await r.json());}}catch(e){} return;}
  // 색·폰트·크기·굵게 편집
  const st=e.target.closest('.epclr,.epclr-on,.epstyle');
  if(st){const cell=st.closest('.epcell'); if(!cell)return;
    // 색을 직접 고르면 그 색을 켠 것으로 간주(체크 자동 ON)
    if(st.classList.contains('epclr')){const cb=cell.querySelector(`.epclr-on[data-clr=${st.dataset.clr}]`); if(cb)cb.checked=true;}
    try{const r=await fetch('/api/emphasis',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:+cell.dataset.id,style:collectStyle(cell)})});
      if(r.ok){renderEmphasis(await r.json()); toast('저장됨 ✓ 다음 생성부터 반영','ok',1200);}else{toast('저장 실패','err');}}
    catch(e){toast('저장 오류','err');}}
});
// 강조 밀도 저장
$('#emph').addEventListener('click',async e=>{const btn=e.target.closest('[data-action="save-emphasis-config"]'); if(!btn)return;
  const root=$('#emph');
  const cfg={
    min_per_paragraph: root.querySelector('[data-key="min_per_paragraph"]').value.trim() || null,
    max_per_paragraph: root.querySelector('[data-key="max_per_paragraph"]').value.trim() || null,
    min_sentence_gap: root.querySelector('[data-key="min_sentence_gap"]').value.trim() || null,
  };
  btn.disabled=true;
  try{const r=await fetch('/api/emphasis',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({config:cfg})});
    if(r.ok){renderEmphasis(await r.json()); toast('강조 밀도 저장됨 ✓ 다음 생성부터 반영','ok',1600);}else{toast('저장 실패','err');}}
  catch(e){toast('저장 오류','err');}
  finally{btn.disabled=false;}
});
let PROMPTKIND='place';  // 편집 중인 프롬프트 종류(맛집=default.md / 상품=product.md / 장소=venue.md / 공통 포맷=common_style.md)
const PROMPTKIND_LABEL={place:'맛집',product:'상품',venue:'장소',common:'공통 포맷'};
let PROMPTRAW=false;   // true면 원문(통짜) 편집 모드
let PROMPTSECS=null;   // 섹션 파싱 결과 — #promptsections의 textarea들과 1:1 대응
function parsePromptSections(text){
  const re=/^#{2,3}[ \t].*$/gm; const marks=[]; let m;
  while((m=re.exec(text))) marks.push(m.index);
  if(!marks.length) return {pre:text, sections:[]};
  const secs=[];
  for(let i=0;i<marks.length;i++){
    const seg=text.slice(marks[i], i+1<marks.length?marks[i+1]:text.length);
    const nl=seg.indexOf('\n');
    secs.push({head:nl===-1?seg:seg.slice(0,nl), body:nl===-1?'':seg.slice(nl+1)});
  }
  return {pre:text.slice(0,marks[0]), sections:secs};
}
function sectionsToText(){
  const areas=$$('#promptsections textarea');
  const pre=(areas[0]?areas[0].value:'').trim();
  const parts=[]; if(pre)parts.push(pre);
  PROMPTSECS.sections.forEach((s,i)=>{const body=(areas[i+1]?areas[i+1].value:'').trim();
    parts.push(body?s.head+'\n\n'+body:s.head);});
  return parts.join('\n\n')+'\n';
}
function currentPromptText(){return (PROMPTRAW||!PROMPTSECS)?$('#promptedit').value:sectionsToText();}
function renderPromptSections(text){
  PROMPTSECS=parsePromptSections(text);
  const box=$('#promptsections'); box.innerHTML='';
  const mk=(title,val)=>{const d=document.createElement('details'); d.className='psec';
    const s=document.createElement('summary'); s.textContent=title; d.appendChild(s);
    const a=document.createElement('textarea'); a.className='promptarea psecarea'; a.value=val;
    a.style.minHeight=Math.min(60+val.split('\n').length*20,420)+'px';
    d.appendChild(a); box.appendChild(d);};
  mk('📄 파일 안내 · 메타 (모델에는 전송되지 않음)', PROMPTSECS.pre.trim());
  PROMPTSECS.sections.forEach(sec=>{
    const sub=sec.head.startsWith('###');
    mk((sub?'· ':'')+sec.head.replace(/^#+[ \t]*/,''), sec.body.trim());});
}
async function loadPrompt(){try{const p=await (await fetch('/api/prompt?kind='+PROMPTKIND)).json();
  $('#promptedit').value=p.base_raw||'';
  if(!PROMPTRAW) renderPromptSections(p.base_raw||'');
  $('#prompthdr').textContent='— '+(p.path||'config/prompts/default.md');
  $('#promptstat').textContent='';
  $('#promptlayers').innerHTML='<div class=promptbox>'+p.layers.map(([t,b])=>`<details><summary>${esc(t)}</summary><pre>${esc(b)}</pre></details>`).join('')+'</div>';
}catch(e){$('#promptlayers').innerHTML='<div class=muted>로드 실패</div>';}}
function setPromptKind(k){if(k===PROMPTKIND)return; PROMPTKIND=k;
  $$('#promptkindseg button').forEach(b=>b.classList.toggle('on',b.dataset.k===k));
  loadPrompt();}
$$('#promptkindseg button').forEach(b=>b.onclick=()=>setPromptKind(b.dataset.k));
$('#promptmode').onclick=()=>{
  if(PROMPTRAW){renderPromptSections($('#promptedit').value);}  // 원문 → 파트(편집 내용 반영)
  else{$('#promptedit').value=sectionsToText();}                 // 파트 → 원문
  PROMPTRAW=!PROMPTRAW;
  $('#promptsections').style.display=PROMPTRAW?'none':'';
  $('#promptedit').style.display=PROMPTRAW?'':'none';
  $('#promptmode').textContent=PROMPTRAW?'파트별로 편집':'원문으로 편집';
};
$('#promptsave').onclick=async()=>{
  $('#promptsave').disabled=true; $('#promptstat').textContent='저장 중…';
  try{const base=currentPromptText();
    const r=await fetch('/api/prompt',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({base,kind:PROMPTKIND})});
    if(r.ok){$('#promptedit').value=base; if(!PROMPTRAW)renderPromptSections(base);}
    $('#promptstat').textContent=r.ok?('저장됨 ✓ ('+(PROMPTKIND_LABEL[PROMPTKIND]||'맛집')+') 다음 생성부터 반영돼요'):'저장 실패';
  }catch(e){$('#promptstat').textContent='오류';}finally{$('#promptsave').disabled=false;}
};
// 수정 흔적 표시 — 저장을 눌러야 반영된다는 걸 잊지 않게
const promptDirty=()=>{$('#promptstat').innerHTML='<b style="color:#d98a00">수정됨</b> — [저장]을 눌러야 다음 생성부터 반영돼요';};
$('#promptedit').addEventListener('input',promptDirty);
$('#promptsections').addEventListener('input',promptDirty);
// ── 스타일 풀(유행어·카오모지·고정 문구) 편집 ──
let POOL=null;
const POOL_KAO={taste:'맛·만족',cheer:'응원·파이팅',sad:'아쉬움·슬픔',angry:'분노·불만',cute:'귀여움·꾸미기'};
const POOL_LISTS={structure_place:'맛집 섹션 흐름 변형',structure_product:'상품 섹션 흐름 변형',quote_position:'핵심 한마디 위치 후보',checklist_heading:'상품 추천 소제목 변형(🌟 뒤 문구)',summary_connector:'요약 박스 연결 문자 후보',pick_transition:'PICK 전환 멘트 변형'};
const SLANG_FREQ=[['0','안 씀'],['1','가끔'],['2','보통'],['3','자주']];
function poolInput(v,ph){const i=document.createElement('input'); i.value=v||''; i.placeholder=ph||''; return i;}
function renderPool(){
  const box=$('#stylepool'); box.innerHTML='';
  if(!POOL){box.innerHTML='<div class=muted>로드 실패</div>'; return;}
  const kao=POOL.kaomoji||(POOL.kaomoji={});
  const sec=(title,desc)=>{const d=document.createElement('details'); d.className='psec';
    const s=document.createElement('summary'); s.innerHTML=esc(title)+(desc?` <span class=muted style="font-weight:400">— ${esc(desc)}</span>`:''); d.appendChild(s);
    const b=document.createElement('div'); b.style.padding='10px 14px'; d.appendChild(b); box.appendChild(d); return b;};
  Object.keys(POOL_KAO).forEach(cat=>{
    const items=Array.isArray(kao[cat])?kao[cat]:(kao[cat]=[]);
    const b=sec('표정 이모티콘 · '+POOL_KAO[cat], items.length+'개 — 글마다 일부만 뽑혀요');
    const wrap=document.createElement('div'); b.appendChild(wrap);
    const draw=()=>{wrap.innerHTML=''; items.forEach((k,i)=>{const c=document.createElement('span'); c.className='poolchip';
      c.append(k); const x=document.createElement('button'); x.textContent='×'; x.onclick=()=>{items.splice(i,1); draw();}; c.appendChild(x); wrap.appendChild(c);});};
    draw();
    const row=document.createElement('div'); row.className='poolrow'; row.style.marginTop='8px';
    const inp=poolInput('','카오모지 추가 — !·~ 포함 불가(자동 치환에 깨져요)');
    const add=document.createElement('button'); add.textContent='추가'; add.className='pooladd'; add.style.marginTop='0';
    const doAdd=()=>{const v=inp.value.trim(); if(!v)return;
      if(v.includes('!')||(v.includes('~')&&v!=='(๑´~ˋ๑)')){toast('!·~가 든 카오모지는 자동 치환에 깨져서 넣을 수 없어요','err');return;}
      if(!items.includes(v))items.push(v); inp.value=''; draw();};
    add.onclick=doAdd; inp.onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing&&e.keyCode!==229){e.preventDefault();doAdd();}};
    row.append(inp,add); b.appendChild(row);
  });
  const slang=Array.isArray(POOL.slang)?POOL.slang:(POOL.slang=[]);
  const sb=sec('유행어', slang.length+'개 — 빈도는 후보로 뽑힐 확률 가중치예요');
  const sw=document.createElement('div'); sb.appendChild(sw);
  const drawSlang=()=>{sw.innerHTML='';
    slang.forEach((s,i)=>{const row=document.createElement('div'); row.className='poolrow';
      const e1=poolInput(s.expr,'표현'), e2=poolInput(s.meaning,'뜻'), e3=poolInput(s.example,'예시');
      e1.oninput=()=>s.expr=e1.value; e2.oninput=()=>s.meaning=e2.value; e3.oninput=()=>s.example=e3.value;
      e1.style.flex='0 0 110px'; e3.style.flex='1.4';
      const sel=document.createElement('select'); SLANG_FREQ.forEach(([v,l])=>{const o=document.createElement('option'); o.value=v; o.textContent='빈도: '+l; sel.appendChild(o);});
      sel.value=String(s.weight??1); sel.onchange=()=>s.weight=Number(sel.value);
      const del=document.createElement('button'); del.textContent='×'; del.className='pooldel'; del.onclick=()=>{slang.splice(i,1); drawSlang();};
      row.append(e1,e2,e3,sel,del); sw.appendChild(row);});
    const add=document.createElement('button'); add.textContent='+ 유행어 추가'; add.className='pooladd';
    add.onclick=()=>{slang.push({expr:'',meaning:'',example:'',weight:1}); drawSlang();};
    sw.appendChild(add);};
  drawSlang();
  Object.keys(POOL_LISTS).forEach(key=>{
    const items=Array.isArray(POOL[key])?POOL[key]:(POOL[key]=[]);
    const b=sec(POOL_LISTS[key], items.length+'개 — 글마다 하나가 뽑혀요');
    const w=document.createElement('div'); b.appendChild(w);
    const draw=()=>{w.innerHTML='';
      items.forEach((v,i)=>{const row=document.createElement('div'); row.className='poolrow';
        const inp=poolInput(v,''); inp.oninput=()=>items[i]=inp.value;
        const del=document.createElement('button'); del.textContent='×'; del.className='pooldel'; del.onclick=()=>{items.splice(i,1); draw();};
        row.append(inp,del); w.appendChild(row);});
      const add=document.createElement('button'); add.textContent='+ 추가'; add.className='pooladd';
      add.onclick=()=>{items.push(''); draw();}; w.appendChild(add);};
    draw();
  });
}
async function loadPool(){try{const d=await (await fetch('/api/style-pool')).json(); POOL=d.pool||{}; renderPool();
  $('#poolstat').textContent=d.overridden?'수정본 사용 중':'';
}catch(e){$('#stylepool').innerHTML='<div class=muted>로드 실패</div>';}}
const poolDirty=()=>{$('#poolstat').innerHTML='<b style="color:#d98a00">수정됨</b> — [저장]을 눌러야 반영돼요';};
$('#stylepool').addEventListener('input',poolDirty);
$('#stylepool').addEventListener('click',e=>{if(e.target.closest('.pooldel,.pooladd,.poolchip button'))poolDirty();});
$('#poolsave').onclick=async()=>{
  $('#poolsave').disabled=true; $('#poolstat').textContent='저장 중…';
  try{const r=await fetch('/api/style-pool',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({pool:POOL})});
    const d=await r.json(); POOL=d.pool||POOL; renderPool();
    $('#poolstat').textContent=r.ok?'저장됨 ✓ 다음 생성부터 반영돼요':'저장 실패';
  }catch(e){$('#poolstat').textContent='오류';}finally{$('#poolsave').disabled=false;}
};
$('#poolreset').onclick=()=>askConfirm('↺ 기본값 복원','스타일 풀을 기본값으로 되돌릴까요? 수정한 내용은 사라져요.','되돌리기',async()=>{
  try{const r=await fetch('/api/style-pool',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({reset:true})});
    const d=await r.json(); POOL=d.pool||{}; renderPool(); $('#poolstat').textContent='기본값 복원됨 ✓';
  }catch(e){$('#poolstat').textContent='오류';}
});
async function loadVariants(){try{const f=await (await fetch('/api/format')).json();
  const row=(items,type,qcls)=>{
    if(!items.length)return '<div class=muted>캡쳐된 종류가 없어요</div>';
    return '<div class=vgrid>'+items.map(it=>`<div class="vcell ${qcls}${it.enabled?' on':''}" data-type=${type} data-value="${it.value}">
      <div class=vinfo><div class=vname>${it.name} ${it.enabled?'<span class=vck>✓</span>':''}</div><div class=vdesc>${it.desc}</div></div>
      <img loading=lazy src="/variant-img?type=${type}&value=${encodeURIComponent(it.value)}"></div>`).join('')+'</div>';};
  $('#variants').innerHTML='<div class=muted style="margin-bottom:8px">쓰고 싶은 종류를 여러 개 골라두세요. 글 생성 때 그 중에서 쓰입니다.</div>'
    +'<div class=sub-h>구분선</div>'+row(f.dividers,'divider','')
    +'<div class=sub-h>인용구</div>'+row(f.quotes,'quote','q');
}catch(e){$('#variants').innerHTML='<div class=muted>로드 실패</div>';}}
$('#variants').onclick=async e=>{const c=e.target.closest('.vcell'); if(!c)return;
  const type=c.dataset.type, value=c.dataset.value, on=!c.classList.contains('on');
  c.classList.toggle('on',on);
  c.querySelector('.vname').innerHTML=c.querySelector('.vname').textContent.replace(' ✓','')+(on?' <span class=vck>✓</span>':'');
  try{await fetch('/api/format',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type,value,on})});}catch(e){}
};
$('#tone').onchange=savePrefs;

// ===== 문체(페르소나) =====
async function loadPersonas(){try{const d=await (await fetch('/api/personas')).json();
  PERSONAS=d.personas||[]; TONES=d.tones||[]; renderPersonaSelect(); autoPickPersona(); renderPersonaList();
}catch(e){$('#personalist').innerHTML='<div class=muted>로드 실패</div>';}}
function renderPersonaSelect(){const sel=$('#persona'); if(!sel)return;
  // 내장 어투 프리셋 + 내 문체(페르소나). 기본 프리셋은 value=""(선택 안 함과 동일 경로).
  const tOpt=t=>`<option value="${t.default?'':'tone:'+t.id}" title="${esc(t.desc||'')}">${esc(t.name)}${t.default?' (기본)':''}</option>`;
  const tones=TONES.length?TONES.map(tOpt).join(''):'<option value="">기본 (설정 안 함)</option>';
  sel.innerHTML=`<optgroup label="내장 어투">${tones}</optgroup>`+
    (PERSONAS.length?`<optgroup label="내 문체">${PERSONAS.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('')}</optgroup>`:'');
  const valid=new Set(['',...TONES.filter(t=>!t.default).map(t=>'tone:'+t.id),...PERSONAS.map(p=>p.id)]);
  sel.value=valid.has(PERSONA_ID)?PERSONA_ID:''; if(sel.value!==PERSONA_ID)PERSONA_ID=sel.value;}
function renderPersonaList(){const c=$('#personalist'); if(!c)return;
  if(!PERSONAS.length){c.innerHTML='<div class=pempty><b>아직 저장된 문체가 없어요</b><br>위에서 블로그 주소를 넣고 첫 문체를 만들어 보세요</div>';return;}
  // 행을 details 카드로: 펼치면 문체 특징을 확인·수정할 수 있다(save는 같은 id면 갱신).
  const chev='<svg class=pchev viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';
  c.innerHTML=PERSONAS.map(p=>{const n=(p.sources||[]).length;
    return `<details class=pcard data-id="${p.id}">
      <summary>
        <div class=pava>${esc((p.name||'?').trim().charAt(0).toUpperCase()||'?')}</div>
        <div class=pinfo><div class=pname>${esc(p.name)}</div>
          <div class=psub>${p.blog?`<span>${esc(p.blog)}</span>`:''}${n?`<span class=ptag>인기글 ${n}개 학습</span>`:''}</div></div>
        <button class=pdel data-id="${p.id}">삭제</button>${chev}
      </summary>
      <div class=pbody>
        <label class=f style="margin-top:0">문체 특징 <span class=muted style="font-weight:400">— 고친 뒤 [수정 저장]을 누르면 반영돼요</span></label>
        <textarea class="promptarea pprof">${esc(p.profile||'')}</textarea>
        <div style="display:flex;align-items:center;gap:10px;margin-top:10px">
          <button class="btn psave" data-id="${p.id}" style="width:auto;padding:8px 16px;font-size:13px">수정 저장</button>
        </div>
      </div>
    </details>`;}).join('');}
$('#persona').onchange=()=>{PERSONA_ID=$('#persona').value; PERSONA_PICKED=true; savePrefs();};
$('#pf_fetch').onclick=async()=>{
  const blog=$('#pf_blog').value.trim(); if(!blog){toast('블로그 주소를 입력하세요','err');return;}
  const btn=$('#pf_fetch'); btn.disabled=true; $('#pf_stat').textContent='인기글 불러오는 중…';
  $('#pf_posts').innerHTML=''; $('#pf_extractrow').style.display='none'; $('#pf_result').style.display='none';
  try{const r=await fetch('/api/personas/fetch',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({blog})});
    const d=await r.json(); if(!r.ok){$('#pf_stat').textContent=''; toast('불러오기 실패: '+(d.error||''),'err'); return;}
    PF={blogId:d.blogId, posts:d.posts||[]};
    if(!PF.posts.length){$('#pf_stat').textContent='인기글을 찾지 못했어요.'; return;}
    $('#pf_stat').textContent=`인기글 ${PF.posts.length}개 — 학습에 쓸 글을 고르세요 (기본 전체 선택).`;
    $('#pf_posts').innerHTML=PF.posts.map((p,i)=>`<label class=pfrow>
      <input type=checkbox class=pchk data-i="${i}" checked>
      <span style="flex:1;min-width:0;font-size:13.5px">${esc(p.title||('글 '+(i+1)))}</span>
      <span class=muted style="font-size:12px;white-space:nowrap">공감 ${p.sympathy} · 댓글 ${p.comments}</span></label>`).join('');
    pfModelSelect(); $('#pf_extractrow').style.display='flex';
  }catch(e){$('#pf_stat').textContent='';}finally{btn.disabled=false;}};
// 키 등록된 텍스트 모델만 드롭다운에 — 지금 쓰는 모델이 키가 있으면 그걸 기본 선택.
function pfModelSelect(){const sel=$('#pf_model');
  const keyed=(API_TEXT||[]).filter(a=>MODEL_KEYS[a.provider]);
  sel.innerHTML=keyed.map(a=>`<option value="${a.model}">${esc(nicer(a.model))}${a.model===TEXT_MODEL?' (사용 중)':''}</option>`).join('');
  sel.style.display=keyed.length?'':'none';
  if(keyed.some(a=>a.model===TEXT_MODEL))sel.value=TEXT_MODEL;
  return keyed.length;}
$('#pf_extract').onclick=async()=>{
  const logNos=$$('#pf_posts .pchk:checked').map(c=>PF.posts[+c.dataset.i].logNo);
  if(!logNos.length){toast('최소 한 개는 선택하세요','err');return;}
  if(!pfModelSelect()){toast('API 키가 등록된 텍스트 모델이 없어요. [프롬프트만 복사]로 ChatGPT·Claude에 붙여넣어 진행하거나, [모델] 탭에서 키를 등록하세요.','err');return;}
  const model=$('#pf_model').value;
  const btn=$('#pf_extract'); btn.disabled=true; $('#pf_stat').textContent=`문체 추출 중… ${nicer(model)}(이)가 글 본문을 읽고 분석해요 (20~40초)`;
  try{const r=await fetch('/api/personas/extract',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({blog:PF.blogId, logNos, model})});
    const d=await r.json(); if(!r.ok){$('#pf_stat').textContent=''; toast('추출 실패: '+(d.error||''),'err'); return;}
    PF.profile=d.profile; PF.sources=d.sources||[];
    $('#pf_profile').value=d.profile||'';
    if(!$('#pf_name').value.trim())$('#pf_name').value=(PF.blogId||'')+' 문체';
    $('#pf_result').style.display='block'; $('#pf_stat').textContent='추출 완료 — 내용을 다듬고 이름을 정해 저장하세요.';
  }catch(e){$('#pf_stat').textContent='';}finally{btn.disabled=false;}};
$('#pf_promptonly').onclick=async()=>{
  const logNos=$$('#pf_posts .pchk:checked').map(c=>PF.posts[+c.dataset.i].logNo);
  if(!logNos.length){toast('최소 한 개는 선택하세요','err');return;}
  const btn=$('#pf_promptonly'); btn.disabled=true; $('#pf_stat').textContent='프롬프트 만드는 중… 글 본문을 읽어요';
  try{const r=await fetch('/api/personas/prompt',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({blog:PF.blogId, logNos})});
    const d=await r.json(); if(!r.ok){$('#pf_stat').textContent=''; toast('만들기 실패: '+(d.error||''),'err'); return;}
    let copied=false; try{await navigator.clipboard.writeText(d.prompt); copied=true;}catch(e){PF.prompt=d.prompt;}
    // 프롬프트는 클립보드로만. 문체 특징 칸은 유저가 'LLM 분석 결과'를 붙여넣을 자리이므로 비워서 노출.
    $('#pf_profile').value=''; $('#pf_result').style.display='block';
    if(!$('#pf_name').value.trim())$('#pf_name').value=(PF.blogId||'')+' 문체';
    $('#pf_stat').textContent=copied
      ?'프롬프트를 클립보드에 복사했어요. ChatGPT·Claude 등에 붙여넣어 받은 분석 결과를 아래 [문체 특징] 칸에 붙여넣고 저장하세요.'
      :'복사 권한이 막혀 있어요. 콘솔에서 PF.prompt 를 복사하거나 다시 시도하세요.';
    toast(copied?'프롬프트 복사 완료 — LLM 결과를 문체 특징 칸에 붙여넣으세요':'프롬프트 생성됨','ok');
  }catch(e){$('#pf_stat').textContent='';}finally{btn.disabled=false;}};
$('#pf_save').onclick=async()=>{
  const name=$('#pf_name').value.trim(), profile=$('#pf_profile').value.trim();
  if(!name||!profile){toast('이름과 문체 내용을 모두 채워주세요','err');return;}
  const btn=$('#pf_save'); btn.disabled=true; $('#pf_savestat').textContent='저장 중…';
  try{const r=await fetch('/api/personas/save',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({name, blog:PF.blogId||$('#pf_blog').value.trim(), profile, sources:PF.sources||[]})});
    if(!r.ok){$('#pf_savestat').textContent=''; toast('저장 실패','err'); return;}
    const d=await r.json();
    $('#pf_savestat').textContent='저장됨 ✓'; await loadPersonas();
    if(d.id){PERSONA_ID=d.id; PERSONA_PICKED=true; const sel=$('#persona'); if(sel)sel.value=d.id; savePrefs();}  // 방금 만든 문체를 글쓰기 기본으로
    PF={}; $('#pf_result').style.display='none'; $('#pf_posts').innerHTML=''; $('#pf_extractrow').style.display='none';
    $('#pf_blog').value=''; $('#pf_name').value=''; $('#pf_profile').value=''; $('#pf_stat').textContent='';
    toast('문체가 저장됐어요. 글쓰기 문체로 바로 선택해뒀어요.','ok');
  }catch(e){$('#pf_savestat').textContent='';}finally{btn.disabled=false;}};
$('#personalist').onclick=async e=>{
  const b=e.target.closest('.pdel');
  if(b){e.preventDefault();  // summary 안의 버튼 — 펼침 토글 방지
    askConfirm('🗑 문체 삭제','이 문체를 삭제할까요? 되돌릴 수 없어요.','삭제',async()=>{
      try{await fetch('/api/personas/delete',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id:b.dataset.id})});
        if(PERSONA_ID===b.dataset.id){PERSONA_ID=''; PERSONA_PICKED=false; savePrefs();}  // 선택 문체 삭제 → 남은 내 문체가 있으면 다시 자동 선택
        await loadPersonas();
      }catch(e){}
    });return;}
  const sv=e.target.closest('.psave'); if(!sv)return;
  const p=PERSONAS.find(x=>x.id===sv.dataset.id); if(!p)return;
  const profile=sv.closest('details').querySelector('.pprof').value.trim();
  if(!profile){toast('문체 내용이 비어 있어요','err');return;}
  sv.disabled=true;
  try{const r=await fetch('/api/personas/save',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({id:p.id,name:p.name,blog:p.blog||'',profile,sources:p.sources||[]})});
    if(!r.ok){toast('저장 실패','err');return;}
    toast('수정이 저장됐어요','ok'); await loadPersonas();
  }catch(e){}finally{sv.disabled=false;}};

$('#addprodlink').onclick=()=>addProdLink(''); resetProdLinks();
setKind('place',false); loadPhotos(); setupUpload(); setupDraftImport(); loadPrefs(); loadModels(); loadEmphasis(); loadPrompt(); loadPool(); loadVariants(); loadCategories(); loadPhotoCats(); loadPersonas();
$('#photobtn').onclick=openPhotoModal; $('#phclose').onclick=closePhotoModal; $('#phdone').onclick=closePhotoModal;
$('#phmodal').onclick=e=>{ if(e.target===$('#phmodal'))closePhotoModal(); };
$('#newpost').onclick=newPost;
$('#npok').onclick=doNewPost; $('#npx').onclick=closeNP; $('#npcancel').onclick=closeNP;
$('#npmodal').onclick=e=>{ if(e.target===$('#npmodal'))closeNP(); };
$('#tgx').onclick=closeTG; $('#tgcancel').onclick=closeTG;
$('#tpx').onclick=closeTP; $('#tpskip').onclick=closeTP; $('#tpok').onclick=applyPendThumb;
$('#tpcopy').onclick=async()=>{ const p=PENDTHUMB&&PENDTHUMB.prompt; if(!p){toast('복사할 프롬프트가 없어요.','info');return;}
  try{await navigator.clipboard.writeText(p); toast('프롬프트를 복사했어요 — 외부 이미지 모델에 붙여넣으세요.','ok');}
  catch(e){ prompt('아래 프롬프트를 복사하세요 (Ctrl/Cmd+C):', p); } };
$('#tsx').onclick=closeTS; $('#tscancel').onclick=closeTS; $('#tsfile').onclick=swapThumbFile;
$('#tsmodal').onclick=e=>{ if(e.target===$('#tsmodal'))closeTS(); };
$('#tscopypr').onclick=async()=>{ const p=await thumbPrompt();
  if(!p){toast('프롬프트 템플릿(config/prompts/thumbnail_copy.md)을 못 읽었어요.','info');return;}
  try{await navigator.clipboard.writeText(p); toast('프롬프트를 복사했어요 — 사진과 함께 붙여넣으세요.','ok');}
  catch(e){ prompt('아래 프롬프트를 복사하세요 (Ctrl/Cmd+C):', p); } };
$('#tscopyimg').onclick=()=>{  // 원본을 PNG로 변환해 클립보드에 — 외부 모델 입력창에 바로 붙여넣기용
  // ClipboardItem에 Promise를 동기로 넘겨야 함 — await 후 write하면 Safari가 클릭 제스처 소멸로 거부
  const blobP=fetch($('#tsdl').href)
    .then(r=>{ if(!r.ok)throw new Error('원본사진을 못 읽었어요(HTTP '+r.status+') — 사진이 바뀌었으면 모달을 다시 열어보세요'); return r.blob(); })
    .then(createImageBitmap).then(bm=>{
    const c=document.createElement('canvas'); c.width=bm.width; c.height=bm.height;
    c.getContext('2d').drawImage(bm,0,0);
    return new Promise(r=>c.toBlob(r,'image/png'));
  });
  navigator.clipboard.write([new ClipboardItem({'image/png':blobP})])
    .then(()=>toast('원본사진을 복사했어요 — 외부 모델 입력창에 붙여넣으세요.','ok'))
    .catch(e=>toast('사진 복사 실패('+(e&&(e.message||e.name)||e)+') — ⬇ 사진 저장을 이용하세요.','info')); };
$('#tgmodal').onclick=e=>{ if(e.target===$('#tgmodal'))closeTG(); };
$('#tgok').onclick=()=>{ const t=$('#tgtitle').value.trim(), ex=$('#tgextra').value.trim(); closeTG(); runThumbGen(t,ex); };
$('#aix').onclick=closeAI; $('#aicancel').onclick=closeAI;
$('#aimodal').onclick=e=>{ if(e.target===$('#aimodal'))closeAI(); };
$('#aiok').onclick=()=>{ const hint=$('#aihint').value.trim(); closeAI(); runAiCaption(aiTargets(),hint); };  // 요청사항은 지우지 않고 유지 — 이어서/재분석 때 재사용
// 범용 확인 모달 — 네이티브 confirm() 대신 앱 스타일로
let CFCB=null;
function askConfirm(title,desc,okLabel,cb){
  $('#cftitle').textContent=title; $('#cfdesc').textContent=desc;
  $('#cfok').textContent=okLabel||'확인'; CFCB=cb; $('#cfmodal').style.display='flex';
}
function closeCF(){ $('#cfmodal').style.display='none'; CFCB=null; }
$('#cfx').onclick=closeCF; $('#cfcancel').onclick=closeCF;
$('#cfmodal').onclick=e=>{ if(e.target===$('#cfmodal'))closeCF(); };
$('#cfok').onclick=()=>{ const cb=CFCB; closeCF(); if(cb)cb(); };
$('#catok').onclick=catSubmit; $('#catx').onclick=closeCatModal; $('#catcancel').onclick=closeCatModal;
$('#catinput').onkeydown=e=>{ if(e.key==='Enter'&&!e.isComposing&&e.keyCode!==229)catSubmit(); };  // Esc는 아래 공통 핸들러가 처리(이중 닫힘 방지)
$('#catmodal').onclick=e=>{ if(e.target===$('#catmodal'))closeCatModal(); };
$('#capok').onclick=capSubmit; $('#capx').onclick=closeCapModal; $('#capcancel').onclick=closeCapModal;
$('#capinput').onkeydown=e=>{ if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();capSubmit();} };  // Enter 저장 · Shift+Enter 줄바꿈
$('#capmodal').onclick=e=>{ if(e.target===$('#capmodal'))closeCapModal(); };
// Esc로 열린 모달 닫기 — 스택 위(사진 모달 위에 뜨는 작은 모달)부터, 배경 클릭과 같은 닫기 함수로
const MODAL_ESC=[['aimodal',closeAI],['capmodal',closeCapModal],['catmodal',closeCatModal],['cfmodal',closeCF],['tgmodal',closeTG],['npmodal',closeNP],['imodal',closeIM],['pmodal',closePM],['phmodal',closePhotoModal]];
document.addEventListener('keydown',e=>{
  if(e.key!=='Escape')return;
  if(GENABORT){ GENABORT.abort(); return; }  // 생성 중 빠른 취소
  if(document.querySelector('.alertbg,.okbg'))return;  // 알림 카드는 자체 Esc 처리
  for(const [id,fn] of MODAL_ESC){ const m=document.getElementById(id); if(m&&m.style.display!=='none'){fn();return;} }
});
// 메모를 치는 대로 현재 탭 제목이 갱신되게(초안 생성 전에도 어느 탭인지 알아보게).
{ const mo=$('#memo'); if(mo) mo.addEventListener('input', ()=>renderTabs()); }
// 저장된 탭 작업이 있으면 복원(새로고침·크래시 후 사진·순서·분류 유지), 없으면 새 탭 1개.
if(!restoreWS()) initWorkspaces();
// 자동 저장: 종료/새로고침 직전 + 10초마다(크래시·서버 재시작 대비).
window.addEventListener('beforeunload', persistWS);
setInterval(persistWS, 10000);
</script></body></html>"""


def _video_thumb(cache: dict, size: int = 320) -> bytes:
    """동영상은 썸네일 추출 없이, 어두운 타일 + 재생(▶) 아이콘 플레이스홀더로 표시.

    /photo 가 모든 미디어에 같은 <img src>로 쓰여, 영상도 이 한 장으로 그리드·캡션·대표
    미리보기 어디서나 일관되게 보인다(언어/폰트 비의존, PIL 도형만 사용)."""
    if "__video__" in cache:
        return cache["__video__"]
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (size, size), "#2b2f36")
    d = ImageDraw.Draw(im)
    cx, cy, r = size // 2, size // 2, size // 6
    d.ellipse([cx - r * 1.6, cy - r * 1.6, cx + r * 1.6, cy + r * 1.6], fill="#000000")
    d.polygon([(cx - r // 2, cy - r), (cx - r // 2, cy + r), (cx + r, cy)], fill="#ffffff")
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=80)
    cache["__video__"] = buf.getvalue()
    return cache["__video__"]


def _thumb(path: Path, cache: dict, size: int = 320) -> bytes | None:
    key = str(path)
    if key in cache:
        return cache[key]
    if is_video(str(path)):
        return _video_thumb(cache, size)  # 영상은 공용 플레이스홀더(경로별 캐시 불필요)
    try:
        from PIL import Image

        im = Image.open(path)
        im.thumbnail((size, size))
        im = im.convert("RGB")
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=80)
        cache[key] = buf.getvalue()
        return cache[key]
    except Exception:
        return None


def _list_photos() -> list[dict]:
    if not PHOTO_DIR.exists():
        return []
    out = []
    for p in sorted(PHOTO_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in _MEDIA_EXT:
            out.append(
                {"path": str(p), "name": p.name, "kind": "video" if is_video(p.name) else "image"}
            )
    return out


def _safe_photo(path: str) -> Path | None:
    p = Path(path).resolve()
    for base in (PHOTO_DIR.resolve(), UPLOAD_DIR.resolve()):
        try:
            p.relative_to(base)
            return p if p.exists() else None
        except ValueError:
            continue
    return None


def _save_upload(filename: str, b64: str) -> str:
    """업로드 미디어(사진/영상)를 data/uploads/에 저장하고 경로 반환.

    네이버 에디터가 못 받는 이미지 형식(webp·bmp 등 — 외부 AI 모델 다운로드가 흔히 webp)은
    저장 시점에 PNG/JPEG로 변환한다. 안 그러면 게시 단계에서 업로드가 조용히 실패해
    사진이 빠지고 ★ 대표 지정도 어긋난다. 변환 실패 시엔 원본 그대로 저장(영상은 대상 아님).
    """
    import base64
    import uuid

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(b64)
    safe = Path(filename).name or "media"
    ext = Path(safe).suffix.lower()
    if not is_video(safe) and ext not in {".jpg", ".jpeg", ".png", ".gif"}:
        try:
            from PIL import Image

            im = Image.open(BytesIO(raw))
            buf = BytesIO()
            if "A" in im.getbands():  # 투명도 보존
                im.save(buf, format="PNG")
                new_ext = ".png"
            else:
                im.convert("RGB").save(buf, format="JPEG", quality=92)
                new_ext = ".jpg"
            raw = buf.getvalue()
            safe = (Path(safe).stem or "media") + new_ext
        except Exception:  # noqa: BLE001 - 변환은 보조, 실패해도 원본 저장
            pass
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{safe}"
    dest.write_bytes(raw)
    return str(dest)


def _friendly_error(exc: Exception) -> str:
    """유저 화면에 보낼 오류 메시지를 짧고 읽기 좋게 정리한다.

    Playwright 타임아웃 등 내부 자동화 오류는 수십 줄짜리 call log를 str()에 그대로 담아
    화면에 노출돼 사용자가 이해할 수 없다. 서버 로그엔 원본 트레이스백을 남기되(호출부에서),
    사용자에겐 원인·다음 행동을 담은 안내문으로 바꾼다. 우리가 의도적으로 던진 RuntimeError
    등 이미 사람 읽는 메시지는 그대로 둔다(단, 여러 줄이면 첫 줄만).
    """
    try:
        from playwright.sync_api import TimeoutError as _PWTimeout
    except Exception:  # noqa: BLE001 - playwright 미설치 등
        _PWTimeout = ()
    if _PWTimeout and isinstance(exc, _PWTimeout):
        return (
            "네이버 에디터가 제때 반응하지 않았어요(임시저장 창이 안 열리거나 안내 팝업이 "
            "남아 있었을 수 있어요). 잠시 후 다시 시도해 주세요. 계속되면 설정에서 "
            "‘저장 디버그’를 켜고 화면을 직접 확인해 주세요."
        )
    msg = (str(exc) or exc.__class__.__name__).strip()
    return msg.splitlines()[0][:300]  # 혹시 call log가 붙은 긴 메시지는 첫 줄만


def _make_handler(state: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json", cache: bool = False):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # 사진 타일은 캐시 허용 — 분류판이 재렌더될 때마다(칸 순서 드래그 등) 전 장을
            # 재다운로드하며 흰 타일로 깜빡이던 문제 방지. 파일 경로가 키라 내용이 바뀌면 경로도 바뀜
            # (업로드·불러오기·AI 썸네일 모두 uuid 새 파일). max-age=3600이면 탭을 1시간 넘게
            # 열어둔 뒤 재렌더 때 전 장 만료→재다운로드로 흰 타일이 재발해 immutable 영구 캐시.
            self.send_header(
                "Cache-Control", "public, max-age=31536000, immutable" if cache else "no-store"
            )
            self.end_headers()
            self.wfile.write(body)

        def _json_body(self):
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def _stream_begin(self, code=200):
            """NDJSON 스트리밍 응답 시작 — 진행 상태를 한 줄씩 흘려보낸다.

            HTTP/1.0(기본) + Connection: close라 Content-Length 없이 EOF로 종료한다.
            클라이언트는 줄 단위 JSON({stage}/{prompt}/{error})을 읽어 상태를 갱신한다.
            """
            self.send_response(code)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()

        def _stream_write(self, obj):
            self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        def do_GET(self):
            try:
                self._route_get()
            except BrokenPipeError:
                pass  # 클라이언트가 먼저 끊음 — 무시
            except Exception as exc:  # noqa: BLE001
                import traceback

                print(f"[webui] GET {self.path} 실패: {exc}", flush=True)
                traceback.print_exc()

        def _route_get(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/":
                from autoblog.publish.editor import reserve_ready

                html = _PAGE.replace("/*FONTFACES*/", _font_face_css())
                html = html.replace("/*RESERVE_READY*/", "true" if reserve_ready() else "false")
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/font":
                name = Path(q.get("name", [""])[0]).name  # 경로 차단
                fp = FONTS_DIR / f"{name}.woff2"
                if fp.exists() and fp.parent == FONTS_DIR:
                    self._send(200, fp.read_bytes(), "font/woff2")
                else:
                    self._send(404, b"x", "text/plain")
            elif u.path == "/asset":
                name = Path(q.get("name", [""])[0]).name  # 경로 차단
                fp = ASSETS_DIR / name
                mime = {"js": "text/javascript", "json": "application/json"}.get(fp.suffix.lstrip("."))
                if mime and fp.exists() and fp.parent == ASSETS_DIR:
                    self._send(200, fp.read_bytes(), f"{mime}; charset=utf-8")
                else:
                    self._send(404, b"x", "text/plain")
            elif u.path == "/api/photos":
                self._send(200, json.dumps(_list_photos()).encode())
            elif u.path == "/photo":
                p = _safe_photo(q.get("path", [""])[0])
                if p and q.get("full"):  # 원본 그대로 — 외부 이미지 모델에 넘길 다운로드·복사용
                    import mimetypes

                    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    self._send(200, p.read_bytes(), mime, cache=True)
                    return
                img = _thumb(p, state["thumbs"]) if p else None
                if not img:  # 타일이 '깨진 아이콘'으로만 보이면 원인을 못 찾는다 — 경로를 로그에 남긴다
                    print(f"[webui] /photo 404: {q.get('path', [''])[0]!r}", flush=True)
                self._send(200, img, "image/jpeg", cache=True) if img else self._send(404, b"x", "text/plain")
            elif u.path == "/img":
                img = _sticker_image(q.get("ref", [""])[0])
                self._send(200, img.read_bytes(), "image/png") if (img and img.exists()) else self._send(404, b"x", "text/plain")
            elif u.path == "/api/catalog":
                self._send(200, json.dumps(_catalog_summary()).encode())
            elif u.path == "/api/label/status":
                self._send(200, json.dumps(state["label"]).encode())
            elif u.path == "/api/models":
                self._send(200, json.dumps(_models_info()).encode())
            elif u.path == "/variant-img":
                typ = Path(q.get("type", [""])[0]).name
                val = Path(q.get("value", [""])[0]).name
                fp = PREVIEW_DIR / f"{typ}_{val}.png"
                if fp.exists() and fp.parent == PREVIEW_DIR:
                    self._send(200, fp.read_bytes(), "image/png")
                else:
                    self._send(404, b"x", "text/plain")
            elif u.path == "/api/format":
                self._send(200, json.dumps(_format_summary()).encode())
            elif u.path == "/api/emphasis":
                self._send(200, json.dumps(_emphasis_preview()).encode())
            elif u.path == "/api/prompt":
                kind = (parse_qs(u.query).get("kind", ["place"])[0] or "place")
                self._send(200, json.dumps(_prompt_preview(kind)).encode())
            elif u.path == "/api/thumbprompt":
                from autoblog.thumbnail import load_thumbnail_copy_prompt

                self._send(200, json.dumps({"prompt": load_thumbnail_copy_prompt()}, ensure_ascii=False).encode())
            elif u.path == "/api/style-pool":
                self._send(200, json.dumps(_style_pool_payload(), ensure_ascii=False).encode())
            elif u.path == "/api/categories":
                self._send(200, json.dumps({"categories": _load_categories()}).encode())
            elif u.path == "/api/photo_categories":
                from autoblog.config import load_photo_categories

                self._send(200, json.dumps(load_photo_categories()).encode())
            elif u.path == "/api/prefs":
                self._send(200, json.dumps(_load_prefs()).encode())
            elif u.path == "/api/personas":
                self._send(200, json.dumps(_personas_payload(), ensure_ascii=False).encode())
            elif u.path == "/api/ranks":
                from autoblog.rank import list_entries

                self._send(200, json.dumps({"rows": list_entries()}, ensure_ascii=False).encode())
            elif u.path == "/api/keyword-check":
                from autoblog.rank import keyword_competition

                q = parse_qs(u.query).get("q", [""])[0]
                try:
                    self._send(200, json.dumps(
                        keyword_competition(q), ensure_ascii=False
                    ).encode())
                except Exception as exc:  # noqa: BLE001 — 키 미설정·네트워크 등 안내로 전달
                    self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False).encode())
            elif u.path == "/api/keyword-suggest":
                from autoblog.rank import keyword_suggest

                q = parse_qs(u.query).get("q", [""])[0]
                try:
                    self._send(200, json.dumps(
                        keyword_suggest(q), ensure_ascii=False
                    ).encode())
                except Exception as exc:  # noqa: BLE001 — 키 미설정·네트워크 등 안내로 전달
                    self._send(400, json.dumps({"error": str(exc)}, ensure_ascii=False).encode())
            elif u.path == "/api/searchad-key":
                from autoblog.config import load_env

                self._send(200, json.dumps({"set": load_env().has_searchad}).encode())
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/generate":
                    self._generate(self._json_body())
                elif path == "/api/export-prompt":
                    self._export_prompt(self._json_body())
                elif path == "/api/import-draft":
                    self._import_draft(self._json_body())
                elif path == "/api/prefetch-card":
                    self._prefetch_card(self._json_body())
                elif path == "/api/personas/fetch":
                    self._persona_fetch(self._json_body())
                elif path == "/api/personas/extract":
                    self._persona_extract(self._json_body())
                elif path == "/api/personas/prompt":
                    self._persona_prompt(self._json_body())
                elif path == "/api/personas/save":
                    self._persona_save(self._json_body())
                elif path == "/api/personas/delete":
                    self._persona_delete(self._json_body())
                elif path == "/api/publish":
                    self._publish(self._json_body())
                elif path == "/api/drafts":
                    self._list_drafts()
                elif path == "/api/drafts/import":
                    self._import_draft_photos(self._json_body())
                elif path == "/api/photos/missing":
                    # 탭 복원 상태의 사진 경로 중 '지금 서버가 못 주는 것'을 알려준다.
                    # (앱을 옮기거나 dev↔패키지 앱을 섞어 쓰면 경로가 어긋나 타일이 전부 깨진다)
                    paths = self._json_body().get("paths") or []
                    missing = [p for p in paths if isinstance(p, str) and not _safe_photo(p)]
                    self._send(200, json.dumps({"missing": missing}).encode())
                elif path == "/api/client-error":
                    # 프런트 JS 에러 수신(sendBeacon, text/plain) → ui.log에 스택까지 남긴다.
                    length = int(self.headers.get("Content-Length", 0))
                    msg = self.rfile.read(length).decode("utf-8", "replace")[:4000]
                    print(f"[webui] 프런트 에러: {msg}", flush=True)
                    self._send(200, b"{}")
                elif path == "/api/favorite":
                    body = self._json_body()
                    n = _toggle_favorite(body.get("ref", ""), bool(body.get("on")))
                    self._send(200, json.dumps({"ok": True, "favorites": n}).encode())
                elif path == "/api/sponsor-sticker":
                    body = self._json_body()
                    ref = _set_sponsor_sticker(body.get("ref", ""))
                    self._send(200, json.dumps({"ok": True, "sponsor": ref}).encode())
                elif path == "/api/upload":
                    body = self._json_body()
                    p = _save_upload(body.get("filename", ""), body.get("data", ""))
                    self._send(200, json.dumps({"path": p}).encode())
                elif path == "/api/photos/caption":
                    self._caption_photos(self._json_body())
                elif path == "/api/thumbnail":
                    self._gen_thumbnail(self._json_body())
                elif path == "/api/categories":
                    with state["publish_lock"]:  # 다른 브라우저 작업과 직렬화(세션 충돌 방지)
                        cats = _fetch_categories()
                    state["categories"] = cats
                    self._send(200, json.dumps({"categories": cats}).encode())
                elif path == "/api/sticker-tags":
                    body = self._json_body()
                    out = _set_sticker_tags(body.get("ref", ""), body.get("tags", []))
                    self._send(200, json.dumps(out).encode())
                elif path == "/api/sticker-kind":
                    body = self._json_body()
                    out = _set_sticker_kind(body.get("ref", ""), body.get("kind", ""))
                    self._send(200, json.dumps(out).encode())
                elif path == "/api/prompt":
                    pbody = self._json_body()
                    _save_prompt(pbody.get("base", ""), (pbody.get("kind") or "place"))
                    self._send(200, b'{"ok":true}')
                elif path == "/api/style-pool":
                    payload = _save_style_pool(self._json_body())
                    self._send(200, json.dumps(payload, ensure_ascii=False).encode())
                elif path == "/api/prefs":
                    _save_prefs(self._json_body())
                    self._send(200, b'{"ok":true}')
                elif path == "/api/models":
                    body = self._json_body()
                    if body.get("preset"):
                        _set_model_preset(body["preset"])
                    else:
                        _set_model_selection(body.get("text"), body.get("vision"))
                    self._send(200, b'{"ok":true}')
                elif path == "/api/llm-key":
                    body = self._json_body()
                    _set_llm_key(body.get("provider", "anthropic"), body.get("key", ""))
                    self._send(200, b'{"ok":true}')
                elif path == "/api/searchad-key":
                    # 네이버 검색광고 API(월간 검색량) 키 3종을 .env에 저장
                    from autoblog.config import save_env_value

                    body = self._json_body()
                    vals = {
                        "NAVER_SEARCHAD_API_KEY": (body.get("api_key") or "").strip(),
                        "NAVER_SEARCHAD_SECRET": (body.get("secret") or "").strip(),
                        "NAVER_SEARCHAD_CUSTOMER_ID": (body.get("customer_id") or "").strip(),
                    }
                    if not all(vals.values()):
                        self._send(400, json.dumps(
                            {"error": "액세스라이선스·비밀키·CUSTOMER_ID를 모두 입력하세요"},
                            ensure_ascii=False).encode())
                    else:
                        for k, v in vals.items():
                            save_env_value(k, v)
                        self._send(200, b'{"ok":true}')
                elif path == "/api/format":
                    import yaml

                    body = self._json_body()
                    cfg = _load_format()
                    key = "divider_enabled" if body.get("type") == "divider" else "quote_enabled"
                    lst = list(cfg.get(key) or ["default"])
                    value, on = body.get("value"), bool(body.get("on"))
                    if on and value not in lst:
                        lst.append(value)
                    elif not on and value in lst:
                        lst.remove(value)
                    cfg[key] = lst or ["default"]  # 최소 1개 유지
                    FORMAT_CONFIG_PATH.write_text(
                        yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"
                    )
                    self._send(200, json.dumps({"ok": True, "enabled": cfg[key]}).encode())
                elif path == "/api/emphasis":
                    body = self._json_body()
                    if body.get("config") is not None:
                        _save_emphasis_config(body.get("config"))
                    elif body.get("style") is not None:
                        _save_emphasis_style(body.get("id"), body.get("style"))
                    elif body.get("id") is not None:
                        _save_emphasis_preset_tag(body.get("id"), body.get("tag", ""))
                    self._send(200, json.dumps(_emphasis_preview()).encode())
                elif path == "/api/ranks":
                    from autoblog.rank import add_entry, remove_entry

                    body = self._json_body()
                    if body.get("delete"):
                        remove_entry(body.get("keyword", ""), body.get("url", ""))
                    else:
                        add_entry(body.get("keyword", ""), body.get("url", ""))
                    self._send(200, b'{"ok":true}')
                elif path == "/api/ranks/check":
                    from autoblog.rank import check_all

                    self._send(200, json.dumps({"rows": check_all()}, ensure_ascii=False).encode())
                elif path == "/api/label":
                    lab = state["label"]
                    if lab.get("running"):
                        self._send(200, json.dumps({"running": True, "total": lab["total"]}).encode())
                        return
                    from autoblog.publish.stickers import load_sticker_catalog

                    total = _label_targets(load_sticker_catalog())
                    if total == 0:
                        self._send(200, json.dumps({"total": 0}).encode())
                        return
                    lab.update({"running": True, "done": 0, "total": total})
                    threading.Thread(target=_run_label, args=(state,), daemon=True).start()
                    self._send(200, json.dumps({"total": total}).encode())
                else:
                    self._send(404, b"not found", "text/plain")
            except BrokenPipeError:
                pass  # 클라이언트가 먼저 끊음(새로고침/이탈) — 무시
            except Exception as exc:  # noqa: BLE001
                import traceback

                print(f"[webui] POST {path} 실패: {exc}", flush=True)
                traceback.print_exc()
                try:
                    self._send(500, json.dumps({"error": _friendly_error(exc)}).encode())
                except Exception:  # noqa: BLE001
                    pass

        @staticmethod
        def _resolve_src(body):
            """body의 srcval+kind → (srcval, src) — generate/export 공통 종류 판정."""
            srcval = (body.get("srcval") or "").strip()
            kind = (body.get("kind") or "").strip()
            # 유저가 명시한 선택(kind)을 srcval 유무와 무관하게 존중한다. 상품은 스마트스토어
            # WTM 차단으로 검색어를 비우는 경우가 많은데, 예전엔 srcval이 비면 kind를 버려서
            # 상품 글이 맛집 프롬프트로 떨어졌다(빈 상품 카드는 collect_card가 card_kind로 처리).
            if kind in ("place", "product"):
                return srcval, kind
            is_url = srcval.startswith("http") or "naver.me" in srcval or "place" in srcval
            return srcval, ("place" if (srcval and is_url) else ("product" if srcval else None))

        def _export_prompt(self, body):
            """수집+내 프롬프트+지시문을 한 텍스트로 합쳐 반환(다른 챗봇에 붙여넣기용)."""
            from autoblog.draft.rules import CommonRules
            from autoblog.pipeline import build_export_prompt

            # 리스타일 모드: 생성(/api/generate)과 동일하게 베이스를 restyle.md로 바꾸고
            # 새 수집을 건너뛴다. 안 하면 default.md가 걸려 원문 표·나열을 문장으로 풀어버린다.
            restyle = bool(body.get("restyle"))
            srcval, src = self._resolve_src(body)
            photos = [p for p in (body.get("photos") or []) if p]
            photo_meta = body.get("photoMeta") if isinstance(body.get("photoMeta"), dict) else {}
            tone = (body.get("tone") or "").strip() or None
            style = _style_for(body.get("personaId"), tone)
            rules = CommonRules(**body["rules"]) if body.get("rules") else None
            guidelines = _build_guidelines(body)
            base_prompt = None
            if restyle:
                from autoblog.draft.prompts import load_restyle_prompt

                base_prompt = load_restyle_prompt()
            dkeys, qkeys = _enabled_variant_keys()  # '서식'에서 고른 종류만 프롬프트에 안내

            # 진행 상태를 스트리밍으로 흘려보내며 수집·조립(수집 캐시 재사용으로 반복 호출 빠름)
            self._stream_begin()
            self._stream_write({"stage": "자료를 준비하는 중…"})

            def progress(msg):
                try:
                    self._stream_write({"stage": msg})
                except (BrokenPipeError, OSError):
                    pass  # 클라이언트가 끊어도 수집은 계속 진행

            try:
                text = build_export_prompt(
                    body.get("memo", ""),
                    place_url=None if restyle else (srcval if src == "place" else None),
                    product=None if restyle else (srcval if src == "product" else None),
                    card_kind="place" if restyle else src,
                    place_hint=None if restyle else (body.get("placeHint") or "").strip() or None,
                    base_prompt=base_prompt,
                    photos=photos or None,
                    photo_meta=photo_meta,
                    style=style,
                    rules=rules,
                    guidelines=guidelines,
                    emphasis=bool(body.get("emphasis")),
                    structure=bool(body.get("structure")),
                    stickers=bool(body.get("stickers")),
                    sticker_favorites_only=not bool(body.get("stickerAll")),
                    divider_variants=dkeys,
                    quote_variants=qkeys,
                    use_cache=True,
                    inplace=bool(body.get("inplace")),  # 불러온 글: [영상] 순서 고정 지시 포함
                    restyle=restyle,  # 자가 점검의 해시태그 항목 제외(태그줄 없는 초안)
                    wishlist=bool(body.get("wishlist")),  # 아직 안 산 위시리스트 상품 글(상품 카드에만 적용)
                    consumed=bool(body.get("consumed")),  # 이번에 산 것들 모음 상품 글(상품 카드에만 적용)
                    progress=progress,
                )
            except Exception as exc:  # noqa: BLE001 — 오류도 스트림으로 전달
                self._stream_write({"error": str(exc)})
                return
            self._stream_write({"prompt": text})

        def _prefetch_card(self, body):
            """맛집 URL 붙여넣기 직후 미리 수집(캐시 워밍) — 생성 시 수집 대기 제거.

            ThreadingHTTPServer라 요청 스레드에서 그대로 돌린다. 실패 카드는
            collect_card가 캐시하지 않으므로 '프롬프트 만들기' 때 자동 재시도된다."""
            from autoblog.pipeline import collect_card

            srcval, src = self._resolve_src(body)
            if not srcval or src != "place":
                self._send(200, json.dumps({"ok": False}).encode())
                return
            try:
                card = collect_card(place_url=srcval, use_cache=True)
            except Exception as exc:  # noqa: BLE001 — 미리 수집 실패는 안내만
                self._send(200, json.dumps({"ok": False, "error": str(exc)}).encode())
                return
            name = card.place.name if card.place else None
            self._send(200, json.dumps({"ok": not card.is_fallback, "name": name}).encode())

        def _caption_photos(self, body):
            """온디맨드 '✨ AI 자동 추천' — 사진 맥락 캡션 → [{path,label,caption}]."""
            from autoblog.pipeline import caption_photos

            srcval, src = self._resolve_src(body)
            photos = [p for p in (body.get("photos") or []) if p]
            if not photos:
                self._send(400, json.dumps({"error": "선택된 사진이 없어요"}).encode())
                return
            try:
                items = caption_photos(
                    body.get("memo", ""),
                    place_url=srcval if src == "place" else None,
                    product=srcval if src == "product" else None,
                    photos=photos,
                    review_type=(body.get("reviewType") or src or None),
                    hint=str(body.get("hint") or ""),
                )
            except Exception as exc:  # noqa: BLE001 — 키 미설정/패키지 미설치/API 오류 그대로 안내
                self._send(400, json.dumps({"error": str(exc)}).encode())
                return
            self._send(200, json.dumps({"photos": items}).encode())

        def _gen_thumbnail(self, body):
            """★ 대표사진 → VLM 묘사+FLUX.1-dev(NVIDIA)로 손그림 썸네일 → uploads 저장 → {path}."""
            import uuid

            from autoblog.thumbnail import generate_thumbnail

            photo = _safe_photo(body.get("photo") or "")
            if not photo:
                self._send(400, json.dumps({"error": "대표사진을 찾을 수 없어요"}).encode())
                return
            if is_video(photo.name):
                self._send(
                    400,
                    json.dumps({"error": "영상은 썸네일로 못 만들어요 — 사진을 ★로 지정하세요"}).encode(),
                )
                return
            try:
                png, prompt = generate_thumbnail(
                    str(photo),
                    (body.get("title") or "").strip(),
                    extra=(body.get("extra") or "").strip(),
                )
            except Exception as exc:  # noqa: BLE001 — 키 미설정/API 오류 그대로 안내
                self._send(400, json.dumps({"error": str(exc)}).encode())
                return
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            dest = UPLOAD_DIR / f"thumb_{uuid.uuid4().hex[:8]}.png"
            dest.write_bytes(png)
            self._send(200, json.dumps({"path": str(dest), "prompt": prompt}).encode())

        def _persona_fetch(self, body):
            """블로그 주소 → 인기글 top N 메타데이터(제목·공감수). 본문은 추출 단계에서."""
            from autoblog.collect.blog_posts import fetch_popular_posts, parse_blog_id

            try:
                blog_id = parse_blog_id(body.get("blog", ""))
                posts = fetch_popular_posts(blog_id, n=int(body.get("count") or 5))
            except Exception as exc:  # noqa: BLE001 — 주소 오류/네트워크 그대로 안내
                self._send(400, json.dumps({"error": str(exc)}).encode())
                return
            self._send(
                200,
                json.dumps({"blogId": blog_id, "posts": posts}, ensure_ascii=False).encode(),
            )

        def _persona_extract(self, body):
            """선택한 인기글 본문을 모아 평소 문체 특징(프로필)을 추출(LLM)."""
            from autoblog.collect.blog_posts import collect_style_samples, parse_blog_id
            from autoblog.draft.style import extract_style_profile

            try:
                blog_id = parse_blog_id(body.get("blog", ""))
                log_nos = [str(x) for x in (body.get("logNos") or []) if str(x).strip()]
                samples = collect_style_samples(
                    blog_id, log_nos=log_nos or None, n=int(body.get("count") or 5)
                )
                if not samples:
                    self._send(400, json.dumps({"error": "글 본문을 가져오지 못했어요"}).encode())
                    return
                # model: 프론트에서 고른 키 보유 텍스트 모델(없으면 선택된 기본 모델)
                profile = extract_style_profile(
                    [s["text"] for s in samples],
                    model=(body.get("model") or "").strip() or None,
                )
            except Exception as exc:  # noqa: BLE001
                self._send(400, json.dumps({"error": str(exc)}).encode())
                return
            sources = [{"title": s.get("title", ""), "url": s.get("url", "")} for s in samples]
            self._send(
                200,
                json.dumps({"profile": profile, "sources": sources}, ensure_ascii=False).encode(),
            )

        def _persona_prompt(self, body):
            """선택한 글 본문 + 분석 지시를 합친 '문체 분석 프롬프트'를 반환(LLM 미호출).

            API 키가 없을 때 사용자가 ChatGPT·Claude 등에 그대로 붙여넣어 쓰는 용도.
            """
            from autoblog.collect.blog_posts import collect_style_samples, parse_blog_id
            from autoblog.draft.style import build_style_prompt

            try:
                blog_id = parse_blog_id(body.get("blog", ""))
                log_nos = [str(x) for x in (body.get("logNos") or []) if str(x).strip()]
                samples = collect_style_samples(
                    blog_id, log_nos=log_nos or None, n=int(body.get("count") or 5)
                )
                if not samples:
                    self._send(400, json.dumps({"error": "글 본문을 가져오지 못했어요"}).encode())
                    return
                prompt = build_style_prompt([s["text"] for s in samples])
            except Exception as exc:  # noqa: BLE001
                self._send(400, json.dumps({"error": str(exc)}).encode())
                return
            self._send(200, json.dumps({"prompt": prompt}, ensure_ascii=False).encode())

        def _persona_save(self, body):
            """추출·편집한 문체를 이름표와 함께 저장(같은 id면 갱신).

            ChatGPT 등에서 붙여넣은 분석 결과도 기본 페르소나와 같은 형식으로 정돈해 저장.
            """
            from autoblog.draft.persona import Persona, PersonaSource, save_persona
            from autoblog.draft.style import normalize_profile

            name = (body.get("name") or "").strip()
            profile = normalize_profile((body.get("profile") or "").strip())
            if not name or not profile:
                self._send(400, json.dumps({"error": "이름과 문체 내용을 모두 채워주세요"}).encode())
                return
            sources = [
                PersonaSource(title=s.get("title", ""), url=s.get("url", ""))
                for s in (body.get("sources") or [])
                if isinstance(s, dict)
            ]
            persona = Persona(
                name=name, blog=(body.get("blog") or "").strip(), profile=profile, sources=sources
            )
            if body.get("id"):
                persona.id = str(body["id"])
            saved = save_persona(persona)
            self._send(200, saved.model_dump_json().encode())

        def _persona_delete(self, body):
            from autoblog.draft.persona import delete_persona

            delete_persona((body.get("id") or "").strip())
            self._send(200, b'{"ok":true}')

        def _generate(self, body):
            from autoblog.draft.rules import CommonRules
            from autoblog.pipeline import run_pipeline

            # 리스타일 모드: 메모칸에 붙여넣은 '완성된 외부 초안'에 내 문체·이모티콘만 다시
            # 입힌다. 맛집/상품 구조를 강제하지 않도록 베이스 프롬프트를 restyle.md로 바꾸고,
            # 새로 수집(place/product)하지 않는다(사진 분류만 유지). 나머지 파이프라인은 동일.
            restyle = bool(body.get("restyle"))
            srcval, src = self._resolve_src(body)
            photos = [p for p in (body.get("photos") or []) if p]
            photo_meta = body.get("photoMeta") if isinstance(body.get("photoMeta"), dict) else {}
            tone = (body.get("tone") or "").strip() or None
            style = _style_for(body.get("personaId"), tone)
            rules = CommonRules(**body["rules"]) if body.get("rules") else None
            guidelines = _build_guidelines(body)
            base_prompt = None
            if restyle:
                from autoblog.draft.prompts import load_restyle_prompt

                base_prompt = load_restyle_prompt()
            dv, qv = _enabled_variants()  # 활성 종류 중 첫 번째를 기본 적용(다중 중 우선)
            dkeys, qkeys = _enabled_variant_keys()  # 프롬프트에 안내할 고른 종류 전체
            result = run_pipeline(
                body["memo"],
                place_url=None if restyle else (srcval if src == "place" else None),
                product=None if restyle else (srcval if src == "product" else None),
                card_kind="place" if restyle else src,
                place_hint=None if restyle else (body.get("placeHint") or "").strip() or None,
                base_prompt=base_prompt,
                photos=photos or None,
                photo_meta=photo_meta,
                style=style,
                rules=rules,
                guidelines=guidelines,
                emphasis=bool(body.get("emphasis")),
                structure=bool(body.get("structure")),
                stickers=bool(body.get("stickers")),
                sticker_favorites_only=not bool(body.get("stickerAll")),
                divider_variant=dv[0],
                quote_variant=qv[0],
                divider_variants=dkeys,
                quote_variants=qkeys,
                sponsored=bool(body.get("sponsored")),
                sponsor_links=_links(body),
                product_links=_links(body, "productLinks"),
                sponsor_sticker=(body.get("sponsorSticker") or "").strip(),
                use_cache=True,  # 같은 URL 재수집 방지(export/캡션과 캐시 공유)
                inplace=bool(body.get("inplace")),  # 불러온 글 in-place 편집(사진 재정렬 휴리스틱 끔)
                restyle=restyle,  # 자가 점검의 해시태그 항목 제외(태그줄 없는 초안)
                wishlist=bool(body.get("wishlist")),  # 아직 안 산 위시리스트 상품 글(상품 카드에만 적용)
                consumed=bool(body.get("consumed")),  # 이번에 산 것들 모음 상품 글(상품 카드에만 적용)
            )
            self._send_plan(result, draft_id=(body.get("draftId") or "").strip() or None)

        def _import_draft(self, body):
            """외부 챗봇에서 받아온 초안 텍스트 → 마커 파싱 → 게시 플랜(생성과 동일 흐름)."""
            from autoblog.pipeline import _place_info, cached_place_card, plan_from_text

            text = (body.get("text") or "").strip()
            if not text:
                self._send(400, json.dumps({"error": "붙여넣은 글이 비어 있어요"}).encode())
                return
            photos = [p for p in (body.get("photos") or []) if p]
            photo_meta = body.get("photoMeta") if isinstance(body.get("photoMeta"), dict) else {}
            # 플레이스 URL이 있으면 세션 캐시에 수집된 가게 카드에서 [지도] 마커용
            # 가게명·도로명 주소를 채운다(생성 경로와 동일). 캐시에 없으면 None → [지도:가게명] 폴백.
            place_query = place_address = None
            srcval, src = self._resolve_src(body)
            if src == "place" and srcval:
                card = cached_place_card(srcval)
                if card is not None:
                    _, place_query, place_address = _place_info(card)
                if not place_query:
                    # 캐시 미스(앱 재시작 등)여도 [지도]가 조용히 사라지지 않게 수집링크를
                    # 그대로 넘긴다 — plan이 URL을 실시간으로 가게명·주소로 해석하고,
                    # 실패하면 URL 텍스트가 남아 에디터 단계 '지도 삽입 실패' 경고로 드러난다.
                    place_query = srcval
            dv, qv = _enabled_variants()
            result = plan_from_text(
                text,
                photos=photos or None,
                photo_meta=photo_meta,
                emphasis=bool(body.get("emphasis")),
                structure=bool(body.get("structure")),
                stickers=bool(body.get("stickers")),
                sticker_favorites_only=not bool(body.get("stickerAll")),
                divider_variant=dv[0],
                quote_variant=qv[0],
                place_query=place_query,
                place_address=place_address,
                sponsored=bool(body.get("sponsored")),
                sponsor_links=_links(body),
                product_links=_links(body, "productLinks"),
                sponsor_sticker=(body.get("sponsorSticker") or "").strip(),
                guidelines=_build_guidelines(body),  # 받아온 글도 생성과 동일하게 자동 대조
            )
            self._send_plan(result, draft_id=(body.get("draftId") or "").strip() or None)

        def _send_plan(self, result, draft_id: str | None = None):
            """PipelineResult → {title, blocks, debug} JSON. generate/import 공통.

            draft_id(탭 id)가 오면 그 글을 state["drafts"]에 id로 보관해, 나중에 게시가
            '그 탭의 글'을 정확히 집어 저장하게 한다(여러 탭이 state["last"]를 덮어써도 안전).
            """
            state["last"] = result
            if draft_id:
                drafts = state["drafts"]
                drafts[draft_id] = result
                # 무한증식 방지: 삽입 순서상 가장 오래된 것부터 버려 최근 30개만 유지.
                while len(drafts) > 30:
                    drafts.pop(next(iter(drafts)))
            blocks = []
            for b in result.plan.blocks:
                blk = {"kind": b.kind, "text": b.text, "variant": b.variant, "align": b.align}
                if b.kind == "sticker":
                    blk["sticker_ref"] = f"{b.sticker_pack}:{b.sticker_index}"
                elif b.kind in ("image", "video"):
                    blk["image_path"] = b.image_path
                    blk["image_label"] = b.image_label
                elif b.kind == "link":
                    blk["link_url"] = b.link_url
                elif b.kind == "table":
                    blk["table_rows"] = b.table_rows
                elif b.kind == "text":
                    blk["emphases"] = [
                        {"text": e.text, "text_color": e.style.text_color,
                         "background_color": e.style.background_color,
                         "font_family": e.style.font_family,
                         "font_size": e.style.font_size,
                         "bold": e.style.bold}
                        for e in b.emphases
                    ]
                blocks.append(blk)
            self._send(200, json.dumps(
                {"title": result.plan.title, "blocks": blocks, "tags": result.plan.tags,
                 "debug": result.draft.debug,
                 "checklist": [
                     {"item": c.item, "ok": c.ok, "detail": c.detail}
                     for c in result.draft.checklist
                 ]}
            ).encode())

        def _publish(self, body):
            import uuid as _uuid

            from autoblog.publish.editor import BlogPublisher

            jobs = state["jobs"]
            # 재시도 요청(retryJob=작업id): 처음 저장 때 잡아둔 그 글의 스냅샷을 그대로 다시 쓴다.
            # 유저가 이미 다음 글로 넘어가 state["last"]가 바뀌었어도, '실패한 그 글'을 저장한다.
            retry_id = (body.get("retryJob") or "").strip() or None
            if retry_id:
                snap = jobs.get(retry_id)
                if not snap:
                    self._send(400, json.dumps(
                        {"error": "다시 시도할 저장 작업을 찾지 못했어요(서버가 다시 시작됐을 수 있어요)"}
                    ).encode())
                    return
                job_id = retry_id
                result = snap["result"]
                category = snap["category"]
                prune = snap["prune"]
                imported = snap["imported"]
                inplace_draft = snap["inplace_draft"]
                reserve_at = snap.get("reserve_at")
            else:
                # 게시할 플랜은 '요청이 들어온 시점'의 초안으로 고정한다(락 대기 전에 스냅샷).
                # 유저가 저장을 누른 뒤 곧바로 새 글을 써서 state["last"]가 바뀌어도,
                # 이 요청은 방금 누른 그 글을 저장한다(연속 저장이 안 섞이게).
                # 멀티 탭: 요청이 draftId(탭 id)를 주면 그 탭의 글을 정확히 집는다.
                # 없거나 못 찾으면 가장 최근 글(state["last"])로 폴백(단일 탭 하위호환).
                draft_id = (body.get("draftId") or "").strip() or None
                result = (state["drafts"].get(draft_id) if draft_id else None) or state.get("last")
                if not result:
                    self._send(400, json.dumps({"error": "먼저 초안을 생성하세요"}).encode())
                    return
                category = (body.get("category") or "").strip() or None
                prefs0 = _load_prefs()
                prune = bool(prefs0.get("pruneDrafts", True))  # 설정 토글(기본 켬)
                # 사진을 가져왔던 원본 임시저장 글(있으면). 저장 직후 그 글을 삭제한다.
                imported = body.get("importedDraft") if prune else None
                if not isinstance(imported, dict) or not (imported.get("title") or "").strip():
                    imported = None
                # 불러온 글 in-place 편집 요청(불러오기로 들어온 글). 있으면 원본을 '갱신'한다
                # — 새 글 생성·원본 삭제·사진 재업로드 없이, 기존 사진/영상 사이에 본문만 끼워 넣는다.
                inplace_draft = body.get("inplaceDraft") if body.get("inplace") else None
                if not isinstance(inplace_draft, dict) or not (inplace_draft.get("title") or "").strip():
                    inplace_draft = None
                # 예약 발행 시각(로컬 naive, 예: "2026-07-22T15:30"). 새 글에만 적용(in-place 제외).
                # 파싱 실패·과거 시각이면 400. 예약 경로는 editor에서 fail-closed(미준비면 발행 안 함).
                reserve_at = None
                reserve_raw = (body.get("reserveAt") or "").strip()
                if reserve_raw and not inplace_draft:
                    from datetime import datetime as _dt

                    try:
                        reserve_at = _dt.fromisoformat(reserve_raw)
                    except ValueError:
                        self._send(400, json.dumps(
                            {"error": "예약 시각 형식이 올바르지 않아요"}, ensure_ascii=False
                        ).encode())
                        return
                    if reserve_at <= _dt.now():
                        self._send(400, json.dumps(
                            {"error": "예약 시각은 미래여야 해요"}, ensure_ascii=False
                        ).encode())
                        return
                # 플랜 생성 '뒤'에 바뀐 ★ 대표·AI 표시(AI 썸네일 적용·사진 대체)를 굳은 플랜에
                # 덧반영 — 안 하면 새 이미지가 본문에 안 들어가고 대표도 옛 사진으로 지정된다.
                photo_meta = body.get("photoMeta")
                if isinstance(photo_meta, dict) and photo_meta:
                    from autoblog.publish.plan import apply_photo_meta_overrides

                    apply_photo_meta_overrides(result.plan, photo_meta)
                # 미리보기에서 직접 고친 발행 태그 — 굳은 플랜의 태그를 덮어쓴다
                # (태그가 빈 초안도 유저가 채워 넣을 수 있게). 스냅샷 전이라 재시도에도 반영.
                tags = body.get("tags")
                if isinstance(tags, list):
                    result.plan.tags = [
                        c for c in (str(t).strip().lstrip("#").strip() for t in tags) if c
                    ][:30]
                # 이 글의 저장 옵션·플랜을 작업id로 스냅샷해 둔다 — 실패 시 재시도(retryJob)가 참조한다.
                job_id = _uuid.uuid4().hex[:12]
                jobs[job_id] = {
                    "result": result, "category": category, "prune": prune,
                    "imported": imported, "inplace_draft": inplace_draft,
                    "reserve_at": reserve_at,
                }

            prefs = _load_prefs()
            # 디버그 토글이 켜져 있으면 저장 과정을 화면에 띄워(headful) 직접 보게 한다(기본 끔=백그라운드).
            headless = not bool(prefs.get("saveDebug", False))
            # 불러오기(in-place) 시 원본 글의 기존 제목·본문·장식을 비우고 새로 쓸지(설정 토글, 기본 켬).
            clean_imported = bool(prefs.get("cleanImported", True))
            # AI 생성 이미지(FLUX 썸네일 등)에 네이버 'AI 활용' 표시를 켤지(설정 토글, 기본 켬).
            mark_ai = bool(prefs.get("markAiImages", True))

            try:
                # 연속으로 저장을 눌러도 한 건씩 순서대로 처리한다(대기열). 락을 못 잡으면
                # 앞 건이 끝날 때까지 이 스레드가 대기 → 브라우저가 하나만 뜬다.
                with state["publish_lock"]:
                    # 임시저장(submit=False)은 사람 확인이 필요 없으니 평소엔 백그라운드(headless).
                    # 세션이 없으면 wait_for_login이 headful로 재기동해 직접 로그인하게 한다.
                    pub = BlogPublisher(headless=headless)
                    pub.start()
                    try:
                        if not pub.wait_for_login():
                            raise RuntimeError("네이버 로그인이 필요합니다")
                        if inplace_draft:
                            photo_paths = [
                                ph.path for ph in result.card.photos
                                if getattr(ph, "media_kind", "image") != "video"
                            ]
                            warnings, infos = pub.publish_inplace(
                                result.plan,
                                draft_title=inplace_draft.get("title") or "",
                                draft_date=inplace_draft.get("date") or "",
                                photo_paths=photo_paths,
                                category=category,
                                save=True,
                                clean_imported=clean_imported,
                                mark_ai=mark_ai,
                            )
                        else:
                            infos = []
                            warnings = pub.publish(
                                result.plan,
                                category=category,
                                save=True,
                                submit=False,
                                reserve_at=reserve_at,
                                prune_same_title=prune,
                                delete_imported=imported,
                                mark_ai=mark_ai,
                            )
                    finally:
                        pub.close()
            except Exception as exc:  # noqa: BLE001 — 실패해도 스냅샷을 남겨 상단 탭에서 재시도 가능
                import traceback

                print(f"[webui] POST /api/publish 실패: {exc}", flush=True)
                traceback.print_exc()
                self._send(500, json.dumps(
                    {"error": _friendly_error(exc), "jobId": job_id}
                ).encode())
                return
            jobs.pop(job_id, None)  # 성공 → 스냅샷 정리(더는 재시도 불필요)
            self._send(200, json.dumps(
                {"ok": True, "warnings": warnings or [],
                 "infos": infos or [], "jobId": job_id}
            ).encode())

        def _list_drafts(self):
            """네이버 임시저장 글 목록을 읽어 [{idx,title,date}]로 반환."""
            from autoblog.publish.editor import BlogPublisher

            # 게시와 같은 락으로 직렬화한다. 같은 네이버 세션을 쓰는 브라우저가 동시에 뜨면
            # '작성 중이던 글' 이어쓰기 팝업 등이 겹쳐 클릭이 막힌다(딤 인터셉트).
            with state["publish_lock"]:
                pub = BlogPublisher(headless=True)
                pub.start()
                try:
                    if not pub.wait_for_login():
                        raise RuntimeError("네이버 로그인이 필요합니다")
                    drafts = pub.list_drafts()
                finally:
                    pub.close()
            self._send(200, json.dumps({"drafts": drafts}).encode())

        def _import_draft_photos(self, body):
            """선택한 임시저장 글(idx)의 본문 미디어를 문서 순서대로 반환.

            사진은 다운로드해 경로를 주고, 영상은 재업로드 불가라 빈 placeholder 경로만 준다.
            프론트는 이 순서를 유지해 영상 타일도 함께 띄우고(유저가 캡션), 재료·플랜이 영상
            위치를 알게 한다. 하위호환으로 paths(사진만)도 함께 내려준다."""
            from autoblog.publish.editor import BlogPublisher

            try:
                idx = int(body.get("idx"))
            except (TypeError, ValueError):
                self._send(400, json.dumps({"error": "idx가 필요합니다"}).encode())
                return
            # 게시와 같은 락으로 직렬화(동시 브라우저→세션 충돌·이어쓰기 팝업 겹침 방지).
            with state["publish_lock"]:
                pub = BlogPublisher(headless=True)
                pub.start()
                try:
                    if not pub.wait_for_login():
                        raise RuntimeError("네이버 로그인이 필요합니다")
                    manifest = pub.import_draft_media(idx, UPLOAD_DIR)
                finally:
                    pub.close()
            # 프론트로: 사진·영상은 경로 있는 미디어로, 콜라주(고정 앵커)는 경로 없이 종류만.
            media = [m for m in manifest if m.get("path")]
            paths = [m["path"] for m in media if m["kind"] == "image"]
            self._send(200, json.dumps({"media": media, "paths": paths}).encode())

    return Handler


FORMAT_CONFIG_PATH = USER_CONFIG_DIR / "format.yaml"  # 유저가 서식 저장 → 쓰기
PREVIEW_DIR = CONFIG_DIR / "editor_previews"  # 번들 자산(읽기전용)
PREFS_PATH = USER_CONFIG_DIR / "ui_prefs.json"  # 유저 설정 → 쓰기

# 글쓰기 화면 기본 설정(서버가 기준). 새 키가 추가돼도 저장본 위에 머지된다.
DEFAULT_MIN_CHARS = 1500  # 글자 수를 따로 안 넣으면 기본 최소 글자 수

_PREFS_DEFAULT = {
    "rules": {
        "mobile_friendly": True, "authenticity": True,
        "structure_guide": True, "seo": True, "emoji": False,
    },
    "fmt": {
        "emphasis": True, "structure": True, "stickers": True,
        "stickerAll": False, "hideDefault": True,
        "sponsored": False, "sponsorSticker": "",
    },
    "tone": "",
    "personaId": "",  # 글쓰기에서 선택한 문체 페르소나(config/personas.json의 id)
    "keywords": "",
    "minChars": DEFAULT_MIN_CHARS,
    "category": "",
    # 임시저장 시 같은 제목의 이전 임시저장 글 자동 정리(기본 켬). asked는 최초 1회 안내 노출 여부.
    "pruneDrafts": True,
    "pruneDraftsAsked": False,
    # 디버그: 임시저장 시 브라우저를 화면에 띄워(headful) 작업 과정을 직접 본다(기본 끔=백그라운드).
    "saveDebug": False,
    # 불러오기(in-place) 시 원본 글의 기존 제목·본문·스티커·지도 등을 비우고 새로 작성(기본 켬).
    "cleanImported": True,
    # AI 생성 이미지(FLUX 썸네일·외부 AI 대체)에 네이버 'AI 활용' 표시를 켬(자율 표기, 기본 켬).
    "markAiImages": True,
}


def _personas_payload() -> dict:
    """저장된 문체 페르소나 + 내장 어투 프리셋 목록(관리·선택 UI용)."""
    from autoblog.draft.persona import load_personas
    from autoblog.draft.tones import load_tones

    return {
        "personas": [p.model_dump() for p in load_personas()],
        "tones": [
            {"id": t.id, "name": t.name, "desc": t.desc, "default": t.default}
            for t in load_tones()
        ],
    }


def _style_for(persona_id, tone):
    """선택한 문체(내장 프리셋 'tone:<id>' 또는 페르소나 id) + 이번 글 톤 → StyleProfile.

    아무것도 안 고르면 None — generate가 기본 어투 프리셋(effective_style)을 채운다.
    id가 유효하지 않으면 무시하고 톤만 적용한다(역시 기본 프리셋으로 폴백).
    """
    from autoblog.draft.persona import get_persona
    from autoblog.draft.style import StyleProfile

    pid = str(persona_id or "")
    if pid.startswith("tone:"):
        from autoblog.draft.tones import get_tone

        preset = get_tone(pid[len("tone:"):])
        if preset:
            return StyleProfile(profile=preset.prompt, tone=tone, ornaments=preset.ornaments)
        pid = ""  # 모르는 프리셋 id → 기본 어투와 동일 취급
    profile = None
    if pid:
        persona = get_persona(pid)
        if persona:
            profile = persona.profile
    if profile or tone:
        return StyleProfile(profile=profile, tone=tone)
    return None


def _build_guidelines(body: dict):
    """요청 body의 키워드·글자수 입력으로 Guidelines를 만든다(둘 다 비어도 글자수 기본 적용).

    keywords: 쉼표/줄바꿈으로 구분한 필수 키워드. minChars: 최소 글자 수(빈 값이면 1500).
    """
    import re

    from autoblog.draft.guideline import Guidelines

    raw_kw = body.get("keywords") or ""
    keywords = [k.strip() for k in re.split(r"[,\n]", raw_kw) if k.strip()]
    raw_min = body.get("minChars")
    try:
        min_chars = int(raw_min)
    except (TypeError, ValueError):
        min_chars = DEFAULT_MIN_CHARS
    if min_chars <= 0:
        min_chars = DEFAULT_MIN_CHARS
    return Guidelines(required_keywords=keywords, min_chars=min_chars)


def _load_prefs() -> dict:
    """저장된 글쓰기 설정(없거나 깨지면 기본값). 기본값 위에 저장본을 머지해 반환."""
    try:
        saved = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _PREFS_DEFAULT.items()}
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def _save_prefs(body: dict) -> None:
    """들어온 일부 키만 머지 저장(rules/fmt는 dict 머지, tone은 교체)."""
    cur = _load_prefs()
    for k in ("rules", "fmt"):
        if isinstance(body.get(k), dict):
            cur[k].update(body[k])
    if "tone" in body:
        cur["tone"] = body.get("tone") or ""
    if "personaId" in body:
        cur["personaId"] = body.get("personaId") or ""
    if "keywords" in body:
        cur["keywords"] = body.get("keywords") or ""
    if "minChars" in body:
        try:
            cur["minChars"] = int(body.get("minChars"))
        except (TypeError, ValueError):
            cur["minChars"] = DEFAULT_MIN_CHARS
    if "category" in body:
        cur["category"] = body.get("category") or ""
    if "pruneDrafts" in body:
        cur["pruneDrafts"] = bool(body.get("pruneDrafts"))
    if "pruneDraftsAsked" in body:
        cur["pruneDraftsAsked"] = bool(body.get("pruneDraftsAsked"))
    if "saveDebug" in body:
        cur["saveDebug"] = bool(body.get("saveDebug"))
    if "cleanImported" in body:
        cur["cleanImported"] = bool(body.get("cleanImported"))
    if "markAiImages" in body:
        cur["markAiImages"] = bool(body.get("markAiImages"))
    PREFS_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_format() -> dict:
    import yaml

    try:
        return yaml.safe_load(FORMAT_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}


def _format_summary() -> dict:
    """구분선/인용구 종류 목록(이름·용도·인덱스) + 유저가 쓸 종류(다중 선택)."""
    from autoblog.publish.plan import DIVIDER_META, QUOTE_META

    cfg = _load_format()
    den = cfg.get("divider_enabled") or ["default"]
    qen = cfg.get("quote_enabled") or ["default"]

    def build(meta, enabled):
        return [
            {"value": v, "index": idx, "name": name, "desc": desc, "enabled": v in enabled}
            for v, (idx, name, desc) in meta.items()
        ]

    return {"dividers": build(DIVIDER_META, den), "quotes": build(QUOTE_META, qen)}


def _links(body: dict, key: str = "links") -> list[str]:
    """요청 바디의 링크 목록(links=쿠팡파트너스, productLinks=상품 필수 링크) → 공백 제거 URL."""
    return [u.strip() for u in (body.get(key) or []) if isinstance(u, str) and u.strip()]


def _enabled_variant_keys() -> tuple[list[str], list[str]]:
    """현재 활성화된 구분선/인용구 종류 키 목록(프롬프트 안내에 사용)."""
    from autoblog.publish.plan import DIVIDER_META, QUOTE_META

    cfg = _load_format()
    den = [v for v in (cfg.get("divider_enabled") or ["default"]) if v in DIVIDER_META]
    qen = [v for v in (cfg.get("quote_enabled") or ["default"]) if v in QUOTE_META]
    return den or ["default"], qen or ["default"]


def _enabled_variants() -> tuple[list[int], list[int]]:
    """현재 활성화된 구분선/인용구 variant 인덱스 목록(생성에 사용)."""
    from autoblog.publish.plan import DIVIDER_META, QUOTE_META

    den, qen = _enabled_variant_keys()
    dv = [DIVIDER_META[v][0] for v in den]
    qv = [QUOTE_META[v][0] for v in qen]
    return dv or [1], qv or [1]


def _editor_options() -> dict:
    """라이브 캡처한 에디터 실제 옵션(config/editor_options.json). 없으면 빈 dict."""
    p = CONFIG_DIR / "editor_options.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


# 스마트에디터 글자 크기 옵션(fs<N>) — 본문 기본은 15.
_EDITOR_FONT_SIZES = [11, 13, 15, 16, 19, 24, 28, 30, 34, 38]


def _size_num(size) -> str | None:
    """'16px'/'16'/16 → '16'. 빈 값이면 None."""
    if size in (None, ""):
        return None
    return str(size).strip().lower().replace("px", "") or None


def _emphasis_preview() -> dict:
    """현재 강조 설정으로 실제 적용될 색을 해석(미리보기).

    프로젝트 프리셋(config/power_shortcuts.json)이 있으면 그 색으로, 없으면 내장 기본으로 해석.
    """
    from autoblog.publish.emphasis import (
        DEFAULT_STYLES,
        build_emphasis_instruction,
        load_default_power_shortcuts,
        load_emphasis_config,
    )

    cfg = load_emphasis_config()
    # 색(번호)별 기본 시드 — 있으면 파워 단축키 프리셋, 없으면 내장 기본. 그 위에 사용자가
    # 서식 탭에서 직접 편집한 styles를 덮어쓴다(색·폰트·크기는 사용자 편집이 최우선).
    presets = dict(load_default_power_shortcuts() or DEFAULT_STYLES)
    presets.update(cfg.styles)
    source = "내 설정" if cfg.styles else "기본값(편집 가능)"
    font_opts = _editor_options().get("fonts", [])
    fonts = {f.get("value"): f.get("name", "").split("\n")[0] for f in font_opts}

    # 프리셋ID → 태그(용도). preset_tags가 있으면 그대로, 없으면 레거시에서 파생해 보여준다.
    pools = cfg.tag_pools()
    tag_of = {pid: tag for tag, ids in pools.items() for pid in ids}

    def resolve(pid):
        st = presets.get(pid)
        base = {"id": pid, "tag": tag_of.get(pid, ""), "edited": pid in cfg.styles}
        if not st:
            return {**base, "defined": False}
        return {**base, "defined": True, "text_color": st.text_color,
                "background_color": st.background_color, "bold": st.bold,
                "font": st.font_family, "font_name": fonts.get(st.font_family),
                "size": _size_num(st.font_size)}

    all_styles = [resolve(i) for i in sorted(presets)]
    # 같은 태그가 몇 색에 걸렸는지(순환 여부 표시용)
    groups = [{"tag": t, "ids": ids} for t, ids in pools.items()]
    # 드롭다운에 보여줄 갈래 = 기본(강조/주의/부정) + 사용자가 이미 쓴 갈래(중복 제거, 순서 유지)
    from autoblog.publish.emphasis import DEFAULT_LANES, LANE_DESC

    lane_names = list(dict.fromkeys([*DEFAULT_LANES, *pools.keys()]))
    lanes = [{"name": t, "desc": LANE_DESC.get(t, t)} for t in lane_names]
    # 색마다 직접 고를 폰트·크기 후보(에디터 실제 옵션). 폰트는 value 있는 것만, 맨 앞에 '기본'.
    font_choices = [{"value": "", "name": "기본"}] + [
        {"value": f["value"], "name": f.get("name", "").split("\n")[0]}
        for f in font_opts if f.get("value")
    ]
    return {
        "source": source,
        "all": all_styles,
        "groups": groups,
        "lanes": lanes,
        "fonts": font_choices,
        "sizes": _EDITOR_FONT_SIZES,
        "config": {
            "cycling_pool": cfg.cycling_pool,
            "negative_pool": cfg.negative_pool,
            "fixed_map": cfg.fixed_map,
            "max_per_paragraph": cfg.max_per_paragraph,
            "min_per_paragraph": cfg.min_per_paragraph,
            "min_sentence_gap": cfg.min_sentence_gap,
        },
        # LLM에게 실제로 들어가는 강조 지시문(가시성 — 어떻게 쓰이는지 그대로 보여줌)
        "instruction": build_emphasis_instruction(cfg),
        "max_per_paragraph": cfg.max_per_paragraph,
        "min_per_paragraph": cfg.min_per_paragraph,
        "min_sentence_gap": cfg.min_sentence_gap,
    }


def _save_emphasis_config(data: dict) -> None:
    """config/emphasis.yaml에서 순환 풀·고정 매핑·밀도 설정을 저장."""
    import re

    import yaml

    from autoblog.publish.emphasis import _EMPHASIS_CONFIG_PATH, load_emphasis_config

    cfg = load_emphasis_config()
    if "cycling_pool" in data:
        cfg.cycling_pool = [int(x) for x in (data.get("cycling_pool") or []) if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]
    if "negative_pool" in data:
        cfg.negative_pool = [int(x) for x in (data.get("negative_pool") or []) if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]
    if "fixed_map" in data:
        fixed = {}
        for k, v in (data.get("fixed_map") or {}).items():
            try:
                fixed[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
        cfg.fixed_map = fixed
    if "max_per_paragraph" in data:
        cfg.max_per_paragraph = int(data["max_per_paragraph"]) if data.get("max_per_paragraph") not in (None, "") else None
    if "min_per_paragraph" in data:
        cfg.min_per_paragraph = int(data["min_per_paragraph"]) if data.get("min_per_paragraph") not in (None, "") else None
    if "min_sentence_gap" in data:
        cfg.min_sentence_gap = int(data["min_sentence_gap"]) if data.get("min_sentence_gap") not in (None, "") else None

    path = _EMPHASIS_CONFIG_PATH
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    # 밀도 블록 헤더 주석(중복 누적 방지) + 각 키 제거 후 끝에 다시 쓴다.
    # 주의: (?m)만 — DOTALL(s)을 쓰면 .* 가 줄바꿈을 넘어 파일 끝까지 먹어 뒤 블록을 통째로 삭제한다.
    raw = re.sub(r"\n*# 강조 배정 설정 \(서식 탭에서 편집\)[^\n]*\n", "\n", raw)
    raw = re.sub(r"(?m)^cycling_pool:\n(?:[ \t]+.*\n?)*", "", raw)
    raw = re.sub(r"(?m)^negative_pool:\n(?:[ \t]+.*\n?)*", "", raw)
    raw = re.sub(r"(?m)^fixed_map:\n(?:[ \t]+.*\n?)*", "", raw)
    raw = re.sub(r"(?m)^max_per_paragraph:.*\n?", "", raw)
    raw = re.sub(r"(?m)^min_per_paragraph:.*\n?", "", raw)
    raw = re.sub(r"(?m)^min_sentence_gap:.*\n?", "", raw)
    body = {}
    if cfg.cycling_pool:
        body["cycling_pool"] = cfg.cycling_pool
    if cfg.negative_pool:
        body["negative_pool"] = cfg.negative_pool
    if cfg.fixed_map:
        body["fixed_map"] = cfg.fixed_map
    if cfg.max_per_paragraph is not None:
        body["max_per_paragraph"] = cfg.max_per_paragraph
    if cfg.min_per_paragraph is not None:
        body["min_per_paragraph"] = cfg.min_per_paragraph
    if cfg.min_sentence_gap is not None:
        body["min_sentence_gap"] = cfg.min_sentence_gap
    block = ""
    if body:
        block = (
            "\n# 강조 배정 설정 (서식 탭에서 편집) — 순환 풀, 고정 매핑, 밀도 규칙\n"
            + yaml.safe_dump(body, allow_unicode=True, sort_keys=False)
        )
    path.write_text(raw.rstrip("\n") + "\n" + block, encoding="utf-8")


def _save_emphasis_style(preset_id, style: dict) -> None:
    """색(프리셋ID)의 글자색·배경·굵게·폰트·크기를 config/emphasis.yaml의 styles에 저장.

    서식 탭에서 색마다 직접 편집한 값. 모든 속성이 비면 해당 색의 사용자 설정을 제거(= 기본으로 복귀).
    기존 주석·내용은 보존하고 styles 블록만 교체한다.
    """
    import re

    import yaml

    from autoblog.publish.emphasis import (
        _EMPHASIS_CONFIG_PATH,
        EmphasisStyle,
        load_emphasis_config,
    )

    try:
        pid = int(preset_id)
    except (TypeError, ValueError):
        return

    style = style or {}
    tc = (style.get("text_color") or "").strip() or None
    bg = (style.get("background_color") or "").strip() or None
    font = (style.get("font") or "").strip() or None
    size = _size_num(style.get("size"))
    bold = bool(style.get("bold"))
    st = EmphasisStyle(text_color=tc, background_color=bg, font_family=font,
                       font_size=size, bold=bold)

    styles = {int(k): v for k, v in (load_emphasis_config().styles or {}).items()}
    if st.is_empty():
        styles.pop(pid, None)
    else:
        styles[pid] = st

    path = _EMPHASIS_CONFIG_PATH
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    raw = re.sub(r"\n*# 색\(강조\)별 글자색[^\n]*\n", "\n", raw)
    raw = re.sub(r"(?m)^styles:\n(?:[ \t]+.*\n?)*", "", raw)
    block = ""
    if styles:
        # 빈 속성은 빼고 깔끔히 덤프(색마다 설정한 값만).
        dump = {
            sid: {k: v for k, v in s.model_dump().items() if v not in (None, False)}
            for sid, s in sorted(styles.items())
        }
        body = yaml.safe_dump({"styles": dump}, allow_unicode=True, sort_keys=False)
        block = ("\n# 색(강조)별 글자색·배경·굵게·폰트·크기 (서식 탭에서 직접 편집)\n" + body)
    path.write_text(raw.rstrip("\n") + "\n" + block, encoding="utf-8")


def _save_emphasis_preset_tag(preset_id, tag: str) -> None:
    """프리셋(강조색)의 태그를 config/emphasis.yaml의 preset_tags에 저장(기존 주석·내용 보존).

    빈 태그를 주면 해당 프리셋의 태그를 제거(= 안 쓰는 색). 콜론·꺾쇠는 마커와 충돌하므로 제거.
    """
    import re

    import yaml

    from autoblog.publish.emphasis import _EMPHASIS_CONFIG_PATH, load_emphasis_config

    try:
        pid = int(preset_id)
    except (TypeError, ValueError):
        return
    tag = re.sub(r"[:<>]", "", tag or "").strip()
    pt = {int(k): v for k, v in (load_emphasis_config().preset_tags or {}).items()}
    if tag:
        pt[pid] = tag
    else:
        pt.pop(pid, None)

    path = _EMPHASIS_CONFIG_PATH
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    # 기존 preset_tags 블록(헤더 주석 + 매핑) 제거 후 끝에 다시 쓴다.
    raw = re.sub(r"\n*# 프리셋\(강조색\)별 태그[^\n]*\n", "\n", raw)
    raw = re.sub(r"(?m)^preset_tags:\n(?:[ \t]+.*\n?)*", "", raw)
    block = ""
    if pt:
        body = yaml.safe_dump({"preset_tags": dict(sorted(pt.items()))},
                              allow_unicode=True, sort_keys=False)
        block = ("\n# 프리셋(강조색)별 태그 (서식 탭에서 편집) — 색마다 용도. "
                 "같은 태그를 여러 색에 주면 자동 순환. LLM은 <<태그:어구>>로 고름\n" + body)
    path.write_text(raw.rstrip("\n") + "\n" + block, encoding="utf-8")


def _prompt_path_for(kind: str):
    """kind('product'|'venue'|'common'|'place') → 편집 대상 프롬프트 파일 경로."""
    from autoblog.draft.prompts import (
        COMMON_STYLE_PROMPT_PATH,
        DEFAULT_PROMPT_PATH,
        PRODUCT_PROMPT_PATH,
        VENUE_PROMPT_PATH,
    )

    if kind == "product":
        return PRODUCT_PROMPT_PATH
    if kind == "venue":
        return VENUE_PROMPT_PATH
    if kind == "common":
        return COMMON_STYLE_PROMPT_PATH
    return DEFAULT_PROMPT_PATH


def _prompt_preview(kind: str = "place") -> dict:
    """초안 생성에 쓰이는 프롬프트(편집용 raw 베이스 + 우리가 얹는 마커 지시문 레이어).

    kind='product'면 상품 베이스(product.md), 'venue'면 체험형 장소 베이스(venue.md),
    'common'이면 세 유형 뒤에 이어 붙는 공통 문체(common_style.md), 그 외엔 맛집
    베이스(default.md)를 보여준다. 마커 레이어(강조/구조/스티커)는 공통이고,
    자가 점검만 유형에 따라 나열 박스 예외·검색 제목/정보 문구가 달라진다.
    """
    from autoblog.publish.emphasis import build_emphasis_instruction, load_emphasis_config
    from autoblog.publish.plan import build_structure_instruction
    from autoblog.publish.stickers import build_sticker_instruction, load_sticker_catalog

    dkeys, qkeys = _enabled_variant_keys()  # 미리보기도 현재 고른 종류만 반영
    layers = [
        ["강조 표시 (강조색 켤 때)", build_emphasis_instruction(load_emphasis_config())],
        ["구조 마커 (구분선·인용구 켤 때)", build_structure_instruction(dkeys, qkeys)],
    ]
    sticker_instr = build_sticker_instruction(load_sticker_catalog().labels())
    if sticker_instr:  # 보유 스티커 라벨이 있을 때만(감정·구분선 스티커 안내)
        layers.append(["스티커 (스티커 켤 때)", sticker_instr])
    from autoblog.draft.prompts import build_selfcheck_instruction

    layers.append(
        [
            "자가 점검 (항상 맨 끝에)",
            build_selfcheck_instruction(kind == "product", is_venue=kind == "venue"),
        ]
    )
    path = _prompt_path_for(kind)
    return {
        "base_raw": path.read_text(encoding="utf-8"),
        "layers": layers,
        "kind": kind if kind in ("product", "venue", "common") else "place",
        "path": f"config/prompts/{path.name}",
    }


def _save_prompt(text: str, kind: str = "place") -> None:
    _prompt_path_for(kind).write_text(text, encoding="utf-8")


def _style_pool_payload() -> dict:
    """스타일 풀(유행어·카오모지·고정 문구) — 유저 수정본이 있으면 그걸 보여준다."""
    from autoblog.draft.variation import (
        STYLE_POOL_PATH,
        STYLE_POOL_USER_PATH,
        load_style_pool,
        sanitize_style_pool,
    )

    overridden = STYLE_POOL_USER_PATH.exists()
    return {
        "pool": sanitize_style_pool(load_style_pool()),  # UI가 아는 형태로 정규화해 전달
        "overridden": overridden,
        "path": str(STYLE_POOL_USER_PATH if overridden else STYLE_POOL_PATH),
    }


def _save_style_pool(body: dict) -> dict:
    """스타일 풀 저장 — 번들 자산은 읽기전용이라 유저 수정본(USER_CONFIG_DIR)에 쓴다.

    reset=True면 수정본을 지워 번들 기본값으로 되돌린다.
    """
    import yaml

    from autoblog.draft.variation import STYLE_POOL_USER_PATH, sanitize_style_pool

    if body.get("reset"):
        STYLE_POOL_USER_PATH.unlink(missing_ok=True)
        return _style_pool_payload()
    pool = sanitize_style_pool(body.get("pool") or {})
    STYLE_POOL_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
    STYLE_POOL_USER_PATH.write_text(
        yaml.safe_dump(pool, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return _style_pool_payload()


def _models_info() -> dict:
    """현재 적용 모델 + 텍스트 선택용 API 후보(API 전용 — 비전은 Gemini 고정)."""
    from autoblog.config import load_env, load_models_config, provider_for_model

    cfg = load_models_config()
    eff = cfg.effective()
    # 텍스트 API 모델 후보 — 프리셋에서 추출(모델명 기준 중복 제거)
    api_text: dict[str, dict] = {}
    for p in cfg.presets.values():
        api_text.setdefault(p.text, {
            "model": p.text, "provider": p.provider, "label": p.label,
        })
    env = load_env()
    return {
        "text": eff.text,
        "vision": eff.vision,
        "text_provider": eff.provider,
        "vision_provider": provider_for_model(eff.vision),  # 비전은 Gemini 고정
        "api_text": list(api_text.values()),
        "keys": {
            "anthropic": bool(env.anthropic_api_key),
            "openai": bool(env.openai_api_key),
            "gemini": bool(env.gemini_api_key),
            "nvidia": bool(env.nvidia_api_key),
        },
    }


_LLM_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",  # 텍스트·비전(qwen3.5)·AI 썸네일(FLUX.1-dev)
}


def _set_llm_key(provider: str, key: str) -> None:
    from autoblog.config import load_env, save_env_value

    env_var = _LLM_KEY_ENV.get(provider)
    if not env_var:
        raise ValueError(f"알 수 없는 provider: {provider!r}")
    save_env_value(env_var, key.strip())
    load_env.cache_clear()


CATEGORIES_PATH = USER_CONFIG_DIR / "categories.json"  # 유저 분류 저장 → 쓰기


def _load_categories() -> list:
    """저장해둔 카테고리(한 번 불러오면 파일에 캐시). 없으면 빈 목록."""
    try:
        return json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def _fetch_categories() -> list:
    """네이버 블로그 카테고리(이름+뎁스)를 헤드리스로 불러와 파일에 저장(브라우저 안 뜸).

    저장된 세션(storage_state)으로 자동로그인되므로 백그라운드(headless)로 동작한다.
    """
    from autoblog.publish.editor import BlogPublisher

    pub = BlogPublisher(headless=True)
    pub.start()
    try:
        if not pub.wait_for_login():
            raise RuntimeError("네이버 로그인이 필요합니다")
        cats = pub.get_categories_detailed()
    finally:
        pub.close()
    CATEGORIES_PATH.write_text(json.dumps(cats, ensure_ascii=False), encoding="utf-8")
    return cats


def _write_models_yaml(data: dict) -> None:
    import yaml

    from autoblog.config import CONFIG_DIR, load_models_config

    path = CONFIG_DIR / "models.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    load_models_config.cache_clear()  # lru_cache 무효화


def _read_models_yaml() -> dict:
    import yaml

    from autoblog.config import CONFIG_DIR

    return yaml.safe_load((CONFIG_DIR / "models.yaml").read_text(encoding="utf-8"))


def _set_model_preset(key: str) -> None:
    """프리셋 한 방 적용 — 텍스트·비전 둘 다 그 프리셋 값으로 selection에 기록."""
    data = _read_models_yaml()
    preset = data.get("presets", {}).get(key)
    if not preset:
        return
    data["default"] = key
    data["selection"] = {"text": preset["text"], "vision": preset["vision"]}
    _write_models_yaml(data)


def _set_model_selection(text: str | None, vision: str | None) -> None:
    """텍스트/비전을 독립적으로 변경(준 값만 갱신, 나머지는 유지)."""
    data = _read_models_yaml()
    sel = dict(data.get("selection") or {})
    if text:
        sel["text"] = text
    if vision:
        sel["vision"] = vision
    data["selection"] = sel
    _write_models_yaml(data)


def _sticker_image(ref: str) -> Path | None:
    from autoblog.publish.stickers import load_sticker_catalog

    s = load_sticker_catalog().by_ref().get(ref)
    if not s or not s.image:
        return None
    p = Path(s.image)
    return p if p.is_absolute() else USER_DATA_DIR / p


def _catalog_summary() -> dict:
    from autoblog.publish.stickers import DEFAULT_PACKS, load_sticker_catalog

    cat = load_sticker_catalog()
    favset = set(cat.favorites)
    stickers = [
        {"ref": s.ref, "pack": s.pack, "index": s.index, "tags": s.tags,
         "kind": s.kind, "fav": s.ref in favset}
        for s in cat.stickers
        if not s.stale
    ]
    return {
        "total": len(stickers),
        "favorites": list(cat.favorites),
        "label_count": len(cat.labels()),
        "stickers": stickers,
        "default_packs": sorted(DEFAULT_PACKS),
        "sponsor": cat.sponsor,  # 현재 협찬 고지로 지정된 스티커 ref(없으면 "")
    }


def _label_targets(cat) -> int:
    from autoblog.publish.stickers import _needs_label

    favs = set(cat.favorites)
    return sum(1 for s in cat.stickers if s.ref in favs and _needs_label(s, True))


def _run_label(state: dict) -> None:
    """즐겨찾기 중 태그 없는 것만 비전 라벨링(백그라운드 스레드). 진행은 state['label']에 기록."""
    from autoblog.publish.stickers import (
        STICKER_CONFIG_PATH,
        label_catalog,
        load_sticker_catalog,
        save_sticker_catalog,
    )

    lab = state["label"]
    try:
        cat = load_sticker_catalog()
        favs = set(cat.favorites)

        def prog(done, total, s):
            lab["done"], lab["total"] = done, total

        result = label_catalog(
            cat, only_refs=favs, only_new=True, on_progress=prog,
            save_path=STICKER_CONFIG_PATH, save_every=3,
        )
        save_sticker_catalog(result)
    finally:
        lab["running"] = False


def _set_sticker_tags(ref: str, tags: list) -> dict:
    """스티커 태그를 유저가 직접 수정 → config/stickers.yaml 저장(reviewed=True로 보호).

    바뀐 분류(kind)를 함께 반환 — 태그 편집('헤더' 칩 삭제 등)이 분류를 바꿀 수 있어
    UI가 분류 버튼을 동기화한다.
    """
    from autoblog.publish.stickers import load_sticker_catalog, save_sticker_catalog

    cat = load_sticker_catalog()
    by = cat.by_ref()
    s = by.get(ref)
    if not s:
        return {"ok": False}
    clean = []
    for t in tags:
        t = str(t).strip()
        if t and t not in clean:
            clean.append(t)
    s.tags = clean
    s.reviewed = True
    save_sticker_catalog(cat)
    return {"ok": True, "tags": s.tags, "kind": s.kind}


def _set_sticker_kind(ref: str, kind: str) -> dict:
    """스티커 분류(감정/구분선/헤더)를 유저가 직접 지정 — 태그 마커를 갈아끼우고 저장."""
    from autoblog.publish.stickers import apply_kind, load_sticker_catalog, save_sticker_catalog

    cat = load_sticker_catalog()
    s = cat.by_ref().get(ref)
    if not s:
        return {"ok": False}
    apply_kind(s, kind)
    s.reviewed = True  # 유저가 분류를 정함 → 자동 라벨링이 덮어쓰지 않게
    save_sticker_catalog(cat)
    return {"ok": True, "tags": s.tags, "kind": s.kind}


def _toggle_favorite(ref: str, on: bool) -> int:
    """즐겨찾기 추가/해제 후 config/stickers.yaml 저장. 새 즐겨찾기 수 반환."""
    from autoblog.publish.stickers import load_sticker_catalog, save_sticker_catalog

    cat = load_sticker_catalog()
    favs = [f for f in cat.favorites if f != ref]
    if on and ref in cat.by_ref():
        favs.append(ref)
    cat.favorites = favs
    save_sticker_catalog(cat)
    return len(favs)


def _set_sponsor_sticker(ref: str) -> str:
    """협찬 고지 스티커를 ref로 지정(같은 ref면 해제). 하나만 유지. 새 sponsor ref 반환."""
    from autoblog.publish.stickers import load_sticker_catalog, save_sticker_catalog

    cat = load_sticker_catalog()
    cat.sponsor = "" if cat.sponsor == ref else (ref if ref in cat.by_ref() else "")
    save_sticker_catalog(cat)
    return cat.sponsor


def serve_ui(host: str = "127.0.0.1", port: int = 8770) -> ThreadingHTTPServer:
    """글쓰기 UI 서버 생성. publish는 블로킹이라 스레드 서버 사용."""
    state: dict = {
        "last": None,
        # 멀티 탭: 생성/불러온 글을 draftId별로 보관(탭마다 독립). 게시 때 이 id로 '그 탭의 글'을
        # 정확히 집어 저장한다. state["last"](가장 최근 하나)만으론 여러 탭이 서로 덮어써서
        # 엉뚱한 탭이 게시되는 사고가 난다. 무한증식 방지로 최근 N개만 유지(_store_draft).
        "drafts": {},
        "thumbs": {},
        "label": {"running": False, "done": 0, "total": 0},
        # 임시저장을 한 건씩 순서대로 처리하는 직렬화 락(여러 건을 연속으로 눌러도
        # 헤드리스 브라우저/세션이 동시에 뜨지 않게 한 번에 하나만 게시한다).
        "publish_lock": threading.Lock(),
        # 백그라운드 임시저장 '작업' 스냅샷 저장소(작업id→플랜/옵션). 저장이 실패해도
        # 스냅샷을 남겨, 유저가 이미 다음 글로 넘어갔어도(state["last"]가 바뀌어도) 그
        # 실패한 '그 글'을 상단 탭에서 다시 시도할 수 있게 한다. 성공하면 스냅샷을 지운다.
        "jobs": {},
    }
    ThreadingHTTPServer.request_queue_size = 128  # 동시 요청(이미지 다발) 대비 backlog 확대
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), _make_handler(state))
    server.daemon_threads = True
    return server
