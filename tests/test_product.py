from io import BytesIO

from PIL import Image

from autoblog.collect.fact_card import CardType, Source
from autoblog.collect.product import collect_product, parse_shop_item
from autoblog.vision import (
    ProductDetail,
    VisionUnavailable,
    _parse_detail,
    _parse_specs,
    _split_tall_image,
)

# 쇼핑 검색 API 실응답 형태 (라이브 캡처 기반)
SHOP_ITEM = {
    "title": "<b>강아지</b> <b>노즈워크</b> 장난감 분리불안 훈련 노즈볼",
    "link": "https://smartstore.naver.com/main/products/2370335571",
    "image": "https://shopping-phinf.pstatic.net/main_1302551/13025510058.28.jpg",
    "lprice": "19900",
    "hprice": "",
    "mallName": "펫프닝",
    "productId": "13025510058",
    "brand": "노즈워크",
    "maker": "",
    "category1": "생활/건강",
    "category2": "반려동물",
    "category3": "강아지 장난감/훈련",
    "category4": "노즈워크",
}


def test_parse_shop_item():
    facts = parse_shop_item(SHOP_ITEM)
    assert facts.name == "강아지 노즈워크 장난감 분리불안 훈련 노즈볼"  # <b> 제거
    assert facts.price == "19,900원"
    assert facts.brand == "노즈워크"
    assert facts.maker is None  # 빈 문자열 → None
    assert facts.category == "생활/건강>반려동물>강아지 장난감/훈련>노즈워크"
    assert facts.mall_name == "펫프닝"
    assert facts.image.startswith("https://")


def test_collect_product_basics(monkeypatch):
    monkeypatch.setattr("autoblog.collect.product.search_product", lambda q, display=5: [parse_shop_item(SHOP_ITEM)])
    card = collect_product("강아지 노즈워크")
    assert card.type == CardType.product
    assert Source.search_api in card.sources
    assert card.product.name.startswith("강아지")
    assert not card.is_fallback


def test_collect_product_text_only(monkeypatch):
    # 텍스트만 입력하면 Vision 없이 그대로 상세설명으로 사용
    monkeypatch.setattr("autoblog.collect.product.search_product", lambda q, display=5: [parse_shop_item(SHOP_ITEM)])
    card = collect_product("강아지 노즈워크", detail_text="  말랑말랑 젤리 촉감, 1+1 구성  ")
    assert card.product.detail_text == "말랑말랑 젤리 촉감, 1+1 구성"
    assert Source.vision not in card.sources  # 이미지 없으니 Vision 미호출


def test_collect_product_text_and_image_combined(monkeypatch):
    # 텍스트 + 이미지 둘 다 주면 본문이 합쳐지고 스펙/포인트는 이미지에서
    monkeypatch.setattr("autoblog.collect.product.search_product", lambda q, display=5: [parse_shop_item(SHOP_ITEM)])
    detail = ProductDetail(text="이미지 전사 문구", selling_points=["촉감 좋음"], specs=[])
    monkeypatch.setattr("autoblog.vision.extract_product_detail", lambda imgs, model=None, context=None: detail)
    card = collect_product("강아지 노즈워크", detail_text="사용자 입력", detail_images=["/tmp/d.jpg"])
    assert card.product.detail_text == "사용자 입력\n\n이미지 전사 문구"
    assert card.product.selling_points == ["촉감 좋음"]
    assert Source.vision in card.sources


def test_collect_product_vision_unavailable(monkeypatch):
    # Vision 미연동(서버다운 등)이면 경고만 남기고 기본정보는 유지
    monkeypatch.setattr("autoblog.collect.product.search_product", lambda q, display=5: [parse_shop_item(SHOP_ITEM)])

    def _fail(paths, model=None, context=None):
        raise VisionUnavailable("ollama down")

    monkeypatch.setattr("autoblog.vision.extract_product_detail", _fail)
    card = collect_product("강아지 노즈워크", detail_images=["/tmp/detail1.jpg"])
    assert card.product.detail_images == ["/tmp/detail1.jpg"]
    assert card.product.specs == []
    assert any("Vision" in w for w in card.warnings)


def test_parse_detail():
    content = (
        '{"text":"블핑 멤버가 쓰던 촉감","selling_points":["동일 촉감","휴대 간편"],'
        '"specs":[{"key":"재질","value":"젤리"}]}'
    )
    d = _parse_detail(content)
    assert d.text == "블핑 멤버가 쓰던 촉감"
    assert d.selling_points == ["동일 촉감", "휴대 간편"]
    assert d.specs[0].key == "재질" and d.specs[0].value == "젤리"
    assert _parse_detail("not json").text == ""


def test_parse_specs_list_value():
    # 모델이 값을 배열로 줄 때 콤마로 합쳐 문자열화
    specs = _parse_specs([{"key": "구성", "value": ["당근 12개", "매트 1개"]}])
    assert specs[0].key == "구성"
    assert specs[0].value == "당근 12개, 매트 1개"


def _png(w, h):
    buf = BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_split_tall_image(tmp_path):
    # 정사각형 → 1조각
    sq = tmp_path / "sq.png"
    sq.write_bytes(_png(400, 400))
    assert len(_split_tall_image(str(sq))) == 1
    # 매우 긴 이미지(가로400 세로2000, max_aspect=2 → 800px 타일 → 3조각) → 분할
    tall = tmp_path / "tall.png"
    tall.write_bytes(_png(400, 2000))
    assert len(_split_tall_image(str(tall))) == 3
