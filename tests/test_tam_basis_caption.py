"""기획서 개요 카드의 TAM 기준 연도 회귀 테스트 (2026-07-29 결함 I).

## 무엇이 문제였는가

`docx_export.py`가 개요 카드 문구를 `"2022년 시장 규모 기준 (Top-down)"` 으로
**하드코딩**하고 있었다. 실제 근거 연도와 무관하게 모든 기획서가 2022년이라고 적혔다.

    한국 HMR     개요 2022년  ↔  근거 2021년
    유럽 포장재   개요 2022년  ↔  근거 2025년(예측치)
    북미 웨어러블  개요 2022년  ↔  근거 2021년

**세 건 모두 틀렸다.**

## 왜 지금까지 안 드러났는가

세 가지가 겹쳤다.

  · **TAM 값 자체는 맞다.** 연도만 틀렸다.
  · **개요와 02장이 다른 페이지에 있다.** 나란히 놓고 대조하지 않으면 모른다.
  · **검증기는 fact를 채점하지 기획서를 채점하지 않는다.** 이 문자열은 fact가 아니라
    문서 템플릿에 박힌 것이라 어떤 검증 계층도 지나지 않았다.

산출물 루브릭(`eval/rubric/hisrubric.py` 항목 10 — *"개요의 수치와 02장의 수치가
일치한다(연도 포함)"*)이 발견했다. 그 항목을 넣을 때는 *"당연히 통과하겠지"* 라고
생각했는데 세 문서 전부 실패였다. **인상 평가로는 못 잡는 것을 루브릭이 잡은 사례다.**

## 이 파일이 지키는 것

  1. 근거에서 연도를 실제로 뽑는가 (계약)
  2. 예측치 표기를 보존하는가 — 2025년 예측치를 "2025년 시장 규모"로 쓰면 안 된다
  3. **뽑지 못하면 거짓 연도를 쓰지 않는가** — 이 프로젝트의 "지어내지 않는다" 원칙
  4. 카드 생성 경로가 실제로 이 함수를 타는가 (배선)
"""

import re

import pytest

from agents.docx_export import tam_basis_caption
from fact_store.schema import MarketSizing


def _ms(*assumptions: str) -> MarketSizing:
    return MarketSizing(unit="USD", assumptions=list(assumptions))


# ------------------------------------------------------------------ ① 계약
@pytest.mark.parametrize("assumption,expected_year", [
    ('[Top-down] TAM=1,811,594,203 USD (2021 기준, 근거: "...")', "2021"),
    ('[Top-down] TAM=11,613,000,000 USD (2025 (예측치) 기준, 근거: "...")', "2025"),
    ('[Top-down] TAM=15,067,050,000 USD [원문 150.7억 x 100,000,000] (2019 기준, 근거: "...")', "2019"),
])
def test_근거에서_기준_연도를_뽑는다(assumption, expected_year):
    out = tam_basis_caption(_ms(assumption))
    assert expected_year in out, f"연도를 못 뽑았다: {out!r}"
    assert "2022" not in out or expected_year == "2022", "하드코딩된 2022가 되살아났다"


def test_예측치_표기를_보존한다():
    """2025년 예측치를 '2025년 시장 규모'로 쓰면 실측치인 것처럼 읽힌다.

    「Relevant Is Not Warranted」가 말하는 temporal validity — 시점 부정합이다.
    예측치를 실측치처럼 제시하는 것은 근거 강도를 부풀리는 것이다.
    """
    out = tam_basis_caption(_ms('[Top-down] TAM=116 USD (2025 (예측치) 기준, 근거: "...")'))
    assert "예측치" in out, f"예측치 표기가 사라졌다: {out!r}"
    assert "시장 규모" not in out, f"예측치인데 실측치처럼 적혔다: {out!r}"


def test_실측치는_예측치로_표기하지_않는다():
    out = tam_basis_caption(_ms('[Top-down] TAM=100 USD (2021 기준, 근거: "...")'))
    assert "예측치" not in out
    assert "2021년 시장 규모" in out


@pytest.mark.parametrize("ms", [
    None,
    MarketSizing(unit="USD", assumptions=[]),
    MarketSizing(unit="USD", assumptions=["[Top-down] TAM=123 USD 근거 형식이 바뀌었음"]),
    MarketSizing(unit="USD", assumptions=["[Bottom-up] 미계산 — 파라미터 없음"]),
])
def test_연도를_모르면_거짓_연도를_쓰지_않는다(ms):
    """가장 중요한 시험이다.

    파싱이 실패했을 때 **틀린 연도를 쓰느니 안 쓰는 편이 낫다.** 근거 형식이 바뀌면
    조용히 실패하는데, 그때 임의의 연도가 나가면 결함 I가 그대로 재발한다.
    """
    out = tam_basis_caption(ms)
    assert not re.search(r"\d{4}년", out), f"근거 없이 연도를 적었다: {out!r}"
    assert "Top-down" in out, "무엇을 기준으로 한 값인지는 남아야 한다"


