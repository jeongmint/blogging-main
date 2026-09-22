"""스티커 검수 UI — 로컬 웹(표준 http.server, 의존성 없음).

자동 비전 라벨은 못 미더우므로([[smart-editor-publish]]) 유저가 **이미지를 보며**
태그를 고치고 ★즐겨찾기를 지정한다. 저장하면 config/stickers.yaml에 반영(reviewed=True).
핵심 사용 흐름: pull → label(초안) → review(유저 검수, 특히 즐겨찾기) → 초안/게시에서 picker 사용.

유저 입장 쉬움: `autoblog stickers review` 한 줄이 서버 기동 + 브라우저 자동 오픈.
Electron 셸(기획 §7)에선 동일 서버를 자식 프로세스로 띄우고 BrowserWindow를 localhost로
가리키면 이 화면이 그대로 "버튼 하나"로 바뀐다(로컬서버+웹뷰는 Electron 표준 패턴).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from autoblog.config import USER_DATA_DIR
from autoblog.publish.stickers import (
    StickerCatalog,
    load_sticker_catalog,
    save_sticker_catalog,
)

_PAGE = """<!doctype html><html lang=ko><head><meta charset=utf-8>
<title>스티커 검수</title><style>
 body{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;margin:0;background:#f6f7f9;color:#222}
 header{position:sticky;top:0;background:#fff;border-bottom:1px solid #e3e5e8;padding:12px 18px;display:flex;gap:12px;align-items:center;z-index:9}
 header h1{font-size:16px;margin:0;flex:0 0 auto}
 header .sp{flex:1}
 button{font-size:13px;padding:7px 14px;border:1px solid #d0d3d7;background:#fff;border-radius:7px;cursor:pointer}
 button.primary{background:#03c75a;color:#fff;border-color:#03c75a;font-weight:600}
 .filters label{font-size:13px;margin-right:10px;cursor:pointer}
 #stat{font-size:12px;color:#888}
 .pack{margin:18px}
 .pack h2{font-size:13px;color:#555;margin:0 0 8px;font-weight:600}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
 .card{background:#fff;border:1px solid #e3e5e8;border-radius:10px;padding:8px;display:flex;flex-direction:column;gap:6px}
 .card.fav{border-color:#03c75a;box-shadow:0 0 0 1px #03c75a inset}
 .card.reviewed .ref{color:#03c75a}
 .thumb{width:100%;aspect-ratio:1;object-fit:contain;background:#fafbfc;border-radius:6px}
 .ref{font-size:10px;color:#aaa;display:flex;justify-content:space-between;align-items:center}
 .star{cursor:pointer;font-size:18px;line-height:1;color:#ccc;background:none;border:none;padding:0}
 .star.on{color:#ffb400}
 .card input.tags{font-size:12px;border:1px solid #e3e5e8;border-radius:6px;padding:5px 6px;width:100%;box-sizing:border-box}
 .card input.tags:focus{outline:2px solid #03c75a55;border-color:#03c75a}
 /* 토스트 — 중요한 알림(저장 실패 등)만 화면 상단에 띄움 */
 #toasts{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:99;display:flex;flex-direction:column;gap:8px;align-items:center;pointer-events:none}
 .toast{pointer-events:auto;min-width:240px;max-width:520px;padding:12px 40px 12px 14px;border-radius:12px;font-size:13px;font-weight:700;color:#fff;line-height:1.45;box-shadow:0 10px 30px rgba(0,0,0,.24);position:relative;animation:tin .22s cubic-bezier(.2,.9,.3,1.25)}
 .toast.err{background:linear-gradient(135deg,#f15a4d,#e23b2e)}
 .toast.ok{background:linear-gradient(135deg,#1ec46c,#06a94f)}
 .toast .x{position:absolute;top:8px;right:9px;cursor:pointer;opacity:.85;font-weight:400}
 @keyframes tin{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:none}}
</style></head><body>
<div id=toasts></div>
<header>
 <h1>스티커 검수</h1>
 <span class=filters>
   <label><input type=radio name=f value=all checked> 전체</label>
   <label><input type=radio name=f value=fav> ★즐겨찾기</label>
   <label><input type=radio name=f value=unreviewed> 미검수</label>
 </span>
 <input id=q placeholder="태그 검색" style="padding:6px 8px;border:1px solid #d0d3d7;border-radius:7px">
 <span class=sp></span>
 <span id=stat></span>
 <button class=primary id=save>저장</button>
</header>
<main id=app></main>
<script>
let CAT=null, dirty=false;
const refOf=s=>s.pack+':'+s.index;
function toast(msg,kind='err',ms){if(ms==null)ms=kind==='ok'?2500:5000;
  const t=document.createElement('div');t.className='toast '+kind;
  const ic=kind==='ok'?'✅ ':'⚠️ ';
  t.innerHTML='<span>'+ic+String(msg).replace(/</g,'&lt;')+'</span><span class=x title=닫기>✕</span>';
  const close=()=>t.remove();t.querySelector('.x').onclick=close;
  document.getElementById('toasts').appendChild(t);setTimeout(close,ms);}
async function load(){CAT=await (await fetch('/api/catalog')).json(); render();}
function stat(){const a=CAT.stickers.filter(s=>!s.stale);
  document.getElementById('stat').textContent=
    `${a.length}개 · ★${CAT.favorites.length} · 검수 ${a.filter(s=>s.reviewed).length}`+(dirty?' · 변경됨':'');}
function render(){
 const f=document.querySelector('input[name=f]:checked').value;
 const q=document.getElementById('q').value.trim();
 const favs=new Set(CAT.favorites);
 const packs={};
 for(const s of CAT.stickers){ if(s.stale) continue;
   if(f==='fav'&&!favs.has(refOf(s)))continue;
   if(f==='unreviewed'&&s.reviewed)continue;
   if(q&&!(s.tags||[]).some(t=>t.includes(q)))continue;
   (packs[s.pack]=packs[s.pack]||[]).push(s);}
 const app=document.getElementById('app'); app.innerHTML='';
 for(const pack of Object.keys(packs)){
   const sec=document.createElement('section'); sec.className='pack';
   sec.innerHTML=`<h2>${pack} <small>(${packs[pack].length})</small></h2>`;
   const g=document.createElement('div'); g.className='grid';
   for(const s of packs[pack]){
     const ref=refOf(s), on=favs.has(ref);
     const c=document.createElement('div'); c.className='card'+(on?' fav':'')+(s.reviewed?' reviewed':'');
     c.innerHTML=`<div class=ref><span>${ref}</span><button class=star${on?' on':''}>★</button></div>
       <img class=thumb loading=lazy src="/img?ref=${encodeURIComponent(ref)}">
       <input class=tags value="${(s.tags||[]).join(', ').replace(/"/g,'&quot;')}" placeholder="상황 태그(쉼표)">`;
     c.querySelector('.star').onclick=()=>{const i=CAT.favorites.indexOf(ref);
       if(i>=0)CAT.favorites.splice(i,1); else CAT.favorites.push(ref);
       dirty=true; render();};  // 즐겨찾기는 선택일 뿐 — reviewed(태그 검수)는 안 건드림
     c.querySelector('.tags').onchange=e=>{s.tags=e.target.value.split(',').map(t=>t.trim()).filter(Boolean);
       s.reviewed=true; dirty=true; stat();};
     g.appendChild(c);
   }
   sec.appendChild(g); app.appendChild(sec);
 }
 stat();
}
document.querySelectorAll('input[name=f]').forEach(r=>r.onchange=render);
document.getElementById('q').oninput=render;
document.getElementById('save').onclick=async()=>{
 const r=await fetch('/api/save',{method:'POST',headers:{'content-type':'application/json'},
   body:JSON.stringify({stickers:CAT.stickers,favorites:CAT.favorites})});
 if(r.ok){dirty=false; stat(); const b=document.getElementById('save'); b.textContent='저장됨 ✓';
   setTimeout(()=>b.textContent='저장',1200);}
 else toast('저장 실패 — 다시 시도해 주세요','err');
};
load();
</script></body></html>"""


def _make_handler(state: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 콘솔 조용히
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")  # 편집 중 이미지/카탈로그 stale 방지
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/api/catalog":
                self._send(200, state["cat"].model_dump_json().encode("utf-8"))
            elif u.path == "/img":
                ref = parse_qs(u.query).get("ref", [""])[0]
                s = state["cat"].by_ref().get(ref)
                img = _resolve_image(s.image) if s and s.image else None
                if img and img.exists():
                    self._send(200, img.read_bytes(), "image/png")
                else:
                    self._send(404, b"no image", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if urlparse(self.path).path != "/api/save":
                self._send(404, b"not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                cat = StickerCatalog(**data)
            except Exception as exc:  # noqa: BLE001
                self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                return
            save_sticker_catalog(cat, state["path"])
            state["cat"] = cat
            self._send(200, b'{"ok":true}')

    return Handler


def _resolve_image(image: str) -> Path:
    p = Path(image)
    return p if p.is_absolute() else USER_DATA_DIR / p


def serve_review(
    path: Path | None = None, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    """검수 서버 생성(아직 serve 안 함). 호출 측에서 serve_forever()."""
    cat = load_sticker_catalog(path) if path else load_sticker_catalog()
    from autoblog.publish.stickers import STICKER_CONFIG_PATH

    state = {"cat": cat, "path": path or STICKER_CONFIG_PATH}
    return ThreadingHTTPServer((host, port), _make_handler(state))
