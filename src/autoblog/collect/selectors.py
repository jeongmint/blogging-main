"""스크래핑 셀렉터 집결지 (기획서 §3.1).

네이버 구조 변경 시 '여기 한 곳'만 수정하면 되도록 모든 CSS/XPath 셀렉터를 모은다.
값은 실제 페이지 구조 확인 후 채운다 — 현재는 자리표시자.
"""

from __future__ import annotations

# 네이버 플레이스 (m.place.naver.com)
# 주의: 상세 데이터(메뉴/가격/평점/좌표)는 CSS 셀렉터로 긁지 않고
# 페이지에 SSR된 window.__APOLLO_STATE__ JSON을 파싱한다(place_detail.py).
# 클래스명 변경에 덜 깨지므로 이쪽이 기본. CSS 셀렉터는 필요 시에만 추가.
PLACE: dict[str, str] = {}

# 상품 페이지 (쿠팡·스마트스토어 등) — 텍스트형/이미지형 판별에 사용
PRODUCT = {
    "title": "",
    "price": "",
    "detail_container": "",  # 상세설명 영역
    "detail_images": "",  # 이미지형일 때 다운로드 대상 <img>
}

# 네이버 Smart Editor ONE (게시 단계, §6).
# 확인 결과: 에디터는 별도 iframe이 아니라 글쓰기 페이지(top frame)에 직접 렌더된다.
# se-* 클래스는 안정적, 발행 버튼은 data-click-area 속성으로 잡는다(해시 클래스 회피).
SMART_EDITOR = {
    "editor_iframe": "",  # 없음(top frame). 비워두면 page에서 바로 조작.
    "title_area": ".se-documentTitle .se-text-paragraph",  # 제목 입력 영역
    "title_component": ".se-component.se-documentTitle",
    "content_area": ".se-component.se-text .se-text-paragraph",  # 본문 입력 영역
    "content_component": ".se-component.se-text",
    "image_upload_button": ".se-toolbar-item-image button",  # 사진 추가 버튼
    "image_file_input": "input[type=file]",  # 파일 input
    # 사진 크기 — 삽입한 이미지를 선택하면 뜨는 컨텍스트 툴바의 '배치/크기' 토글(라이브 캡처).
    # 세 모드: 작게(normal) / 문서 너비(fit, 기본) / 옆트임(extend). '가장 작게'=작게(normal).
    # 버튼이 선택 즉시 바로 보이므로 메뉴를 펼칠 필요 없음(image_size_menu 비움).
    "image_size_menu": "",
    "image_size_smallest": "button.se-object-arrangement-normal-toolbar-button",  # '작게'(data-value=normal)
    # 동영상: 사진과 달리 '동영상' 툴바 버튼 → 업로더 모달(.nvu_wrap)이 뜬다. 모달에서
    # 로컬 파일 버튼으로 파일창을 열어 업로드 → 서버 인코딩 → 제목(필수) 입력 → '완료'로
    # 본문에 .se-component.se-video 삽입. (셀렉터는 scripts/probe_video_upload.py 로 라이브 캡처)
    "video_upload_button": ".se-toolbar-item-video button",  # '동영상 추가' 툴바 버튼
    "video_uploader_modal": ".se-popup-video-upload",  # 업로더 팝업(.nvu_wrap 포함)
    "video_local_button": ".nvu_btn_append.nvu_local",  # 모달 내 '동영상 추가'(로컬 파일) → 파일창
    "video_title_input": "input.nvu_inp",  # 제목 입력(필수, 최대 40자)
    "video_submit_button": ".nvu_btn_submit",  # '완료'(등록 → 본문 삽입)
    "editor_video": ".se-component.se-video",  # 본문에 삽입된 동영상 컴포넌트
    "divider_button": "button.se-insert-horizontal-line-default-toolbar-button",  # 구분선
    "quote_button": "button.se-insert-quotation-default-toolbar-button",  # 인용구
    # 스티커: 툴바 버튼 → 우측 사이드바 패널(팩 탭 + 스티커 그리드). (팩코드,인덱스)로 삽입.
    "sticker_button": "li.se-toolbar-item-sticker button",
    "sticker_panel": ".se-sidebar-container-sticker",
    "sticker_tab_button": "ul.se-panel-tab-list li.se-tab-item button.se-tab-button",
    "sticker_active_list": "ul.se-sidebar-list.se-is-on",  # 선택된 팩의 스티커 목록
    "sticker_element": "button.se-sidebar-element-sticker",  # [data-index=N]
    "canvas_bottom_button": "button.se-canvas-bottom-button",  # 본문 끝에 새 문단(블록 탈출용)
    "save_button": 'button[data-click-area="tpb.save"]',  # 임시저장
    # 임시저장 글 불러오기(사진 추출용)
    "save_count_button": 'button[data-click-area="tpb*s.count"]',  # '저장글 N' → 목록 팝업 열기
    "draft_list": 'ul[aria-label="임시저장된 글"]',  # 임시저장 목록 컨테이너(li 항목들)
    "draft_item_button": 'button[data-click-area="tpb*s.tlist"]',  # 목록 항목(클릭 시 에디터에 로드)
    # 항목별 '삭제' 버튼(라이브 캡처: data-click-area=tpb*s.del, title='삭제'). 삭제는 복구 불가.
    "draft_item_delete": 'ul[aria-label="임시저장된 글"] button[data-click-area="tpb*s.del"]',
    "draft_load_confirm": "button.se-popup-button-confirm",  # 불러오기 시 뜨는 확인 팝업
    "draft_delete_confirm": "button.se-popup-button-confirm",  # 삭제 확인 팝업(확인)
    "editor_image": "img.se-image-resource",  # 본문 사진(지도 se-map-image는 제외됨)
    # AI 활용 표시(네이버 자율 표기, 2025~): 이미지에 마우스를 올리면 뜨는 'AI 활용 설정' 배지의
    # 토글 버튼(대표 배지와 같은 hover 방식). 클릭하면 se-is-selected가 붙고 발행 시 이미지
    # 우하단에 'AI 활용' 아이콘이 붙는다. (라이브 검증 2026-07-23, scripts/probe_ai_label.py)
    # 비워두면 _mark_ai_images가 no-op(발행은 그대로).
    "image_ai_label": "button.se-set-ai-mark-button-toggle",
    "publish_button": 'button[data-click-area="tpb.publish"]',  # 발행(설정 레이어 열기)
    "publish_confirm": 'button[data-click-area="tpb*i.publish"]',  # 레이어 내 최종 발행
    "category_button": 'button[data-click-area="tpb*i.category"]',  # 카테고리 선택 열기
    # 발행 레이어의 태그 입력칸(라이브 캡처 2026-07-29, scripts/probe_tag_input.py).
    # input#tag-input, placeholder "태그 입력 (최대 30개)", 입력+Enter로 칩(#태그) 확정.
    # 해시 클래스(tag_input__XXX)는 배포 때 바뀌므로 data-click-area·id로 잡는다.
    # 못 찾으면 태그 입력만 건너뛰고 경고한다(_fill_tags fail-open, 저장·발행은 진행).
    "tag_input": 'input[data-click-area="tpb*i.tag"], input#tag-input, input[placeholder*="태그"]',
    # 예약 발행(발행시점) — 라이브 캡처(2026-07-22, scripts/probe_reserve_ui.py).
    # 해시 클래스(input_date__XXX)는 배포 때 바뀔 수 있어 [class*=] 부분일치로 잡는다.
    # 예약 경로는 fail-closed: '예약' 라디오가 checked로 확인 안 되면 발행하지 않는다.
    "reserve_radio": '[data-click-area="tpb*i.schedule"]',  # '예약' 라디오(name=radio_time,value=pre)
    "reserve_now_radio": '[data-click-area="tpb*i.now"]',  # '현재' 라디오(폴백 식별용)
    "reserve_date_input": "input[class*=input_date]",  # 날짜(type=text, 형식 "2026. 07. 22")
    "reserve_hour_select": "select[class*=hour_option]",  # 시 select(옵션값 "00"~"23")
    "reserve_minute_select": "select[class*=minute_option]",  # 분 select(10분 단위 "00"~"50")
    # 서식 툴바 (글자색은 font-color 클래스)
    "toolbar_text_color": "button.se-font-color-toolbar-button",
    "toolbar_bg_color": "button.se-background-color-toolbar-button",
    # 색상 '더보기' 커스텀 hex 입력(네이티브, 저장 유지) — 정확한 커스텀 색의 핵심
    "color_more_button": "div.se-color-picker-more-button",
    "color_hex_input": "input.se-selected-color-hex",
    "color_apply_button": "button.se-color-picker-apply-button",
    # 글쓰기 진입 시 뜨는 팝업/오버레이 닫기
    "draft_popup_cancel": ".se-popup-button-cancel",  # '이전 글 이어쓰기' 팝업 취소
    "help_close": "button.se-help-panel-close-button",  # 도움말 패널 닫기
}

# 네이버 로그인
NAVER_LOGIN = {
    "url": "https://nid.naver.com/nidlogin.login",
    "write_url": "https://blog.naver.com/{blog_id}/postwrite",
    "id_input": "#id",
    "pw_input": "#pw",
    "login_button": ".btn_login",
}
