"""fact의 지역 정보 보존 회귀 테스트 (결함 G, 2026-07-28).

## 어떻게 발견했나

사람 라벨 실험에서 나왔다. 관련성을 사람이 채점하게 했더니 "도메인을 모르니 애매하다"는
반응이 나왔고, 질문을 '주제 범위'와 '지역·대상 범위'로 쪼개 다시 재보니 원인이 드러났다.

    fact 문장 70건 중 34건(49%)에 지역어가 아예 없었다.

    "2030년까지 모든 포장재 디자인을 재활용 가능하게 설계해야 한다"  ← 어느 나라 규제인가
    "불필요한 포장 감축 목표는 2030년까지 5%, 2035년까지 10%이다"    ← 누구의 목표인가
    "방수 및 내구성 있는 구조로 야외 활동에서도 신뢰할 수 있다"        ← 무엇에 대한 설명인가

같은 34건을 두고 사람은 지역·대상을 '아니오'(범위 밖) 23건으로, Claude는 '부분' 25건으로
판정했다. 사람 쪽이 옳다 — 유럽 시장 기획서의 근거가 되려면 그 fact가 유럽에 관한
것임이 드러나야 하고, 드러나지 않으면 근거가 아니다.

## 왜 심각한가

  · 사람이 관련성을 판정할 수 없다(표본의 절반)
  · **결함 A 수정이 이 문제를 키웠다** — 관련성 채점에서 원문을 제거했으므로,
    fact 문장에 지역이 없으면 검증기도 판정 근거가 전혀 없다
  · 기획서 독자가 그 근거를 자기 시장 이야기로 믿게 된다

## 왜 놓치고 있었나

`Fact` 스키마에 `region` 필드가 **원래 있었다**. 그런데 추출 스키마가 문자열 배열이라
담을 자리가 없었고, 아무도 채우지 않아 배포 데이터 340건이 **전부 None**이었다.
스키마에 필드를 만들어두고 채우는 코드를 쓰지 않으면 그 필드는 존재하지 않는 것과 같다.
"""

import json

import pytest

from agents.competitor import COMPETITOR_FACTS_SCHEMA
from agents.market_research import FACTS_SCHEMA, normalize_region
from agents.verification import build_grading_prompt


def _item_props(schema: dict) -> dict:
    return schema["json_schema"]["schema"]["properties"]["facts"]["items"]["properties"]


# ───────────────────────────── 추출 스키마
@pytest.mark.parametrize("schema,name", [
    (FACTS_SCHEMA, "market_research"),
    (COMPETITOR_FACTS_SCHEMA, "competitor"),
])
def test_추출_스키마가_지역을_함께_받는다(schema, name):
    """문자열 배열로 되돌리면 담을 자리가 없어져 결함 G가 재발한다."""
    items = schema["json_schema"]["schema"]["properties"]["facts"]["items"]
    assert items["type"] == "object", f"{name}: 문자열 배열로 되돌아갔다"
    assert set(items["required"]) == {"text", "region"}


@pytest.mark.parametrize("schema,name", [
    (FACTS_SCHEMA, "market_research"),
    (COMPETITOR_FACTS_SCHEMA, "competitor"),
])
def test_지역_불명을_허용하고_추측을_금지한다(schema, name):
    """'불명'을 허용하지 않으면 LLM이 목표시장을 베껴 적는다 — 무관한 fact가
    관련 있어 보이게 되는 최악의 실패다."""
    desc = _item_props(schema)["region"]["description"]
    assert "불명" in desc
    assert "추측" in desc and "목표시장" in desc


@pytest.mark.parametrize("schema,name", [
    (FACTS_SCHEMA, "market_research"),
    (COMPETITOR_FACTS_SCHEMA, "competitor"),
])
def test_fact_문장이_독립적으로_읽히도록_요구한다(schema, name):
    desc = _item_props(schema)["text"]["description"]
    assert "따로 읽어도" in desc or "지역" in desc


# ───────────────────────────── 지역 표기 정규화
@pytest.mark.parametrize("raw,expected", [
    ("EU", "유럽"), ("유럽연합", "유럽"), ("Europe", "유럽"), ("european union", "유럽"),
    ("US", "미국"), ("USA", "미국"), ("United States", "미국"),
    ("North America", "북미"), ("북아메리카", "북미"),
    ("Korea", "한국"), ("국내", "한국"), ("대한민국", "한국"),
    ("UK", "영국"), ("global", "글로벌"), ("전 세계", "글로벌"),
])
def test_같은_지역의_다른_표기를_하나로_모은다(raw, expected):
    """정규화하지 않으면 'EU'와 '유럽'이 다른 값으로 저장되고, 지역 일치 판정이
    무의미해진다."""
    assert normalize_region(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "없음", "N/A", "unknown"])
def test_빈값과_모르는_표현은_불명으로_모은다(raw):
    assert normalize_region(raw) == "불명"


def test_목록에_없는_지역은_버리지_않고_남긴다():
    """모르는 지역을 '불명'으로 뭉치면 정보가 사라진다."""
    assert normalize_region("오세아니아") == "오세아니아"
    assert normalize_region("동남아시아") == "동남아시아"


def test_None은_불명과_구분한다():
    """None은 '아직 안 채웠다', '불명'은 '채우려 했지만 근거가 없었다'다.
    배포 데이터 340건이 전부 None이었던 것이 바로 이 구분이 없어서 생긴 혼란이었다."""
    assert normalize_region(None) is None


# ───────────────────────────── 채점에서 실제로 쓰이는가
def test_관련성_프롬프트에_지역이_들어간다():
    """필드를 채우기만 하고 쓰지 않으면 또 죽은 필드가 된다."""
    p = build_grading_prompt("어떤 fact", "원문", "친환경 포장재", "유럽 B2B 유통 시장",
                             "relevance", region="인도")
    assert "인도" in p
    assert "이 fact가 다루는 지역" in p


