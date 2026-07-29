"""검색 질의의 연도 회귀 테스트 (2026-07-29 하드코딩 감사).

## 무엇이 문제였는가

경쟁사 심층조사의 가격 질의에 **연도가 문자열로 박혀 있었다.**

    price_query = f"{name} price review comparison 2026"
    price_query = f"{name} 가격 비교 리뷰 추천 2026"

2027년에 실행하면 한 해 지난 리뷰 기사를 겨냥한다. 조용히 낡아가고, 검색 결과가
나빠져도 원인이 코드에 있다는 것을 알기 어렵다.

**결함 I(기획서 개요의 `"2022년 시장 규모 기준"` 하드코딩)와 같은 유형이다.**
다만 파이프라인 위치가 다르다.

    결함 I  — 문서 **출력** 단계. 틀린 연도가 독자에게 보인다.
    이 결함 — 검색 **입력** 단계. 틀린 연도가 그 뒤 모든 단계에 낡은 자료를 공급한다.

입력 쪽이 더 이르므로 피해 범위가 넓다. 그런데 **출력보다 눈에 안 띈다** — 검색 결과가
조금 나빠지는 것으로만 나타나기 때문이다.

## 어떻게 찾았는가

산출물 루브릭이 결함 I를 잡은 뒤, *"같은 유형이 더 있는가"* 를 AST로 전수조사했다.
`docstring`이 아닌 문자열 상수에서 `19xx|20xx` 패턴을 찾는 방식이다.
**눈으로 훑지 않고 기계로 훑은 것이 요점이다** — 결함 I도 눈으로는 세 문서를 읽고도
못 봤다(검증 총정리 9-8절).

## 이 파일이 지키는 것

  1. 질의 연도가 실행 시각을 따라가는가
  2. 두 언어 분기 모두 그러한가 — 한쪽만 고치면 다른 쪽이 낡는다
  3. 테스트를 위해 연도를 고정할 수 있는가 (재현성)
  4. 코드에 연도 리터럴이 되살아나지 않는가
"""

import ast
import re
from datetime import date

import pytest

from agents.competitor import _deep_dive_queries


def test_기본값은_실행_시각의_연도를_쓴다():
    q = _deep_dive_queries("Apple", "북미 시니어 건강관리 시장")[0]
    assert str(date.today().year) in q, f"올해 연도가 질의에 없다: {q!r}"


@pytest.mark.parametrize("year", [2026, 2027, 2030, 2035])
def test_연도를_주면_그_연도를_쓴다(year):
    """미래 연도로도 동작해야 한다 — 하드코딩이면 이 시험이 깨진다."""
    q = _deep_dive_queries("테트라팍", "유럽 B2B 유통 시장", current_year=year)[0]
    assert str(year) in q, f"지정한 연도가 반영되지 않았다: {q!r}"
    assert "2026" not in q or year == 2026, f"옛 하드코딩 연도가 남아 있다: {q!r}"


@pytest.mark.parametrize("market,expect_english", [
    ("북미 시니어 건강관리 시장", True),
    ("유럽 B2B 유통 시장", True),
    ("한국 시니어 케어푸드 시장", False),
])
def test_두_언어_분기_모두_연도가_동적이다(market, expect_english):
    """한쪽만 고치면 다른 쪽이 조용히 낡는다.

    실제로 2026-07-23에 언어 분기를 도입할 때 영어 질의만 손보고 한국어 질의는
    그대로 뒀다면 이 결함이 절반만 고쳐졌을 것이다. 두 분기를 함께 검사한다.
    """
    q = _deep_dive_queries("어떤회사", market, current_year=2033)[0]
    assert "2033" in q, f"{market}: 연도가 반영되지 않았다 — {q!r}"
    assert ("comparison" in q) is expect_english, f"언어 분기가 바뀌었다: {q!r}"


def test_가격_질의만_연도를_갖는다():
    """투자·채널 질의에는 연도를 넣지 않는다.

    가격은 시점에 따라 바뀌므로 최신 리뷰를 겨냥하는 것이 맞지만, 투자·매출·유통망은
    연도를 붙이면 오히려 검색 범위가 좁아진다. 의도한 비대칭이므로 박제한다.
    """
    qs = _deep_dive_queries("Apple", "북미", current_year=2029)
    assert len(qs) == 3
    assert "2029" in qs[0]
    assert not any("2029" in q for q in qs[1:]), f"가격 외 질의에 연도가 붙었다: {qs[1:]}"


def test_질의_템플릿에_연도_리터럴이_없다():
    """리터럴이 되살아나는 것을 막는다.

    docstring은 옛 코드를 인용해야 하므로 AST로 걸러낸다 — 결함 I 테스트에서 같은
    문제를 겪었다(설명하려면 그 문자열을 적어야 하는데 검색이 그것까지 잡았다).
    """
    import agents.competitor as M

    tree = ast.parse(open(M.__file__, encoding="utf-8").read())
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))

    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docs:
            continue
        v = node.value
        # 검색 질의만 골라낸다. 처음에는 '리뷰|price' 등 단어로만 걸렀는데
        # **LLM 프롬프트가 걸렸다** — 그 안에 '가격' 이라는 말과 변경 이력 날짜
        # ('2026-07-24 추가'), 예시 문장('2016년 Mars Petcare에 인수됨')이 함께 있다.
        # 질의는 한 줄이고 짧다는 성질로 구분한다.
        if "\n" in v or len(v) > 80:
            continue
        if re.search(r"(리뷰|추천|비교|review|comparison|price)", v, re.I) \
                and re.search(r"\b(19|20)\d\d\b", v):
            offenders.append((node.lineno, v))
    assert not offenders, f"질의 문자열에 연도가 하드코딩됐다: {offenders}"
