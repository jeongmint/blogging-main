# 네이버 검색 API (지역검색) 키 발급 가이드

맛집 사실 카드의 **가게 식별·주소·좌표·전화번호** 수집에 쓰는 무료 API.
하루 25,000회 호출 가능(개인 서비스엔 사실상 무료). 로그인(OAuth) 불필요한 오픈 API.

> 제약(2020.07~): 지역검색은 결과 5개·`start=1` 고정, 상세정보 없음.
> → 영업시간·메뉴·평점은 이 API로 안 나오므로 플레이스 스크래핑으로 보완(기획서 §3.1).

## 발급 단계

1. **네이버 개발자 센터 로그인**
   <https://developers.naver.com> → 우상단 로그인(네이버 계정).

2. **애플리케이션 등록**
   상단 메뉴 `Application` → `애플리케이션 등록`.

3. **정보 입력**
   - 애플리케이션 이름: 자유 (예: `autoblog`)
   - 사용 API: **검색** 선택
   - 비로그인 오픈 API 환경 추가:
     - `WEB 설정` 선택 → 서비스 URL 입력 (로컬 개발은 `http://localhost` 입력 가능)

4. **등록 완료 → 키 확인**
   생성된 애플리케이션 화면의 `Client ID`, `Client Secret` 복사.

## .env 연동

저장소 루트의 `.env`에 값 입력:

```dotenv
NAVER_CLIENT_ID=발급받은_클라이언트_ID
NAVER_CLIENT_SECRET=발급받은_클라이언트_시크릿
```

`.env`는 `.gitignore` 처리되어 커밋되지 않는다.

## 연동 검증

```bash
uv run autoblog doctor                 # 키 인식 + 라이브 호출 점검
uv run autoblog place "교대 김밥천국"     # 실제 검색 결과로 사실 카드 출력
```

`doctor`가 `검색 API 라이브: OK`를 출력하면 정상 연동.

## 참고

- 지역검색 API 문서: <https://developers.naver.com/docs/serviceapi/search/local/local.md>
- 좌표는 KATECH(TM128) 형식으로 내려옴 — 지도 표시용 WGS84 변환은 별도 처리 필요.
