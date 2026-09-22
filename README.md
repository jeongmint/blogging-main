<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Pacifico&size=72&color=03C75A&center=true&vCenter=true&width=520&height=115&duration=4000&pause=99999999&lines=Autoblog" alt="Autoblog" />

<img src="https://readme-typing-svg.demolab.com?font=Noto+Sans+KR&weight=600&size=21&duration=2600&pause=700&color=03C75A&center=true&vCenter=true&width=560&height=42&lines=%EC%82%AC%EC%A7%84%EC%9D%84+%EB%84%A3%EC%9C%BC%EB%A9%B4%2C+%EA%B2%BD%ED%97%98+%EC%A4%91%EC%8B%AC%EC%9D%98+%EA%B8%80%EC%9D%84;%EA%B0%95%EC%A1%B0%C2%B7%EA%B5%AC%EB%B6%84%EC%84%A0%C2%B7%EC%8A%A4%ED%8B%B0%EC%BB%A4%EA%B9%8C%EC%A7%80+%EC%9E%90%EB%8F%99+%EC%84%9C%EC%8B%9D;%EB%84%A4%EC%9D%B4%EB%B2%84+%EB%B8%94%EB%A1%9C%EA%B7%B8%EC%97%90+%EC%9E%84%EC%8B%9C%EC%A0%80%EC%9E%A5%C2%B7%EB%B0%9C%ED%96%89%EA%B9%8C%EC%A7%80" alt="typing" />

<br>

**사진과 가게·상품 정보만 넣으면, 경험을 중심으로 한 네이버 블로그 글을 자동으로 써서 게시까지 해주는 데스크톱 프로그램입니다.**

