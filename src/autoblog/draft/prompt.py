"""프롬프트 계층 조립 (기획서 §4.1).

[맨 위] 가이드라인(있을 때만, 최우선) → 베이스 프롬프트 → 공통 규칙 → 문체 지시
재료: 경험 메모(주연) + 사실 카드(조연).
"""

from __future__ import annotations

from autoblog.collect.fact_card import FactCard
from autoblog.draft.guideline import Guidelines
from autoblog.draft.rules import CommonRules
from autoblog.draft.style import StyleProfile


def render_fact_card(card: FactCard) -> str:
    """사실 카드 → 초안 재료용 한국어 사실 요약(조연)."""
    lines: list[str] = []
    if card.place:
        p = card.place
        lines.append(f"가게명: {p.name}")
        if p.category:
            lines.append(f"분류: {p.category}")
        if p.road_address:
            lines.append(f"주소: {p.road_address}")
        if p.business_hours:
            lines.append(f"영업시간: {p.business_hours}")
        if p.phone:
            lines.append(f"전화: {p.phone}")
        if p.rating:
            lines.append(f"평점: {p.rating}")
        if p.description:
            lines.append(f"소개: {p.description}")
        if p.menus:
            menu_str = ", ".join(
                f"{m.name}({m.price})" if m.price else m.name for m in p.menus[:12]
            )
            lines.append(f"메뉴: {menu_str}")
        if p.directions:
            lines.append(f"찾아가는 길·주차 안내: {p.directions}")
        if p.conveniences:
            lines.append(f"편의시설: {', '.join(p.conveniences)}")
        if p.payment_info:
            lines.append(f"결제수단: {', '.join(p.payment_info)}")
        if p.review_keywords:
            kw = ", ".join(f"{k.name}({k.count})" for k in p.review_keywords[:8])
            lines.append(f"방문자 키워드: {kw}")
        if p.reviews:
            snippet = " / ".join(r.body[:60] for r in p.reviews[:3])
            lines.append(f"방문자 리뷰 일부: {snippet}")
    if card.product:
        pr = card.product
        lines.append(f"상품명: {pr.name}")
        if pr.price:
            lines.append(f"가격: {pr.price}")
        if pr.brand:
            lines.append(f"브랜드: {pr.brand}")
        if pr.category:
            lines.append(f"분류: {pr.category}")
        if pr.selling_points:
            lines.append(f"셀링포인트: {', '.join(pr.selling_points)}")
        if pr.specs:
            spec_str = ", ".join(f"{s.key}: {s.value}" for s in pr.specs)
            lines.append(f"스펙: {spec_str}")
        if pr.detail_text:
            lines.append(f"상세설명: {pr.detail_text}")
    return "\n".join(lines)


def build_system_prompt(
    base_prompt: str,
    style: StyleProfile | None = None,
    guidelines: Guidelines | None = None,
    rules: CommonRules | None = None,
) -> str:
    """계층 순서대로 시스템 프롬프트 조립 (기획서 §4.1).

    [맨 위] 가이드라인(최우선) → 베이스 프롬프트(역할·포맷·문체) →
    추가 규칙(선택) → 추가 문체 지시(선택).
    """
    blocks: list[str] = []

    if guidelines and not guidelines.is_empty():
        blocks.append(guidelines.as_prompt())  # 최우선 제약

    blocks.append(base_prompt)

    if rules:
        fragments = rules.active_fragments()
        if fragments:
            blocks.append("[추가 규칙]\n" + "\n".join(f"- {f}" for f in fragments))

    if style and style.as_prompt():
        blocks.append(
            "[추가 문체 지시] — 아래 지시가 베이스 프롬프트의 문체 규칙(어투·이모티콘·"
            "강조 표현 포함)과 충돌하면 아래가 우선한다.\n" + style.as_prompt()
        )

    return "\n\n".join(blocks)


