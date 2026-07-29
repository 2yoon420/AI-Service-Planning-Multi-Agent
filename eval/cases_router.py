"""Router 6-way 분류 골든셋 — 케이스 정의.

## 왜 이 파일이 필요했는가

1차 외부 검토(2026-07-24) ②, 3차 검토(2026-07-28) 4순위로 **세 번 지적받고 세 번
미뤘던** 항목이다.

> *"`decide_next_action()`은 6-way 분류인데 정확도를 측정할 테스트셋이 없다.
> 오분류 비용이 비대칭적으로 크다(엉뚱한 재실행 = 웹검색 + LLM 다수 호출 +
> `REVISION_CAP` 1회 소진). **설계안 3-3절에서 옵션 B를 택한 근거가 '테스트 용이성'
> 이었으나 정작 테스트가 없다.**"*

마지막 문장이 특히 아프다 — **설계 근거가 스스로를 겨누는 상태**였다.

그리고 3차 검토 3절의 검증 밀도 표에서 Router는 유일하게 빈 칸이었다.

    검증기      ██████████  4중 측정
    산출물      ████████    루브릭 82%
    Router      ░░░░░░░░░░  없음

**Router는 사용자가 실제로 만지는 유일한 판단 지점**이다. 검증기는 뒤에서 조용히 돌지만
Router가 틀리면 *"경쟁사 부분 다시 해줘"* 에 PESTEL이 도는 것이 화면에 그대로 보인다.

## 정답은 어디서 나왔는가 — 세 규칙

케이스의 정답을 내가 임의로 정하면 그것도 근거 없는 값이 된다. **코드와 프롬프트가
스스로 선언한 규칙**에서 도출한다.

### 규칙 A — 경계 케이스의 정답이 코드 주석에 있다

`orchestrator/graph.py`의 `pestel_revision_node`:

> *"PESTEL 에이전트는 원래 새 웹검색을 하지 않으므로 … **재검색이 필요한 요청이면
> Router가 `revise_market_research`로 먼저 보내야 한다.**"*

따라서 *"PESTEL에 최신 규제 반영해줘"* 의 정답은 **`revise_market_research`** 다.
새 규제를 반영하려면 검색이 필요하고, PESTEL 노드는 검색을 하지 않는다.
1차 검토가 이것을 *"검증 대상"* 으로 지목했다.

**이 전제의 한계**: 주석이 곧 사양이라고 보는 것이다. 주석이 틀렸을 가능성은 배제하지
않았다. 만약 실측에서 모델이 일관되게 `revise_pestel`을 고르고 그게 더 자연스럽다면,
**고칠 대상은 모델이 아니라 주석일 수도 있다.**

### 규칙 B — 애매하면 되묻는 것이 정답이다

`_router_decision_prompt()`가 명시한다.

> *"애매한데 대충 짐작해서 다른 action을 고르지 마세요 — 잘못 넘겨짚어 엉뚱한 재작업을
> 시작하는 것보다 되묻는 편이 훨씬 낫습니다."*

즉 모호 발화에서 `unclear`가 아닌 답이 나오면 **명시적 지시 위반**이다. 이건 취향이
아니라 계약 위반이므로 오답으로 센다.

### 규칙 C — `revision_count`는 판단에 영향을 주지 않아야 한다

프롬프트에 값이 들어가지만 판단 규칙 1~6에는 쓰이지 않는다(상한 도달 시 종료는
`router_node`가 LLM 호출 **전에** 처리한다). 같은 발화를 `revision_count` 0과 4로 넣어
답이 달라지면 **누출**이다. `leak_check=True` 케이스가 이것을 잰다.

## 케이스 구성

| 층 | 수 | 목적 |
|---|---|---|
| 명확(clear) | 24 | 6 action × 4 — 기본 분류 능력 |
| **경계(boundary)** | 12 | 규칙 A 검증. 두 action 사이에서 코드가 선언한 쪽을 고르는가 |
| 모호(ambiguous) | 6 | 규칙 B 검증. 넘겨짚지 않고 되묻는가 |
| **합계** | **42** | |

경계 케이스에 `also_acceptable`을 둔 것이 있다. **정답이 하나로 확정되지 않는 케이스를
틀렸다고 세면 측정이 왜곡된다.** 다만 규칙 A가 적용되는 케이스에는 두지 않는다 —
코드가 답을 정했으므로 관용할 여지가 없다.
"""

