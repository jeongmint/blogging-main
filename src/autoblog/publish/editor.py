"""네이버 Smart Editor 3.0 자동 게시 스켈레톤 (기획서 §6).

가장 깨지기 쉬운 부분. 공식 쓰기 API가 없어 Playwright 브라우저 자동화가 필수다.
Smart Editor 3.0은 iframe 기반 커스텀 에디터라 일반 textarea 입력이 불가하고
내부 contenteditable을 직접 조작해야 한다.

⚠️ 이 모듈은 사용자 네이버 로그인이 필요해 개발 환경에서 끝까지 테스트할 수 없다.
   실제 셀렉터(collect.selectors.SMART_EDITOR)는 로그인 후 에디터 구조를 확인해 채운다.
   여기서는 게시 흐름의 골격과 연동 지점을 정의한다.

세션은 쿠키(persistent context)로 유지해 매번 로그인하지 않는다.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from autoblog.collect.selectors import NAVER_LOGIN, SMART_EDITOR
from autoblog.config import DATA_DIR, USER_DATA_DIR
from autoblog.publish.emphasis import EmphasisStyle
from autoblog.publish.plan import PublishBlock, PublishPlan

# 로그인 세션을 storage_state(JSON)로 저장해 재사용.
# (persistent context는 세션 쿠키 NID_AUT를 닫을 때 버려 매번 로그인됨 → storage_state로 해결)
STATE_PATH = DATA_DIR / "naver_state.json"


def _original_url_candidates(src: str) -> list[str]:
    """에디터 img src(표시용 축소본, ?type=w966 등) → 원본 화질 후보 URL 목록.

    in-place 재업로드는 여기서 받은 파일을 다시 올리므로 축소본을 받으면 화질이
    영구 열화된다(협찬마크는 크롤러가 픽셀 매칭을 못 해 인식 실패). type 파라미터
    제거 → type=w3840(뷰어 '원본보기'와 동일) → 표시본 그대로 순서로 시도한다.
    """
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(src)
    q = [(k, v) for k, v in parse_qsl(parts.query) if k != "type"]
    stripped = urlunsplit(parts._replace(query=urlencode(q)))
    biggest = urlunsplit(parts._replace(query=urlencode(q + [("type", "w3840")])))
    return list(dict.fromkeys([stripped, biggest, src]))  # 순서 유지 중복 제거

# 본문에서 특정 텍스트의 화면 좌표(Range rect)를 구하는 JS.
# SE는 프로그램적 Range 선택을 색상 적용에 반영하지 않으므로, 좌표를 받아
# 실제 마우스 드래그로 선택해야 SE가 선택을 인식한다.
_RANGE_RECT_JS = """(t) => {
  // 본문 텍스트 컴포넌트를 '전부' 순회한다(첫 컴포넌트만 보면 뒤쪽 문단의
  // 강조 문구를 못 찾아 강조가 통째로 빠진다). 찾은 텍스트는 화면 안으로
  // 스크롤한 뒤 좌표를 재측정한다 — 타이핑 후 스크롤이 끝에 가 있어 위쪽
  // 텍스트가 viewport 밖이면 마우스 드래그 선택이 빗나가기 때문.
  const roots = document.querySelectorAll('.se-component.se-text');
  for (const root of roots) {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while (n = w.nextNode()) {
      const tc = n.textContent;
      let i = tc.indexOf(t);
      // 해시태그(#로 시작하는 토큰) 안의 매치는 건너뛴다 — 본문 강조 문구가
      // '#가게명' 같은 해시태그 속 같은 글자에 잘못 입혀지는 충돌을 막는다.
      while (i > 0 && /[#＃]/.test(tc[i - 1])) i = tc.indexOf(t, i + 1);
      if (i !== -1) {
        const r = document.createRange();
        r.setStart(n, i); r.setEnd(n, i + t.length);
        const el = n.parentElement;
        if (el && el.scrollIntoView) el.scrollIntoView({block: 'center'});
        const b = r.getBoundingClientRect();
        return {x: b.x, y: b.y, w: b.width, h: b.height};
      }
    }
  }
  return null;
}"""

# 색 팔레트에 떠 있는 프리셋 스와치(.se-color-palette)들의 RGB와 화면 중심좌표.
# 목표색과 일치하는 스와치를 '실제 마우스 클릭'해 색을 넣으면 '더보기 hex 입력'(~1.4s)
# 대비 ~0.3s로 끝나고 저장도 유지된다(라이브 검증됨). 숨은 스와치(rect 0)는 제외.
_SWATCH_DUMP_JS = r"""
() => {
  const out = [];
  for (const el of document.querySelectorAll('.se-color-palette')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const m = getComputedStyle(el).backgroundColor.match(/\d+/g);
    if (!m || m.length < 3) continue;
    out.push({r: +m[0], g: +m[1], b: +m[2], x: r.x + r.width / 2, y: r.y + r.height / 2});
  }
  return out;
}
"""


# 캐럿이 '문서상 마지막' se-text 컴포넌트 안에 있는지(어느 se-text든이 아니라) 확인하는 JS.
# 인용구/표/장소 삽입 뒤 '본문 추가' 버튼을 눌러도, 클릭이 실제로 포커스를 옮기기 전에
# 다음 keyboard.type()이 시작되면 캐럿이 '이전' 문단에 그대로 남아있을 수 있다 — 그
# 상태에서 타이핑하면 글자가 엉뚱한 앞쪽 문단 한가운데로 꽂힌다(실측: 표/인용구 뒤에
# 넣은 문장이 그보다 앞선 문단 중간에 끼어듦). _caret_in_body()는 '어느 se-text든
# 안에 있으면' 통과라 이 경우를 못 잡는다 — 반드시 '마지막' 컴포넌트인지까지 본다.
_CARET_IN_LAST_TEXT_JS = """() => {
  const comps = document.querySelectorAll('.se-component.se-text');
  const last = comps[comps.length - 1];
  if (!last) return false;
  const s = getSelection();
  if (!s || !s.rangeCount) return false;
  let n = s.getRangeAt(0).startContainer;
  if (n.nodeType === 3) n = n.parentNode;
  return !!(n && n.closest && n.closest('.se-component.se-text') === last);
}"""

# 위 확인이 몇 차례 재시도해도 실패할 때 마지막 안전망 — UI 클릭에 기대지 않고 '마지막'
# se-text 컴포넌트의 끝으로 캐럿을 직접 옮긴다(JS Range/Selection, 클릭 타이밍 문제 우회).
_FORCE_CARET_TO_LAST_TEXT_END_JS = """() => {
  const comps = document.querySelectorAll('.se-component.se-text');
  const last = comps[comps.length - 1];
  if (!last) return false;
  const ed = last.querySelector('[contenteditable=true]') || last;
  ed.focus();
  const r = document.createRange();
  r.selectNodeContents(ed);
  r.collapse(false);
  const s = getSelection();
  s.removeAllRanges();
  s.addRange(r);
  return true;
}"""


class EditorNotImplemented(NotImplementedError):
    """로그인 후 셀렉터 확정 전까지 미구현인 단계."""


class BlogPublisher:
    """Smart Editor 자동 게시 오케스트레이터.

    사용 흐름:
        pub = BlogPublisher(blog_id="myblog")
        pub.start()           # 브라우저(persistent) 기동
        pub.ensure_login()    # 세션 없으면 로그인(최초 1회는 수동 보조)
        pub.publish(plan)     # 게시
        pub.close()
    """

    def __init__(self, blog_id: str | None = None, headless: bool = False, state_path: Path | None = None):
        from autoblog.config import load_env

        self.blog_id = blog_id or load_env().naver_blog_id
        if not self.blog_id:
            raise ValueError("blog_id가 필요합니다(.env NAVER_BLOG_ID 또는 인자로 전달)")
        self.headless = headless  # 게시는 사람 확인이 필요할 때가 많아 기본 headful
        self.state_path = state_path or STATE_PATH
        self._ctx = None
        self._page = None
        # 업로드가 확인되지 않은 이미지 경로 — 대표 지정·AI 표시의 k번째 매핑에서 제외해
        # 인덱스가 밀리는 걸 막는다(webp 등 미지원 형식 무음 실패 대비).
        self._failed_images: set[str] = set()

    # --- 세션/브라우저 ---
    def start(self):
        """브라우저 기동. 저장된 storage_state(JSON)가 있으면 로드해 자동 로그인."""
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless, args=["--disable-blink-features=AutomationControlled"]
        )
        storage = str(self.state_path) if self.state_path.exists() else None
        self._ctx = self._browser.new_context(
            storage_state=storage, locale="ko-KR", viewport={"width": 1440, "height": 900}
        )
        self._page = self._ctx.new_page()
        return self

    def save_state(self):
        """현재 로그인 세션을 storage_state(JSON)로 저장(세션 쿠키 포함 → 다음 실행 자동 로그인)."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._ctx.storage_state(path=str(self.state_path))

    def is_logged_in(self) -> bool:
        """현재 세션이 로그인 상태인지 확인(NID_AUT 쿠키)."""
        return any(c["name"] == "NID_AUT" for c in self._ctx.cookies())

    def wait_for_login(self, timeout_sec: int = 360) -> bool:
        """로그인 페이지를 띄우고 사용자가 직접 로그인할 때까지 대기(세션 없을 때).

        headless로 떠 있으면 창이 안 보여 로그인이 불가능하다(최초 실행·세션 만료).
        그 경우 화면 있는 창으로 재기동한 뒤 로그인 페이지를 띄운다.
        """
        import time

        if self.is_logged_in():
            return True
        if self.headless:
            self.close()
            self.headless = False
            self.start()
        self._page.goto(NAVER_LOGIN["url"], wait_until="domcontentloaded")
        for _ in range(timeout_sec // 4):
            if self.is_logged_in():
                self.save_state()  # 로그인 즉시 세션 저장
                return True
            time.sleep(4)
        return False

    # --- 게시 ---
    def open_write_page(self):
        url = NAVER_LOGIN["write_url"].format(blog_id=self.blog_id)
        self._page.goto(url, wait_until="domcontentloaded")
        # 고정 4초 대신 '에디터 본문이 떴다'는 실제 준비 신호를 기다린다(보통 더 빠름).
        self._page.wait_for_selector(SMART_EDITOR["content_component"], timeout=20000)
        self._page.wait_for_timeout(600)  # 진입 팝업(이어쓰기)이 렌더될 짧은 여유
        self._dismiss_draft_popup()

    def _dismiss_draft_popup(self):
        """진입 시 뜨는 팝업/오버레이를 '딤이 사라질 때까지' 닫는다.

        이어쓰기 팝업은 취소 버튼이 있지만, 공지·안내형은 취소가 없고 확인/닫기만 있거나
        팝업이 늦게(수백 ms 뒤) 렌더되기도 한다. 그래서 셀렉터 한 번씩 눌러보는 걸로는
        딤(se-popup-dim)이 남아 다음 클릭(저장글 버튼 등)을 인터셉트할 수 있다.
        여기서는 딤이 실제로 사라졌는지 확인하며 여러 방법(취소/확인/닫기/Esc)을 반복한다.
        """
        page = self._page
        dim_sel = ".se-popup-dim"
        # 팝업이 늦게 뜨는 케이스까지 잡으려 몇 라운드 반복. 각 라운드에서 딤이 없으면 종료.
        for _ in range(8):
            dim = page.query_selector(dim_sel)
            if not (dim and dim.is_visible()):
                return  # 딤 없음 = 막는 오버레이 없음
            clicked = False
            for sel in (
                SMART_EDITOR["draft_popup_cancel"],  # 이어쓰기 '취소'
                "button:has-text('취소')",
                "button.se-popup-close-button",       # 닫기(X)
                SMART_EDITOR["help_close"],            # 도움말 패널
            ):
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        clicked = True
                        page.wait_for_timeout(300)
                        break
                except Exception:
                    pass
            if not clicked:
                # 취소/닫기 버튼을 못 찾으면(확인만 있는 안내 등) Esc로 강제로 닫는다.
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                page.wait_for_timeout(300)

    def _click_content_component_safe(self) -> None:
        """본문(제목 아래) 클릭 — 팝업에 안전하게(_click_safe로 위임)."""
        self._click_safe(SMART_EDITOR["content_component"])

    def _click_safe(self, selector: str) -> None:
        """'작성 중인 글이 있습니다' 이어쓰기 알림이 예고 없이(제목 타이핑 뒤는 물론, 제목
        재시도 클릭 도중에도) 나타나 클릭을 가로채는 경우가 있다(_load_draft_into_editor와
        동일 현상). 이 알림은 se-popup-dim을 쓰지 않아 _dismiss_draft_popup의 딤 감지로는
        안 잡힌다. 그래서 어떤 요소를 클릭하든 직전마다 이 팝업만 콕 집어 닫으며 재시도한다."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        for _ in range(5):
            self._dismiss_entry_popup()
            try:
                self._page.click(selector, timeout=5000)
                return
            except PlaywrightTimeoutError:
                self._page.wait_for_timeout(400)
        # 안전망: 그래도 안 닫히면 딤 기반 팝업 정리까지 시도한 뒤 강제 클릭.
        self._dismiss_draft_popup()
        self._page.click(selector, force=True)

    def _dismiss_entry_popup(self) -> bool:
        """진입 '이어쓰기' 팝업(작성 중인 글이 있습니다)만 콕 집어 '취소'로 닫는다.

        _dismiss_draft_popup과 달리 Esc·일반 닫기 버튼을 쓰지 않는다 — 임시저장 목록 팝업이
        열려 있을 때 호출되므로, 목록까지 같이 닫아버리지 않도록 이어쓰기 팝업의 취소 버튼만 누른다.
        닫을 팝업이 있었으면 True."""
        page = self._page
        try:
            cancel = page.query_selector(SMART_EDITOR["draft_popup_cancel"])
            if cancel and cancel.is_visible():
                cancel.click()
                page.wait_for_timeout(300)
                return True
        except Exception:  # noqa: BLE001 - 없거나 이미 닫혔으면 무시
            pass
        return False

    def publish(
        self,
        plan: PublishPlan,
        *,
        category: str | None = None,
        save: bool = True,
        submit: bool = False,
        reserve_at=None,
        prune_same_title: bool = True,
        delete_imported: dict | None = None,
        mark_ai: bool = True,
    ) -> list[str]:
        """게시 플랜을 에디터에 주입. 기본은 임시저장만, submit=True면 발행까지.

        reserve_at(datetime)이 주어지면 그 시각으로 '예약 발행'한다(시간차 발행으로
        연속 도배 방지). 예약 확인에 실패하면 발행하지 않고 예외를 던진다(즉시 발행 방지).

        category가 주어지면 발행 레이어에서 해당 카테고리를 선택한다(유저별 동적).
        prune_same_title=True면 임시저장 직후, 같은 제목의 이전 임시저장 글을 자동 정리한다
        (최근 1건=방금 저장한 글만 남김. 삭제는 복구 불가라 제목 완전일치로만 한정).
        delete_imported={"title","date"}가 주어지면(사진을 가져왔던 원본 글) 저장 직후 그 글을
        식별해 삭제한다 — 새 글 제목은 보통 원본과 달라 prune_same_title로는 안 지워지므로 별도 처리.
        자동 삽입에 실패해 본문에서 빠진 항목(예: 검색 결과 없는 지도)이 있으면 사람이
        읽을 수 있는 경고 메시지 목록으로 반환한다(유저가 나중에 직접 보완하도록 안내용)."""
        warnings: list[str] = []
        self._failed_images = set()  # 지난 저장의 실패 기록이 이번 매핑에 섞이지 않게
        self.open_write_page()
        self._type_title(plan.title)
        self._click_content_component_safe()
        self._reset_text_toggles()  # 이전 세션에서 남은 토글 서식(취소선 등) 해제
        emphases = []
        for block in plan.blocks:
            if block.kind == "text":
                self._type_text_block(block)
                emphases.extend(block.emphases)
            elif block.kind == "image" and block.image_path:
                warn = self._insert_image(block.image_path, size=block.image_size)
                if warn:
                    warnings.append(warn)
            elif block.kind == "video" and block.image_path:
                if not self._insert_video(block.image_path, title=block.image_label):
                    warnings.append(
                        f"동영상 자동 삽입 실패: ‘{block.image_path}’ — 업로드/인코딩이 지연됐어요. "
                        "에디터에서 직접 ‘동영상’을 추가해 주세요."
                    )
            elif block.kind == "divider":
                self._insert_divider(block.variant, align=block.align)
            elif block.kind == "quote":
                self._insert_quote(block.text, block.variant, align=block.align)
            elif block.kind == "sticker" and block.sticker_pack is not None:
                self._insert_sticker(block.sticker_pack, block.sticker_index or 0)
            elif block.kind == "place" and block.text:
                try:
                    why = self._insert_place(block.text, address=block.place_address)
                except Exception as exc:  # noqa: BLE001 - 지도는 보조, 실패해도 본문 유지
                    self._page.keyboard.press("Escape")
                    why = f"에디터 오류({type(exc).__name__}: {exc})."
                if why:
                    warnings.append(
                        f"지도(장소) 자동 삽입 실패: ‘{block.text}’ — {why} "
                        "에디터에서 직접 ‘장소’를 추가해 주세요."
                    )
            elif block.kind == "link" and block.link_url:
                self._insert_link(block.link_url, keep_url_text=block.keep_url_text)
            elif block.kind == "table" and block.table_rows:
                if not self._insert_table(block.table_rows):
                    warnings.append(
                        "표 자동 삽입 실패 — 에디터에서 직접 ‘표’를 추가해 주세요."
                    )
        # 본문 입력을 모두 마친 뒤 강조 서식 적용(커서 간섭 방지)
        for span in emphases:
            try:
                self._apply_emphasis(span.text, span.style)
            except Exception as exc:  # noqa: BLE001 - 강조는 보조라 실패해도 본문 유지
                self._page.keyboard.press("Escape")
                _ = exc
        # 저장 직전: 문단 정렬을 플랜과 대조해 자동복구(사진 정렬 상속/무음 실패 대비).
        self._heal_alignment(plan, warnings)
        # AI 생성 이미지에 'AI 활용' 표시(대표 지정보다 먼저 — 대표 플래그를 안 건드림).
        if mark_ai:
            self._mark_ai_images(plan)
        # 대표사진 지정은 반드시 '맨 마지막' — 사진 조작이 더 남아 있으면 플래그가 또 옮겨간다.
        self._set_rep_photo(plan, warnings)
        # 본문 검증은 반드시 여기(타이핑+강조+정렬복구+AI표시+대표지정을 모두 마친 뒤,
        # save_draft 바로 전)에서 한다 — 더 일찍 하면 그 뒤 단계들이 저지르는 손상을
        # 놓친다(실측: 초반 검증은 통과했는데 이후 단계를 거치며 599자→396자로 더 깎였다).
        self._verify_body_text(plan)
        if reserve_at is not None:
            # 예약 발행 = 발행이므로 임시저장/정리 팝업(딤 레이어)을 만들지 않고 바로 예약 발행한다
            # — save_draft·prune의 목록 팝업이 발행 레이어 클릭을 가로채는 충돌을 피한다.
            self._submit_reserved(reserve_at, category, tags=plan.tags, warnings=warnings)
            return warnings
        if save:
            # 임시저장에도 카테고리·태그가 반영되도록, 발행 레이어에서 설정만 하고 레이어를 닫는다.
            # (submit이면 아래 발행 분기에서 적용하므로 중복 적용하지 않는다.)
            if (category or plan.tags) and not submit:
                self._apply_category_for_draft(category, tags=plan.tags, warnings=warnings)
            self.save_draft()
            # 임시저장 직후: 같은 제목의 이전 임시저장 글 정리(최근 1건만 남김).
            # 정리는 보조 기능이라 실패해도 본문 저장은 그대로 둔다(warnings는 '빠진 항목'
            # 용이라 여기 성공 메시지를 섞지 않는다).
            if prune_same_title:
                try:
                    self.delete_drafts_by_title(plan.title)
                except Exception:  # noqa: BLE001 - 정리 실패는 저장 결과에 영향 없음
                    pass
            # 사진을 가져왔던 원본 임시저장 글 정리(새 글로 내용이 옮겨졌으니 원본은 삭제).
            if delete_imported and isinstance(delete_imported, dict):
                try:
                    self.delete_imported_draft(
                        delete_imported.get("title") or "",
                        delete_imported.get("date") or "",
                        keep_title=plan.title,
                    )
                except Exception:  # noqa: BLE001 - 정리 실패는 저장 결과에 영향 없음
                    pass
        if submit:
            if category or plan.tags:
                self._open_publish_layer()
                if category:
                    self.select_category(category)
                self._fill_tags(plan.tags, warnings)
            self._submit()
        return warnings

    def _apply_category_for_draft(
        self, category: str | None, tags: list[str] | None = None,
        warnings: list[str] | None = None,
    ):
        """발행하지 않고 카테고리·태그만 설정해 임시저장에 반영한다.

        발행 레이어를 열어 카테고리를 고르고 태그칸을 채운 뒤, Esc로 레이어만 닫는다(발행 X).
        적용에 실패해도 본문 임시저장은 그대로 진행한다(보조 기능).
        """
        try:
            self._open_publish_layer()
            if category:
                self.select_category(category)
            self._fill_tags(tags, warnings)
            self._page.keyboard.press("Escape")  # 발행하지 않고 레이어만 닫기
            self._page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001 - 카테고리·태그는 보조, 실패해도 저장 진행
            self._page.keyboard.press("Escape")

    def _fill_tags(self, tags: list[str] | None, warnings: list[str] | None = None):
        """발행 레이어의 태그 입력칸에 태그를 입력한다(레이어가 열려 있다고 가정).

        태그는 본문이 아니라 네이버 태그칸으로 들어간다(검색 노출용, 네이버 최대 30개).
        입력칸을 못 찾거나 실패하면 저장·발행은 그대로 진행하고 warnings로 알린다.
        """
        clean = [t.lstrip("#").replace(" ", "") for t in (tags or [])]
        clean = [t for t in clean if t]
        if not clean:
            return
        try:
            inp = self._page.wait_for_selector(SMART_EDITOR["tag_input"], timeout=3000)
            inp.click()
            for t in clean:
                inp.type(t)
                self._page.keyboard.press("Enter")  # 엔터로 태그 칩 확정
                self._page.wait_for_timeout(150)
        except Exception:  # noqa: BLE001 - 태그는 보조, 실패해도 저장·발행 진행
            if warnings is not None:
                warnings.append(
                    "태그 자동 입력 실패 — 발행 창의 태그 칸에 직접 넣어 주세요: "
                    + " ".join("#" + t for t in clean)
                )

    def _verify_body_text(self, plan: PublishPlan) -> None:
        """저장 직전, 실제 제목·본문 글자 수가 플랜과 크게 어긋나면 저장을 막는다.

        _insert_table/_insert_link처럼 '문서 끝'이 아닌 곳으로 커서가 튀는 삽입 뒤에는,
        그 지점부터 이어지는 타이핑이 본문이 아니라 허공으로 들어가 통째로 사라진다 —
        Python 예외 없이 조용히 저장까지 '성공'해 버린다(실측: 폼폼푸린 글에서 본문 절반
        유실). 제목도 예외가 아니다 — 같은 세션에서 제목 타이핑(_type_title, 블록
        삽입보다 먼저 실행됨) 자체가 "[폼폼푸린...전체" 중 "[폼폼"만 남고 잘린 채로
        저장된 사례가 실측됐다 — 커서/포커스가 튀는 원인이 특정 삽입 함수가 아니라 더
        근본적인(에디터·네트워크 타이밍) 문제라는 뜻이라, 제목도 함께 검증한다.
        저장 직전에 실제 제목·se-text 컴포넌트 글자 수를 플랜과 대조해 크게 어긋나면
        예외로 막는다 — 경고만 남기면 다음에도 똑같이 못 알아챈다."""
        actual_title = (
            self._page.eval_on_selector(SMART_EDITOR["title_component"], "el => el ? el.innerText : ''")
            or ""
        ).strip()
        expected_title = (plan.title or "").strip()
        if expected_title and actual_title != expected_title:
            raise RuntimeError(
                f"제목 유실/손상 감지 — 플랜 제목은 {expected_title!r}인데 실제 에디터에는 "
                f"{actual_title!r}만 들어갔어요. 잘못된 내용으로 저장되지 않도록 여기서 "
                "중단합니다 — 다시 시도해 주세요."
            )
        text_blocks = [b.text for b in plan.blocks if b.kind == "text" and b.text]
        expected = sum(len(t) for t in text_blocks)
        if expected < 50:
            return  # 사진 위주라 본문 텍스트가 거의 없는 플랜은 검증 의미가 작음
        texts = self._page.eval_on_selector_all(
            ".se-component.se-text", "els => els.map(e => e.innerText || '')"
        )
        actual = sum(len(t) for t in texts)
        # 임계값 0.6→0.92: 완전 유실(예: 표 삽입 커서 버그, ~50% 소실)뿐 아니라, 타이핑 도중
        # 포커스가 순간적으로 다른 곳으로 튀어 문단 순서가 뒤섞이는 부분 유실(실측: 816자 중
        # 115자 누락 + 전후반 통째로 뒤바뀜, 중복 없음)도 잡아야 한다 — 후자는 합계 손실률이
        # 작아(약 14%) 0.6 임계값은 통과해버렸다.
        if actual < expected * 0.92:
            raise RuntimeError(
                f"본문 유실 감지 — 플랜상 텍스트는 {expected}자인데 실제 에디터에는 "
                f"{actual}자만 들어갔어요(커서가 엉뚱한 곳으로 튀어 일부가 허공에 타이핑되거나 "
                "순서가 뒤섞인 것으로 보여요). 잘못된 내용으로 저장되지 않도록 여기서 "
                "중단합니다 — 다시 시도해 주세요."
            )
        # 글자 수 합계만으로는 못 잡는 손상이 있다 — 실측: 총 글자 수는 기준을 통과했는데,
        # 실제로는 문단 경계에서 다른 문단과 글자 단위로 들러붙거나(예: "폼폼푸린백화점
        # 구경을...") 단어 중간이 끊기고 그 나머지가 엉뚱한 곳에 재등장했다(예: "폼폼머랭쉐"
        # 뒤에 끊겼다가 한참 뒤에 "이크였어요"로 재등장). 그래서 각 텍스트 블록의 내용을
        # 공백 제거 후 '그대로 이어진 덩어리'로 찾아, 문단 하나라도 안 보이면(=다른 문단과
        # 섞여 원래 형태를 잃음) 막는다.
        actual_norm = "".join("".join(t.split()) for t in texts)
        broken = sum(1 for t in text_blocks if "".join(t.split()) not in actual_norm)
        if broken:
            raise RuntimeError(
                f"본문 순서/경계 손상 감지 — 텍스트 블록 {len(text_blocks)}개 중 {broken}개가 "
                "다른 문단과 뒤섞이거나 잘려서 원래 형태 그대로 본문에서 찾을 수 없어요. "
                "잘못된 내용으로 저장되지 않도록 여기서 중단합니다 — 다시 시도해 주세요."
            )

    def save_draft(self):
        """임시저장."""
        # 캐럿 복원용 내부 표식(data-ab-caret)이 예외 경로로 남았을 수 있어 저장 전에 걷어낸다
        # — 본문 HTML에 내부 속성이 섞여 저장되지 않게 하는 안전망(정상 경로는 이미 제거됨).
        self._clear_caret_mark()
        self._page.click(SMART_EDITOR["save_button"])
        self._page.wait_for_timeout(1500)

    # --- 임시저장 글 불러오기(사진 추출) ---
    def _open_draft_list(self):
        """'저장글 N' 버튼을 눌러 임시저장 목록 팝업을 연다(필요 시 글쓰기 페이지부터)."""
        if "postwrite" not in (self._page.url or ""):
            self.open_write_page()
        if not self._page.query_selector(SMART_EDITOR["draft_list"]):
            self._page.click(SMART_EDITOR["save_count_button"])
            self._page.wait_for_selector(SMART_EDITOR["draft_list"], timeout=8000)
            self._page.wait_for_timeout(600)

    def _read_draft_items(self) -> list[dict]:
        """현재 열린 임시저장 목록의 li들을 [{idx, title, date}]로 읽는다(팝업이 열려있다고 가정)."""
        return self._page.eval_on_selector_all(
            SMART_EDITOR["draft_list"] + " li",
            """els => els.map((e, i) => ({
                idx: i,
                title: ((e.querySelector('[data-click-area="tpb*s.tlist"] strong') || {}).innerText || '').trim(),
                date: ((e.querySelector('[class*=date]') || {}).innerText || '').trim(),
            }))""",
        )

    def list_drafts(self) -> list[dict]:
        """임시저장 글 목록을 [{idx, title, date}]로 반환."""
        self._open_draft_list()
        return self._read_draft_items()

    def delete_drafts_by_title(self, title: str) -> int:
        """제목이 title과 정확히 같은 임시저장 글을, 가장 최근 1건만 남기고 모두 삭제한다.

        '새 글을 임시저장한 뒤 같은 제목의 이전 버전을 정리'하는 용도. 삭제는 복구 불가라
        제목 완전일치로만 한정하며(불일치면 아무것도 안 지움 — 안전한 실패), 가장 최근(날짜
        최대) 1건은 방금 저장한 글로 보고 남긴다. 삭제한 건수를 반환한다.

        삭제마다 목록 li 인덱스가 바뀌므로 매 회 다시 읽고, 가장 오래된 일치 항목부터 지운다.
        """
        norm = (title or "").strip()
        if not norm:
            return 0
        self._open_draft_list()
        deleted = 0
        # 무한루프 방지: 같은 제목이 아무리 많아도 목록 전체 건수 이상은 돌지 않는다.
        for _ in range(len(self._read_draft_items()) + 1):
            items = self._read_draft_items()
            matches = [d for d in items if (d.get("title") or "").strip() == norm]
            if len(matches) <= 1:
                break  # 최근 1건만 남으면(또는 없으면) 종료
            matches.sort(key=lambda d: d.get("date") or "")  # 날짜 오름차순 → [0]이 가장 오래된 것
            if not self._delete_draft_at(matches[0]["idx"]):
                break  # 삭제가 안 먹히면 같은 대상을 무한 재시도하지 않고 중단
            deleted += 1
        return deleted

    def delete_imported_draft(self, title: str, date: str = "", *, keep_title: str = "") -> bool:
        """사진을 가져왔던 '원본' 임시저장 글 한 건을 삭제한다(불러온 뒤 새 글로 옮겨 저장한 경우).

        식별은 다음 순서로 — 안전 우선(못 찾으면 아무것도 안 지움):
          1) (제목, 저장일시) 완전일치 항목. 날짜가 절대표기면 이게 가장 정확하다.
          2) 1이 빗나갈 때(예: 날짜가 '5분 전' 식 상대표기라 그새 달라짐) 폴백:
             - 원본 제목이 방금 저장한 글 제목(keep_title)과 다르면, 같은 제목 항목 전부 삭제
               (방금 저장한 글은 제목이 달라 안 걸림 → 원본만 정리).
             - 제목이 같으면, 가장 오래된 1건만 원본으로 보고 삭제(최신=방금 저장한 글은 보존).
        하나라도 삭제했으면 True.
        """
        page = self._page
        t = (title or "").strip()
        d = (date or "").strip()
        keep = (keep_title or "").strip()
        if not t:
            return False  # 제목 없는 글은 안전하게 식별 불가 → 건드리지 않음
        self._open_draft_list()

        # 1) (제목, 날짜) 완전일치 한 건
        if d:
            items = self._read_draft_items()
            exact = [
                it
                for it in items
                if (it.get("title") or "").strip() == t and (it.get("date") or "").strip() == d
            ]
            if exact:
                return self._delete_draft_at(exact[0]["idx"])

        # 2) 폴백: 제목 기준
        deleted = False
        for _ in range(len(self._read_draft_items()) + 1):
            items = self._read_draft_items()
            same = [it for it in items if (it.get("title") or "").strip() == t]
            if t == keep:
                # 새 글과 제목이 같으면 최신 1건(방금 저장)은 남기고 오래된 것만.
                if len(same) <= 1:
                    break
                same.sort(key=lambda it: it.get("date") or "")  # 오래된 것이 [0]
                if not self._delete_draft_at(same[0]["idx"]):
                    break
            else:
                if not same:
                    break
                if not self._delete_draft_at(same[0]["idx"]):
                    break
            deleted = True
        return deleted

    def _delete_draft_at(self, idx: int) -> bool:
        """임시저장 목록 idx번 항목을 삭제. 목록이 실제로 줄었는지 확인해 성공 여부를 반환한다.
        (목록이 열려있다고 가정)

        2026-07 개편 실측 두 가지: ① 삭제 버튼은 항목 hover 중에만 보인다(안 하면 클릭
        타임아웃), ② 확인창이 DOM 팝업이 아니라 네이티브 confirm이다 — Playwright가 기본으로
        dismiss해 삭제가 조용히 무산되므로 수락 핸들러를 달아야 한다. 구 DOM 팝업도 폴백으로
        계속 처리한다(UI 재변경 대비)."""
        page = self._page
        items_before = len(self._read_draft_items())
        lis = page.query_selector_all(SMART_EDITOR["draft_list"] + " > li")
        del_buttons = page.query_selector_all(SMART_EDITOR["draft_item_delete"])
        if idx < 0 or idx >= len(del_buttons):
            return False

        def _accept(dialog):
            # 삭제 확인 confirm만 수락 — 다른 다이얼로그는 기본 동작(닫기)대로
            if "삭제" in (dialog.message or ""):
                dialog.accept()
            else:
                dialog.dismiss()

        page.on("dialog", _accept)
        try:
            if idx < len(lis):
                lis[idx].hover()  # 삭제 버튼은 hover 중에만 visible
                page.wait_for_timeout(200)
            del_buttons[idx].click(timeout=8000)
            page.wait_for_timeout(500)
            confirm = page.query_selector(SMART_EDITOR["draft_delete_confirm"])  # 구 DOM 팝업 폴백
            if confirm and confirm.is_visible():
                confirm.click()
            page.wait_for_timeout(900)  # 목록 갱신 대기
        except Exception:  # noqa: BLE001 - 실패는 False로 알려 호출부 루프가 멈추게
            page.keyboard.press("Escape")
            return False
        finally:
            try:
                page.remove_listener("dialog", _accept)
            except Exception:  # noqa: BLE001 - 이미 해제됐으면 무시
                pass
        return len(self._read_draft_items()) < items_before

    def _resolve_draft_idx(self, title: str, date: str = "") -> int | None:
        """제목(+날짜)으로 현재 임시저장 목록에서 idx를 '지금' 다시 찾는다.

        불러올 때의 위치 번호는 그새 다른 글을 저장하면 밀려서 엉뚱한 글을 가리킬 수 있다.
        그래서 발행 직전에 (제목,날짜) 완전일치 우선·없으면 제목만 일치 중 가장 최근으로 재해석한다.
        못 찾으면 None(호출부가 '안전 실패'로 중단 — 엉뚱한 글을 덮어쓰지 않게)."""
        t = (title or "").strip()
        d = (date or "").strip()
        if not t:
            return None
        self._open_draft_list()
        items = self._read_draft_items()
        if d:
            exact = [
                it for it in items
                if (it.get("title") or "").strip() == t and (it.get("date") or "").strip() == d
            ]
            if exact:
                return exact[0]["idx"]
        same = [it for it in items if (it.get("title") or "").strip() == t]
        if same:
            same.sort(key=lambda it: it.get("date") or "")  # 가장 최근이 마지막
            return same[-1]["idx"]
        return None

    def _load_draft_into_editor(self, idx: int):
        """idx번 임시저장 글을 에디터에 로드(목록 열기 → 항목 클릭 → 불러오기 확인).

        import_draft_photos(사진 추출)와 publish_inplace(in-place 편집)가 공유한다."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        page = self._page
        self._open_draft_list()
        buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
        if idx < 0 or idx >= len(buttons):
            raise ValueError(f"임시저장 인덱스를 벗어남: {idx} (총 {len(buttons)}건)")
        # 진입 '이어쓰기' 팝업(작성 중인 글이 있습니다)은 600ms 뒤 늦게 떠, 목록은 열렸는데
        # 그 딤이 항목 클릭을 가로채는 경우가 있다(30초 타임아웃). 클릭 직전에 이 팝업만
        # 콕 집어 닫고(목록 팝업은 건드리지 않게), 그래도 가로채이면 몇 번 더 닫으며 재시도한다.
        for attempt in range(5):
            self._dismiss_entry_popup()
            buttons = page.query_selector_all(SMART_EDITOR["draft_item_button"])
            if idx >= len(buttons):
                raise ValueError(f"임시저장 인덱스를 벗어남: {idx} (총 {len(buttons)}건)")
            try:
                buttons[idx].click(timeout=5000)
                break
            except PlaywrightTimeoutError:
                page.wait_for_timeout(400)  # 늦게 뜬 팝업이 렌더될 여유 → 다음 라운드에서 걷어냄
        else:
            raise TimeoutError("임시저장 글 클릭이 팝업 딤에 계속 가로채여 로드하지 못했어요.")
        page.wait_for_timeout(1500)
        confirm = page.query_selector(SMART_EDITOR["draft_load_confirm"])  # '불러오기' 확인 팝업
        if confirm and confirm.is_visible():
            confirm.click()
        page.wait_for_timeout(800)

    # --- in-place 편집 (불러온 글에 직접 본문을 짜 넣는다) ---
    def _editor_photos(self):
        """본문 사진 img 요소들(문서 순). 클릭하면 그 사진 컴포넌트가 선택된다."""
        return self._page.query_selector_all(SMART_EDITOR["editor_image"])

    def _editor_video(self):
        """본문 영상 컴포넌트(첫 번째). 없으면 None."""
        v = self._page.query_selector_all(".se-component.se-video")
        return v[0] if v else None

    def _anchor_after_photo(self, k: int) -> bool:
        """k번째 사진을 선택 → Enter로 그 사진 '바로 뒤'에 빈 문단을 만들고 커서를 둔다.

        사진을 클릭하면 객체선택이라 바로 타이핑하면 글자가 사라진다(검증됨) → 반드시 Enter."""
        page = self._page
        imgs = self._editor_photos()
        if not imgs:
            return False
        k = max(0, min(k, len(imgs) - 1))
        imgs[k].scroll_into_view_if_needed()
        imgs[k].click()
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        # Enter가 먹지 않으면(객체선택이 안 잡힌 경우) 캐럿이 본문 밖에 남아, 뒤이은 삽입이
        # 엉뚱한 자리에 붙는다 — 성공 여부를 실제 캐럿 위치로 판정한다.
        return self._caret_in_body()

    def _anchor_after_video(self) -> bool:
        """영상 컴포넌트를 선택 → Enter로 영상 '바로 뒤'에 커서를 둔다(영상 자체는 안 건드림)."""
        return self._anchor_after_video_index(0)

    def _anchor_after_video_index(self, n: int) -> bool:
        """n번째 영상(문서 순)을 선택 → Enter로 그 영상 '바로 뒤'에 커서를 둔다(영상 자체 보존).

        in-place 사진 재배치에서 '구간 앵커'로 쓴다 — 영상은 옮길 수 없어 고정점이 된다."""
        page = self._page
        vids = self._page.query_selector_all(SMART_EDITOR["editor_video"])
        if not vids or n < 0 or n >= len(vids):
            return False
        vids[n].scroll_into_view_if_needed()
        vids[n].click()
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        return self._caret_in_body()  # 사진 앵커와 동일 — 캐럿이 본문에 들어갔는지로 판정

    def _count_collages(self) -> int:
        """콜라주(한 컴포넌트에 사진 2장 이상)의 개수. 낱장으로 못 옮겨 고정 앵커로 둔다."""
        return self._page.evaluate(
            """() => [...document.querySelectorAll('.se-component')]
                 .filter(c => c.querySelectorAll('img.se-image-resource').length >= 2).length"""
        )

    # 본문 img 들의 lazy src 를 전부 로드시킨다(스크롤·폴링). 외부/네이버 판별이 src 기반이라
    # 미로드(빈 src) 상태로 분류하면 보존해야 할 외부 이미지를 지울 수 있다.
    _FORCE_LOAD_IMGS_JS = r"""
    async () => {
      for (const im of document.querySelectorAll('img.se-image-resource')) {
        im.scrollIntoView({block: 'center'});
        for (let t = 0; t < 25; t++) {
          if (im.src && !im.src.startsWith('data:')) break;
          await new Promise(r => setTimeout(r, 150));
        }
      }
    }
    """

    def _delete_movable_photos(self) -> int:
        """단일 '네이버 업로드' 사진 컴포넌트만 모두 삭제한다(영상·콜라주·외부 이미지는 보존).

        in-place 사진 재배치: 지운 자리에 플랜 순서대로 사진을 다시 넣는다. 콜라주(img 2장↑)와
        영상은 재업로드가 불가/불완전하므로 건드리지 않는다. src가 pstatic이 아닌 외부 이미지
        (체험단 협찬 배너 = 플랫폼 추적 URL을 핫링크)는 지우고 재업로드하면 URL이 네이버 CDN으로
        바뀌어 협찬 인식이 깨지므로 절대 건드리지 않는다(고정 앵커). 진전이 없으면 멈춘다.
        (프리미티브 검증: scripts/probe_photo_rebuild.py)"""
        page = self._page
        page.evaluate(self._FORCE_LOAD_IMGS_JS)  # src 로드 후에야 외부/네이버 판별 가능
        removed = 0
        prev = None
        for _ in range(200):  # 안전 상한
            # 콜라주(2장↑)가 아니고 외부 핫링크도 아닌, 단일 사진 컴포넌트의 첫 img를 찾는다.
            handle = page.evaluate_handle(
                r"""() => {
                  for (const c of document.querySelectorAll('.se-component')) {
                    const imgs = c.querySelectorAll('img.se-image-resource');
                    if (imgs.length !== 1) continue;
                    const s = imgs[0].src || '';
                    if (/^https?:/.test(s) && !/pstatic\.net/.test(s)) continue;  // 외부 이미지 보존
                    return imgs[0];
                  }
                  return null;
                }"""
            )
            el = handle.as_element()
            if el is None:
                break
            cur = len(self._editor_photos())
            if prev is not None and cur >= prev:
                break  # 진전 없음 — 더 시도해도 소용없음
            prev = cur
            try:
                el.scroll_into_view_if_needed()
                el.click()  # 사진 컴포넌트 객체 선택
                page.wait_for_timeout(200)
                page.keyboard.press("Delete")
                page.wait_for_timeout(300)
            except Exception:  # noqa: BLE001 - 한 장 실패가 전체를 막지 않게
                page.keyboard.press("Escape")
                break
            removed += 1
        return removed

    def _set_rep_photo(self, plan, warnings: list[str]) -> None:
        """저장 직전 마지막 스텝: 플랜의 대표 사진에 '대표' 배지를 클릭해 명시 지정한다.

        네이버의 대표 플래그는 문서에 붙어 있어, in-place의 사진 삭제·재삽입 중 남은 아무
        사진으로 넘어가 버린다(첫 이미지=대표라는 암묵 규칙이 깨짐). 그래서 모든 사진 조작이
        끝난 뒤 항상 마지막에 재지정한다. 매핑: 플랜의 k번째 이미지 블록 = 본문의 k번째
        '단일 네이버 업로드' 사진(문서 순) — 콜라주·외부 핫링크 이미지는 플랜 블록이
        아니므로 제외(_delete_movable_photos와 동일 기준). 실패는 warnings로 안내만 한다.
        (mechanic 검증: scripts/probe_rep_photo.py — hover 후 배지 클릭으로 플래그 이동)"""
        rep = getattr(plan, "rep_image_path", None)
        if not rep:
            return
        if rep in self._failed_images:  # 대표사진 자체가 업로드 실패 — 지정 불가
            warnings.append(
                "★ 대표사진 업로드가 실패해 대표 지정을 건너뛰었어요 — 에디터에서 사진을 "
                "직접 추가하고 대표로 지정해 주세요."
            )
            return
        page = self._page
        # 업로드 실패한 이미지는 본문에 없으므로 매핑에서 빼야 k번째가 안 밀린다
        plan_imgs = [
            b.image_path for b in plan.blocks
            if b.kind == "image" and b.image_path and b.image_path not in self._failed_images
        ]
        try:
            k = plan_imgs.index(rep)
            page.evaluate(self._FORCE_LOAD_IMGS_JS)  # 외부/네이버 판별은 src 로드 후에만 가능
            handle = page.evaluate_handle(
                r"""(k) => {
                  const singles = [...document.querySelectorAll('.se-component')].filter(c => {
                    const imgs = c.querySelectorAll('img.se-image-resource');
                    if (imgs.length !== 1) return false;
                    const s = imgs[0].src || '';
                    return !(/^https?:/.test(s) && !/pstatic\.net/.test(s));
                  });
                  return singles[k] || null;
                }""",
                k,
            )
            comp = handle.as_element()
            if comp is None:
                raise RuntimeError("대상 사진 컴포넌트를 찾지 못함")
            comp.scroll_into_view_if_needed()
            comp.hover()  # 배지는 hover 시에만 렌더된다
            page.wait_for_timeout(300)
            btn = comp.query_selector(".se-set-rep-image-button")
            if btn is None:
                raise RuntimeError("대표 배지 없음")
            btn.click()
            page.wait_for_timeout(300)
            if "se-is-selected" not in (btn.get_attribute("class") or ""):
                raise RuntimeError("클릭 후에도 미선택")
        except Exception:  # noqa: BLE001 - 대표 지정은 보조, 실패해도 저장 진행
            page.keyboard.press("Escape")
            warnings.append(
                "대표사진 자동 지정에 실패했어요 — 발행 전에 대표사진이 맞는지 확인해 주세요."
            )

    def _mark_ai_images(self, plan) -> None:
        """AI 생성 이미지(plan의 ai_generated 블록)에 네이버 'AI 활용' 표시를 켠다(자율 표기).

        매핑은 _set_rep_photo와 동일: 플랜의 k번째 이미지 블록 = 본문의 k번째 '단일 네이버
        업로드' 사진(콜라주·외부 핫링크 제외). 이미지에 hover하면 뜨는 'AI 활용 설정' 배지의
        토글 버튼(button.se-set-ai-mark-button-toggle)을 클릭한다 — 대표 배지와 같은 hover 방식.
        클릭하면 se-is-selected가 붙어(=켜짐) 발행 시 이미지 우하단에 'AI 활용' 아이콘이 붙는다.
        이미 켜져 있으면(se-is-selected) 다시 눌러 꺼지지 않게 건너뛴다. 표시는 보조 기능이라
        실패해도 저장은 그대로 진행. SMART_EDITOR['image_ai_label']이 비면 no-op.
        (라이브 검증 2026-07-23: scripts/probe_ai_label.py — hover→토글 클릭 시 se-is-selected 부착)"""
        sel = SMART_EDITOR.get("image_ai_label")
        if not sel:
            return  # 토글 셀렉터 미설정 — 발행은 그대로
        # 업로드 실패한 이미지는 본문에 없으므로 매핑에서 빼야 k번째가 안 밀린다
        plan_imgs = [
            b.image_path for b in plan.blocks
            if b.kind == "image" and b.image_path and b.image_path not in self._failed_images
        ]
        ai_idx = [
            plan_imgs.index(b.image_path)
            for b in plan.blocks
            if b.kind == "image" and b.image_path and b.ai_generated
            and b.image_path in plan_imgs
        ]
        if not ai_idx:
            return
        page = self._page
        page.evaluate(self._FORCE_LOAD_IMGS_JS)  # 외부/네이버 판별은 src 로드 후에만 가능
        for k in ai_idx:
            try:
                handle = page.evaluate_handle(
                    r"""(k) => {
                      const singles = [...document.querySelectorAll('.se-component')].filter(c => {
                        const imgs = c.querySelectorAll('img.se-image-resource');
                        if (imgs.length !== 1) return false;
                        const s = imgs[0].src || '';
                        return !(/^https?:/.test(s) && !/pstatic\.net/.test(s));
                      });
                      return singles[k] || null;
                    }""",
                    k,
                )
                comp = handle.as_element()
                if comp is None:
                    continue
                comp.scroll_into_view_if_needed()
                comp.hover()  # 배지는 hover 시에만 렌더된다(대표 배지와 동일)
                page.wait_for_timeout(300)
                toggle = comp.query_selector(sel)
                if toggle is None:
                    continue
                if "se-is-selected" in (toggle.get_attribute("class") or ""):
                    continue  # 이미 켜짐 — 다시 누르면 꺼진다
                toggle.click()
                page.wait_for_timeout(200)
            except Exception:  # noqa: BLE001 - AI 표시는 보조, 실패해도 저장 진행
                page.keyboard.press("Escape")
        page.keyboard.press("Escape")  # hover 상태 정리(대표 지정 단계로)

    # --- 캐럿(커서) 보존 ---
    # 지도(장소)처럼 '팝업을 여는' 삽입은 그 사이 contenteditable의 selection이 날아간다.
    # selection이 없으면 SE가 카드를 문서 기본 위치(=맨 위)에 꽂아 순서가 통째로 어긋난다
    # (지도만 유독 최상단으로 튀고, 뒤이어 넣는 문단이 밀려 '1.' 문단이 맨 아래로 남던 원인).
    # _insert_link 는 activeElement 를 되찾는 방어가 있지만 그것만으론 '어느 문단이었는지'가
    # 남지 않는다 → 삽입 직전 캐럿이 있던 문단에 표식을 찍고, 삽입 시점에 그 문단 끝으로 되돌린다.
    _CARET_ATTR = "data-ab-caret"

    def _mark_caret(self) -> bool:
        """현재 캐럿이 놓인 본문 문단에 표식을 남긴다(복원용). 본문에 캐럿이 없으면 False."""
        try:
            return bool(
                self._page.evaluate(
                    """(attr)=>{
                      const s=getSelection();
                      if(!s||!s.rangeCount) return false;
                      let n=s.getRangeAt(0).startContainer;
                      if(n.nodeType===3) n=n.parentNode;
                      if(!n||!n.closest) return false;
                      const p=n.closest('.se-text-paragraph');
                      if(!p) return false;
                      document.querySelectorAll('['+attr+']').forEach(e=>e.removeAttribute(attr));
                      p.setAttribute(attr,'1');
                      return true;
                    }""",
                    self._CARET_ATTR,
                )
            )
        except Exception:  # noqa: BLE001 - 캐럿 보존은 보조, 실패해도 삽입은 진행
            return False

    def _restore_caret(self) -> bool:
        """_mark_caret 으로 찍어둔 문단 끝으로 캐럿을 되돌린다(표식은 남겨 재복원 가능)."""
        try:
            return bool(
                self._page.evaluate(
                    """(attr)=>{
                      const p=document.querySelector('['+attr+']');
                      if(!p||!p.closest) return false;
                      const ed=p.closest('[contenteditable=true]');
                      if(!ed) return false;
                      ed.focus();
                      const r=document.createRange(); r.selectNodeContents(p); r.collapse(false);
                      const s=getSelection(); s.removeAllRanges(); s.addRange(r);
                      return true;
                    }""",
                    self._CARET_ATTR,
                )
            )
        except Exception:  # noqa: BLE001
            return False

    def _clear_caret_mark(self) -> None:
        """캐럿 표식 제거 — 저장되는 본문에 내부 속성이 남지 않게 한다."""
        try:
            self._page.evaluate(
                "(attr)=>{document.querySelectorAll('['+attr+']')"
                ".forEach(e=>e.removeAttribute(attr));}",
                self._CARET_ATTR,
            )
        except Exception:  # noqa: BLE001
            pass

    def _caret_in_body(self) -> bool:
        """캐럿이 본문 텍스트 컴포넌트(.se-component.se-text) 안에 있는지.

        '제목 끝에서 Enter' 앵커가 빗나가면 캐럿이 제목 칸에 남아, 뒤이은 타이핑이 제목
        안에 박힌다(본문이 통째로 사라지는 실측 실패 모드). 앵커 성공 검증에 쓴다."""
        try:
            return bool(
                self._page.evaluate(
                    """()=>{
                      const s=getSelection();
                      if(!s||!s.rangeCount) return false;
                      let n=s.getRangeAt(0).startContainer;
                      if(n.nodeType===3) n=n.parentNode;
                      return !!(n&&n.closest&&n.closest('.se-component.se-text'));
                    }"""
                )
            )
        except Exception:  # noqa: BLE001
            return False

    def _anchor_before_first_media(self) -> bool:
        """첫 미디어(사진/영상) '위'에 커서를 둔다. 캐럿이 본문에 들어갔는지 검증한다.

        맨 위 사진은 선택 툴바가 컴포넌트 top edge-button을 덮어 클릭이 막힌다(프로브로 확인:
        edge force/JS/좌표 클릭, Ctrl+Home 전부 실패). 대신 '제목 칸 끝에서 Enter'를 치면 제목
        바로 아래(=첫 미디어 위)에 본문 문단이 생기고 캐럿도 그리로 간다(프로브에서 유일하게 성공).

        예전엔 항상 True를 돌려줘, 앵커가 빗나가도 호출부(in-place 역순 삽입)가 그대로
        다음 블록을 꽂았다 — 커서가 남아 있던 자리에 붙어 순서가 뒤집히던 원인."""
        page = self._page
        # 미디어가 없어도 같은 경로를 쓴다 — 예전엔 본문 컴포넌트를 클릭했는데, Playwright가
        # 요소 '정중앙'을 클릭해 이미 입력한 문장 한가운데에 커서가 박혔다(in-place 역순 삽입에서
        # 사진 전부 삭제 직후 = 미디어 0개 구간의 본문 뒤섞임 원인). 제목 끝→Enter는 미디어
        # 유무와 무관하게 항상 '제목 바로 아래 = 본문 맨 위'를 만든다.
        page.click(SMART_EDITOR["title_component"])
        page.wait_for_timeout(200)
        # 제목이 두 줄로 접히면 키보드 'End'는 시각 줄 끝(제목 중간)에 멈춰, 뒤이은 Enter가 본문으로
        # 못 넘어가고 본문 글자가 제목 안에 박힌다(전체선택+Enter는 선택분 삭제로 제목이 날아감).
        # 그래서 선택을 만들지 않고 JS로 캐럿을 제목 '논리적 끝'에 둔 뒤 Enter로 본문에 진입한다.
        page.evaluate(
            """(sel)=>{const comp=document.querySelector(sel);
              if(!comp) return false;
              const ed=comp.querySelector('[contenteditable=true]')||comp;
              ed.focus();
              const r=document.createRange(); r.selectNodeContents(ed); r.collapse(false);
              const s=getSelection(); s.removeAllRanges(); s.addRange(r); return true;}""",
            SMART_EDITOR["title_component"],
        )
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        return self._caret_in_body()

    def _place_anchor(self, anchor) -> None:
        """anchor 위치(맨 앞 / 사진 k 뒤 / 영상 뒤)에 커서를 둔다."""
        if anchor is None:
            self._anchor_before_first_media()
        elif anchor[0] == "photo":
            self._anchor_after_photo(anchor[1])
        else:
            self._anchor_after_video()

    # 불러온 글에서 지울 '장식' 컴포넌트를 고르는 JS.
    # 사진(se-image)·영상(se-video)·본문 텍스트(se-text)·제목(se-documentTitle)이 '아닌' 모든
    # 컴포넌트(= 스티커·지도(장소)·링크카드·인용구·구분선 등)를 대상으로 본다. 종류마다 클래스가
    # 달라도 '보존 대상이 아니면 제거'로 잡아 놓치지 않는다. skip개를 건너뛴 다음 제거 대상의
    # 문서 순 인덱스와 남은 제거 대상 총수({idx, count})를 돌려준다(skip = 삭제가 안 먹혀
    # 문서에 남아 있는 컴포넌트 수 — 그 다음 것부터 계속 시도하기 위한 커서).
    _REMOVABLE_COMP_JS = r"""
    (skip) => {
      const comps = [...document.querySelectorAll('.se-component')];
      const keep = /se-text|se-image|se-video|se-documentTitle/;
      let idx = -1, count = 0;
      for (let i = 0; i < comps.length; i++) {
        if (keep.test(comps[i].className.toString())) continue;
        count++;
        if (idx < 0 && count > skip) idx = i;
      }
      return {idx, count};
    }
    """

    def _remove_imported_extras(self) -> tuple[int, int]:
        """불러온 임시저장 글에 이미 들어 있던 '장식' 컴포넌트(스티커·지도·링크카드·인용구·구분선·표)를
        지운다 — 사진/영상/본문 텍스트/제목은 그대로 둔다. (지운 개수, 못 지운 개수)를 반환한다.

        새 플랜이 같은 종류(스티커·지도·링크 등)를 다시 넣으므로, 옛것을 남겨두면 중복된다.
        클릭은 컴포넌트 '모서리'로 — 인용구·표처럼 내부가 편집 가능한 컴포넌트는 중앙 클릭이
        텍스트 편집 모드로 들어가 Delete가 글자만 지우고 객체는 남는다(2026-07 실측: 모서리
        클릭은 5종 전부 객체 선택→Delete 삭제 성공). 삭제가 실제로 됐는지 매번 개수로 검증하고,
        안 지워지는 컴포넌트는 건너뛰고 다음 것을 계속 지운다 — 첫 실패에서 멈추면 그 뒤 장식이
        전부 살아남아 유령 중복이 된다(우이락 글 실측).

        사진 많은 글은 이미지 lazy-load로 레이아웃이 밀리며 클릭이 빗나가 멀쩡한 컴포넌트도
        건너뛰어질 수 있다(우이락 재저장 실측: 스티커·지도만 잔존). 시작 전에 이미지를 전부
        강제 로드해 레이아웃을 안정시키고, 그래도 건너뛴 게 있으면 패스를 다시 돌아 재시도한다
        (한 패스 동안 진전이 없으면 종료)."""
        page = self._page
        try:  # 레이아웃 안정화 — 실패해도 삭제 자체는 진행
            page.evaluate(self._FORCE_LOAD_IMGS_JS)
        except Exception:  # noqa: BLE001
            pass
        removed = 0
        skipped = 0
        for _pass in range(3):  # 건너뛴 컴포넌트 재시도 패스(레이아웃 이동으로 빗나간 클릭 회복)
            skipped = 0  # 이번 패스에서 삭제가 안 먹혀 문서에 남은 컴포넌트 수(탐색 커서)
            progressed = False
            for _ in range(80):  # 안전 상한(무한루프 방지)
                info = page.evaluate(self._REMOVABLE_COMP_JS, skipped)
                count, idx = info["count"], info["idx"]
                if idx < 0:
                    break  # 건너뛴 것 말고는 제거 대상 없음
                comps = page.query_selector_all(".se-component")
                if idx >= len(comps):
                    break
                try:
                    comps[idx].scroll_into_view_if_needed()
                    comps[idx].click(position={"x": 4, "y": 4})  # 모서리 클릭 = 객체 선택
                    page.wait_for_timeout(200)
                    page.keyboard.press("Delete")
                    page.wait_for_timeout(300)
                except Exception:  # noqa: BLE001 - 한 컴포넌트 삭제 실패가 전체를 막지 않게
                    page.keyboard.press("Escape")
                    skipped += 1
                    continue
                if page.evaluate(self._REMOVABLE_COMP_JS, 0)["count"] < count:
                    removed += 1
                    progressed = True
                else:
                    skipped += 1  # 이 컴포넌트는 이번엔 안 지워짐 — 다음 것으로(다음 패스에서 재시도)
            if skipped == 0 or not progressed:
                break  # 다 지웠거나, 한 바퀴 내내 진전 없음(더 돌아도 소용없음)
        return removed, skipped

    # 아직 '내용이 있는' 첫 본문 텍스트 컴포넌트의 인덱스와, 내용 있는 텍스트 컴포넌트 총수를
    # 돌려주는 JS(제목 se-documentTitle은 제외 — 제목은 _type_title(clear=True)에서 따로 지운다).
    _NONEMPTY_TEXT_JS = r"""
    () => {
      const cs = [...document.querySelectorAll('.se-component.se-text')];
      let idx = -1, count = 0;
      for (let i = 0; i < cs.length; i++) {
        if ((cs[i].innerText || '').trim().length === 0) continue;
        if (idx < 0) idx = i;
        count++;
      }
      return {idx, count};
    }
    """

    def _clear_imported_body(self) -> int:
        """불러온 글의 본문 텍스트 컴포넌트 내용을 모두 비운다(사진/영상은 보존).

        SE는 컴포넌트마다 별도 contenteditable이라, 텍스트 컴포넌트에 커서를 넣고 Ctrl+A를 누르면
        그 컴포넌트 내용'만' 선택된다(_type_title의 제목 지우기와 같은 방식). Delete로 지우면 빈
        문단만 남고, 그 자리에 새 플랜 본문이 앵커(사진 뒤)로 들어간다. 내용이 남은 텍스트
        컴포넌트가 없을 때까지 반복하고(매번 다시 탐색), 비운 컴포넌트 수를 반환한다."""
        page = self._page
        cleared = 0
        prev_count = None
        for _ in range(200):  # 안전 상한(무한루프 방지)
            info = page.evaluate(self._NONEMPTY_TEXT_JS)
            count, idx = info["count"], info["idx"]
            if count == 0 or idx < 0:
                break
            if prev_count is not None and count >= prev_count:
                break  # 직전 비우기가 반영 안 됨(진전 없음) — 중단
            prev_count = count
            comps = page.query_selector_all(".se-component.se-text")
            if idx >= len(comps):
                break
            try:
                comps[idx].scroll_into_view_if_needed()
                comps[idx].click()  # 그 텍스트 컴포넌트에 커서 진입
                page.wait_for_timeout(150)
                page.keyboard.press("ControlOrMeta+a")  # 그 컴포넌트 내용만 선택
                page.keyboard.press("Delete")
                page.wait_for_timeout(200)
            except Exception:  # noqa: BLE001 - 한 컴포넌트 비우기 실패가 전체를 막지 않게
                page.keyboard.press("Escape")
                break
            cleared += 1
        return cleared

    def publish_inplace(
        self, plan, *, draft_idx: int | None = None,
        draft_title: str | None = None, draft_date: str = "",
        photo_paths: list[str] | None = None,
        category: str | None = None, save: bool = True,
        clean_imported: bool = True, mark_ai: bool = True,
    ) -> tuple[list[str], list[str]]:
        """불러온 임시저장 글을 'in-place'로 편집한다(영상·콜라주 고정, 사진은 플랜대로 재배치).

        반환: (warnings, infos). warnings는 사람이 확인·보완해야 하는 항목,
        infos는 정상 동작에 대한 안내(예: 옛 내용 정리 알림)라 확인이 필요 없다.

        영상은 재업로드가 불가(유실)하고 콜라주는 낱장으로 못 옮기니 '고정 앵커'로 그대로 두고,
        사진은 전부 삭제한 뒤 plan 순서대로 다시 넣는다. 이러면 LLM이 정한 사진·텍스트 순서가
        그대로 반영되고(문서 물리 순서에 안 끌려감), 영상은 원자리에 보존된다. i번째 [영상] 블록을
        i번째 물리 영상으로 매핑해, 그 사이 구간마다 사진·텍스트·인용구·스티커·구분선·링크·지도를
        플랜 순서대로 삽입한다. 한 구간의 블록들은 '역순 삽입'으로 순서를 보존한다(아래 루프 주석).
        저장하면 같은 글이 갱신된다(원본 삭제 없음). (mechanic 검증: scripts/probe_*_rebuild.py)

        글 식별: draft_title을 주면(권장) 발행 직전에 제목+날짜로 목록에서 idx를 '다시' 찾는다
        (위치 번호가 밀려 엉뚱한 글을 덮어쓰는 사고 방지). 못 찾으면 RuntimeError로 중단한다.
        draft_title 없이 draft_idx만 주면 그 번호로 로드한다(테스트·단발 용).

        clean_imported=True(기본)면, 로드 직후 원본 글의 옛 내용을 비우고 새로 쓴다 — 제목·본문
        텍스트·스티커·지도·링크카드 등 장식을 모두 지우고(사진·영상은 그대로 보존) 새 플랜 내용을
        넣는다. 남겨두면 옛 제목·본문·장식이 새 내용과 뒤섞이기 때문. False면 원본을 그대로 두고
        기존 사진/장식 사이에 본문만 끼워 넣는다(옛 본문·장식 유지)."""
        page = self._page
        warnings: list[str] = []
        infos: list[str] = []  # 정상 동작 안내 — warnings와 달리 '확인 필요'가 아님
        self._failed_images = set()  # 지난 저장의 실패 기록이 이번 매핑에 섞이지 않게
        self.open_write_page()
        if draft_title:
            idx = self._resolve_draft_idx(draft_title, draft_date)
            if idx is None:
                raise RuntimeError(
                    f"불러온 글을 목록에서 다시 찾지 못했어요(제목 ‘{draft_title}’). "
                    "엉뚱한 글 덮어쓰기를 막으려고 in-place 저장을 중단합니다."
                )
        elif draft_idx is not None:
            idx = draft_idx
        else:
            raise ValueError("draft_title 또는 draft_idx 중 하나는 필요합니다")
        self._load_draft_into_editor(idx)
        try:
            page.wait_for_selector(SMART_EDITOR["editor_image"], timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(800)

        # 본문을 짜 넣기 전에, 불러온 원본 글의 옛 내용을 비운다(사진/영상은 보존):
        #  ① 스티커·지도·링크카드 등 장식 블록 삭제, ② 본문 텍스트 컴포넌트 내용 비우기.
        # (제목은 아래 _type_title(clear=True)에서 지운다.) 새 플랜이 제목·본문·장식을 모두
        # 다시 넣으므로, 옛것을 남겨두면 새 내용과 뒤섞인다. 정리는 보조라 실패해도 작성은 진행.
        if clean_imported:
            try:
                extras, left = self._remove_imported_extras()
                cleared = self._clear_imported_body()
                if extras or cleared:
                    # 정리는 clean_imported 기본 동작이라 오류·확인 대상이 아님 → 안내(infos)로 전달
                    infos.append(
                        f"불러온 글의 옛 내용을 정리했어요(장식 {extras}개 삭제, 본문 {cleared}곳 비움) "
                        "— 사진·영상은 그대로 두고 새로 작성했어요."
                    )
                if left:
                    # 못 지운 옛 장식은 새 플랜 내용과 중복된다 — 조용히 남기지 않고 알린다
                    warnings.append(
                        f"불러온 글의 옛 장식 {left}개를 지우지 못했어요 — 발행 전에 "
                        "스티커·지도·인용구 등이 중복되지 않았는지 확인해 주세요."
                    )
            except Exception:  # noqa: BLE001 - 정리 실패는 본문 작성에 영향 없음
                page.keyboard.press("Escape")

        # 제목 — 불러온 원본 글의 제목 칸을 새 글 제목으로 교체(기존 내용 지우고 다시 입력).
        # (publish와 달리 in-place는 기존 글을 여는 거라 제목 칸이 차 있으므로 clear 필요)
        if plan.title:
            self._type_title(plan.title, clear=True)
            # 제목 입력 뒤 본문으로 포커스를 옮긴다. 단, 사진만 있는 불러온 글은 본문
            # 텍스트 컴포넌트(se-text)가 아예 없을 수 있어, 있을 때만 클릭한다. 없으면
            # 제목 선택만 풀어두면 아래 _place_anchor가 커서를 알아서 잡는다(30초 타임아웃 방지).
            if page.query_selector(SMART_EDITOR["content_component"]):
                page.click(SMART_EDITOR["content_component"])
                self._reset_text_toggles()  # publish와 동일 — 남은 토글 서식(굵게 등) 해제
            else:
                page.keyboard.press("Escape")

        # ── 사진 재배치(in-place) ─ 영상·콜라주·외부 이미지(협찬 배너)는 옮길 수 없거나 옮기면
        # 안 되어 고정 앵커로 두고, 네이버 업로드 사진은 전부
        # 삭제한 뒤 플랜 순서대로 다시 넣는다. 이러면 LLM이 정한 사진·텍스트 순서가 그대로 반영되고
        # (문서 물리 순서에 끌려가지 않음), 영상은 원자리에 보존된다. i번째 [영상] 블록 = i번째
        # 물리 영상으로 매핑해 그 사이 구간에 사진·텍스트·장식을 배치한다.
        # (프리미티브 검증: scripts/probe_photo_rebuild.py — 삭제→영상 고정→정확한 위치 재삽입.)
        n_phys_video = len(page.query_selector_all(SMART_EDITOR["editor_video"]))
        n_collage = self._count_collages()
        if n_collage:
            warnings.append(
                f"콜라주(여러 장을 묶은 사진) {n_collage}개는 옮길 수 없어 그대로 뒀어요 — "
                "그 주변 사진 순서는 확인해 주세요."
            )
        self._delete_movable_photos()  # 단일 네이버 사진만 삭제(영상·콜라주·외부 이미지 보존)

        # 보존된 외부 핫링크 이미지(협찬 배너 추적 URL) 현황 — 첫 미디어가 외부 이미지면
        # 본문을 그 '뒤'에 쌓아 배너를 최상단에 유지한다(체험단 규정: 고지는 글 상단).
        ext = page.evaluate(
            r"""() => {
              let n = 0, lead = null;
              for (const c of document.querySelectorAll('.se-component')) {
                const cls = c.className.toString();
                const imgs = c.querySelectorAll('img.se-image-resource');
                const isMedia = /se-video/.test(cls) || imgs.length > 0;
                const isExt = imgs.length === 1 && /^https?:/.test(imgs[0].src || '')
                              && !/pstatic\.net/.test(imgs[0].src);
                if (isExt) n++;
                if (isMedia && lead === null) lead = isExt;
              }
              return {n, lead: lead === true};
            }"""
        )
        # 외부 이미지 보존은 정상 동작이라 따로 알리지 않는다(알림이 실패처럼 읽힘).

        # 플랜을 [영상] 블록 기준으로 구간 분할. segment 0 = 첫 영상 앞, segment K = (K-1)번 영상 뒤.
        segments: list[list] = [[]]
        for block in plan.blocks:
            if block.kind == "video":
                segments.append([])
            elif block.kind in ("image", "text", "divider", "quote", "sticker", "place", "link", "table"):
                segments[-1].append(block)
            else:
                warnings.append(f"‘{block.kind}’ 블록은 자동 삽입을 건너뛰었어요(직접 추가 필요).")
        n_plan_video = len(segments) - 1
        if n_plan_video != n_phys_video:
            warnings.append(
                f"동영상 개수가 글({n_phys_video})과 글감({n_plan_video})이 달라 영상 주변 배치가 "
                "어긋날 수 있어요 — 확인해 주세요."
            )

        def _insert_one(block):
            if block.kind == "image" and block.image_path:
                warn = self._insert_image(block.image_path, size=block.image_size)
                if warn:
                    warnings.append(warn)
            elif block.kind == "text":
                self._type_text_block(block)
            elif block.kind == "divider":
                self._insert_divider(block.variant, align=block.align)
            elif block.kind == "quote":
                # at_end=False: 본문 끝으로 점프하지 않는다(다음 블록이 앵커를 다시 잡음)
                self._insert_quote(block.text, block.variant, align=block.align, at_end=False)
            elif block.kind == "sticker":
                self._insert_sticker(block.sticker_pack, block.sticker_index or 0, at_end=False)
            elif block.kind == "place" and block.text:
                try:  # 지도(장소) 카드 — 커서 위치에 삽입. 실패하면 사유 문자열
                    why = self._insert_place(block.text, address=block.place_address)
                except Exception as exc:  # noqa: BLE001 - 지도는 보조, 실패해도 본문 유지
                    page.keyboard.press("Escape")
                    why = f"에디터 오류({type(exc).__name__}: {exc})."
                if why:
                    warnings.append(
                        f"지도(장소) 자동 삽입 실패: ‘{block.text}’ — {why} "
                        "에디터에서 직접 ‘장소’를 추가해 주세요."
                    )
            elif block.kind == "link" and block.link_url:
                self._insert_link(block.link_url, keep_url_text=block.keep_url_text, at_anchor=True)
            elif block.kind == "table" and block.table_rows:
                if not self._insert_table(block.table_rows, at_anchor=True):
                    warnings.append("표 자동 삽입 실패 — 에디터에서 직접 ‘표’를 추가해 주세요.")

        def _anchor_segment(seg_idx) -> bool:
            # 구간 커서: 0=첫 미디어 앞, K>0=(K-1)번 물리 영상 바로 뒤(영상 부족하면 마지막 영상 뒤).
            # 반환값 = 앵커 성공 여부(캐럿이 실제로 본문에 잡혔는지). 역순 삽입 트릭은 매번
            # 같은 지점에 앵커가 잡혀야만 성립하므로, 실패를 삼키면 그 블록이 '직전에 넣은
            # 블록 뒤'에 붙어 순서가 뒤집힌다(맨 마지막에 넣는 '1.' 문단이 최하단에 남던 원인).
            if seg_idx == 0 or n_phys_video == 0:
                # 첫 미디어가 보존된 외부 이미지(협찬 배너)면 그 '뒤'에 쌓는다 — 맨 앞에 쌓으면
                # 본문이 배너 위로 밀려 고지가 상단에서 밀려난다. 실패 시 기존 최상단 앵커로.
                if ext["lead"] and self._anchor_after_photo(0):
                    return True
                return self._anchor_before_first_media()
            return self._anchor_after_video_index(min(seg_idx, n_phys_video) - 1)

        def _anchor_segment_retry(seg_idx) -> bool:
            """앵커를 잡고, 빗나가면 몇 번 다시 시도한다.

            앵커 실패는 팝업 잔여·객체선택 미스 등 일시적 원인이 대부분이라 재시도로 대개
            회복된다. 끝까지 실패하면 그 블록은 순서가 어긋난 자리에 들어가므로 호출부가
            경고를 남긴다(조용히 뒤섞이는 것보다 낫다)."""
            for attempt in range(3):
                if _anchor_segment(seg_idx):
                    return True
                page.keyboard.press("Escape")  # 남은 팝업·객체선택 해제 후 재시도
                page.wait_for_timeout(250 * (attempt + 1))
            return False

        # 각 구간 안에서 블록을 '역순'으로 넣되 매번 구간 앵커를 다시 잡아, 나중 것이 위로 밀려
        # 결과적으로 플랜 순서대로 쌓인다(커서 이어가기에 의존하지 않아 블록 종류가 섞여도 안전).
        anchor_failures = 0
        for seg_idx, blks in enumerate(segments):
            for block in reversed(blks):
                if not _anchor_segment_retry(seg_idx):
                    anchor_failures += 1
                _insert_one(block)
        if anchor_failures:
            warnings.append(
                f"본문 {anchor_failures}곳은 삽입 위치(커서)를 잡지 못해 순서가 어긋났을 수 있어요 "
                "— 발행 전에 문단·사진 순서를 확인해 주세요."
            )
        # 본문 입력 후 강조 적용(커서 간섭 방지 — 기존 publish와 동일한 후처리 패스).
        # 반드시 '플랜(문서) 순서'로 — 삽입은 역순이지만 강조까지 역순(아래→위)으로 걸면,
        # 직전 선택 위에 뜬 SE 플로팅 서식 툴바가 바로 윗줄(다음 대상)을 덮어 드래그 선택이
        # 막히고, 서식이 여전히 선택돼 있는 아랫줄에 덮인다(대제목 서식이 드립 줄에 가던
        # 실측 원인 — scripts/probe_inplace_header_style.py). 위→아래로 걸면 툴바는 항상
        # 이미 처리한 윗줄만 덮는다.
        emphases = [s for b in plan.blocks if b.kind == "text" for s in b.emphases]
        for span in emphases:
            try:
                self._apply_emphasis(span.text, span.style)
            except Exception:  # noqa: BLE001
                page.keyboard.press("Escape")
        # 저장 직전: 문단 정렬 검증·자동복구(in-place는 사진 앵커마다 사진 정렬을 상속해 특히 취약).
        self._heal_alignment(plan, warnings)
        # AI 생성 이미지에 'AI 활용' 표시(대표 지정보다 먼저 — 대표 플래그를 안 건드림).
        if mark_ai:
            self._mark_ai_images(plan)
        # 대표사진 지정은 반드시 '맨 마지막' — 위의 삭제·재삽입이 네이버 대표 플래그를 남은
        # 아무 사진으로 옮겨놓기 때문에, 모든 사진 조작이 끝난 여기서 명시적으로 재지정한다.
        self._set_rep_photo(plan, warnings)
        if save:
            if category or plan.tags:
                self._apply_category_for_draft(category, tags=plan.tags, warnings=warnings)
            self.save_draft()
        return warnings, infos

    def import_draft_photos(self, idx: int, dest_dir: Path) -> list[str]:
        """idx번 임시저장 글을 에디터에 로드해 본문 사진을 dest_dir에 내려받고 로컬 경로 목록을 반환.

        - 본문 사진은 img.se-image-resource(지도 se-map-image는 클래스가 달라 자동 제외).
        - lazy-load라 각 이미지를 화면에 스크롤시켜 실제 CDN URL이 채워질 때까지 폴링한다.
        - 다운로드는 로그인 세션(컨텍스트)으로 수행해 권한 문제를 피한다.
        """
        page = self._page
        self._load_draft_into_editor(idx)
        # 사진이 없는 글일 수 있으니 짧게만 기다린다.
        try:
            page.wait_for_selector(SMART_EDITOR["editor_image"], timeout=8000)
        except Exception:
            return []
        page.wait_for_timeout(1000)
        urls = page.evaluate(
            """async () => {
                const imgs = [...document.querySelectorAll('img.se-image-resource')];
                const out = [];
                for (const im of imgs) {
                    im.scrollIntoView({block: 'center'});
                    for (let t = 0; t < 25; t++) {
                        if (im.src && !im.src.startsWith('data:')) break;
                        await new Promise(r => setTimeout(r, 150));
                    }
                    if (im.src && !im.src.startsWith('data:')) out.push(im.src);
                }
                return out;
            }"""
        )
        # 순서 유지 중복 제거
        seen, ordered = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                ordered.append(u)
        # 로그인 컨텍스트로 다운로드(원본 화질 우선)
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[str] = []
        for u in ordered:
            path = self._download_image(u, dest_dir)
            if path:
                saved.append(path)
        return saved

    def _download_image(self, src: str, dest_dir: Path) -> str | None:
        """본문 사진 한 장을 원본 화질로 내려받아 로컬 경로를 반환(실패 시 None).

        표시용 축소본 src 대신 _original_url_candidates 순서로 시도한다 — 받은 파일이
        in-place에서 그대로 재업로드되므로 여기 화질이 발행 화질이 된다. 확장자는
        content-type을 따른다(협찬 배너는 GIF가 많아 .jpg로 저장하면 애니메이션 유실).
        """
        import uuid

        for url in _original_url_candidates(src):
            try:
                resp = self._ctx.request.get(url)
            except Exception:  # noqa: BLE001 - 후보 실패 시 다음 후보로
                continue
            ctype = resp.headers.get("content-type", "")
            if resp.status != 200 or not ctype.startswith("image/"):
                continue
            subtype = ctype.split("/", 1)[1].split(";", 1)[0].strip().lower()
            ext = {"png": ".png", "gif": ".gif", "webp": ".webp"}.get(subtype, ".jpg")
            dest = dest_dir / f"draft_{uuid.uuid4().hex[:8]}{ext}"
            dest.write_bytes(resp.body())
            return str(dest)
        return None

    # 문서 순서대로 미디어 컴포넌트를 훑어 {kind, src?}를 반환(사진/영상/콜라주 구분).
    #  - 단일사진(img 1개)=image + CDN src, 영상=video(재업로드 불가라 src 없음),
    #    콜라주(img 2개↑)=collage(한 컴포넌트에 여러 장 → 낱장으로 못 옮김, 고정 앵커).
    #  - lazy-load라 image src가 채워질 때까지 스크롤·폴링한다.
    _MEDIA_MANIFEST_JS = r"""
    async () => {
      const comps = [...document.querySelectorAll('.se-component')];
      const out = [];
      for (const c of comps) {
        const cls = c.className.toString();
        if (/se-video/.test(cls)) { out.push({kind: 'video'}); continue; }
        const imgs = [...c.querySelectorAll('img.se-image-resource')];
        if (imgs.length === 0) continue;              // 텍스트·구분선 등은 건너뜀
        if (imgs.length >= 2) { out.push({kind: 'collage', count: imgs.length}); continue; }
        const im = imgs[0];
        im.scrollIntoView({block: 'center'});
        for (let t = 0; t < 25; t++) {
          if (im.src && !im.src.startsWith('data:')) break;
          await new Promise(r => setTimeout(r, 150));
        }
        const src = (im.src && !im.src.startsWith('data:')) ? im.src : '';
        // 외부 핫링크(협찬 배너 추적 URL 등, src가 pstatic이 아님)는 다운로드·재업로드 금지
        // 대상이라 별도 종류로 표시한다(고정 앵커, 사진 목록에서 제외).
        const external = /^https?:/.test(src) && !/pstatic\.net/.test(src);
        out.push({kind: external ? 'external' : 'image', src});
      }
      return out;
    }
    """

    def import_draft_media(self, idx: int, dest_dir: Path) -> list[dict]:
        """idx번 임시저장 글의 미디어를 '문서 순서대로' 반환한다(사진·영상·콜라주 구분).

        반환: [{"kind": "image", "path": 로컬경로}, {"kind": "video"}, {"kind": "collage"}, …]
        - 사진(단일 img, 네이버 업로드)만 dest_dir로 다운로드해 로컬 경로를 준다(재삽입·재배치용).
        - 영상·콜라주는 재업로드가 불가/불완전하므로 다운로드하지 않고 '고정 앵커' placeholder만
          순서에 남긴다(in-place에서 위치 기준점으로 쓰고, 그 자리에 사진을 배치).
        - 외부 핫링크 이미지(협찬 배너 = 플랫폼 추적 URL)도 같은 이유로 placeholder만 남긴다 —
          재업로드하면 URL이 네이버 CDN으로 바뀌어 체험단 크롤러의 협찬 인식이 깨진다.
        import_draft_photos(사진만)의 상위 버전 — in-place가 영상 위치를 알게 하는 게 목적.
        """
        import uuid

        page = self._page
        self._load_draft_into_editor(idx)
        try:
            page.wait_for_selector(
                f"{SMART_EDITOR['editor_image']}, {SMART_EDITOR['editor_video']}", timeout=8000
            )
        except Exception:  # noqa: BLE001 - 미디어 없는 글일 수 있음
            return []
        page.wait_for_timeout(1000)
        items = page.evaluate(self._MEDIA_MANIFEST_JS)

        dest_dir.mkdir(parents=True, exist_ok=True)
        seen_src: set[str] = set()
        manifest: list[dict] = []
        for it in items:
            kind = it.get("kind")
            if kind == "video":
                # 영상은 재업로드 불가라 다운로드하지 않는다. 다만 UI가 타일·캡션으로 다루고
                # 재료/플랜이 위치를 알도록, 빈 .mp4 placeholder 파일을 만들어 경로를 준다
                # (썸네일은 is_video로 플레이스홀더 처리돼 파일을 열지 않음, in-place라 업로드도 안 함).
                dest = dest_dir / f"draft_vid_{uuid.uuid4().hex[:8]}.mp4"
                dest.write_bytes(b"")
                manifest.append({"kind": "video", "path": str(dest)})
                continue
            if kind == "collage":
                # 콜라주(여러 장이 한 컴포넌트)는 낱장으로 못 옮기니 옮기지 않고 고정 앵커로만 남긴다.
                # 사진 목록(이동 대상)에 넣지 않는다 — 실행기가 문서에서 그대로 둔다.
                manifest.append({"kind": "collage"})
                continue
            if kind == "external":
                # 외부 핫링크 이미지(협찬 배너 = 플랫폼 추적 URL). 다운로드해 재업로드하면 URL이
                # 네이버 CDN으로 바뀌어 협찬 인식이 깨진다 → 콜라주처럼 고정 앵커로 보존만 한다.
                manifest.append({"kind": "external"})
                continue
            src = it.get("src") or ""
            if not src or src in seen_src:  # 빈 src·중복(같은 이미지 재노출)은 건너뜀
                continue
            seen_src.add(src)
            path = self._download_image(src, dest_dir)  # 원본 화질 우선(축소본 재업로드 방지)
            if path:
                manifest.append({"kind": "image", "path": path})
        return manifest

    # --- 카테고리 (유저별 동적) ---
    def _open_publish_layer(self):
        self._page.click(SMART_EDITOR["publish_button"])
        self._page.wait_for_timeout(1500)

    def get_categories(self) -> list[str]:
        """현재 유저의 블로그 카테고리 목록을 동적으로 읽는다(발행 레이어).

        하드코딩 없이 계정마다 다른 카테고리를 그대로 가져온다.
        글쓰기 페이지가 아니면 먼저 연다.
        """
        if "postwrite" not in (self._page.url or ""):
            self.open_write_page()
        self._open_publish_layer()
        self._page.click(SMART_EDITOR["category_button"])
        self._page.wait_for_timeout(1000)
        names = self._page.evaluate("""() => {
            const seen = [];
            // 카테고리 셀렉트박스 내부 라벨만(공개설정/발행시점 라디오 제외)
            const scope = document.querySelector('[class*=option_category]') || document;
            scope.querySelectorAll('label[class*=radio_label]').forEach(el => {
                if (!el.offsetParent) return;
                const t = (el.innerText || '').trim().split('\\n').pop().trim();
                if (t && !seen.includes(t)) seen.push(t);
            });
            return seen;
        }""")
        # 네이버 표준 공개설정/발행시점 값은 카테고리가 아니므로 제외
        skip = {"전체공개", "이웃공개", "서로이웃공개", "비공개", "공개", "현재", "예약"}
        return [n for n in names if n not in skip]

    def get_categories_detailed(self) -> list[dict]:
        """카테고리를 이름+뎁스로 읽는다(들여쓰기 padLeft 기준). 중첩 카테고리도 계층 반영.

        반환: [{"name": str, "depth": int}]. depth는 들여쓰기 단계(0=최상위).
        """
        if "postwrite" not in (self._page.url or ""):
            self.open_write_page()
        self._open_publish_layer()
        self._page.click(SMART_EDITOR["category_button"])
        self._page.wait_for_timeout(1000)
        rows = self._page.evaluate("""() => {
            const scope = document.querySelector('[class*=option_category]') || document;
            const out = [];
            scope.querySelectorAll('label[class*=radio_label]').forEach(el => {
                if (!el.offsetParent) return;
                const t = (el.innerText || '').trim().split('\\n').pop().trim();
                const pl = parseFloat(getComputedStyle(el).paddingLeft) || 0;
                if (t) out.push({name: t, pad: pl});
            });
            return out;
        }""")
        skip = {"전체공개", "이웃공개", "서로이웃공개", "비공개", "공개", "현재", "예약"}
        rows = [r for r in rows if r["name"] not in skip]
        if not rows:
            return []
        # 들여쓰기(padLeft)를 뎁스로 환산: 최소 pad=깊이0, 그 위는 최소 양수 차이를 한 단계로
        pads = sorted({r["pad"] for r in rows})
        base = pads[0]
        steps = [b - a for a, b in zip(pads, pads[1:]) if b - a > 0]
        step = min(steps) if steps else 1
        seen, result = set(), []
        for r in rows:
            if r["name"] in seen:
                continue
            seen.add(r["name"])
            result.append({"name": r["name"], "depth": round((r["pad"] - base) / step)})
        return result

    def select_category(self, name: str):
        """카테고리를 이름(텍스트)으로 선택. 레이어/드롭다운이 열려있다고 가정.

        세부(하위) 카테고리는 라벨 innerText가 '하위 카테고리\\n<이름>' 형태라
        get_by_text(name, exact=True)로는 매칭 노드가 클릭 불가(타임아웃)해 빗나간다.
        그래서 옵션 스코프 안에서 get_categories_detailed와 동일한 규칙(마지막 줄 trim)으로
        라벨 인덱스를 찾아 그 라벨을 직접 클릭한다 — 최상위·세부 모두 동작."""
        # 드롭다운이 닫혀 있으면 연다
        try:
            self._page.click(SMART_EDITOR["category_button"], timeout=2000)
            self._page.wait_for_timeout(600)
        except Exception:
            pass
        idx = self._page.evaluate(
            """(target) => {
            const scope = document.querySelector('[class*=option_category]') || document;
            const labels = [...scope.querySelectorAll('label[class*=radio_label]')];
            return labels.findIndex(el => (el.innerText||'').trim().split('\\n').pop().trim() === target);
        }""",
            name,
        )
        if idx < 0:
            raise RuntimeError(f"카테고리를 찾지 못했습니다: {name}")
        label = self._page.locator('[class*=option_category] label[class*=radio_label]').nth(idx)
        label.scroll_into_view_if_needed()
        label.click()
        self._page.wait_for_timeout(500)

    # --- 에디터 조작 ---
    def _type_title(self, title: str, clear: bool = False):
        """제목 입력. 실제로 온전히 들어갔는지 확인하고, 잘렸으면 지우고 재시도한다.

        실측: 이 함수가 블록 삽입보다 먼저 실행되는데도(어떤 삽입 함수의 커서 버그와도
        무관) 제목이 "[폼폼푸린...전체" 중 "["만 남고 잘려서 타이핑된 사례가 나왔다 —
        페이지가 완전히 안정되기 전에 keyboard.type()이 시작되면 앞부분 키 입력이
        씹히는, 이 세션 전반에 걸친 더 근본적인 타이밍 문제로 보인다. 그래서 여기서도
        결과를 검증하고 짧으면 지우고 다시 친다(최대 3회)."""
        page = self._page
        for attempt in range(3):
            self._click_safe(SMART_EDITOR["title_component"])
            page.keyboard.press("ControlOrMeta+a")
            page.keyboard.press("Delete")
            page.wait_for_timeout(150)
            page.keyboard.type(title, delay=8)
            page.wait_for_timeout(200)
            actual = (
                page.eval_on_selector(SMART_EDITOR["title_component"], "el => el ? el.innerText : ''")
                or ""
            ).strip()
            if actual == title.strip():
                return
        # 3회 재시도로도 안 되면 이후 _verify_body_text가 최종 확인에서 막는다(여기선
        # 강제 실패시키지 않고 넘어간다 — clear=False일 때 첫 클릭이 제목 조합 방식에
        # 민감할 수 있어, 조기 예외보다 마지막 안전망에 맡기는 편이 더 안전하다).

    def _reset_text_toggles(self):
        """본문 진입 시, 직전 세션에서 켜진 채 남은 토글 서식(취소선/굵게/기울임/밑줄)이
        활성(se-is-selected)이면 한 번 눌러 끈다. 활성이 아니면 건드리지 않는다.

        커서가 본문에 자리잡고 툴바가 실제 상태를 반영할 시간을 준 뒤(대기) 판정한다 —
        포커스 직후엔 직전 상태가 잠깐 남아 오판할 수 있어 충분히 기다린다.
        """
        page = self._page
        page.wait_for_timeout(500)  # 툴바가 현재 커서 서식을 반영하도록 충분히 대기
        page.evaluate("""() => {
          const names = ['se-strikethrough-toolbar-button','se-bold-toolbar-button',
                         'se-italic-toolbar-button','se-underline-toolbar-button'];
          for (const name of names) {
            const b = document.querySelector('button.' + name);
            if (b && /se-is-selected/.test(b.className)) b.click();  // 활성일 때만 끈다
          }
        }""")
        page.wait_for_timeout(300)

    def _type_text_block(self, block: PublishBlock):
        """본문 한 블록 입력. \\n은 Enter(문단), 블록 끝에 빈 줄 하나.

        정렬은 상속에 맡기지 않고 블록마다 명시한다 — SE는 새 문단이 직전 문단이나
        사진 '컴포넌트'의 정렬을 이어받아, 사진 뒤에 앵커된 문단이 사진 정렬(left 등)을
        그대로 상속한다. 그래서 left 블록도 건너뛰지 않고 걸어야 한다(안 걸면 직전이
        center일 때 left가 조용히 빠진다). 현재 정렬을 읽어 다를 때만 적용해 비용을 줄인다."""
        target = block.align or "left"
        if self._current_align() != target:
            self._apply_align(target)
        self._type_with_keycaps(block.text)
        self._page.keyboard.press("Enter")

    # 키캡 이모지(1️⃣ = 숫자+U+FE0F+U+20E3 결합)는 한 글자씩 치면 결합이 깨져 '1' 따로,
    # 빈 네모(⃣) 따로 들어간다. 통째로 insert_text 하면 브라우저가 한 덩어리로 받아 안 깨진다.
    _KEYCAP_RE = re.compile(r"[0-9](?:️)?⃣")

    def _type_with_keycaps(self, text: str):
        """키캡 이모지 구간만 insert_text로 통째 넣고, 나머지는 기존대로 한 글자씩 친다.

        키캡 외 구간은 \\n을 그대로 넘겨 기존 keyboard.type의 문단(Enter) 처리를 유지한다.
        키캡은 변이 선택자(U+FE0F)를 붙인 표준형으로 정규화해 컬러 이모지로 또렷이 렌더한다."""
        pos = 0
        for m in self._KEYCAP_RE.finditer(text):
            if m.start() > pos:
                self._page.keyboard.type(text[pos : m.start()], delay=4)
            self._page.keyboard.insert_text(m.group()[0] + "️⃣")
            pos = m.end()
        if pos < len(text):
            self._page.keyboard.type(text[pos:], delay=4)

    # 지도(장소) 카드 개수 — 총 컴포넌트 수 증가로는 못 잡는다. SE는 커서가 빈 문단에 있으면
    # 그 문단을 지도 카드로 '치환'해서 총 개수가 그대로일 때가 있고(→ 성공인데 실패로 경고했음),
    # 사진 로드 등 다른 이유로 총 개수가 늘 수도 있다. 지도 카드만 세는 게 정확하다.
    # 지도 카드 표식: 컴포넌트 클래스의 placesMap/se-map 또는 내부 지도 이미지(img.se-map-image).
    _MAP_COUNT_JS = (
        "()=>[...document.querySelectorAll('.se-component')].filter(c=>"
        "/placesMap|se-map/.test(c.className||'')||"
        "c.querySelector('.se-map-image,[class*=\"placesMap\"]')).length"
    )

    def _insert_place(self, query: str, address: str | None = None) -> str:
        """SE 네이티브 '장소' 카드 삽입 — 실패 사유를 돌려준다(성공이면 "").

        어떤 경로로 실패했든 '지도 카드가 실제로 늘었는지'를 마지막에 다시 확인해서,
        카드는 잘 들어갔는데 클릭·대기 사정으로 실패처럼 보인 경우엔 경고하지 않는다
        (헛경고가 실제 실패보다 잦았다)."""
        page = self._page
        maps_before = page.evaluate(self._MAP_COUNT_JS)
        # 장소 팝업이 열리고 닫히는 사이 contenteditable의 selection이 날아간다. 캐럿이 없으면
        # SE가 지도 카드를 문서 기본 위치(=맨 위)에 꽂아, 미리보기와 순서가 완전히 달라진다
        # (지도가 최상단으로 튀던 실측 원인). 삽입 직전 문단에 표식을 찍어 두고 복원한다.
        self._mark_caret()
        try:
            why = self._place_flow(query, address)
        except Exception as exc:  # noqa: BLE001 - 실패해도 아래에서 카드 생성 여부로 재판정
            page.keyboard.press("Escape")
            why = f"에디터 오류({type(exc).__name__}: {exc})."
        finally:
            self._clear_caret_mark()  # 표식이 본문에 남아 저장되지 않게
        if why and page.evaluate(self._MAP_COUNT_JS) > maps_before:
            return ""  # 실패처럼 보였지만 카드는 들어감
        return why

    def _place_flow(self, query: str, address: str | None) -> str:
        """가게명 검색 → 수집 주소와 가장 잘 맞는 결과 '추가' → '확인'. 실패 사유 반환.

        address(수집된 도로명 주소)를 주면 동명 가게가 여럿일 때 주소 유사도로 정확한
        결과를 고른다. 없거나 매칭이 약하면 첫 결과로 폴백. 결과가 아예 없으면 팝업만
        닫고 실패(본문 유지). 커서 위치에 지도 카드가 삽입된다."""
        page = self._page
        n_before = page.evaluate(self._MAP_COUNT_JS)
        page.click("button.se-map-toolbar-button")
        page.wait_for_timeout(1500)
        items: list[dict] = []
        relaxed = False
        for i, q in enumerate(self._place_query_variants(query)):
            items = self._search_place(q)
            if items:
                relaxed = i > 0
                break
        if not items:
            close = page.query_selector("button.se-popup-close-button")
            if close:
                close.click()
            # 팝업을 열고 닫는 동안 캐럿이 날아간 채로 남는다 — 복원 안 하면 이어지는
            # 타이핑이 엉뚱한 위치로 꽂힌다(실측). 성공 경로(아래 _restore_caret)와 동일하게
            # 실패 경로에서도 반드시 복원한다.
            self._restore_caret()
            return "네이버 장소 검색 결과가 없어 건너뛰었어요."
        idx = self._best_place_index(items, query, address)
        if relaxed and not self._addr_matches(items[idx].get("address", ""), address):
            # 완화 질의(브랜드명만)는 엉뚱한 지점이 걸릴 수 있어 주소가 맞을 때만 쓴다
            close = page.query_selector("button.se-popup-close-button")
            if close:
                close.click()
            self._restore_caret()
            return "이름 그대로는 검색 결과가 없고, 완화 검색 결과는 수집 주소와 달라 건너뛰었어요."
        # 결과 리스트가 스크롤 영역이라 Playwright 가시성 검사에 안 걸릴 때가 있어 DOM .click()으로.
        page.evaluate(
            "(i)=>{const its=document.querySelectorAll('.se-place-map-search-result-item');"
            "const b=its[i]&&its[i].querySelector('.se-place-add-button');if(b)b.click();}",
            idx,
        )
        page.wait_for_timeout(800)
        # '확인'을 누르는 순간 SE가 캐럿 위치에 카드를 꽂는다 — 팝업 조작으로 날아간 캐럿을
        # 여기서 되돌려야 지도가 원래 자리(마커가 있던 문단)에 들어간다. 복원 실패 시엔
        # 그대로 진행하고, 위치 어긋남은 호출부가 카드 위치로 검증한다.
        self._restore_caret()
        page.evaluate(
            "()=>{const b=document.querySelector('button.se-popup-button-confirm');if(b)b.click();}"
        )
        # 지도 카드는 타일/좌표 로드가 있어 렌더링이 느릴 수 있음 — _insert_link와 같은
        # 폴링 재시도(최대 ~7초)로 판정한다(고정 1회 대기는 오탐의 원인이었음).
        created = False
        for _ in range(14):
            page.wait_for_timeout(500)
            confirm = page.query_selector("button.se-popup-button-confirm")
            if confirm:
                try:  # 팝업이 막 닫히는 중이면 핸들이 떨어져 예외 — 삽입 자체는 성공일 수 있다
                    confirm.click()
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(600)
            if page.evaluate(self._MAP_COUNT_JS) > n_before:
                created = True
                break
        if not created:
            page.keyboard.press("Escape")  # 팝업이 남아 있으면 닫아 다음 삽입 보호
            return "검색 결과는 있었지만 장소 카드가 만들어지지 않았어요."
        return ""

    def _search_place(self, q: str) -> list[dict]:
        """열려 있는 장소 팝업에서 q로 검색 → 결과 항목 [{title, address}]."""
        page = self._page
        page.fill("input.react-autosuggest__input", "")
        page.fill("input.react-autosuggest__input", q)
        page.wait_for_timeout(400)
        # 자동완성 드롭다운이 검색 버튼을 덮으면 Playwright click이 가시성 검사에서 막힌다 — DOM click으로 우회
        page.evaluate(
            "()=>{const b=document.querySelector('button.se-place-search-button');if(b)b.click();}"
        )
        page.wait_for_timeout(2800)
        return page.evaluate(
            r"""()=>[...document.querySelectorAll('.se-place-map-search-result-item')].map(it=>({
              title:(it.querySelector('.se-place-map-search-result-title')||{}).textContent||'',
              address:(it.querySelector('.se-place-map-search-result-address')||{}).textContent||'',
            }))"""
        )

    @staticmethod
    def _place_query_variants(name: str) -> list[str]:
        """검색 0건일 때 순서대로 시도할 질의 — 원본 → 지점 접미사 제거.

        '차지 강남플래그십점'처럼 지점명이 붙으면 SE 장소 검색이 0건으로 나오는 경우가 있어
        브랜드명만으로 한 번 더 찾는다(대신 주소가 맞을 때만 채택)."""
        out = [name]
        base = re.sub(r"\s*\S*점$", "", name).strip()
        if base and base != name:
            out.append(base)
        return out

    @classmethod
    def _addr_matches(cls, found: str, address: str | None) -> bool:
        """검색 결과 주소가 수집 주소와 같은 곳인지(한쪽이 다른 쪽을 포함)."""
        a1, a2 = cls._norm_addr(address), cls._norm_addr(found)
        return bool(a1 and a2 and (a1 in a2 or a2 in a1))

    def _insert_link(self, url: str, keep_url_text: bool = False, at_anchor: bool = False) -> bool:
        """SE 링크 카드(oglink) 삽입 — 본문에 URL을 합성 paste 이벤트로 붙여넣어 카드 생성.

        툴바 '링크'(글감검색) 버튼은 외부 URL을 "글감을 가져올 수 없습니다"로 거부하므로 못 쓴다.
        대신 contenteditable에 DataTransfer 기반 paste 이벤트를 디스패치하면(시스템 클립보드 불필요
        → 권한 팝업 없음) 네이버가 OG 메타데이터를 받아 se-oglink 카드를 만든다. 붙여넣기는 URL을
        '일반 텍스트 줄'로도 남기므로, 카드 생성 뒤 그 텍스트 줄을 찾아 삭제한다(SEO상 맨 URL 방지).
        라이브 검증: 쿠팡파트너스 링크 → 'Coupang Partners' 카드 1개, 텍스트 잔여 없음.

        keep_url_text=True면 그 'URL 텍스트 줄'을 지우지 않고 카드와 함께 남긴다 — 협찬/체험단
        플랫폼 크롤러가 발행글 HTML에서 '지정 캠페인 URL 문자열'을 찾아 인식하는데, oglink 카드의
        href는 네이버 리다이렉트로 감싸져 원본 URL이 안 보일 수 있어 텍스트로도 남겨둬야 잡힌다.

        at_anchor=True(in-place)면 본문 끝으로 가지 않고 '현재 커서'(앵커가 잡아둔 사진 뒤 빈
        문단)에 그대로 붙여넣는다 — 일반 게시는 끝에 몰아 넣으면 되지만 in-place는 위치가 중요."""
        page = self._page
        if not at_anchor:
            # 사진·구분선·인용구 등으로 본문이 이미 여러 se-text 컴포넌트로 쪼개진 뒤라
            # content_component 셀렉터로 클릭하면 '첫' 컴포넌트가 잡혀 커서가 문서 앞으로
            # 튄다(_resize_image_smallest의 _focus_body_end와 동일 문제) — 항상 진짜
            # 문서 끝으로 보내는 canvas 하단 버튼을 쓴다.
            self._focus_body_end()
            page.wait_for_timeout(200)

        before = page.evaluate("()=>document.querySelectorAll('.se-component.se-oglink').length")
        dispatched = page.evaluate(
            """(url)=>{
              const el=(document.activeElement&&document.activeElement.isContentEditable)
                ? document.activeElement : document.querySelector('[contenteditable=true]');
              if(!el) return false;
              el.focus(); const dt=new DataTransfer(); dt.setData('text/plain', url);
              el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
              return true;
            }""",
            url,
        )
        if not dispatched:
            return False
        # OG 카드 변환 대기(최대 ~7초). 첨부 확인 팝업이 뜨면 확인 클릭.
        created = False
        for _ in range(14):
            page.wait_for_timeout(500)
            confirm = page.query_selector("button.se-popup-button-confirm")
            if confirm:
                confirm.click()
                page.wait_for_timeout(600)
            if page.evaluate("()=>document.querySelectorAll('.se-component.se-oglink').length") > before:
                created = True
                break
        if not created:
            return False
        # 협찬 링크는 크롤러가 URL 문자열을 잡도록 텍스트 줄을 일부러 남긴다.
        if keep_url_text:
            return True
        # 붙여넣기가 남긴 '일반 URL 텍스트 줄' 제거(트리플클릭으로 줄 선택 → 삭제)
        box = page.evaluate(
            """(url)=>{
              const t=[...document.querySelectorAll('.se-component.se-text')]
                .find(c=>(c.textContent||'').trim()===url);
              if(!t) return null; const r=t.getBoundingClientRect();
              return {x:r.x+r.width/2, y:r.y+r.height/2};
            }""",
            url,
        )
        if box:
            page.mouse.click(box["x"], box["y"], click_count=3)
            page.wait_for_timeout(200)
            page.keyboard.press("Delete")
            page.wait_for_timeout(150)
            page.keyboard.press("Backspace")  # 남은 빈 줄 제거
            page.wait_for_timeout(300)
        return True

    def _insert_table(self, rows: list[list[str]], at_anchor: bool = False) -> bool:
        """마크다운 표(행×셀) → 네이티브 SE 표. _insert_link과 같은 합성 paste(text/html) 기법.

        네이버 에디터는 클립보드의 text/html에 <table>이 있으면 SE 표 컴포넌트로 변환한다.
        시스템 클립보드 대신 DataTransfer로 paste 이벤트를 디스패치해 권한 팝업을 피한다.
        라이브 세션에서만 실제 변환 확인 가능 — 표 컴포넌트가 안 생기면 False(사람이 직접 조치)."""
        import html as _html

        if not rows:
            return False
        page = self._page
        tr = "".join(
            "<tr>" + "".join(f"<td>{_html.escape(c)}</td>" for c in r) + "</tr>" for r in rows
        )
        table_html = f"<table><tbody>{tr}</tbody></table>"
        if not at_anchor:
            # _insert_link과 동일 문제: 본문이 이미 여러 se-text 컴포넌트로 쪼개진 뒤라
            # content_component 클릭은 '첫' 컴포넌트를 잡아 커서가 문서 앞으로 튄다.
            # 표를 거기 끼워 넣으면 그 뒤에 이어질 타이핑 전부가 잘못된 위치로 밀린다
            # (이번 폼폼푸린 글에서 본문 절반이 유실된 원인) — 진짜 문서 끝으로 보내는
            # canvas 하단 버튼을 쓴다.
            self._focus_body_end()
            page.wait_for_timeout(200)
        before = page.evaluate("()=>document.querySelectorAll('.se-component').length")
        page.evaluate(
            """(html)=>{
              const el=(document.activeElement&&document.activeElement.isContentEditable)
                ? document.activeElement : document.querySelector('[contenteditable=true]');
              if(!el) return; el.focus();
              const dt=new DataTransfer(); dt.setData('text/html', html);
              el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
            }""",
            table_html,
        )
        for _ in range(10):  # 표 컴포넌트 생성 대기(~5초)
            page.wait_for_timeout(500)
            if page.evaluate("()=>document.querySelectorAll('.se-table,.se-component-table').length"):
                return True
            if page.evaluate("()=>document.querySelectorAll('.se-component').length") > before:
                return True
        return False

    # 시/도 풀네임 → 약칭(수집 주소는 '서울', SE 결과는 '서울특별시'라 통일)
    _SIDO = {
        "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
        "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
        "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북",
        "충청남도": "충남", "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
        "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주", "제주도": "제주",
    }

    @classmethod
    def _norm_addr(cls, s: str) -> str:
        s = s or ""
        for long, short in cls._SIDO.items():
            s = s.replace(long, short)
        return re.sub(r"\s+", "", s)

    @classmethod
    def _best_place_index(cls, items: list[dict], name: str, address: str | None) -> int:
        """검색 결과 중 수집한 이름·주소와 가장 잘 맞는 항목의 인덱스(약하면 0)."""
        a1 = cls._norm_addr(address) if address else ""
        best_i, best_score = 0, -1.0
        for i, it in enumerate(items):
            ns = difflib.SequenceMatcher(None, name or "", it.get("title", "")).ratio()
            a2 = cls._norm_addr(it.get("address", ""))
            if a1 and a2:
                asc = difflib.SequenceMatcher(None, a1, a2).ratio()
                if a1 in a2 or a2 in a1:  # 한쪽이 다른 쪽을 포함하면 강한 일치
                    asc = max(asc, 0.95)
            else:
                asc = 0.0
            score = 0.55 * asc + 0.45 * ns if a1 else ns
            if score > best_score:
                best_i, best_score = i, score
        # 주소 힌트가 있는데도 매칭이 약하면(동명 다수·오검색 의심) 그래도 최고점을 쓰되,
        # 첫 결과가 더 그럴듯하면 첫 결과. 임계 미만이면 0으로 폴백.
        return best_i if best_score >= 0.5 else 0

    # 커서가 놓인 문단의 '현재 정렬'을 정렬 툴바 버튼 클래스에서 읽는 JS.
    # SE는 커서 문단의 정렬을 se-align-{left|center|right}-toolbar-button 클래스로 반영한다(라이브 검증됨).
    _CURRENT_ALIGN_JS = (
        "()=>{const b=document.querySelector('li.se-toolbar-item-align button');"
        "if(!b)return '';const m=b.className.toString().match(/se-align-(\\w+)-toolbar-button/);"
        "return m?m[1]:'';}"
    )

    def _current_align(self) -> str:
        """커서가 놓인 문단의 현재 정렬(left/center/right). 못 읽으면 ''."""
        try:
            return self._page.evaluate(self._CURRENT_ALIGN_JS) or ""
        except Exception:  # noqa: BLE001
            return ""

    def _apply_align(self, value: str):
        """현재 단락 정렬(left/center/right/justify). 선택 없이 커서 위치 단락에 적용.

        드롭다운 클릭이 타이밍에 따라 빈손으로 끝나(옵션 미렌더) 정렬이 조용히 안 걸리는 일이
        있었다 → 적용 후 툴바 상태로 검증하고, 어긋나면 몇 번 재시도한다(무음 실패 제거)."""
        page = self._page
        for _ in range(3):
            page.evaluate("()=>{const b=document.querySelector('li.se-toolbar-item-align button');if(b)b.click();}")
            page.wait_for_timeout(300)
            page.evaluate(
                "(v)=>{const o=document.querySelector("
                "'button[data-name=\"align-drop-down-with-justify\"][data-value=\"'+v+'\"]');if(o)o.click();}",
                value,
            )
            page.wait_for_timeout(250)
            cur = self._current_align()
            if cur == value or cur == "":  # 일치하면 끝(못 읽으면 더 깨지않게 멈춘다)
                return

    # 본문 텍스트 문단별 (index, 정렬토큰, 내용유무, 내용)를 떠내는 JS.
    # 정렬은 문단 className 의 se-text-paragraph-align-{left|center|right} 로 박힌다(라이브 검증됨).
    # text는 플랜의 텍스트 블록 줄과 대조해 '이 문단이 원래 어떤 정렬이어야 하는지' 찾는 데 쓴다.
    _PARA_ALIGN_DUMP_JS = r"""
    () => {
      const out = [];
      const paras = document.querySelectorAll('.se-component.se-text .se-text-paragraph');
      paras.forEach((p, i) => {
        const m = (p.className.toString().match(/se-text-paragraph-align-(\w+)/) || [])[1] || 'left';
        const t = (p.textContent || '').trim();
        out.push({i, align: m, hasText: t.length > 0, text: t});
      });
      return out;
    }
    """

    def _read_paragraph_aligns(self) -> list[dict]:
        """본문 텍스트 문단들의 실제 정렬을 DOM에서 읽어 [{i, align, hasText}, ...] 로 반환."""
        try:
            return self._page.evaluate(self._PARA_ALIGN_DUMP_JS) or []
        except Exception:  # noqa: BLE001
            return []

    def _verify_and_fix_alignment(self, expected: str = "center", passes: int = 3) -> int:
        """게시 후 본문 문단 정렬을 읽어 expected와 다른(내용 있는) 문단을 다시 정렬한다.

        왼쪽정렬 사진 뒤에 끼워넣은 문단이 사진 정렬을 상속하거나 _apply_align 이 한 번
        빗나가면 중앙정렬이 빠진다. 여기서 실제 DOM 정렬을 '읽어' 검증하고 어긋난 문단에
        커서를 넣어 다시 정렬한다(SE 상속 때문에 한 번 고치면 뒤 빈 문단도 따라오므로 몇 번 훑는다).
        고친 문단 수를 반환한다(0이면 모두 정상)."""
        fixed = 0
        for _ in range(passes):
            bad = [p for p in self._read_paragraph_aligns() if p["hasText"] and p["align"] != expected]
            if not bad:
                break
            for p in bad:
                nodes = self._page.query_selector_all(".se-component.se-text .se-text-paragraph")
                if p["i"] >= len(nodes):
                    continue
                try:
                    nodes[p["i"]].scroll_into_view_if_needed()
                    nodes[p["i"]].click()
                    self._page.wait_for_timeout(150)
                    self._apply_align(expected)
                    fixed += 1
                except Exception:  # noqa: BLE001 - 한 문단 복구 실패가 전체를 막지 않게
                    self._page.keyboard.press("Escape")
        return fixed

    # 문단 내용 대조용 정규화 — 공백과 변이 선택자(U+FE0F)를 지운다. 키캡 이모지는
    # 타이핑 시 표준형(숫자+FE0F+⃣)으로 정규화돼 플랜 원문과 DOM이 다를 수 있어서다.
    @staticmethod
    def _norm_para_key(s: str) -> str:
        return re.sub(r"[\s️]+", "", s or "")

    def _heal_alignment(self, plan, warnings: list[str]) -> None:
        """저장 직전, 본문 문단들의 실제 정렬을 플랜과 '내용으로' 대조해 어긋난 문단을 복구한다.

        문단 내용(공백 제거)으로 플랜 텍스트 블록의 줄을 찾아 그 줄의 기대 정렬과 비교하므로,
        정렬이 섞인 글(해시태그 left + 본문 center 등)도 문단 단위로 정확히 복구한다
        (종전에는 '전부 center'일 때만 복구하고 섞이면 경고만 남겼다). 같은 내용의 줄이
        여럿이면 문서 순서대로 플랜 순서에 대응시킨다. 한 문단을 고치면 SE 상속으로 뒤
        빈 문단 정렬이 바뀔 수 있어 몇 번 훑는다."""
        expected: dict[str, list[str]] = {}
        for b in plan.blocks:
            if b.kind != "text":
                continue
            for ln in b.text.split("\n"):
                key = self._norm_para_key(ln)
                if key:
                    expected.setdefault(key, []).append(b.align or "left")
        if not expected:
            return
        fixed = 0
        for _ in range(3):
            pending = {k: list(v) for k, v in expected.items()}
            bad: list[tuple[int, str]] = []
            for p in self._read_paragraph_aligns():
                aligns = pending.get(self._norm_para_key(p.get("text", "")))
                if not aligns:
                    continue  # 플랜에 없는 문단(빈 줄·불러온 글 잔여 등)은 건드리지 않는다
                want = aligns.pop(0)
                if p["align"] != want:
                    bad.append((p["i"], want))
            if not bad:
                break
            for i, want in bad:
                nodes = self._page.query_selector_all(".se-component.se-text .se-text-paragraph")
                if i >= len(nodes):
                    continue
                try:
                    nodes[i].scroll_into_view_if_needed()
                    nodes[i].click()
                    self._page.wait_for_timeout(150)
                    self._apply_align(want)
                    fixed += 1
                except Exception:  # noqa: BLE001 - 한 문단 복구 실패가 전체를 막지 않게
                    self._page.keyboard.press("Escape")
        if fixed:
            warnings.append(f"정렬이 어긋난 문단 {fixed}개를 자동으로 다시 정렬했어요.")

    def _apply_emphasis(self, text: str, style: EmphasisStyle):
        """본문에서 text를 선택 → 글자색/배경색을 커스텀 hex로 정확히 적용.

        '더보기 → hex 입력 → 확인'은 SE 네이티브 명령이라 내부 모델을 갱신 →
        커스텀 색이 저장까지 유지된다(검증됨).
        """
        if not (style.text_color or style.background_color or style.font_family or style.font_size):
            return
        if not self._select_body_text(text):  # 한 번만 선택(SE가 적용 후 선택 유지)
            return
        if style.text_color:
            self._apply_color(SMART_EDITOR["toolbar_text_color"], style.text_color)
        if style.background_color:
            self._apply_color(SMART_EDITOR["toolbar_bg_color"], style.background_color)
        if style.font_family:
            self._apply_font(style.font_family)
        if style.font_size:
            self._apply_font_size(style.font_size)

    def _apply_font(self, font_value: str):
        """선택 텍스트에 서체 적용(프리셋 fontFamily). 드롭다운 열고 data-value 옵션 클릭.

        드롭다운이 타이밍에 따라 늦게 렌더되면 옵션 클릭이 빈손으로 끝나 서체가 조용히
        안 먹는다(_apply_align에서 잡았던 것과 같은 무음 실패) → 옵션을 실제로 눌렀는지
        확인하고 못 눌렀으면 드롭다운을 다시 열어 재시도한다."""
        self._pick_toolbar_option(
            "li.se-toolbar-item-font-family button", "font-family", font_value
        )

    def _apply_font_size(self, size):
        """선택 텍스트에 글자 크기 적용(프리셋 fontSize → data-value 'fs<N>'). 무음 실패 재시도 동일."""
        self._pick_toolbar_option(
            "li.se-toolbar-item-font-size-code button", "font-size", f"fs{size}"
        )

    def _pick_toolbar_option(self, button_sel: str, name: str, value: str) -> bool:
        """툴바 드롭다운을 열고 data-name/data-value 옵션을 '확인하며' 클릭(서체·글자크기 공용).

        옵션이 아직 안 떠 못 눌렀으면 드롭다운을 다시 열어 몇 번 재시도한다. 눌렀으면 True."""
        page = self._page
        for _ in range(3):
            page.evaluate(
                "(sel)=>{const b=document.querySelector(sel);if(b)b.click();}", button_sel
            )
            page.wait_for_timeout(400)
            clicked = page.evaluate(
                "(a)=>{const o=[...document.querySelectorAll("
                "'button[data-name=\"'+a.name+'\"][data-role=\"option\"]')]"
                ".find(e=>e.getAttribute('data-value')===a.value);"
                "if(o){o.click();return true;}return false;}",
                {"name": name, "value": value},
            )
            page.wait_for_timeout(300)
            if clicked:
                return True
        return False

    def _select_body_text(self, text: str) -> bool:
        """본문에서 text를 실제 마우스 드래그로 선택(SE가 선택을 인식하도록)."""
        rect = self._page.evaluate(_RANGE_RECT_JS, text)
        if not rect or rect["w"] < 1:
            return False
        page = self._page
        y = rect["y"] + rect["h"] / 2
        page.mouse.move(rect["x"] + 1, y)
        page.mouse.down()
        # 끝점은 range 경계(x+w) 정확히 — w-1은 마지막 글자 안쪽에 떨어져 좁은 글자('.')가
        # 선택에서 빠지는 off-by-one이 실측됨. 경계 지점이라 다음 글자를 넘겨 잡지도 않는다.
        page.mouse.move(rect["x"] + rect["w"], y, steps=6)
        page.mouse.up()
        # SE 선택은 iframe 안에 있어 top-frame window.getSelection()으로 관측되지 않는다
        # (프로브 확인됨). 폴링 신호가 없어 고정 settle 대기를 유지한다.
        page.wait_for_timeout(200)
        return True

    @staticmethod
    def _parse_hex(hex_color: str) -> tuple[int, int, int] | None:
        v = (hex_color or "").strip().lstrip("#")
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        if len(v) != 6:
            return None
        try:
            return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
        except ValueError:
            return None

    # 스와치를 '같은 색'으로 인정하는 RGB 제곱거리 상한(채널당 ~3 차이 ≈ ΔE 수준).
    # 파워단축키 색은 대부분 SE 프리셋의 정확한 멤버(거리 0)라 거의 항상 스와치로 끝난다.
    _SWATCH_MATCH_MAX = 30

    def _apply_color(self, toolbar_button: str, hex_color: str):
        """선택 텍스트에 글자색/배경색 적용.

        1순위(빠름): 색 팔레트에서 목표색과 일치하는 프리셋 스와치를 직접 클릭(~0.3s).
        2순위(폴백): 일치 스와치가 없으면 '더보기 → hex 입력 → 확인'으로 임의 hex를
                     정확히 적용(~1.4s). 둘 다 네이티브 명령이라 저장까지 유지된다.
        """
        page = self._page
        page.click(toolbar_button)
        # 팔레트가 뜨는 즉시 진행(고정 350ms 대신). 못 뜨면 짧게만 기다리고 폴백으로.
        try:
            page.wait_for_selector(".se-color-palette", state="visible", timeout=2000)
        except Exception:
            page.wait_for_timeout(350)
        tgt = self._parse_hex(hex_color)
        if tgt is not None:
            best, best_d = None, None
            for s in page.evaluate(_SWATCH_DUMP_JS):
                d = (s["r"] - tgt[0]) ** 2 + (s["g"] - tgt[1]) ** 2 + (s["b"] - tgt[2]) ** 2
                if best_d is None or d < best_d:
                    best, best_d = s, d
            if best is not None and best_d <= self._SWATCH_MATCH_MAX:
                page.mouse.click(best["x"], best["y"])  # 실제 클릭이어야 SE가 선택에 반영
                page.wait_for_timeout(250)
                return
        # 폴백: 더보기 → hex 입력 → 확인
        page.click(SMART_EDITOR["color_more_button"])
        page.wait_for_timeout(350)
        inp = page.query_selector(SMART_EDITOR["color_hex_input"])
        inp.click()
        inp.fill(hex_color.lstrip("#"))
        page.wait_for_timeout(200)
        page.click(SMART_EDITOR["color_apply_button"])
        page.wait_for_timeout(350)

    def _insert_divider(self, variant: int = 1, align: str | None = None):
        """구분선 삽입. 항상 종류 드롭다운에서 variant번째를 고른다(variant=1=기본선).

        기본 빠른버튼(...-default-toolbar-button)을 쓰지 않는 이유: 드롭다운으로 한 번
        다른 종류를 고르면 SE-ONE이 그 종류를 기억해 빠른버튼 클래스가 바뀌어 사라진다.
        그래서 변형>1 다음 변형1을 넣을 때 기본 버튼을 못 찾는다 → 경로를 드롭다운으로 통일."""
        self._pick_insert_variant("horizontal-line", max(variant, 1))
        self._page.wait_for_timeout(500)
        if align and align != "left":
            self._align_divider(align)

    def _align_divider(self, value: str = "center"):
        """방금 넣은 구분선(HR 컴포넌트)을 가운데 등으로 정렬.

        구분선은 텍스트 '문단'이 아니라 컴포넌트라, 커서 위치 정렬(_apply_align)은 옆 빈 문단에만
        걸리고 HR엔 안 박힌다(짧은 장식형 구분선이 왼쪽에 붙는 원인). HR 컴포넌트를 직접 클릭해
        선택한 뒤 정렬하고, 내부 .se-section의 se-section-align-{value} 클래스로 실제 적용을 검증한다."""
        page = self._page
        comps = page.query_selector_all(".se-component.se-horizontalLine")
        if not comps:  # 못 찾으면 종전 방식이라도 시도
            self._apply_align(value)
            return
        hr = comps[-1]
        # HR 컴포넌트 클릭도 객체선택이라 캐럿을 뺏는다(스티커 정렬과 동일) — 되돌려 놓는다.
        had_caret = self._mark_caret()
        try:
            self._align_divider_passes(hr, value)
        finally:
            if had_caret:
                self._restore_caret()
                self._clear_caret_mark()

    def _align_divider_passes(self, hr, value: str) -> None:
        """구분선 컴포넌트를 선택해 정렬을 적용하고, 실제 클래스로 검증하며 재시도한다."""
        page = self._page
        for _ in range(3):
            try:
                hr.scroll_into_view_if_needed()
                hr.click()  # HR 컴포넌트 선택(객체 선택)
            except Exception:  # noqa: BLE001
                page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            # 컴포넌트(구분선) 정렬은 data-name="align" 버튼을 쓴다 — 텍스트 문단용
            # align-drop-down-with-justify(=_apply_align)는 구분선엔 옵션이 안 떠 무음 실패한다.
            page.evaluate(
                "()=>{const b=document.querySelector('li.se-toolbar-item-align button');if(b)b.click();}"
            )
            page.wait_for_timeout(300)
            page.evaluate(
                "(v)=>{const o=document.querySelector("
                "'button[data-name=\"align\"][data-value=\"'+v+'\"]');if(o)o.click();}",
                value,
            )
            page.wait_for_timeout(250)
            sec = hr.query_selector(".se-section-horizontalLine")
            if sec and f"se-section-align-{value}" in (sec.get_attribute("class") or ""):
                return

    def _insert_quote(
        self, text: str, variant: int = 1, align: str | None = None, at_end: bool = True
    ):
        """인용구 삽입 후 본문 텍스트 입력. 구분선과 같은 이유로 드롭다운 경로로 통일.

        text의 \\n은 인용구 안에서 줄바꿈(Enter)으로 넣어 한마디를 여러 줄로 보여준다.
        at_end=False(in-place)면 본문 끝으로 점프하지 않는다 — 다음 블록이 앵커를 다시 잡으므로
        커서 위치를 옮길 필요가 없고, 점프하면 in-place 삽입 위치가 어긋난다."""
        self._pick_insert_variant("quotation", max(variant, 1))
        self._page.wait_for_timeout(500)
        for i, line in enumerate(text.split("\n")):
            if i:
                self._page.keyboard.press("Enter")
            self._page.keyboard.type(line, delay=4)
        self._page.wait_for_timeout(200)
        if align and align != "left":
            self._apply_align(align)  # 내용 입력 후(커서가 인용구 안에 있을 때) 정렬 적용
        if not at_end:
            return
        # 인용 블록 탈출: '본문 추가'로 블록 뒤에 새 문단을 만들고 거기로 포커스.
        # _focus_body_end()가 클릭 뒤 캐럿이 실제로 본문에 들어갔는지 확인까지 하므로
        # (고정 대기만으로는 다음 블록 타이핑 앞부분이 소리 없이 사라지는 게 실측됨) 그걸 쓴다.
        self._focus_body_end()

    def _pick_insert_variant(self, name: str, n: int):
        """삽입 종류 드롭다운 열고 N번째 옵션 클릭(구분선/인용구 종류 선택)."""
        page = self._page
        item = (
            "li.se-toolbar-item-insert-horizontal-line"
            if name == "horizontal-line"
            else "li.se-toolbar-item-insert-quotation"
        )
        page.evaluate(
            "(sel)=>{const b=document.querySelector(sel+' button.se-document-toolbar-select-option-button');if(b)b.click();}",
            item,
        )
        page.wait_for_timeout(500)
        page.evaluate(
            """(args)=>{const {name,n}=args;
              const opts=[...document.querySelectorAll('button[data-name='+JSON.stringify(name)+'][data-role=\\"option\\"]')].filter(e=>e.offsetParent);
              if(opts[n-1]) opts[n-1].click();}""",
            {"name": name, "n": n},
        )
        page.wait_for_timeout(500)

    # --- 스티커 ---
    def _open_sticker_panel(self):
        """스티커 사이드바 패널을 연다(이미 열려있으면 그대로)."""
        panel = self._page.query_selector(SMART_EDITOR["sticker_panel"])
        if panel and panel.is_visible():
            return
        self._page.click(SMART_EDITOR["sticker_button"])
        self._page.wait_for_selector(SMART_EDITOR["sticker_panel"], timeout=8000)
        self._page.wait_for_timeout(800)

    def _select_sticker_pack(self, pack: str):
        """팩 코드(ogq_xxx/clip_xxx)가 썸네일 URL에 든 탭을 클릭해 그 팩을 활성화."""
        ok = self._page.evaluate(
            """(code)=>{
              const tabs=[...document.querySelectorAll('ul.se-panel-tab-list li.se-tab-item button.se-tab-button')];
              const t=tabs.find(b=>((b.getAttribute('style')||'')+ (b.querySelector('*')?.getAttribute?.('style')||'')).includes(code));
              if(t){t.click();return true;} return false;
            }""",
            pack,
        )
        self._page.wait_for_timeout(700)
        return ok

    def _align_stickers_center(self):
        """본문의 스티커 컴포넌트 중 가운데 정렬이 아닌 것을 전부 가운데로 맞춘다(멱등).

        스티커는 구분선처럼 텍스트 '문단'이 아닌 컴포넌트라 커서 정렬(_apply_align)도
        문단 힐링(_heal_alignment)도 안 닿아, 삽입 기본값(왼쪽)이 그대로 남았다.
        '방금 넣은 것'(comps[-1])만 고치면 in-place 역순 삽입에서 이미 넣은 아래쪽
        스티커를 잡는 오지정이 나서, '안 맞은 것 전부'를 고치는 패스로 돈다 — 덕분에
        이전 실행이 남긴 왼쪽 정렬 스티커도 다음 발행 때 같이 복구된다."""
        page = self._page
        # 컴포넌트 클릭(객체선택)은 캐럿을 본문 밖으로 뺏는다 — 객체가 선택된 채로 다음 블록을
        # 타이핑하면 글자가 사라지거나 그 컴포넌트를 덮어쓴다. 정렬 전 캐럿을 찍어 두고 끝에서
        # 되돌려, 이어지는 삽입이 원래 자리에서 계속되게 한다.
        had_caret = self._mark_caret()
        try:
            for _ in range(6):  # 스티커 수+재시도 상한 — 정렬 클래스가 안 붙는 이례 케이스에 무한루프 방지
                todo = None
                for c in page.query_selector_all(".se-component.se-sticker"):
                    sec = c.query_selector("[class*='se-section-']")
                    if sec and "se-section-align-center" not in (sec.get_attribute("class") or ""):
                        todo = c
                        break
                if todo is None:
                    return
                try:
                    todo.scroll_into_view_if_needed()
                    todo.click()  # 컴포넌트 선택(객체 선택) — 구분선 정렬과 동일 메커니즘
                except Exception:  # noqa: BLE001
                    page.keyboard.press("Escape")
                page.wait_for_timeout(200)
                page.evaluate(
                    "()=>{const b=document.querySelector('li.se-toolbar-item-align button');if(b)b.click();}"
                )
                page.wait_for_timeout(300)
                page.evaluate(
                    "()=>{const o=document.querySelector("
                    "'button[data-name=\"align\"][data-value=\"center\"]');if(o)o.click();}"
                )
                page.wait_for_timeout(250)
        finally:
            # 어느 경로로 끝나든(조기 return 포함) 캐럿을 원래 문단으로 되돌린다.
            if had_caret:
                self._restore_caret()
                self._clear_caret_mark()

    def _insert_sticker(self, pack: str, index: int, at_end: bool = True):
        """(팩, 인덱스) 스티커를 본문 커서 위치에 삽입(검증된 메커니즘).

        패널 열기 → 팩 탭 선택 → 활성 목록에서 data-index 클릭 → 본문 끝으로 포커스 복귀.
        at_end=False(in-place)면 본문 끝으로 점프하지 않는다 — 다음 블록이 앵커(사진 뒤)를
        다시 잡으므로 포커스 복귀가 불필요하고, 점프하면 in-place 삽입 위치가 어긋난다.
        """
        self._open_sticker_panel()
        self._select_sticker_pack(pack)
        sel = f"{SMART_EDITOR['sticker_active_list']} {SMART_EDITOR['sticker_element']}[data-index='{index}']"
        try:
            self._page.click(sel, timeout=4000)
        except Exception:
            return  # 해당 스티커가 없으면(팩 변경 등) 조용히 건너뜀
        self._page.wait_for_timeout(700)
        self._align_stickers_center()
        if not at_end:
            return
        # 다음 본문 입력을 위해 본문 끝으로 포커스 복귀
        try:
            self._page.click(SMART_EDITOR["canvas_bottom_button"])
            self._page.wait_for_timeout(200)
        except Exception:
            pass

    def pull_stickers(self, out_dir: Path | None = None) -> list:
        """현재 계정의 스티커를 전부 훑어 개별 고해상도 PNG로 저장하고 Sticker 목록 반환(라이브).

        에디터에서 보유 팩(코드·인덱스·애니여부)만 열거하고, 이미지는 **CDN 개별 원본**을
        직접 받는다(에디터 스프라이트는 ~80px로 깨짐). CDN 실패 팩(clip/moti 등 다른 스킴)은
        그 자리에서 element 스크린샷으로 폴백. 팩 코드는 스티커 span URL에서 추출.
        """
        from autoblog.publish.stickers import (
            STICKER_DATA_DIR,
            Sticker,
            crop_sprite,
            download_sprite,
            download_sticker_image,
        )

        out_dir = out_dir or STICKER_DATA_DIR
        page = self._page
        self.open_write_page()
        page.click(SMART_EDITOR["content_component"])
        self._open_sticker_panel()
        tabs = page.query_selector_all(SMART_EDITOR["sticker_tab_button"])
        results: list = []
        for tab in tabs:
            if "history" in (tab.get_attribute("class") or ""):
                continue  # 최근사용 탭은 건너뜀(중복)
            try:
                tab.click()
                page.wait_for_timeout(700)
            except Exception:
                continue
            meta = page.evaluate(
                """() => {
                  const ul=document.querySelector('ul.se-sidebar-list.se-is-on');
                  if(!ul) return {pack:null, items:[]};
                  const btns=[...ul.querySelectorAll('button.se-sidebar-element-sticker')];
                  const span=btns[0]?.querySelector('.se-sidebar-sticker');
                  const bg=span?getComputedStyle(span).backgroundImage:'';
                  const m=bg.match(/pstatic\\.net\\/([^/]+)\\//);
                  // cols = 서로 다른 background-position-x 개수(스프라이트 격자 열 수)
                  const xs=new Set(btns.map(b=>{const s=b.querySelector('.se-sidebar-sticker');
                    return s?getComputedStyle(s).backgroundPositionX:'';}));
                  return {pack: m?m[1]:null, cols: xs.size||3,
                          items: btns.map(b=>({idx:+b.getAttribute('data-index'),
                                               animated:b.getAttribute('data-animated')==='true'}))};
                }"""
            )
            pack = meta.get("pack")
            if not pack:
                continue
            pack_dir = out_dir / pack
            btns = page.query_selector_all(
                f"{SMART_EDITOR['sticker_active_list']} {SMART_EDITOR['sticker_element']}"
            )
            btn_by_idx = {it["idx"]: b for b, it in zip(btns, meta["items"])}
            cols = meta.get("cols") or 3
            count = len(meta["items"])
            sprite: bytes | None | bool = False  # False=미시도, None=없음, bytes=받음
            for item in meta["items"]:
                idx = item["idx"]
                img_path = pack_dir / f"{idx}.png"
                # 1순위: CDN 개별 고해상도(ogq/clip/일부 cafe). 실패 시 스프라이트 크롭, 그래도 안 되면 스크린샷.
                if download_sticker_image(pack, idx, img_path):
                    pass
                else:
                    if sprite is False:  # 이 팩에서 처음 폴백 — 스프라이트 1회 받기
                        sprite = download_sprite(pack)
                    if sprite:
                        pack_dir.mkdir(parents=True, exist_ok=True)
                        img_path.write_bytes(crop_sprite(sprite, cols, count, idx))
                    else:  # 최후: 에디터 버튼 스크린샷(저화질)
                        b = btn_by_idx.get(idx)
                        if b is None:
                            continue
                        try:
                            b.evaluate("e => e.scrollIntoView({block: 'center'})")
                            page.wait_for_timeout(60)
                            box = b.bounding_box()
                            if not box or box["width"] < 1:
                                continue
                            pack_dir.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(img_path), animations="disabled", clip=box)
                        except Exception:
                            continue
                rel = (
                    str(img_path.relative_to(USER_DATA_DIR))
                    if img_path.is_relative_to(USER_DATA_DIR)
                    else str(img_path)
                )
                results.append(Sticker(pack=pack, index=idx, animated=item["animated"], image=rel))
        return results

    def _insert_image(self, path: str, size: str | None = None) -> str | None:
        """이미지 툴바 버튼 → 파일 다이얼로그로 업로드.

        size="small"이면(협찬 고지 사진 등) 업로드 후 그 사진을 선택해 에디터 네이티브
        크기 컨트롤로 가장 작은 크기 + 가운데 정렬로 바꾼다(원본 파일은 그대로).
        크기·정렬 변경에 실패하면 사람이 읽을 경고 메시지를 반환한다(성공/해당없음=None).
        """
        page = self._page
        # in-place는 본문 '중간'에 끼워 넣으므로 imgs[-1]이 방금 사진이 아니다 —
        # 업로드 전 src 목록과 대조해 '새로 생긴' 사진의 인덱스를 찾아 크기·정렬을 건다.
        before_srcs = page.evaluate(
            "(sel)=>[...document.querySelectorAll(sel)].map(i=>i.src)",
            SMART_EDITOR["editor_image"],
        )
        before = len(before_srcs)
        with page.expect_file_chooser() as fc_info:
            page.click(SMART_EDITOR["image_upload_button"])
        fc_info.value.set_files(path)
        # 업로드 완료 폴링 — 고정 대기(2.5초)는 글의 첫 이미지(세션 워밍업)나 큰 파일에서
        # 모자라, 협찬 사진 '작게' 변경이 사진을 못 찾고 조용히 스킵되는 원인이었다.
        uploaded = False
        for _ in range(30):  # 최대 15초
            page.wait_for_timeout(500)
            if len(page.query_selector_all(SMART_EDITOR["editor_image"])) > before:
                uploaded = True
                break
        page.wait_for_timeout(800)  # 컴포넌트 출현 직후 에디터 내부 처리 여유
        if not uploaded:
            # 무음 실패 방지 — 여기서 안 알리면 사진이 조용히 빠지고, 대표 지정·AI 표시의
            # k번째 매핑도 밀려 엉뚱한 사진에 배지가 붙는다(실패 경로는 매핑에서 제외).
            self._failed_images.add(path)
            return (
                f"사진 자동 삽입이 확인되지 않았어요: ‘{Path(path).name}’ — 파일 형식(webp 등)이나 "
                "용량 문제일 수 있어요. 발행 전에 본문 사진과 대표사진을 확인해 주세요."
            )
        if size == "small":
            new_idx = page.evaluate(
                "(a)=>{const c={};a.before.forEach(s=>c[s]=(c[s]||0)+1);"
                "const im=[...document.querySelectorAll(a.sel)].map(i=>i.src);"
                "for(let k=im.length-1;k>=0;k--){if(c[im[k]]>0)c[im[k]]--;else return k;}"
                "return im.length-1;}",
                {"before": before_srcs, "sel": SMART_EDITOR["editor_image"]},
            )
            if not self._resize_image_smallest(new_idx):
                return (
                    "협찬 사진 크기·정렬 자동 변경 실패 — 에디터에서 사진을 선택해 "
                    "‘작게’·가운데 정렬로 직접 바꿔 주세요."
                )
        return None

    def _insert_video(self, path: str, title: str = "") -> bool:
        """동영상 업로더 모달로 영상 삽입(사진과 흐름이 다름).

        '동영상' 툴바 버튼 → 업로더 모달(.nvu_wrap)에서 로컬 파일 버튼으로 파일창을 열어
        업로드 → 서버 인코딩(수~수십 초) → 제목(필수) 입력 → '완료'로 본문에 영상 컴포넌트
        삽입. 인코딩이 길어 사진의 고정 대기로는 부족하므로 단계마다 넉넉히 폴링한다.
        실패(타임아웃 등)하면 모달을 닫고 False를 반환(본문은 그대로, 호출부가 경고로 안내).
        """
        page = self._page
        before = len(page.query_selector_all(SMART_EDITOR["editor_video"]))
        try:
            page.click(SMART_EDITOR["video_upload_button"])
            page.wait_for_selector(SMART_EDITOR["video_uploader_modal"], timeout=8000)
            page.wait_for_timeout(800)
            with page.expect_file_chooser(timeout=8000) as fc:
                page.click(SMART_EDITOR["video_local_button"])
            fc.value.set_files(path)
        except Exception:
            self._close_video_modal()
            return False

        # 업로드 완료 대기('업로드 완료' 텍스트 출현, 최대 120초)
        uploaded = False
        for _ in range(40):
            page.wait_for_timeout(3000)
            txt = page.evaluate(
                "() => { const r = document.querySelector('.nvu_wrap');"
                " return r ? r.textContent : ''; }"
            )
            if "업로드 완료" in (txt or ""):
                uploaded = True
                break
            if not page.query_selector(SMART_EDITOR["video_uploader_modal"]):
                break  # 모달이 사라짐(예외적) — 아래 컴포넌트 출현으로 판정
        if not uploaded and page.query_selector(SMART_EDITOR["video_uploader_modal"]):
            self._close_video_modal()
            return False

        # 제목(필수) 입력 후 '완료'
        try:
            ttl = (title or "동영상").strip()[:40]
            page.fill(SMART_EDITOR["video_title_input"], ttl)
            page.wait_for_timeout(300)
            page.click(SMART_EDITOR["video_submit_button"])
        except Exception:
            self._close_video_modal()
            return False

        # 본문에 동영상 컴포넌트가 늘어날 때까지 대기(최대 60초)
        for _ in range(20):
            page.wait_for_timeout(3000)
            if len(page.query_selector_all(SMART_EDITOR["editor_video"])) > before:
                self._focus_body_end()
                return True
            if not page.query_selector(SMART_EDITOR["video_uploader_modal"]):
                # 모달은 닫혔는데 컴포넌트 미확인 → 한 번 더 확인
                if len(page.query_selector_all(SMART_EDITOR["editor_video"])) > before:
                    self._focus_body_end()
                    return True
        return False

    def _close_video_modal(self):
        """동영상 업로더 모달이 떠 있으면 닫는다(실패 후 정리)."""
        try:
            if self._page.query_selector(SMART_EDITOR["video_uploader_modal"]):
                self._page.keyboard.press("Escape")
                self._page.wait_for_timeout(400)
        except Exception:
            pass

    def _resize_image_smallest(self, idx: int = -1) -> bool:
        """idx번째(기본 마지막) 본문 사진을 '작게' + 가운데 정렬로 변경. 성공 여부를 반환.

        SE-ONE은 사진을 클릭하면 해당 컴포넌트가 선택(se-is-selected)되고 사진 전용 크기
        툴바가 뜬다. 거기서 '가장 작은' 크기 항목을 누른다. 정확한 셀렉터는 라이브에서
        캡처해 SMART_EDITOR에 채운다(scripts/probe_image_resize.py). 실패해도 본문은 유지.
        '작게'(normal 배치)는 기본이 왼쪽 정렬이라, 이어서 구분선·스티커와 같은 컴포넌트
        정렬 메커니즘(data-name="align")으로 가운데를 적용하고 클래스로 검증한다.
        """
        page = self._page
        size_sel = SMART_EDITOR.get("image_size_smallest")
        if not size_sel:
            return False  # 크기 셀렉터 미설정 — 기본 크기로 두고 넘어감(라이브 캡처 후 채움)
        try:
            imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
            if not imgs:
                return False
            if not (0 <= idx < len(imgs)):
                idx = len(imgs) - 1
            imgs[idx].click()  # 방금 삽입한 사진 선택 → 크기 툴바 노출
            page.wait_for_timeout(300)
            menu_sel = SMART_EDITOR.get("image_size_menu")
            if menu_sel:  # 크기 메뉴를 먼저 펼쳐야 하는 경우
                page.click(menu_sel)
                page.wait_for_timeout(200)
            page.click(size_sel, timeout=8000)
            page.wait_for_timeout(300)
            ok = self._center_image(idx)
            # '작게' 버튼 클릭 뒤엔 포커스가 그 툴바 버튼에 남는다. 이 상태로 다음 블록을
            # 타이핑하면 글자가 본문이 아닌 허공으로 들어가 그 블록이 통째로 사라진다.
            # 사진 선택을 풀고 본문 끝에 새 문단을 만들어 커서를 본문으로 되돌린다.
            self._focus_body_end()
            return ok
        except Exception:
            page.keyboard.press("Escape")  # 크기 변경 실패해도 사진은 남김
            self._focus_body_end()
            return False

    def _center_image(self, idx: int = -1) -> bool:
        """idx번째(기본 마지막) 사진 컴포넌트를 가운데 정렬하고 클래스로 검증.

        사진도 구분선·스티커처럼 텍스트 '문단'이 아닌 컴포넌트라 커서 정렬(_apply_align)이
        안 닿는다 — 컴포넌트를 선택해 data-name="align" 옵션을 누르고, 내부 .se-section의
        se-section-align-center 클래스로 실제 적용을 확인한다(_align_divider와 동일)."""
        page = self._page
        imgs = page.query_selector_all(SMART_EDITOR["editor_image"])
        if not imgs:
            return False
        if not (0 <= idx < len(imgs)):
            idx = len(imgs) - 1
        comp = imgs[idx].evaluate_handle("el=>el.closest('.se-component')").as_element()
        if comp is None:
            return False
        for _ in range(3):
            sec = comp.query_selector("[class*='se-section-']")
            if sec and "se-section-align-center" in (sec.get_attribute("class") or ""):
                return True
            try:
                comp.scroll_into_view_if_needed()
                comp.click()  # 컴포넌트 선택(객체 선택)
            except Exception:  # noqa: BLE001
                page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            page.evaluate(
                "()=>{const b=document.querySelector('li.se-toolbar-item-align button');if(b)b.click();}"
            )
            page.wait_for_timeout(300)
            page.evaluate(
                "()=>{const o=document.querySelector("
                "'button[data-name=\"align\"][data-value=\"center\"]');if(o)o.click();}"
            )
            page.wait_for_timeout(250)
        sec = comp.query_selector("[class*='se-section-']")
        return bool(sec and "se-section-align-center" in (sec.get_attribute("class") or ""))

    def _focus_body_end(self):
        """사진/객체 선택을 풀고 본문 끝에 빈 문단을 만들어 커서를 본문으로 되돌린다.

        객체(이미지) 선택 상태에서 곧바로 타이핑하면 글자가 본문에 안 들어가고 사라진다.
        '본문 추가' 버튼으로 끝에 새 문단을 만들고 거기에 포커스를 둔다(인용구 탈출과 동일).

        버튼 클릭 뒤 고정 대기(250ms)만 믿고 바로 타이핑을 시작하면, 포커스 전환이 그
        시점까지 실제로 안 끝났을 때 다음 keyboard.type()의 앞부분 글자가 아직 전환
        중인 요소로 들어가 조용히 사라진다(실측: 인용구 뒤 문단에서 "인용구 삽입 후
        테스트 문단입니다"처럼 앞 절반이 통째로 빠지고 뒷부분만 남음) — 고정 대기 대신
        캐럿이 실제로 '마지막' 본문 컴포넌트에 들어갔는지 확인하며 재시도한다 — 단순히
        '본문 어딘가'(구 _caret_in_body 기준)에 있는지만 보면, 캐럿이 이전(앞쪽) 문단에
        남은 채로도 통과해 버려 다음 타이핑이 그 앞쪽 문단 한가운데로 꽂히는 걸 못 잡는다."""
        page = self._page
        page.keyboard.press("Escape")  # 객체 선택 해제
        page.wait_for_timeout(150)
        try:
            self._click_safe(SMART_EDITOR["canvas_bottom_button"])
        except Exception:
            self._click_safe(SMART_EDITOR["content_component"])  # 폴백: 본문 컴포넌트 클릭
        settled = False
        for _ in range(10):
            if page.evaluate(_CARET_IN_LAST_TEXT_JS):
                settled = True
                break
            page.wait_for_timeout(100)
        if not settled:
            # 안전망: UI 클릭으로 안 되면 JS로 마지막 컴포넌트 끝에 캐럿을 강제로 둔다.
            page.evaluate(_FORCE_CARET_TO_LAST_TEXT_END_JS)
        # 셀렉션이 '마지막' 컴포넌트에 들어간 뒤에도, 에디터 내부 모델이 그 DOM 변화를
        # 다 반영하기까지 추가로 시간이 걸릴 수 있다(표/장소/인용구처럼 합성 이벤트로
        # 삽입한 직후 특히 그렇다) — 셀렉션만 보고 바로 타이핑하면 그 사이의 내부
        # 재조정과 keyboard.type()이 겹쳐 글자가 엉뚱한 자리로 꽂힌다(실측: 표/장소/
        # 인용구 뒤 문단 손상이 셀렉션 확인만으로는 안 잡혔음). 추가 여유를 둔다.
        page.wait_for_timeout(600)

    def _submit(self):
        self._clear_caret_mark()  # 내부 표식이 발행 본문에 남지 않게(save_draft와 동일 안전망)
        self._page.click(SMART_EDITOR["publish_button"])
        self._page.wait_for_timeout(1500)
        try:
            self._page.click(SMART_EDITOR["publish_confirm"], timeout=5000)
        except Exception:
            pass  # 발행 레이어 확인 버튼은 라이브에서 확정

    # --- 예약 발행(발행시점) ---
    # ⚠️ 시간 피커 셀렉터가 라이브 미검증이라, 이 경로는 fail-closed로만 동작한다:
    # '예약' 모드가 확실히 켜진 걸 확인하지 못하면 발행을 아예 하지 않는다(즉시 발행 방지).
    def _reserve_is_selected(self) -> bool:
        """'예약' 라디오가 실제로 checked인지 읽어 확인한다(fail-closed 가드용)."""
        return bool(self._page.evaluate(
            "(sel) => { const r = document.querySelector(sel); return !!(r && r.checked); }",
            SMART_EDITOR["reserve_radio"],
        ))

    def set_reserve_time(self, when) -> bool:
        """발행 레이어에서 '예약' 발행시점을 켜고 날짜/시간을 when(datetime)으로 설정.

        예약 라디오가 checked이고, 시/분 select가 원하는 값으로 '읽혀야' True를 돌려준다
        (시각이 안 맞으면 False → 호출부가 발행을 중단 = fail-closed). 레이어는 이미
        열려 있다고 가정(호출부에서 _open_publish_layer)."""
        # 1) '예약' 라디오 켜기(라디오 직접 → 라벨 폴백).
        radio = SMART_EDITOR["reserve_radio"]
        clicked = False
        for how in ("check", "click"):
            try:
                getattr(self._page, how)(radio, timeout=3000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            try:
                self._page.click('label:has-text("예약")', timeout=2000)
            except Exception:
                return False
        self._page.wait_for_timeout(500)
        if not self._reserve_is_selected():
            return False
        # 2) 날짜 — 오늘과 다를 때만 설정(형식 "YYYY. MM. DD"). 같으면 건드리지 않는다.
        date_sel = SMART_EDITOR["reserve_date_input"]
        want_date = when.strftime("%Y. %m. %d")
        try:
            cur_date = (self._page.input_value(date_sel) or "").strip()
        except Exception:
            cur_date = ""
        if cur_date != want_date:
            try:
                self._page.fill(date_sel, want_date)
                self._page.wait_for_timeout(300)
            except Exception:
                pass  # 실패해도 아래 시각 read-back이 최종 판정
        # 3) 시/분 select — 옵션값은 "00"~"23" / 10분 단위 "00"~"50".
        hour_sel = SMART_EDITOR["reserve_hour_select"]
        min_sel = SMART_EDITOR["reserve_minute_select"]
        want_hour = when.strftime("%H")
        want_min = f"{(when.minute // 10) * 10:02d}"
        try:
            self._page.select_option(hour_sel, want_hour)
            self._page.select_option(min_sel, want_min)
            self._page.wait_for_timeout(200)
        except Exception:
            return False
        # 4) read-back — 시/분이 원하는 값으로 실제 반영됐는지 확인(안 맞으면 발행 중단).
        try:
            got_hour = (self._page.input_value(hour_sel) or "").zfill(2)
            got_min = (self._page.input_value(min_sel) or "").zfill(2)
        except Exception:
            return False
        return got_hour == want_hour and got_min == want_min and self._reserve_is_selected()

    def _submit_reserved(
        self, when, category: str | None,
        tags: list[str] | None = None, warnings: list[str] | None = None,
    ):
        """예약 발행 — 예약 모드 확인(fail-closed) 후에만 발행 버튼을 누른다.

        예약 확인에 실패하면 발행하지 않고 예외를 던진다 — 시각 설정 실패가 즉시 발행으로
        이어지는 사고를 막는다(사용자는 에디터에서 직접 예약하면 됨)."""
        # 라이브 미검증 가드: 날짜/시간 셀렉터가 확정되지 않았으면 아예 발행하지 않는다.
        # (예약 모드만 켜지고 시각이 안 잡힌 채 발행되는 사고를 원천 차단 — fail-closed)
        if not reserve_ready():
            raise RuntimeError(
                "예약 발행이 아직 준비되지 않았어요 — 임시저장만 완료했어요. "
                "예약 시간 피커 셀렉터를 확정(scripts/probe_reserve_ui.py)하기 전까지는 "
                "네이버 에디터에서 직접 예약해 주세요."
            )
        self._open_publish_layer()
        if category:
            self.select_category(category)
        self._fill_tags(tags, warnings)
        if not self.set_reserve_time(when) or not self._reserve_is_selected():
            self._page.keyboard.press("Escape")
            raise RuntimeError(
                "예약 설정을 확인하지 못해 발행을 중단했어요(즉시 발행 방지). "
                "네이버 에디터에서 직접 예약 발행해 주세요 — 임시저장은 완료됐어요."
            )
        self._page.click(SMART_EDITOR["publish_confirm"], timeout=5000)
        self._page.wait_for_timeout(1500)

    def close(self, save_session: bool = True):
        if self._ctx:
            if save_session and self.is_logged_in():
                try:
                    self.save_state()  # 세션 영속화(다음 실행 자동 로그인)
                except Exception:
                    pass
            self._ctx.close()
        if getattr(self, "_browser", None):
            self._browser.close()
        if getattr(self, "_pw", None):
            self._pw.stop()


# 핵심 셀렉터가 채워졌는지 점검(개발 보조). editor_iframe은 top frame이라 비워둠.
def selectors_ready() -> bool:
    required = ("title_component", "content_component", "save_button", "publish_button")
    return all(SMART_EDITOR.get(k) for k in required)


def reserve_ready() -> bool:
    """예약 발행 셀렉터(날짜/시·분)가 라이브 검증돼 채워졌는지. 미채움이면 예약 경로는
    fail-closed(발행 안 함) — scripts/probe_reserve_ui.py 로 확정 후 selectors.py에 채운다."""
    return all(SMART_EDITOR.get(k) for k in
               ("reserve_date_input", "reserve_hour_select", "reserve_minute_select"))