def test_하드코딩된_연도가_코드에_없다():
    """리터럴이 되살아나는 것을 막는다.

    단순 문자열 검색으로는 안 된다 — 처음에 그렇게 짰다가 **이 파일과 수정 함수의
    docstring이 옛 문구를 인용한 것**에 걸려 실패했다. 무엇이 문제였는지 설명하려면
    그 문자열을 적어야 하는데, 그것까지 결함으로 잡으면 기록을 못 남긴다.

    그래서 AST로 파싱해 **docstring이 아닌 문자열 상수만** 검사한다.
    설명은 자유롭게 쓰되 코드에는 못 넣게 하는 것이 의도다.
    """
    import ast

    import agents.docx_export as M

    tree = ast.parse(open(M.__file__, encoding="utf-8").read())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))

    offenders = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docstrings
        and re.search(r"\d{4}년 시장 규모 기준", n.value)
    ]
    assert not offenders, f"코드에 연도가 하드코딩됐다: {offenders}"


FALLBACK = "Top-down 기준 (기준 연도는 02장 참고)"


def test_TAM_줄이_아닌_근거에서_연도를_가져오지_않는다():
    """변조실험이 뚫은 구멍 ① — Top-down·TAM 필터를 지워도 테스트가 통과했다.

    `assumptions`에는 TAM 말고도 SAM 비중·SOM 비중·Bottom-up 줄이 함께 들어 있고,
    **그 줄들도 자기 근거 연도를 갖는다.** 필터가 없으면 TAM 줄에서 연도를 못 뽑았을 때
    SAM 줄의 연도를 집어 와서 "TAM 기준 연도"라고 적는다. 값은 그럴듯하고 형식도
    맞아서 눈으로는 절대 못 잡는다 — 결함 I와 같은 종류의 오류를 새로 만드는 것이다.
    """
    ms = _ms(
        "[Top-down] TAM=1,000,000 USD — 근거 형식이 바뀌어 연도가 없음",
        '[Top-down] SAM 비중=15.00% — 2019년 성인 HMR 이용률 기반 (2019 기준, 근거: "...")',
    )
    out = tam_basis_caption(ms)
    assert "2019" not in out, f"SAM 줄의 연도를 TAM 기준으로 가져왔다: {out!r}"
    assert out == FALLBACK


@pytest.mark.parametrize("assumption", [
    '[Top-down] TAM=100 USD (30 기간 동안 성장 전망) 근거 없음',   # '기'만 있고 '기준' 아님
    "[Top-down] TAM=100 USD (21 기준) 출처 미상",                # '근거'가 없음
    "[Top-down] TAM=100 USD (2021 기준) 출처 미상",              # 네 자리지만 '근거' 없음
    "[Top-down] TAM=100 USD (2021 기준, 추정) 출처 미상",         # '근거'가 아닌 다른 말
    '[Top-down] TAM=100 USD 2021 기준, 근거: "..."',            # 괄호가 없음
])
def test_형식이_정확히_맞을_때만_연도를_인정한다(assumption):
    r"""변조실험이 뚫은 구멍 ② — 정규식을 느슨하게 해도 테스트가 통과했다.

    `(\d{4})...기준,\s*근거` 를 `(\d{2,4})...기준?` 처럼 풀면 엉뚱한 괄호에서
    숫자를 집는다. 두 자리 숫자나 '기간'의 '기'까지 연도로 오인한다.
    **틀린 연도를 쓰느니 안 쓰는 편이 낫다**는 것이 이 함수의 설계 원칙이므로,
    형식이 어긋나면 반드시 폴백해야 한다.

    `근거` 라는 말까지 요구하는 이유: 그 단어 뒤에 원문 인용이 따라온다. 인용이 없는
    연도는 **출처 없이 적힌 숫자**이고, 그것을 개요 카드에 실으면 근거가 있는 것처럼
    보인다. 결함 I가 정확히 그런 오류였다.
    """
    assert tam_basis_caption(_ms(assumption)) == FALLBACK


# ------------------------------------------------------------------ ② 배선
def test_카드_생성_경로가_실제로_이_함수를_탄다():
    """계약만으로는 부족하다.

    `tam_basis_caption()`이 완벽해도 `_add_kpi_cards()`가 부르지 않으면 문서에는
    옛 문구가 나간다. 이 프로젝트가 네 번 겪은 실수다(결함 F·G, 그 진단, 판정 경계).
    """
    import inspect

    from agents.docx_export import _add_kpi_cards
    src = inspect.getsource(_add_kpi_cards)
    assert "tam_basis_caption(" in src, "카드 생성부가 이 함수를 부르지 않는다"
    assert "2022년" not in src, "카드 생성부에 하드코딩 연도가 남아 있다"


def test_실제_생성된_카드_문구가_근거와_일치한다(monkeypatch):
    """docx를 실제로 만들어 카드에 들어간 문자열을 확인한다.

    소스 검사(위)는 '부르는가'만 본다. 이 시험은 '결과가 맞는가'를 본다.
    """
    from docx import Document

    from agents.docx_export import _add_kpi_cards

    ms = _ms('[Top-down] TAM=11,613,000,000 USD (2025 (예측치) 기준, 근거: "유럽은…")')
    doc = Document()
    _add_kpi_cards(doc, ms)
    text = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "2025년 예측치" in text, f"카드에 근거 연도가 반영되지 않았다:\n{text}"
    assert "2022" not in text, f"하드코딩 연도가 카드에 남아 있다:\n{text}"
