# autoblog 작업 인수인계 (새 세션에서 "HANDOFF.md 읽고 이어서 해줘"라고 시작)

## 내가 하는 일
사용자 메모 + 사진(구글드라이브 `blog/<이름>` 폴더 또는 채팅 첨부) → 네이버 블로그 글을 **임시저장만** 한다. **절대 발행 금지.**
레포: jeongmint/blogging-main. 초안은 Claude가 직접 쓰고, 사진 캡션도 Claude가 사진을 직접 보고 단다.

## 새 세션 준비 (처음에 한 번)
1. **네이버 로그인 세션**: `naver_state.json`은 git에 없다 → 사용자에게 업로드 받아 `data/naver_state.json`에 복사 (`autoblog.config.DATA_DIR` = `/home/user/blogging-main/data`).
2. **블로그 ID**: `.env`에 `NAVER_BLOG_ID=jeongmint_` (tangerine_t 아님! 사용자 확인 완료). `.env`도 git에 없으니 새로 만들기.
3. **브라우저**: Playwright가 chromium_headless_shell-1223을 찾는데 설치된 건 1194 → 심볼릭 링크 폴더를 만든다.
   ```bash
   P=$S/pw/chromium_headless_shell-1223/chrome-headless-shell-linux64; mkdir -p $P
   for f in /opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/*; do ln -sf $f $P/; done
   ln -sf $P/headless_shell $P/chrome-headless-shell
   touch $S/pw/chromium_headless_shell-1223/{DEPENDENCIES_VALIDATED,INSTALLATION_COMPLETE}
   ```
   저장 명령에 `PLAYWRIGHT_BROWSERS_PATH=$S/pw`.
4. **구글드라이브 커넥터**: 연결 안 돼 있으면 https://claude.ai/customize/connectors 에서 연결 후 새 세션.
5. 아래 도우미 스크립트를 scratchpad(`$S`)에 다시 만든다.

## 글쓰기 규칙 (사용자가 반복해서 지적한 것)
- 말투: 차분한 존댓말, 카오모지 1~2개. **"~더군요 / ~답니다 / ~죠" 금지.** 저장 전에 `grep -c "답니다\|더군요\|죠\."`로 확인.
- 개인 글(콘서트, 입시 등)은 사용자가 원하면 반말(-했다) + 메모 거의 그대로.
- **경험·가격·사실 지어내기 절대 금지.** 사진/메모/공식 안내에 있는 것만. 덧붙인 문장·뺀 내용은 보고.
- 수치·스펙은 WebSearch로 확인하고 확인 안 되면 빼기.
- **이미지 편집·블러 절대 금지.** 형식 변환(HEIC/png/webp→JPG), EXIF 회전, **최대 2400px·q85 리사이즈**(업로드 실패 방지)만. 얼굴·번호 등 개인정보는 보고만.
- 사진은 항상 전부 첨부(다른 글 사진이 섞여 있으면 빼고 보고). 사용자에게 스크린샷 보내지 않기.
- 장소 글 제목: `[시도 동네] 가게명, 한 줄+이모지`. 캠페인 제목 규칙이 있으면 캠페인 우선.
- **본문 1000자 이상**(짧은 내돈내산도 최소 700자 — "너무 짧잖아"라고 혼남). 셀 때 1~3줄, `[...]` 마커 줄, 표 행, URL 줄 제외.
- 협찬 글: 고지 문구 "본 포스팅은 X로부터 … 무상으로 제공받아 작성되었습니다." (캠페인이 위치·문구 지정하면 그대로)
- 건강기능식품 아닌 제품에 효능 표현 금지. 캠페인 금지 표현(전후 비교, 타사 비교, 가격 등) 지키기.
- **상품 링크**: 사용자가 "링크는 내가 넣을게"라고 함 → **링크 카드 넣지 말 것**(product_links 비우고 URL 줄도 빼기). 링크 카드가 본문 순서를 흩트려 혼남. 순서는 사용자가 준 순서 그대로.
- 29CM curator·쇼핑커넥트 등 수수료 링크면 고지 필요 여부를 보고.
- 사용자가 "내용만 바꿔"라고 하면 지정 부분만 고치고 나머지는 원문 그대로.

## 초안 형식 (draft.txt)
- 1줄 제목, 2줄 부제, 3줄 해시태그.
- 마커: `[사진:캡션]`, `[구분선]`, `[인용구]…[/인용구]`, `[지도]`, 마크다운 표. `1. 소제목` → 소제목 블록.
- `[사진:캡션]` 캡션 = job.json 캡션과 정확히 같게.

## job.json
`{"photos":[["/절대경로/1.jpg","라벨","캡션"],...], "product_links":[]}`

## 카테고리
`"* Ballet"`, `"* Beauty...ஐ"`(미용실·스튜디오·뷰티), `"* Wishlist...✪"`(쇼핑·위시), `""`(기본: 맛집·카페·포토부스 등).