from __future__ import annotations

from typing import Literal, NamedTuple, Optional

Action = Literal[
    "approve",
    "revise_market_research",
    "revise_pestel",
    "revise_competitor",
    "capability_question",
    "unclear",
]
Layer = Literal["clear", "boundary", "ambiguous"]


class Case(NamedTuple):
    id: str
    layer: Layer
    message: str
    expect: Action
    why: str                              # 왜 이것이 정답인가 (코드·프롬프트 근거)
    also_acceptable: tuple[Action, ...] = ()   # 정답이 하나로 확정되지 않는 경계 케이스
    revision_count: int = 0
    leak_check: bool = False              # revision_count 누출 검사 대상


CASES: list[Case] = [
    # ────────────────────────────────── 명확 · approve (4)
    Case("C-AP-1", "clear", "좋아요, 이대로 최종본으로 해주세요", "approve",
         "프롬프트 규칙 1의 예시 문구와 사실상 동일"),
    Case("C-AP-2", "clear", "완료", "approve", "규칙 1 예시"),
    Case("C-AP-3", "clear", "확인했습니다. 더 수정할 것 없습니다", "approve",
         "만족 의사 + 추가 요청 없음 명시"),
    Case("C-AP-4", "clear", "네 승인합니다", "approve", "규칙 1 예시"),

    # ────────────────────────────────── 명확 · revise_market_research (4)
    Case("C-MR-1", "clear", "시장 규모 수치를 더 찾아서 다시 계산해주세요",
         "revise_market_research", "규칙 2 — 시장조사 데이터 재검색·재계산"),
    Case("C-MR-2", "clear", "TAM이 너무 큰 것 같은데 다른 출처로 검증해줘",
         "revise_market_research", "규칙 2 — 시장 규모 재검증"),
    Case("C-MR-3", "clear", "투자 유치 현황 자료를 추가로 조사해주세요",
         "revise_market_research", "규칙 2 — 투자·매출은 시장조사 범위"),
    Case("C-MR-4", "clear", "매출 규모 데이터가 부족해요. 보강해주세요",
         "revise_market_research", "규칙 2"),

    # ────────────────────────────────── 명확 · revise_pestel (4)
    Case("C-PE-1", "clear", "PESTEL 분석을 다시 봐주세요", "revise_pestel",
         "규칙 3 — 기존 자료 재분석 요청. 새 자료 요구 없음"),
    Case("C-PE-2", "clear", "환경분석 요약이 너무 짧아요. 다시 정리해주세요",
         "revise_pestel", "규칙 3 — 재요약이므로 새 검색 불필요"),
    Case("C-PE-3", "clear", "PESTEL 여섯 축 중에 빈 게 있어요. 다시 채워주세요",
         "revise_pestel", "규칙 3 — 이미 수집된 fact 재태깅으로 해결 가능"),
    Case("C-PE-4", "clear", "정치·경제 축 서술을 좀 더 구조화해주세요", "revise_pestel",
         "규칙 3 — 서술 재구성"),

    # ────────────────────────────────── 명확 · revise_competitor (4)
    Case("C-CO-1", "clear", "경쟁사 부분 다시 조사해줘", "revise_competitor",
         "규칙 4 — 1차 검토가 '명확 케이스' 예시로 지목한 발화"),
    Case("C-CO-2", "clear", "경쟁사 가격 정보가 비어 있어요. 더 찾아주세요",
         "revise_competitor", "규칙 4"),
    Case("C-CO-3", "clear", "직접 경쟁사가 5개뿐인데 더 있는지 확인해주세요",
         "revise_competitor", "규칙 4"),
    Case("C-CO-4", "clear", "간접 경쟁자도 조사해서 표에 넣어주세요",
         "revise_competitor", "규칙 4"),

    # ────────────────────────────────── 명확 · capability_question (4)
    Case("C-CQ-1", "clear", "이거 PPTX도 만들어줘?", "capability_question",
         "규칙 5 예시 문구와 동일"),
    Case("C-CQ-2", "clear", "SWOT 분석도 되나요?", "capability_question",
         "규칙 5 예시 — 서비스 기능 문의"),
    Case("C-CQ-3", "clear", "이 시스템은 어떤 검색 엔진을 쓰나요?",
         "capability_question", "규칙 5 — 기획서 내용과 무관한 시스템 자체 질문"),
    Case("C-CQ-4", "clear", "재작업은 몇 번까지 할 수 있어요?", "capability_question",
         "규칙 5 — 서비스 제약에 대한 질문"),

    # ────────────────────────────────── 명확 · unclear (4)
    Case("C-UN-1", "ambiguous", "전체적으로 좀 더 좋게 해줘", "unclear",
         "규칙 6 예시 문구와 동일"),
    Case("C-UN-2", "ambiguous", "음… 좀 그런데요", "unclear",
         "1차 검토가 '모호 발화' 예시로 지목. 규칙 B(넘겨짚지 말 것)"),
    Case("C-UN-3", "ambiguous", "뭔가 아쉬워요", "unclear",
         "무엇이 아쉬운지 특정 불가 — 규칙 B"),
    Case("C-UN-4", "ambiguous", "다시 해주세요", "unclear",
         "무엇을 다시 할지 특정 불가. 넘겨짚으면 엉뚱한 재작업 — 규칙 B"),
    Case("C-UN-5", "ambiguous", "글쎄요", "unclear", "판단 근거 없음 — 규칙 B"),
    Case("C-UN-6", "ambiguous", "이게 맞나요?", "unclear",
         "무엇을 묻는지 불명. 승인도 수정 요청도 아니다 — 규칙 B"),

    # ────────────────────────────────── 경계 · 규칙 A (관용 없음, 6)
    Case("B-A-1", "boundary", "PESTEL에 최신 규제 반영해줘", "revise_market_research",
         "★규칙 A. 1차 검토가 지목한 바로 그 케이스. 새 규제 반영에는 검색이 필요하고 "
         "pestel_revision_node는 검색을 하지 않는다 — 코드 주석이 research로 먼저 "
         "보내라고 명시"),
    Case("B-A-2", "boundary", "법률 축에 2026년 새로 생긴 규정을 추가해주세요",
         "revise_market_research",
         "★규칙 A. '새로 생긴 규정'은 기존 fact에 없으므로 검색이 선행돼야 한다"),
    Case("B-A-3", "boundary", "환경 축에 최근 발표된 정책 자료를 찾아서 넣어주세요",
         "revise_market_research",
         "★규칙 A. '찾아서'가 명시적 — 검색 요청이다"),
    Case("B-A-4", "boundary", "PESTEL 내용은 그대로 두고 요약만 다시 써주세요",
         "revise_pestel",
         "★규칙 A의 반대 방향. '내용은 그대로'이므로 새 검색이 필요 없다 — "
         "재요약은 PESTEL 노드의 일이다"),
    Case("B-A-5", "boundary", "기존에 모은 자료로 환경분석을 다시 정리해주세요",
         "revise_pestel",
         "★규칙 A의 반대 방향. '기존에 모은 자료로'가 명시적"),
    Case("B-A-6", "boundary", "규제 관련 최신 동향을 조사해서 PESTEL을 업데이트해주세요",
         "revise_market_research",
         "★규칙 A. '조사해서'가 선행 조건 — 검색 없이는 업데이트가 불가능하다"),

    # ────────────────────────────────── 경계 · 관용 있음 (6)
    Case("B-X-1", "boundary", "경쟁사 매출 규모를 더 찾아주세요", "revise_competitor",
         "경쟁사 특정 정보이므로 competitor가 자연스럽다. 다만 '매출 규모'는 규칙 2의 "
         "시장조사 범위와도 겹친다 — 두 답 다 합리적",
         also_acceptable=("revise_market_research",)),
    Case("B-X-2", "boundary", "시장 점유율 자료를 보강해주세요", "revise_market_research",
         "'시장' 데이터이므로 규칙 2. 다만 점유율은 경쟁사별로 나오는 값이라 "
         "competitor로 볼 여지도 있다",
         also_acceptable=("revise_competitor",)),
    Case("B-X-3", "boundary", "좋은데 경쟁사만 좀 더 봐주세요", "revise_competitor",
         "승인 표현('좋은데')과 수정 요청이 섞였다. 프롬프트가 '여러 요청이 섞여 있으면 "
         "이번엔 하나만 처리'라고 했으므로 수정 요청을 취하는 것이 맞다. "
         "approve로 가면 수정 요청이 유실된다"),
    Case("B-X-4", "boundary", "이대로 좋습니다만 혹시 PPTX로도 받을 수 있나요?",
         "capability_question",
         "승인 + 기능 문의. 기능 문의에 답하지 않고 finalize하면 질문이 유실된다",
         also_acceptable=("approve",)),
    Case("B-X-5", "boundary", "경쟁사랑 시장 규모 둘 다 다시 봐주세요",
         "revise_competitor",
         "두 요청이 명시적으로 병렬. 프롬프트가 '하나만 처리하고 reasoning에 취지를 "
         "남겨 다음 턴에 나머지를 처리'하라고 했으므로 어느 하나든 정답",
         also_acceptable=("revise_market_research",)),
    Case("B-X-6", "boundary", "SWOT은 안 되나요? 안 되면 이대로 마무리할게요",
         "capability_question",
         "기능 문의가 선행 조건이고 승인은 그 답에 달려 있다. 먼저 물음에 답해야 한다",
         also_acceptable=("approve",)),

    # ────────────────────────────────── revision_count 누출 검사 (규칙 C, 4)
    Case("L-C-1", "clear", "경쟁사 부분 다시 조사해줘", "revise_competitor",
         "★규칙 C. C-CO-1과 같은 발화를 revision_count=4로 넣는다. "
         "상한 근접이 판단을 바꾸면 누출이다(상한 처리는 router_node가 LLM 호출 전에 한다)",
         revision_count=4, leak_check=True),
    Case("L-C-2", "clear", "시장 규모 수치를 더 찾아서 다시 계산해주세요",
         "revise_market_research",
         "★규칙 C. C-MR-1과 같은 발화, revision_count=4",
         revision_count=4, leak_check=True),
    Case("L-C-3", "ambiguous", "전체적으로 좀 더 좋게 해줘", "unclear",
         "★규칙 C. C-UN-1과 같은 발화, revision_count=4. 상한이 가깝다는 이유로 "
         "approve로 몰아가면 사용자 의사를 왜곡한다",
         revision_count=4, leak_check=True),
    Case("L-C-4", "clear", "좋아요, 이대로 최종본으로 해주세요", "approve",
         "★규칙 C. C-AP-1과 같은 발화, revision_count=4",
         revision_count=4, leak_check=True),
]

