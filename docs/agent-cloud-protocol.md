# 도우미 ↔ 클라우드 프로토콜 — 인증 · 게시 작업 흐름

> 웹(Vercel)이 어떻게 유저 컴의 로컬 도우미에게 "이 글 게시해" 시키는가.
> 전제 구조: [docs/saas-architecture.md](./saas-architecture.md) · 스키마: [supabase/migrations/0001_init.sql](../supabase/migrations/0001_init.sql)

## 설계 원칙

- 도우미는 **아웃바운드 연결만** 한다(웹이 localhost를 안 부름) → 방화벽/포트 개방 불필요, CORS 회피.
- 도우미는 Supabase에 **그 유저로 인증된 세션**을 가진다 → RLS가 자동으로 본인 행만 허용.
- 네이버 세션/비번은 이 레이어에 **일절 없음**(로컬 도우미 안에만).

## 1) 페어링 — 도우미를 유저 계정에 연결 (OAuth 디바이스 코드 방식)

스마트TV/`gh` 로그인과 같은 **device authorization grant**. 도우미에 비번 입력 안 받고, localhost 콜백도 안 씀.

```
1. 도우미 기동 → POST /device/code
                 ← { device_code, user_code: "ABCD-1234", interval: 5 }
2. 도우미가 화면에 표시: "웹에서 [설정 > 기기연결]에 ABCD-1234 입력"
3. 유저(웹에 이미 로그인됨)가 코드 입력
   → Edge Function이 device_code를 그 user_id에 승인 + devices 행 생성
4. 도우미가 POST /device/token 을 interval마다 폴링
   ← 승인되면 { refresh_token, access_token }  (해당 유저 스코프)
5. 도우미가 refresh_token을 OS 보안 저장소에 보관
   (mac=Keychain, win=Credential Manager/DPAPI) — 평문 저장 금지
```

이후 도우미는 access_token 만료 시 refresh로 갱신하며 계속 그 유저로 동작.

> 필요한 추가 스키마(후속 마이그레이션): `device_codes(device_code, user_code, user_id, approved, expires_at)`.
> 토큰 발급은 Supabase Edge Function 2개(`/device/code`, `/device/token`)로 처리.

## 2) 게시 작업 수명주기 (publish_jobs)

```
[웹] 유저가 "게시" 클릭
   → posts 저장 + publish_jobs insert (status=queued)

[도우미] 자기 user의 queued 작업 감지 (§3)
   → 원자적 claim:
       update publish_jobs
         set status='claimed', device_id=:me, claimed_at=now()
         where id=:job and status='queued'   -- rowcount=1 이어야 내 것
   → status='running'  (네이버 게시 시작; editor.py 엔진)
   → 성공: status='done',  finished_at=now()
     실패: status='failed', error=<사유>, finished_at=now()

[웹] 같은 행을 구독 → 진행상태 실시간 표시
```

**원자적 claim이 핵심**: 유저가 기기 2대를 켜둬도 `where status='queued'` 조건 덕에 한 대만 rowcount=1을 얻어 중복 게시를 막는다. RLS는 user_id=auth.uid()라 통과.

## 3) 작업 감지 — Realtime 우선, 폴링 폴백

- **Realtime(우선)**: `publish_jobs`에 Supabase Realtime 구독(insert, status=queued). RLS가 적용돼 본인 행만 수신.
- **폴링(폴백)**: Realtime 끊김/미지원 시 `select ... where user_id=me and status='queued'`를 3~5초 간격. `publish_jobs_poll_idx`가 받쳐줌.
- 둘 다 아웃바운드 연결.

## 4) 하트비트 / 온라인 표시

도우미가 주기적으로(예: 30초) `devices.last_seen_at = now()` 갱신.
→ 웹이 "도우미 연결됨/오프라인" 표시. 오프라인인데 게시 누르면 "도우미를 켜주세요" 안내.

## 5) 사진 핸들링 접점

게시 작업의 사진은 **로컬 경로**(`post_photos.local_path`)로 참조 → 도우미가 그 유저 디스크에서 직접 읽음. 클라우드는 썸네일만. (정책: [saas-architecture.md](./saas-architecture.md) 이미지 정책)
도우미가 로컬에서 해당 파일을 못 찾으면 job을 `failed`로(사유: 파일 없음) → 웹에서 재선택 유도.

## 보안 요약

- 도우미 토큰 = 그 유저 스코프(RLS). 탈취돼도 **그 유저 본인 데이터까지만** + 네이버 자격은 못 얻음(여기 없음).
- 네이버 세션은 도우미 로컬에만, 클라우드로 전송 안 함.
- 토큰은 OS 보안 저장소. 로그아웃/기기해제 시 devices 행 삭제 + refresh 무효화.

## 미해결 결정

- [ ] Edge Function 런타임(Supabase Functions) vs Vercel API Route 중 어디에 `/device/*`를 둘지
- [ ] refresh_token 수명·회전(rotation) 정책
- [ ] 한 유저 다중 기기 시 기본 게시 대상 기기 선택 UX