## 도우미 스크립트 ($S에 생성)
$S/pubtext.py:
```python
"""job.json + 완성 텍스트 → plan_from_text → 임시저장. 사용: pubtext.py job text [place_query] [place_address] [category]"""
import json, sys
from autoblog.pipeline import plan_from_text
from autoblog.publish.editor import BlogPublisher
job = json.load(open(sys.argv[1])); text = open(sys.argv[2], encoding="utf-8").read()
pq = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
pa = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
cat = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else None
res = plan_from_text(text, photos=[p[0] for p in job["photos"]], photo_meta={p[0]: {"label": p[1], "caption": p[2]} for p in job["photos"]},
    emphasis=True, structure=True, stickers=True, place_query=pq, place_address=pa, product_links=job.get("product_links"))
plan = res.plan
ks = [b.kind for b in plan.blocks]; print(plan.title, {k: ks.count(k) for k in set(ks)}, file=sys.stderr)
for attempt in range(2):
    pub = BlogPublisher(headless=True); pub.start()
    try:
        assert pub.is_logged_in(), "로그인 세션 없음"
        w = pub.publish(plan, category=cat, save=True, submit=False, prune_same_title=True)
        print("임시저장 완료.", w or "", file=sys.stderr); break
    except Exception as e: print("시도", attempt + 1, "실패:", str(e)[:200], file=sys.stderr)
    finally: pub.close()
```
$S/extract.py (드라이브 다운로드 JSON → 원본. TR은 새 세션 tool-results 경로로):
```python
import json,glob,base64,os,sys
S=sys.argv[1].rstrip("/")+"/"
TR="<새 세션 tool-results 폴더>"
for f in glob.glob(TR+"/mcp-Google_Drive-download_file_content-*.txt"):
    j=json.load(open(f))
    if j["title"].upper().endswith((".HEIC",".MOV",".MP4",".JPG",".PNG",".JPEG")):
        open(S+j["title"],"wb").write(base64.b64decode(j["content"])); os.remove(f)
print(len(os.listdir(S)))
```
작은 JPG는 JSON이 아니라 `tool-results/mcp-Google_Drive-blob-*.jpg`로 저장된다 → 직접 raw로 mv하고 원래 파일명으로 바꾸기.

변환(2400px, q85):
```bash
uv run -q --with pillow-heif python -I -c "
import glob,os
from PIL import Image,ImageOps
import pillow_heif;pillow_heif.register_heif_opener()
for f in sorted(glob.glob('$D/raw/*')):
  im=ImageOps.exif_transpose(Image.open(f)).convert('RGB');im.thumbnail((2400,2400))
  im.save('$D/jpg/'+os.path.splitext(os.path.basename(f))[0]+'.jpg',quality=85)"
```
$S/sheet.py (3x3 밀착 인화지, 파일명 표시): `python3 -I $S/sheet.py <jpg폴더> <출력폴더>`
```python
import os,sys
from PIL import Image, ImageDraw
J=sys.argv[1]; fs=sorted(os.listdir(J))
for k in range(0,len(fs),9):
    sh=Image.new("RGB",(1200,1200),"white"); d=ImageDraw.Draw(sh)
    for i,f in enumerate(fs[k:k+9]):
        im=Image.open(os.path.join(J,f)); im.thumbnail((400,400))
        x,y=(i%3)*400,(i//3)*400; sh.paste(im,(x,y)); d.rectangle([x,y,x+150,y+22],fill="black"); d.text((x+3,y+5),f[:20],fill="yellow")
    sh.save(f"{sys.argv[2]}/sheet{k//9}.jpg")
```

## 작업 순서
1. 드라이브: `search_files`로 `parentId = '1hDSTjTjNwnvg9lm2C30ljPcD4p-I_GVr' and title contains '<이름>'` (blog 폴더). 못 찾으면 `createdTime > '<최근>'`으로 새 폴더 찾기. 폴더 안은 `parentId = '<id>'` + pageToken 끝까지.
2. `download_file_content` 10~13개씩 → extract.py → 반복(한 번에 너무 많이 받지 않기).
3. 변환 → 밀착 인화지 Read로 보고 캡션. 메뉴판·안내판·명함은 원본을 Read해서 읽기.
4. draft.txt, job.json → 글자 수 세기.
5. 저장: `cd /home/user/blogging-main && PLAYWRIGHT_BROWSERS_PATH=$S/pw timeout 590 uv run python $S/pubtext.py job.json draft.txt "<장소검색어>" "<주소>" "<카테고리>"`
   - 사진 20장 넘으면 run_in_background + timeout 1500.
   - 같은 제목이면 기존 임시저장을 교체. 첫 저장에서 이미지 삽입 오류가 나면 한 번 더.
   - `pkill -f` 금지.
6. 보고: 제목, 카테고리, 글자 수, 사진 수, 확인할 점(덧붙인 문장, 뺀 내용, 얼굴·개인정보).

## 남은 일 (2026-11-13 기준)
- **45ID 서촌점** (드라이브 끊겨 못 씀): 메모 "빈티지 폴라로이드 2컷 후기, 뽀용하게 잘 나옴 !", 지도 `45ID 서촌점 / 서울 종로구 자하문로7길 59-1 1층`. 사진은 `blog/45ID…` 폴더(이름 확인 필요). 카테고리 기본.
- **코피티암 서촌**, **어리틀케틀**: 드라이브 폴더만 있고 메모 아직 없음 → 메모 받으면 작성.
- 스틱어라운드 스튜디오: 결과물 사진 5장 이상 + 영상(15초↑, 사용자가 직접) + 연락처 필요.
- 언파 차차: 쇼핑커넥트 링크(상품번호 4665968279) 받으면 넣고 수수료 고지 추가.
- 마가린핑거스(플리스 #9) 정식 상품명 받으면 교체.
- 이전 남은 일: 에끌라두 쇼핑커넥트 링크, 발레썸 선생님 정보, 데가제 레오타드 상품명.
