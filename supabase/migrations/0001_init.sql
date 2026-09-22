-- SaaS 초기 스키마 — 웹(Vercel)과 로컬 도우미가 공유하는 데이터 모델.
-- 설계 근거: docs/saas-architecture.md
--
-- 원칙
--  1) 멀티테넌트: 모든 행은 user_id로 묶이고 RLS로 본인 것만 접근.
--  2) 네이버 세션/쿠키는 여기에 절대 저장하지 않는다(로컬 도우미만 보유).
--  3) 사진 원본은 유저 컴에 머문다 — DB엔 로컬 경로 + 썸네일 참조만.
--  4) 엔진이 통째로 주고받는 중첩 구조(fact_card, 서식 설정)는 JSONB.

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- updated_at 자동 갱신 트리거 함수
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ─────────────────────────────────────────────────────────────
-- profiles — auth.users 1:1 확장(앱 전용 필드)
-- ─────────────────────────────────────────────────────────────
create table profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  naver_blog_id text,                       -- 게시 대상 블로그 ID (네이버 로그인과 무관)
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create trigger profiles_updated_at before update on profiles
  for each row execute function set_updated_at();

-- ─────────────────────────────────────────────────────────────
-- devices — 유저가 깐 로컬 도우미. 표시/하트비트용(주 인증은 Supabase Auth 세션).
-- ─────────────────────────────────────────────────────────────
create table devices (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  name         text,                        -- "노트북", "데스크탑" 등 유저 지정
  os           text check (os in ('windows','macos')),
  last_seen_at timestamptz,                 -- 도우미 하트비트
  paired_at    timestamptz not null default now()
);
create index devices_user_idx on devices(user_id);

-- ─────────────────────────────────────────────────────────────
-- posts — 글 한 편. 엔진의 DraftResult + 입력(fact_card/memo) + 서식 설정.
-- ─────────────────────────────────────────────────────────────
create table posts (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  title           text,
  status          text not null default 'draft'
                    check (status in ('draft','ready','publishing','published','failed')),
  experience_memo text,                     -- 유저 경험 메모(초안 입력)
  fact_card       jsonb,                    -- 수집된 PlaceFacts/ProductFacts (통째)
  draft_text      text,                     -- 생성 본문([사진]/[구분선]/[인용구] 등 마커 포함)
  emphases        jsonb not null default '[]',   -- StyledSpan[] (강조 서식)
  settings        jsonb not null default '{}',   -- DraftRequest 설정: emphasis/structure/
                                                 -- divider_variants/quote_variants/sticker_labels/place 등
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index posts_user_idx on posts(user_id, updated_at desc);
create trigger posts_updated_at before update on posts
  for each row execute function set_updated_at();

-- ─────────────────────────────────────────────────────────────
-- post_photos — 글의 사진/영상. 원본은 로컬, 썸네일만 Storage.
-- ─────────────────────────────────────────────────────────────
create table post_photos (
  id          uuid primary key default gen_random_uuid(),
  post_id     uuid not null references posts(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,  -- RLS 편의
  local_path  text not null,               -- 유저 컴 원본 경로(도우미가 읽음)
  thumb_path  text,                         -- Storage 썸네일 경로 (thumbnails 버킷)
  order_index int  not null default 0,      -- 배치 순서
  label       text,                         -- [사진:라벨] 매칭용 (예: '협찬', '음식')
  media_kind  text not null default 'photo' check (media_kind in ('photo','video')),
  created_at  timestamptz not null default now()
);
create index post_photos_post_idx on post_photos(post_id, order_index);

-- ─────────────────────────────────────────────────────────────
-- sticker_catalog — 유저의 스티커 카탈로그(= config/stickers.yaml). 이미지 아님!
--  스티커는 (pack, index) 참조로만 게시되고 네이버가 이미지를 렌더한다.
--  여기엔 메타데이터(태그/즐겨찾기/협찬지정)와 썸네일 '주소'만. 바이트 저장 없음.
--  썸네일은 네이버 CDN URL 핫링크(cdn_thumb_url) 우선, 막히면 Storage 1회 업로드로 폴백.
-- ─────────────────────────────────────────────────────────────
create table sticker_catalog (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  pack           text not null,            -- 팩 코드 (예: clip_001, ogq_60f7003da4337)
  index          int  not null,            -- 팩 내 data-index → 안정키 "pack:index"
  tags           text[] not null default '{}',  -- 감정/상황 라벨(비전+유저)
  favorite       boolean not null default false,
  is_sponsor     boolean not null default false, -- 협찬 고지 스티커 지정
  animated       boolean not null default false,
  cdn_thumb_url  text,                     -- 네이버 CDN 썸네일 주소(웹 미리보기 핫링크)
  reviewed       boolean not null default false,
  stale          boolean not null default false,
  unique (user_id, pack, index)
);
create index sticker_catalog_user_idx on sticker_catalog(user_id);

-- ─────────────────────────────────────────────────────────────
-- publish_jobs — 게시 작업 큐. 도우미가 구독/폴링해 집어간다.
-- ─────────────────────────────────────────────────────────────
create table publish_jobs (
  id          uuid primary key default gen_random_uuid(),
  post_id     uuid not null references posts(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  device_id   uuid references devices(id) on delete set null,  -- 집어간 도우미
  status      text not null default 'queued'
                check (status in ('queued','claimed','running','done','failed')),
  error       text,                         -- 실패 사유
  payload     jsonb,                        -- 게시 시점 스냅샷(본문/마커/사진목록) — 선택
  created_at  timestamptz not null default now(),
  claimed_at  timestamptz,
  finished_at timestamptz
);
-- 도우미가 자기 user의 대기 작업을 빠르게 찾도록
create index publish_jobs_poll_idx on publish_jobs(user_id, status, created_at);

-- ─────────────────────────────────────────────────────────────
-- RLS — 모든 테이블 본인 행만. 멀티테넌트 안전의 핵심.
-- ─────────────────────────────────────────────────────────────
alter table profiles        enable row level security;
alter table devices         enable row level security;
alter table posts           enable row level security;
alter table post_photos     enable row level security;
alter table sticker_catalog enable row level security;
alter table publish_jobs    enable row level security;

create policy "own profile"  on profiles
  for all using (auth.uid() = id)        with check (auth.uid() = id);
create policy "own devices"  on devices
  for all using (auth.uid() = user_id)   with check (auth.uid() = user_id);
create policy "own posts"    on posts
  for all using (auth.uid() = user_id)   with check (auth.uid() = user_id);
create policy "own photos"   on post_photos
  for all using (auth.uid() = user_id)   with check (auth.uid() = user_id);
create policy "own stickers" on sticker_catalog
  for all using (auth.uid() = user_id)   with check (auth.uid() = user_id);
create policy "own jobs"     on publish_jobs
  for all using (auth.uid() = user_id)   with check (auth.uid() = user_id);

-- 가입 시 profiles 자동 생성
create or replace function handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (id) values (new.id);
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function handle_new_user();

-- Storage: 썸네일 버킷은 대시보드/CLI로 생성하고 경로를 {user_id}/{post_id}/{photo_id}.jpg 로,
-- RLS는 (storage.foldername(name))[1] = auth.uid()::text 로 본인 폴더만 접근하게 건다.
