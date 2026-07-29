"""산출물 품질 루브릭 — 기획서 초안을 이진 항목으로 채점한다.

## 왜 필요한가

3차 외부 검토가 이 프로젝트의 가장 큰 구멍으로 꼽은 것이다.

> *"부품은 넷으로 쟀는데 최종 산출물 품질은 한 번도 재지 않았다."*

검증기는 self-test·정렬도·민감도·모델비교로 네 번 쟀다. 그런데 **그 검증기가 만들어낸
기획서가 쓸 만한지**는 인상 평가뿐이었다. NSM이 *"출처검증 통과 기획서 수"* 인데,
이는 **몇 건 만들었는가**이지 **쓸 만한가**가 아니다.

## 설계 원칙 셋

**① 문서를 보고 만들지 않았다.** 관찰한 결함에 맞춰 항목을 만들면 점수가 부풀려진다.
*"시장 진입 기획서가 갖춰야 할 것"* 에서 연역하고 그다음 문서에 적용한다.

**② 전부 예/아니오다.** *"이 장이 좋은가"* 가 아니라 *"TAM에 기준 연도가 있는가"* 다.
정렬도 실험에서 *"1~5점"* 이 도메인 지식을 요구해 라벨이 어려웠던 교훈(9-3절)을 적용했다.
이진이면 채점자가 달라도 같은 답이 나온다.

**③ 입력이 없어 못 하는 것은 "누락의 명시"로 채점한다.**
   SOM Bottom-up은 사업모델 파라미터(잠재고객 수·단가·목표 확보율)가 필요한데 웹검색
   fact만으로는 알 수 없다. 사용자가 입력하지 않았으므로 시스템이 산출하지 못한다.
   **그것을 안 했다고 감점하면 불공정하다.** 대신 *"못 한다는 사실과 필요한 입력을
   밝혔는가"* 를 본다. 이 프로젝트가 주장해온 *"찾지 못한 정보는 지어내지 않고 '정보
   없음'이라고 쓴다"* 를 채점 가능한 형태로 만든 것이다.

   이 원칙은 사용자 질문에서 나왔다 — 초안 루브릭은 SOM 두 경로(Top-down / Bottom-up)를
   구분하지 않아 불공정한 채점이 될 뻔했다.

## 4단 사다리 — 인용이 아니라 차용

FinDeepResearch(arXiv:2510.13936)의 HisRubric 계층 구조를 **참고해** 4단으로 나눴다.

**★ 인용 형태로 쓰지 말 것.** 논문 초록은 이 구조를 3단계로 서술하며
(*"data recognition → metric calculation → strategic summarization and interpretation"*),
`Abstraction`이라는 단어가 초록에 없다. 4단 명칭이 본문에 있을 수는 있으나 확인하지
못했다. 발표·문서에서는 *"FinDeepResearch의 계층 구조를 참고해 4단으로 나눴다"* 처럼
차용임을 밝힌다.

## 한계

  · **국제 벤치마크와 직접 비교할 수 없다.** DeepResearch Bench II의 *"최강 모델도
    루브릭 50% 미만"* 은 과제도 루브릭도 다르다. **"같은 방식으로 쟀다"까지만** 말한다.
  · **항목 13은 외부 확인이 필요하다.** 나머지 31개는 문서만 보면 답이 나오는데,
    *"식별된 경쟁사가 실제 그 시장의 사업자인가"* 만 도메인 지식을 요구한다.
    채점자 간 불일치가 여기서 날 가능성이 가장 높다.
  · **항목 수가 층마다 다르다.** 층별 비율을 비교할 때 가중치가 아니라 분모가 다름을
    기억할 것(Calculation 10 / Recognition 9 / Abstraction 7 / Interpretation 6).
"""

from __future__ import annotations

from typing import Literal, NamedTuple

Rung = Literal["Recognition", "Calculation", "Abstraction", "Interpretation"]