<br>

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Chromium-2EAD33?style=flat-square&logo=playwright&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-Claude·GPT·Gemini·NVIDIA-8A63D2?style=flat-square)
![Platform](https://img.shields.io/badge/소스_실행-macOS·Windows-4C82F7?style=flat-square)
![Status](https://img.shields.io/badge/파이프라인-라이브_검증됨-03C75A?style=flat-square)

</div>

<br>

> [!NOTE]
> **핵심 원칙 — 사용자 경험이 주연, 수집한 사실 정보는 조연입니다.**
> 스펙 나열이 아니라 "내가 겪은 이야기"가 중심인 글을 만드는 것을 목표로 하였습니다.

글쓰기·수집·초안 생성은 **클라우드 LLM API**(Claude / GPT / Gemini / NVIDIA)로 처리하고, 네이버 게시는 **내 PC의 실제 브라우저**로 수행합니다.

## ⚡ 켜는 법

```bash
uv sync && uv run playwright install && cp .env.example .env   # 최초 1회 (.env 키 채우기)
uv run autoblog ui                                             # 👈 이걸로 켭니다 — 로컬 웹 UI
```

자세한 설치·API 키 안내는 [시작하기](#시작하기)를 보세요.

<br>

## 전체 흐름

```text
  입력                   1. 수집                2. 초안               3. 서식               4. 게시
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ 사진·경험 메모 │  ──▶ │ 검색 API      │  ──▶ │ LLM 작성      │  ──▶ │ 모바일 최적화  │  ──▶ │ Smart Editor │
│ 가게/상품 URL │      │ 스크래핑·Vision│      │ 마커 자동 삽입 │      │ 후처리        │      │ 임시저장/발행 │
└─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘      └─────────────┘
     입력 →              사실 카드(JSON) →        초안(+마커) →          정돈된 본문 →           네이버 발행
```

수집한 사실 카드(JSON)를 바탕으로 초안 LLM이 글을 쓰고, 이때 강조·구분선·인용구·스티커·사진 배치·지도 **마커를 스스로 삽입**합니다. 이후 결정적 후처리로 모바일 화면에 맞게 다듬고, Smart Editor 자동화로 네이버에 올립니다.

<br>

## ✨ 하이라이트 — 최근 추가된 기능

<table>
<tr>
<td width="50%" valign="top">

**🎨 AI 썸네일**<br>
대표사진을 비전 모델이 읽고 **FLUX.1-dev**(NVIDIA API)가 손그림 감성 썸네일로 다시 그립니다. 미리보기에서 적용 / 적용 안 함을 고를 수 있습니다.

</td>
<td width="50%" valign="top">

**🟢 NVIDIA 무료 키 하나로**<br>
`NVIDIA_API_KEY` 하나면 텍스트(Nemotron 3 Super · GPT-OSS 120B · Llama 3.3 70B) + 비전(Qwen3.5) + AI 썸네일까지. 한도 초과(402/429)도 원인·해소 시점을 친절히 안내합니다.

</td>
</tr>
<tr>
<td valign="top">

**🗣️ 어투 프리셋 4종 + 스타일 변주**<br>
발랄 구어체(기본) · 차분한 존댓말 · 친근한 반말 · 담백 정보형. 시드 기반 변주로 글마다 카오모지·유행어·특수문자 빈도·구조가 달라져 **매번 다른 글**이 나옵니다.

</td>
<td valign="top">

**🔍 SEO 제목·키워드**<br>
제목은 `[키워드] 내용 + 클릭 유도 훅` 형식에 3종 로테이션, 대표 키워드 앞 25자 배치. 필수 키워드는 해시태그 칩으로 입력하면 인트로·소제목·본문에 자연 배치됩니다.

</td>
</tr>
<tr>
<td valign="top">

**🤝 협찬 글 지원**<br>
협찬 고지 스티커 픽커('협찬' 태그 필터), 협찬 링크는 크롤러가 인식하도록 URL 텍스트 유지, 추적 URL이 걸린 협찬 배너는 in-place에서 그대로 보존합니다.

</td>
<td valign="top">

**📋 외부 챗봇용 복사 프롬프트**<br>
API 키 없이도 조립된 프롬프트를 복사해 ChatGPT 등 다른 챗봇에 붙여넣고, 결과만 가져와 이어서 서식·게시할 수 있습니다.

</td>
</tr>
</table>

<br>

## 화면

일반 사용자는 터미널을 쓰지 않습니다. `autoblog ui` 한 줄(또는 패키징된 더블클릭 앱)이 로컬 웹 서버를 띄우고 브라우저에 글쓰기 화면을 엽니다. **npm·node 없이** 파이썬 표준 라이브러리만으로 동작합니다.

<table>
<tr><td width="120"><b>📝 글쓰기</b></td><td>단계형 흐름 <b>①글감 ②스타일 ③생성 ④검토·발행</b> — 가게URL/상품 수집 · 경험 메모 · 사진 다중선택 · 어투/서식 선택 · 필수 키워드 칩 → <b>초안 생성</b> → 미리보기(강조·구분선·인용구·스티커 실제 렌더) → 🎨 AI 썸네일 → <b>임시저장/발행</b></td></tr>
<tr><td><b>🩷 스티커</b></td><td>보유 스티커 둘러보기 · ★즐겨찾기 · 비전 자동 태그 · 분류 직접 지정(감정/구분선/헤더) — 분류에 따라 초안이 다르게 배치</td></tr>
<tr><td><b>🎨 서식</b></td><td>강조색 프리셋(실제 색·글씨체) · 구분선/인용구 종류 다중선택</td></tr>
<tr><td><b>✏️ 프롬프트</b></td><td>파트별 편집(공통 포맷·역할·규칙) + 스타일 풀 편집기(유행어 빈도 가중치)</td></tr>
<tr><td><b>🗣️ 문체</b></td><td>과거 글을 학습한 문체 프로파일 — 펼쳐서 확인·수정, 추출 모델 선택</td></tr>
<tr><td><b>🧠 모델</b></td><td>텍스트/비전 모델 선택(프리셋) + API 키 상태 + NVIDIA 무료 키 발급 안내</td></tr>
<tr><td><b>⚙️ 설정</b></td><td>글쓰기 규칙 토글 · API 키 입력</td></tr>
</table>

> [!TIP]
> **멀티 탭 워크스페이스** — 상단 작업 탭바로 여러 글을 동시에 준비할 수 있습니다. 네이버 접속(불러오기·게시)은 하나의 세션이라 서버 락으로 한 번에 하나씩 직렬 처리하도록 하였습니다. 임시저장된 여러 글을 한 번에 선택해 각각 새 탭으로 배치 불러오기도 가능합니다..!

<br>

## 시작하기

> [!IMPORTANT]
> **소스 실행은 macOS · Windows 공통입니다.** 클라우드 API를 쓰므로 OS 의존성이 없습니다.
> 다만 더블클릭 배포 앱(PyInstaller)은 **현재 macOS만** 제공하며, Windows 패키징은 로드맵에 두었습니다.

**1. 설치** — Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
uv sync                      # 의존성 설치 (.venv 생성)
uv run playwright install    # 스크래핑/게시용 브라우저 (chromium)
cp .env.example .env         # 아래 키 채우기
```

**2. `.env` 채우기**

```bash
# 네이버 지역검색 API — 가게 식별·주소·좌표 (developers.naver.com, 사실상 무료)
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
NAVER_BLOG_ID=...            # 게시 대상 블로그 ID (첫 실행 시 받아 저장돼도 됩니다)

# 텍스트/비전 LLM — 쓰는 것만 채우면 됩니다 (모델은 '모델' 탭에서 선택)
GEMINI_API_KEY=...           # Gemini 3.5 Flash (기본 프리셋, 무료 티어 OK)
NVIDIA_API_KEY=...           # NVIDIA 무료 크레딧 — 텍스트·비전·🎨 AI 썸네일까지 키 하나로
ANTHROPIC_API_KEY=...        # Claude
OPENAI_API_KEY=...           # GPT
```

> 발급 안내는 [docs/naver-search-api.md](docs/naver-search-api.md) 를 참고하시기 바랍니다.

**3. 실행**

```bash
uv run autoblog ui           # 👈 유저 화면(로컬 웹) — 메인 진입점입니다
uv run autoblog doctor       # 환경 점검(API 키 + 검색 API 라이브 호출)
uv run pytest                # 테스트
```

<details>
<summary><b>🧠 모델 설정</b></summary>

<br>

모델명은 코드에 박지 않고 [config/models.yaml](config/models.yaml) 에서 읽습니다. 프리셋(`gemini`(기본) / `claude` / `claude_sonnet` / `gpt` / `nvidia_nemotron` / `nvidia_gpt_oss` / `nvidia_llama`)을 고르거나 텍스트·비전을 독립적으로 선택할 수 있습니다. NVIDIA 프리셋은 [build.nvidia.com](https://build.nvidia.com) 무료 키 하나로 텍스트·비전(Qwen3.5)·AI 썸네일(FLUX.1-dev)을 모두 처리합니다.

```bash
uv run autoblog models       # 현재 적용 중인 텍스트/비전 모델 확인
```

</details>

<details>
<summary><b>⌨️ CLI — 파워 유저 / 단계별 실행</b></summary>

<br>

UI가 내부적으로 사용하는 엔진을 명령으로 직접 부를 수 있습니다.

```bash
# ── 정보 수집 ─────────────────────────────────────────────
uv run autoblog place-url "<플레이스 URL>"                  # 맛집 상세(메뉴/영업시간/평점/리뷰)
uv run autoblog product "상품명"                            # 상품 기본정보(쇼핑 API)
uv run autoblog product "상품명" -i 상세1.png -i 상세2.png    # 상세설명 이미지 Vision 전사
uv run autoblog product "상품명" --text "상세설명 텍스트"     # 텍스트 직접 입력
uv run autoblog classify 사진1.jpg 사진2.jpg               # 사진 자동 분류

# ── 초안 작성 ─────────────────────────────────────────────
uv run autoblog draft "경험 메모" --place-url "<URL>" -p 사진1.jpg       # 초안 + 사진 배치
uv run autoblog draft "경험 메모" --product "상품명" --tone "친근한 반말로"
uv run autoblog style 과거글1.txt 과거글2.txt -o 내문체.txt             # 과거 글로 문체 추출
uv run autoblog draft "메모" --place-url "<URL>" --style-file 내문체.txt --emphasis

# ── 수집 → 초안 → 게시까지 한 번에 (기본 임시저장, --submit이면 발행) ──
uv run autoblog post "경험 메모" --place-url "<URL>" -p 사진1.jpg
uv run autoblog post "경험 메모" --place-url "<URL>" --dry-run          # 브라우저 없이 초안·플랜만

# ── 스티커 카탈로그 (한 번 세팅하면 초안이 자동으로 골라 씁니다) ──────
uv run autoblog stickers pull      # 보유 스티커 전부 이미지로 저장 + 증분 병합
uv run autoblog stickers review    # 로컬 웹에서 ★즐겨찾기 지정·태그 검수
uv run autoblog stickers label     # 즐겨찾기한 것만 비전 자동 태그
```

글쓰기 스타일은 [config/prompts/default.md](config/prompts/default.md) 를 편집(또는 `--prompt-file`)하면 됩니다. 모든 어투 공통 포맷은 [config/prompts/common_style.md](config/prompts/common_style.md), 어투 프리셋은 [config/prompts/tones.yaml](config/prompts/tones.yaml), 변주 풀은 [config/style_pool.yaml](config/style_pool.yaml) 에 있습니다.

</details>

<br>

## 프로젝트 구조

```
config/
  models.yaml            # 텍스트/비전 모델 프리셋 (모델명은 코드에 박지 않음)
  prompts/
    default.md           #   기본 글쓰기 프롬프트 (사용자 편집)
    common_style.md      #   모든 어투 공통 포맷 규칙 (단일 출처)
    tones.yaml           #   어투 프리셋 4종 (발랄 구어체·차분 존댓말·반말·담백)
  style_pool.yaml        # 시드 변주 풀 (카오모지·유행어·구조)
  emphasis.yaml          # 강조 배정 설정 (순환 풀·고정 매핑)
  stickers.yaml          # 스티커 검수 카탈로그(태그·즐겨찾기·분류)
  fonts/                 # 미리보기용 웹폰트(에디터와 같은 se-* 패밀리)

src/autoblog/
  config.py              # 설정·환경변수·모델 프리셋 로딩 (자산/유저데이터 경로 분리)
  cli.py                 # CLI 엔트리 (ui/doctor/place-url/product/draft/post/stickers)
  webui.py               # 유저 화면 — 로컬 웹(멀티 탭 워크스페이스)
  llm.py                 # 텍스트 LLM 공통 (Claude/GPT/Gemini/NVIDIA 라우팅)
  vision.py              # Vision LLM (멀티모달 — 사진 분류·상품 상세·썸네일 묘사)
  pipeline.py            # 수집→초안→게시 플랜 조립

  collect/               # ① 정보 수집
    selectors.py         #   스크래핑 셀렉터 집결지 (구조 변경 시 여기만)
    link.py              #   URL 타입 감지 → 전략 분기
    place.py             #   맛집: 검색 API + 플레이스 상세(apollo state)
    place_detail.py      #   플레이스 URL → 메뉴/영업시간/리뷰/정보 추출
    product.py           #   상품: 쇼핑 검색 API + 이미지/텍스트 상세
    photos.py            #   입력 사진 Vision 자동 분류
    blog_posts.py        #   임시저장 글 목록/불러오기

  draft/                 # ② 초안 작성
    prompts.py / prompt.py       #   베이스 프롬프트 로딩 + 계층 조립
    rules.py / style.py / persona.py / guideline.py   #   규칙·문체·페르소나·체크리스트
    postprocess.py       #   결정적 포맷 규칙(! → .ᐟ, 줄바꿈 균형)
    generate.py          #   텍스트 LLM 호출 → 초안(+마커 자동)

  publish/               # ④ 네이버 게시
    editor.py            #   Smart Editor 자동화(로그인·제목·본문·이미지·임시저장·발행)
    plan.py              #   마커 → 게시 플랜(블록) 변환
    emphasis.py          #   서식/강조(파워 단축키, 순환 풀/고정 매핑)
    stickers.py / sticker_review.py   #   스티커 카탈로그·검수 UI

packaging/               # 데스크톱 앱 패키징 (PyInstaller + 번들 Chromium)
  app_entry.py / autoblog.spec / build_macos.sh
docs/                    # 검색 API 발급, SaaS 아키텍처, 에이전트 프로토콜
tests/
```

<br>

## 지금까지 (완성된 것)

전 파이프라인을 **라이브 검증**하였으며, 실제 네이버 블로그에 자동 게시까지 동작하는 것을 확인하였습니다.

- **정보 수집** — 맛집(메뉴/영업시간/평점/리뷰/소개/편의시설), 상품(쇼핑 API + 이미지·텍스트 상세), 사진 자동 분류를 구현하였습니다.
- **초안 작성** — 편집 가능한 베이스 프롬프트(파트별), 어투 프리셋 4종 + 시드 변주, 문체 학습, SEO 제목·키워드 규칙, 자연스러움 자가 점검, 후처리를 갖추었고, 초안 LLM이 강조·구분선·인용구·스티커·사진 배치·지도 **마커를 자동 생성**하도록 하였습니다.
- **게시** — Smart Editor 자동화로 자동 로그인, 제목/본문, 강조 색상(커스텀 hex·저장 유지), 카테고리(유저별 동적), 이미지·영상·콜라주, 구분선/인용구, 스티커(가운데 정렬 보정), 지도 카드, 임시저장/발행까지 모두 동작합니다..!
- **불러오기 & in-place 재배치** — 임시저장된 글을 다시 불러와 사진 사이에 텍스트를 끼워넣고(원본 화질 추출), 영상·콜라주·협찬 배너는 고정한 채 사진만 플랜 순서대로 재배치하도록 하였습니다.
- **협찬 글** — 협찬 고지 스티커 픽커, 협찬 링크 크롤러 인식(URL 텍스트 유지), 추적 배너 보존까지 협찬 캠페인 요건을 지원합니다.
- **AI 썸네일** — 대표사진을 손그림 감성 썸네일로 생성(FLUX.1-dev), 미리보기에서 선택 적용합니다.
- **유저 화면** — 7탭 로컬 웹 UI + 멀티 탭 워크스페이스(여러 글 동시 준비, 네이버 접속은 락으로 직렬화) + 앱 모달 통일을 완성하였습니다.
- **패키징** — macOS PyInstaller 골격을 완료하였습니다(자산/유저데이터 경로 분리, 번들 Chromium E2E 게시 검증).

<br>

## 로드맵

- [ ] `.app` / `.dmg` 포장 + 코드서명·공증
- [ ] Windows 빌드
- [ ] 첫 실행 온보딩(네이버 로그인, API 키 입력)
- [ ] SaaS 배포 검토 — 웹은 클라우드, 네이버 게시만 로컬 도우미 ([docs/saas-architecture.md](docs/saas-architecture.md))

<br>

<div align="center">
<sub>네이버 게시는 공식 API가 없어 실제 브라우저 자동화로 동작합니다. 개인 블로그 운영 보조 용도로 사용하시기 바랍니다.</sub>
</div>