def build_user_prompt(
    card: FactCard,
    experience_memo: str,
    template_text: str | None = None,
    inplace: bool = False,
) -> str:
    """재료(경험 메모=주연, 사실 카드=조연) → 사용자 프롬프트.

    재료 구분용 머리말은 모델이 본문에 인용하지 않도록 명시한다(라벨 누수 방지).
    inplace=True(불러온 글 편집)면 동영상은 위치를 못 바꾸므로 [영상] 마커를 재료에 나열된
    순서 그대로 넣도록 못박는다(재업로드 불가 → 순서 고정).
    """
    facts = render_fact_card(card)
    parts = [
        "다음은 글을 쓰기 위한 재료입니다. 이 재료의 머리말·항목 이름(예: '나의 경험', "
        "'참고 정보', '방문자 키워드' 등)을 본문에 절대 언급하거나 인용하지 마세요. "
        "재료에 없는 사실은 지어내지 마세요.",
        "# 나의 경험 (이 내용을 글의 중심으로 삼으세요 — 단, 아래 메모 문구를 그대로 "
        "복사해 어미만 덧붙이지 말고, 문체에 맞는 완전한 문장으로 다시 써서 녹이세요. "
        "메모 말투와 글 말투가 그대로 섞이면 문장이 꼬입니다)\n" + experience_memo.strip(),
        "# 참고 정보 (필요한 것만 자연스럽게 녹이세요)\n" + facts,
    ]
    if card.photos:
        from autoblog.collect.photos import photo_summary

        imgs = [p for p in card.photos if p.media_kind != "video"]
        vids = [p for p in card.photos if p.media_kind == "video"]
        # 라벨 순서 = 분류함 칸 순서(유저가 드래그로 정한 순서). 정렬하지 않고 그대로 쓴다.
        labels = list(dict.fromkeys(p.label for p in imgs))
        n = len(imgs)
        if imgs:
            parts.append(
                "# 사진 구성 (분류 결과)\n"
                f"보유 사진: {photo_summary(imgs)} (총 {n}장)\n"
                f"이 {n}장을 한 장도 빠짐없이 모두 본문에 배치하세요. 사진 수만큼 마커를 넣어야 합니다"
                f"(마커가 모자라면 남은 사진이 글 끝에 몰려 들어갑니다).\n"
                "사진은 글 전체에 고루 나눠, 사진↔설명 문단이 번갈아 오도록 배치하세요. "
                "여러 장을 앞부분에 몰아 넣으면 뒤쪽이 글만 남아 밋밋해집니다 — 사진만 3장 넘게 "
                "연달아 붙이지 말고(꼭 함께 봐야 하는 사진이 아니라면), 사이사이에 그 사진을 "
                "설명하는 문단을 두어 처음부터 끝까지 사진과 글이 고르게 섞이게 하세요.\n"
                "글의 양 끝도 비워 두지 마세요 — 인트로 문단 바로 아래에 가장 시선을 끄는 대표 "
                "사진 1장(맛있어 보이는 음식, 분위기 좋은 내부 등)을 배치해 스크롤을 유도하고, "
                "마무리 총평에도 1~2장을 남겨 글자만 빽빽하게 끝나지 않게 하세요.\n"
                "사진 없이 글만 이어지는 문단이 3개 이상 연속되면 안 됩니다. 총평·꿀팁처럼 딱 맞는 "
                "사진이 없는 섹션이라도 텍스트만으로 채우지 말고, 느슨하게라도 어울리는 남은 사진"
                "(매장 분위기·음식 컷 등)을 한 장 배치하세요 — '관련 사진이 없다'는 이유로 특정 "
                "구간에 사진을 몰아 쓰고 다른 구간을 글만으로 두지 마세요.\n"
                "사진을 먼저 보여주고 그 아래에서 설명하는 순서로 쓰세요. "
                "[사진:라벨] 을 한 줄로 먼저 넣고, 그 다음 문단에서 방금 보여준 사진을 설명하세요"
                f"(라벨은 보유 사진의 분류명: {', '.join(labels)}).\n"
                "이 분류명 나열 순서가 내가 원하는 등장 순서입니다 — 글 흐름상 어색하지 않다면 "
                "이 순서대로 사진(과 그 사진을 다루는 섹션)을 배치하세요.\n"
                "예: [사진:음식] 을 넣고 그 아래 문단에서 음식을 묘사, [사진:외관] 을 넣고 그 아래에서 가게 첫인상을 묘사. "
                "라벨을 모르겠으면 그냥 [사진] 으로 두면 됩니다. 같은 라벨 사진이 여러 장이면 그만큼 마커를 반복하세요."
            )
        if vids:
            nv = len(vids)
            vlines = [
                "# 동영상 구성",
                f"보유 동영상 {nv}개(아래 순서대로). 동영상도 빠짐없이 본문에 배치하세요 — 개수만큼 [영상] 마커를 넣습니다.",
            ]
            for i, v in enumerate(vids, 1):  # 문서 순서대로 번호+내용(유저 캡션)
                cap = (v.caption or v.label or "").strip()
                vlines.append(f"  {i}) {cap}" if cap else f"  {i}) (내용 설명 없음)")
            vlines.append(
                "각 동영상이 어울리는 문맥(예: 매장 분위기·조리 과정·제품 시연)에 [영상] 을 한 줄로 먼저 넣고 "
                "그 아래 문단에서 그 영상 내용을 설명하세요."
            )
            if inplace:
                vlines.append(
                    "중요: 이 글은 기존 글을 편집하는 것이라 동영상은 위치를 바꿀 수 없습니다. "
                    "[영상] 마커는 반드시 위에 나열된 순서 그대로(1번 영상 먼저, 그다음 2번…) 한 개씩 넣고, "
                    "순서를 바꾸거나 빠뜨리지 마세요."
                )
            else:
                vlines.append("[영상] 마커가 모자라면 남은 영상이 본문에 자동 분산됩니다.")
            parts.append("\n".join(vlines))
        if "협찬" in labels:
            parts.append(
                "# 협찬 사진 배치 (필수)\n"
                "'협찬' 라벨 사진은 협찬 고지 이미지입니다. 본문 맨 처음(제목·헤더 다음, 인트로보다도 위)에 "
                "[사진:협찬] 을 한 줄 단독으로 가장 먼저 넣어 최상단에 배치하세요. "
                "다른 어떤 사진·문단보다 앞서야 하며, 협찬 사진에는 따로 설명 문단을 붙이지 않아도 됩니다."
            )
        captioned = [p for p in imgs if p.caption]  # 사진만(영상 캡션은 동영상 구성에 별도)
        if captioned:
            parts.append(
                "# 사진 내용 (각 사진이 구체적으로 무엇인지 — 이 설명에 맞는 문맥에 배치하세요)\n"
                + "\n".join(f"- {p.caption} (라벨: {p.label})" for p in captioned)
                + "\n사진 속 대상을 본문에서 정확히 언급하되, 이 목록의 형식 자체는 본문에 옮기지 마세요."
                "\n같은 라벨 사진이 여러 장이면 [사진:라벨] 마커에는 이 목록에 적힌 순서대로 "
                "사진이 들어갑니다 — 설명 문단도 그 순서를 따르거나, 특정 사진을 콕 집으려면 "
                "라벨 대신 위 설명을 그대로 써서 [사진:설명] 형태로 지정하세요"
                "(예: [사진:치즈카츠 클로즈업])."
            )
    if template_text and template_text.strip():
        parts.append(
            "# 사용 템플릿\n"
            "다음 템플릿은 최종 글의 구조입니다. 템플릿의 사진 마커와 제목 위치를 유지하며, "
            "실제 블로그 제목과 본문 내용으로 자연스럽게 채워주세요. 템플릿의 레이블은 그대로 복사하지 말고 "
            "실제 글 제목/본문으로 바꾸세요.\n"
            + template_text.strip()
        )
    parts.append("위 경험을 중심으로 네이버 블로그 후기 글을 제목과 본문으로 작성하세요.")
    return "\n\n".join(parts)