# 누출 검사 짝: (누출 케이스 id, 대응하는 revision_count=0 케이스 id)
LEAK_PAIRS = [("L-C-1", "C-CO-1"), ("L-C-2", "C-MR-1"),
              ("L-C-3", "C-UN-1"), ("L-C-4", "C-AP-1")]

ACTIONS: list[Action] = [
    "approve", "revise_market_research", "revise_pestel",
    "revise_competitor", "capability_question", "unclear",
]


def verdict(case: Case, action: str) -> bool:
    """정답 판정. also_acceptable이 있으면 그것도 통과로 본다."""
    return action == case.expect or action in case.also_acceptable


def summary() -> str:
    from collections import Counter
    layers = Counter(c.layer for c in CASES)
    acts = Counter(c.expect for c in CASES)
    return (f"케이스 {len(CASES)}개 — "
            + " · ".join(f"{k} {v}" for k, v in layers.items())
            + f" | 정답 분포: " + " · ".join(f"{k.split('_')[-1]} {v}" for k, v in acts.items()))


if __name__ == "__main__":
    print(summary())
    print(f"관용 있는 경계: {sum(1 for c in CASES if c.also_acceptable)}개")
    print(f"누출 검사: {sum(1 for c in CASES if c.leak_check)}개")
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)), f"중복 id: {[i for i in ids if ids.count(i) > 1]}"
    print("id 중복 없음")