def test_지역이_없으면_불명으로_표시된다():
    p = build_grading_prompt("어떤 fact", "원문", "친환경 포장재", "유럽 B2B 유통 시장",
                             "relevance", region=None)
    assert "불명" in p


def test_근거지지도_프롬프트에는_지역이_들어가지_않는다():
    """두 축의 입력이 겹치면 min 결합의 독립 가정이 깨진다(결함 A와 같은 이유)."""
    p = build_grading_prompt("어떤 fact", "원문", "친환경 포장재", "유럽 B2B 유통 시장",
                             "groundedness", region="인도")
    assert "인도" not in p
    assert "이 fact가 다루는 지역" not in p


def test_지역_불일치는_2점_이하라고_지시한다():
    from agents.verification import PERSPECTIVE_PROMPTS
    rel = PERSPECTIVE_PROMPTS["relevance"]
    assert "2점 이하" in rel
    assert "불명" in rel and "3점을 넘지 않습니다" in rel


# ───────────────────────────── 추출 함수가 (text, region)을 돌려주는가
def _fake_client(payload: dict):
    class _C:
        def create(self, *, model, messages, response_format):
            class _M: content = json.dumps(payload, ensure_ascii=False)
            class _Ch: message = _M()
            class _R: choices = [_Ch()]
            return _R()

    class _Client:
        chat = type("_X", (), {"completions": _C()})()
    return _Client()


def test_extract_facts가_지역과_함께_돌려준다():
    from agents.market_research import extract_facts
    payload = {"facts": [
        {"text": "EU는 2030년까지 포장재를 재활용 가능하게 설계하도록 의무화한다", "region": "EU"},
        {"text": "인도 정부가 QR 표시를 의무화했다", "region": "India"},
    ]}
    out = extract_facts(_fake_client(payload), "질문",
                        {"title": "t", "content": "c"}, "친환경 포장재", "유럽 B2B 유통 시장")
    assert out == [
        ("EU는 2030년까지 포장재를 재활용 가능하게 설계하도록 의무화한다", "유럽"),
        ("인도 정부가 QR 표시를 의무화했다", "인도"),
    ]


def test_문자열만_와도_깨지지_않는다():
    """구조화 출력이 계약을 어기는 경우가 실제로 있었다(결함 D의 0점 사례)."""
    from agents.market_research import extract_facts
    out = extract_facts(_fake_client({"facts": ["지역 없는 옛 형식 문장"]}),
                        "질문", {"title": "t", "content": "c"}, "주제", "시장")
    assert out == [("지역 없는 옛 형식 문장", None)]


def test_깨진_인코딩과_메타발언은_지역과_무관하게_걸러진다():
    from agents.market_research import extract_facts
    payload = {"facts": [
        {"text": "제공된 본문에는 해당 정보가 포함되어 있지 않습니다.", "region": "유럽"},
        {"text": "í í¸ë¼Pak ì¸í°ë´ì ë, ìì½ë¥´, ëª¬ë ê·¸ë£¹", "region": "유럽"},
        {"text": "EU는 2030년까지 포장재 재활용을 의무화한다", "region": "유럽"},
    ]}
    out = extract_facts(_fake_client(payload), "질문",
                        {"title": "t", "content": "c"}, "주제", "시장")
    assert len(out) == 1
    assert out[0][0].startswith("EU는")


# ───────────────────────────── 배선 (가장 중요)
def test_저장_경로가_실제로_region을_Fact에_넣는다(monkeypatch):
    """변조실험에서 드러난 구멍.

    `region=region` 한 줄을 Fact 생성에서 지우는 변조를 넣었더니 35개가 전부 통과했다.
    추출 스키마·정규화·프롬프트를 각각 시험하면서, **그것들이 실제로 이어져 있는지는**
    아무도 확인하지 않은 것이다. 어제 결함 F에서 `decode_html`을 직접만 호출하고
    수집 경로를 타지 않아 같은 실수를 했다 — 두 번 반복한 유형이다.

    여기서는 저장 함수를 가로채, 파이프라인이 만든 Fact에 region이 실려 있는지 본다.
    """
    from agents import market_research as M

    saved: list = []

    monkeypatch.setattr(M, "search_web", lambda *a, **k: [{
        "url": "https://example.com/eu", "title": "t",
        "content": "본문", "source_tier": "2차",
    }])
    monkeypatch.setattr(M, "chunk_text", lambda c: [c])
    monkeypatch.setattr(M, "filter_relevant_chunks", lambda *a, **k: "걸러진 본문")
    monkeypatch.setattr(M, "extract_facts", lambda *a, **k: [
        ("EU는 2030년까지 포장재 재활용을 의무화한다", "유럽"),
        ("지역 근거가 없는 문장", "불명"),
    ])

    def _save(fact):
        saved.append(fact)
        return fact, True

    monkeypatch.setattr(M, "save_fact_if_new", _save)
    monkeypatch.setattr(M, "verify_facts_batch", lambda *a, **k: {
        "accepted": 0, "ambiguous": 0, "rejected": 0})

    M._search_extract_and_save(
        client=None, query="q", topic="친환경 포장재",
        target_market="유럽 B2B 유통 시장", results_per_question=1,
        all_facts=[], counters={"n_saved": 0, "n_duplicates": 0},
    )

    assert len(saved) == 2, "fact 2건이 저장돼야 한다"
    assert saved[0].region == "유럽", "region이 Fact에 실리지 않았다 — 결함 G 재발"
    assert saved[1].region == "불명", "'불명'도 그대로 보존돼야 한다"