class Item(NamedTuple):
    no: int
    rung: Rung
    chapter: str
    text: str
    hint: str = ""          # 어디를 보면 되는지 (채점자 도움말, 정답 아님)
    needs_external: bool = False


ITEMS: list[Item] = [
    # ── Calculation (10) — 02 시장규모
    Item(1, "Calculation", "02 시장규모", "TAM 수치가 제시되어 있다",
         "개요 카드 또는 02장 표"),
    Item(2, "Calculation", "02 시장규모", "TAM에 통화가 명시되어 있다",
         "USD·KRW·EUR 등이 적혀 있는가. '억'만 있으면 아니오"),
    Item(3, "Calculation", "02 시장규모", "TAM에 기준 연도가 명시되어 있다",
         "'2025년 기준' 같은 표기"),
    Item(4, "Calculation", "02 시장규모", "TAM이 실측치인지 예측치인지 표기되어 있다",
         "'(예측치)' 또는 그에 준하는 표기. 없으면 아니오"),
    Item(5, "Calculation", "02 시장규모", "TAM 산출의 원문 인용이 제시되어 있다",
         "가정 및 근거에 원문 문장이 따옴표로 인용됐는가"),
    Item(6, "Calculation", "02 시장규모", "SAM 비중의 산출 방식이 서술되어 있다",
         "근거의 타당성이 아니라 '어떻게 그 비율이 나왔는지 썼는가'만 본다"),
    Item(7, "Calculation", "02 시장규모",
         "Top-down SOM 비중의 산출 방식이 서술되어 있다",
         "Bottom-up이 아니라 Top-down 경로만 본다"),
    Item(8, "Calculation", "02 시장규모",
         "SAM·SOM 비중이 출처 없는 추정임을 명시했다",
         "'업계 일반적 추정치, 별도 출처 없음' 같은 문구. 근거 있는 척하지 않았는가"),
    Item(9, "Calculation", "02 시장규모",
         "Bottom-up 미산출을 이유와 필요 입력까지 밝혔다",
         "'미계산'만 쓰면 아니오. 왜 못 하는지와 무엇이 필요한지가 있어야 예"),
    Item(10, "Calculation", "01·02 대조",
         "개요의 수치와 02장의 수치가 일치한다 (연도 포함)",
         "TAM 값뿐 아니라 기준 연도도 대조할 것"),

    # ── Recognition (9) — 03 PESTEL · 04 경쟁사 식별 · 06 출처
    Item(11, "Recognition", "03 PESTEL", "PESTEL 6개 축이 모두 채워져 있다",
         "빈 축이 하나라도 있으면 아니오"),
    Item(12, "Recognition", "03 PESTEL",
         "각 축에 구체적 사실(수치·날짜·고유명사)이 최소 1개 있다",
         "일반론만 있는 축이 하나라도 있으면 아니오"),
    Item(13, "Recognition", "03 PESTEL",
         "법·규제 축에 시행일 또는 규정명이 명시되어 있다",
         "'PPWR(Regulation (EU) 2025/40)', '2026년 8월 12일' 같은 것"),
    Item(14, "Recognition", "04 경쟁사", "직접 경쟁사가 3개 이상 식별되어 있다"),
    Item(15, "Recognition", "04 경쟁사",
         "식별된 경쟁사가 실제 그 시장의 사업자다 (환각 아님)",
         "★ 이 항목만 외부 확인이 필요하다. 회사명을 검색해 실재를 확인할 것",
         needs_external=True),
    Item(16, "Recognition", "06 출처", "모든 fact에 출처 URL이 부착되어 있다",
         "출처 부록에서 URL이 빠진 행이 있는지"),
    Item(17, "Recognition", "06 출처", "출처에 조회일이 표기되어 있다"),
    Item(18, "Recognition", "06 출처", "출처 등급과 검증 판정이 표기되어 있다",
         "'3차/채택' 같은 표기"),
    Item(19, "Recognition", "문서 전체", "문서에 깨진 문자(모지바케)가 없다",
         "U+FFFD(���)나 'í í¸ë¼' 같은 깨진 한글"),

    # ── Abstraction (7) — 03·04 종합
    Item(20, "Abstraction", "03 PESTEL",
         "기회와 위협이 함께 서술되어 있다 (한쪽만 나열 아님)"),
    Item(21, "Abstraction", "03 PESTEL",
         "같은 사실을 3개 이상 축에서 반복하지 않는다",
         "예: 같은 규제 내용이 정치·환경·법률 셋에 그대로 반복되면 아니오"),
    Item(22, "Abstraction", "03 PESTEL", "제외된 fact 건수가 표기되어 있다",
         "'중요도가 낮아 요약에서 제외한 fact: N건' — 무엇을 뺐는지 밝혔는가"),
    Item(23, "Abstraction", "04 경쟁사",
         "경쟁사 유형이 구분되어 있다 (직접/간접/잠재)"),
    Item(24, "Abstraction", "04 경쟁사", "각 경쟁사에 차별화 포인트가 서술되어 있다",
         "한 곳이라도 비어 있으면 아니오"),
    Item(25, "Abstraction", "04 경쟁사",
         "빈 항목이 '정보 없음'으로 명시되어 있다 (빈칸 방치 아님)"),
    Item(26, "Abstraction", "04 경쟁사",
         "경쟁 구도 종합이 개별 나열을 넘어 관계를 서술한다",
         "회사별 소개를 이어붙인 것에 그치면 아니오. 비교·대조·구도가 있어야 예"),

    # ── Interpretation (6) — 05 시사점
    Item(27, "Interpretation", "05 시사점", "시사점이 3개 이상 제시되어 있다"),
    Item(28, "Interpretation", "05 시사점",
         "각 시사점이 앞 장의 구체적 근거를 참조한다",
         "회사명·수치·규정명 등이 인용되는가. 하나라도 근거 없이 떠 있으면 아니오"),
    Item(29, "Interpretation", "05 시사점",
         "일반론이 아니라 이 시장에 특정적이다",
         "'차별화가 중요하다' 류만 있으면 아니오"),
    Item(30, "Interpretation", "05 시사점",
         "실행 가능한 행동을 지시한다 (관찰 서술에 그치지 않음)",
         "'~이 필요하다', '~를 구축한다' 같은 지시가 있는가"),
    Item(31, "Interpretation", "05 시사점",
         "위험·제약을 언급한 시사점이 하나 이상 있다"),
    Item(32, "Interpretation", "문서 전체",
         "비어 있는 정보의 한계가 어딘가에 명시되어 있다",
         "'가격 미공개가 많아 추가 조사 필요' 같은 각주"),
]

RUNGS: list[Rung] = ["Recognition", "Calculation", "Abstraction", "Interpretation"]

# 채점 대상 문서. (별칭, 파일명 조각)
DOCS = [
    ("한국_HMR", "시니어_가정간편식HMR"),
    ("유럽_포장재", "친환경_포장재"),
    ("북미_웨어러블", "웨어러블_헬스케어"),
]


def by_no(n: int) -> Item:
    return next(i for i in ITEMS if i.no == n)


def summary() -> str:
    from collections import Counter
    c = Counter(i.rung for i in ITEMS)
    return " · ".join(f"{r} {c[r]}" for r in RUNGS) + f"  (총 {len(ITEMS)})"


if __name__ == "__main__":
    print("루브릭 항목:", summary())
    ext = [i.no for i in ITEMS if i.needs_external]
    print("외부 확인 필요:", ext)
    for r in RUNGS:
        print(f"\n── {r}")
        for i in ITEMS:
            if i.rung == r:
                print(f"  {i.no:>2}. [{i.chapter}] {i.text}")
                if i.hint:
                    print(f"      → {i.hint}")
