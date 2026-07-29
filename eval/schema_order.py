"""근거지지도 채점의 척도 붕괴 — 2×2 요인 실험.

실행:
    python eval/schema_order.py --dry-run            # LLM 없이 스키마·프롬프트·배선만 점검
    python eval/schema_order.py --repeat 2            # 실제 채점 (30건 × 4조건 × 2회 = 240호출)
    python eval/schema_order.py --conditions A,C      # 조건 골라서
    python eval/schema_order.py --report-only         # 저장된 결과만 다시 집계

## 무엇을 규명하려는가

사람 라벨 30건 대비 근거지지도 정렬도가 κ=0.217(미약)이었다. 관련성 축(0.551)보다
훨씬 나쁘다. 그런데 **편향이 아니라 분산 부족**이었다.

    사람   평균 3.33  표준편차 1.66  쓴 점수 [1,3,4,5]
    기계   평균 3.37  표준편차 1.05  쓴 점수 [2,3,5]

모집단 331건에서 기계가 1점·4점을 쓴 비율은 **2.7%**다. 5단 척도가 사실상
`5 / 3 / 2` 세 단계로 퇴화했고, 그것이 우리 판정 3구간과 우연히 1:1로 맞아떨어진다.

## 두 가설

**H1 — 루브릭에 4점 정의가 없다.**
프롬프트 척도 정의에 5·3·2·1점만 있고 **4점이 없다**(관련성 축도 같다). 무엇인지
알려주지 않은 등급은 쓸 수 없다. 그리고 `ACCEPT_MIN_SCORE = 4` 이므로 **채택 경계가
정의되지 않은 등급에 놓여 있다** — 모집단 채택 162건 중 5점이 156건(96%)이다.

**H2 — 출력 스키마에서 점수가 근거보다 앞에 온다.**
`GRADE_SCHEMA` 가 `score → reasoning` 순서다. Router에서 같은 구조가 확인됐고,
필드 순서를 바꿔 정확도가 88.6% → 99.0~99.5%로 올랐다(premature serialization,
arXiv:2606.09410). 점수를 근거보다 먼저 내놓아야 하면 인접 등급을 가릴 수 없다.

**두 가설 모두 같은 관측을 설명한다.** 한 번에 하나만 바꾸면 어느 쪽인지 모른다.
그래서 2×2로 교차한다.

                4점 미정의(현행)   4점 정의 추가
    score 먼저        A (기준선)         C
    reasoning 먼저    B                  D

## 예측 — 무엇이 나오면 무엇을 뜻하는가

- C·D에서만 4점이 늘면 → 원인은 **루브릭**. 프롬프트 한 줄로 고친다.
- B·D에서만 늘면 → 원인은 **스키마 순서**. Router와 같은 처방.
- 둘 다 늘면 → 독립적으로 더한다.
- 아무것도 안 변하면 → **두 가설 모두 기각.** 다른 원인을 찾아야 한다.

## 이 실험이 재지 못하는 것

C·D의 4점 정의 문구는 **내가 썼다.** 그러므로 이 실험은 *"4점을 정의하면 되는가"* 가
아니라 *"이 정의로 되는가"* 를 잰다. 효과가 없어도 H1이 기각되는 것은 아니고
"이 문구로는 안 된다"까지만 말할 수 있다.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import statistics as st
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agents.verification as V  # noqa: E402
from eval.build_groundedness_sample import NUM_PAT, norm  # noqa: E402
from eval.export_dataset import KNOWN as _KNOWN  # noqa: E402
from eval.groundedness_agreement import cohen_kappa, landis_koch, prf  # noqa: E402
from eval.groundedness_scale import combine, status_of  # noqa: E402

SAMPLE = Path("eval/label/groundedness_sample.json")
LABELS = Path("eval/label/groundedness_labels.json")
OUT_DIR = Path("eval/label")
OUT = OUT_DIR / "schema_order.json"

STATUSES = ["채택", "보류", "기각"]

# 운영 프롬프트에 규칙 0이 들어 있는지 — 배선 검사가 원상 복구를 확인할 때 쓴다.
RULE0_IN_PRODUCTION = "■ 규칙 0" in V.PERSPECTIVE_PROMPTS["groundedness"]

# ── 4점 정의 (H1의 처방) ───────────────────────────────────────────────────
#
# 기존 루브릭의 5점과 3점 사이가 비어 있다.
#   5점 = 원문 내용을 표현만 바꿔 정확히 요약
#   3점 = 수치는 맞는데 원문에 없는 단정·인과가 덧붙음
# 그 사이는 "수치도 맞고 확대해석도 없는데 완벽하지는 않은" 구간이다. 실제로 관측되는
# 형태는 두 가지다 — 원문이 단 조건을 fact가 떨어뜨린 경우, 그리고 원문의 두 군데를
# 합쳐 한 문장으로 만든 경우다. 후자는 값이 다 맞아도 **한 곳에서 근거를 확인할 수
# 없다**는 점에서 5점과 다르다.
#
# ACCEPT_MIN_SCORE = 4 이므로 이 등급은 "채택하되 5점만큼 깔끔하지는 않다"에 놓인다.
# v1 — 처음 쓴 문구. **프롬프트 자신의 전제와 충돌한다.**
# 같은 프롬프트가 "fact는 원문을 사실 하나당 한 줄로 요약·재구성한 것"이라고 말하는데,
# v1은 "원문의 떨어진 두 대목을 합침"을 감점 사유로 넣었다 — 시켜놓고 감점하는 셈이다.
# 그러면 척도를 넓히는 게 아니라 5점을 4점으로 옮기는 실험이 된다.
GRADE_4_LINE_V1 = (
    "- 4점: 수치·날짜·고유명사가 모두 원문과 일치하고 원문에 없는 단정·인과도 없으나,\n"
    "  원문이 달아 둔 조건·범위·시점을 fact가 생략했거나, 원문의 서로 떨어진 두 대목을\n"
    "  합쳐 한 문장으로 만들어 근거를 한 곳에서 확인할 수 없음"
)

# v2 — 두 경우로 좁혔다.
#   ① 조건 누락: 원문 "북미 한정 34%" → fact "34%". 값은 맞지만 근거가 약하다.
#   ② 파생값: 원문에 2023년 100·2024년 120 → fact "20% 성장". **그 값 자체는 원문에 없다.**
#      규칙 1을 엄격히 읽으면 2점인데 원문에서 나온 값이니 2점은 과하다.
#      지금 이 구간이 규칙 1과 5점 정의 사이에서 갈 곳이 없다.
GRADE_4_LINE_V2 = (
    "- 4점: 수치·날짜·고유명사가 원문과 일치하고 확대해석도 없으나, 원문이 달아 둔\n"
    "  조건·범위·시점을 fact가 빠뜨렸거나, 원문에 그 값 자체는 없고 원문의 값에서\n"
    "  계산해 얻은 값임"
)

GRADE_4_VARIANTS = {"v1": GRADE_4_LINE_V1, "v2": GRADE_4_LINE_V2}
GRADE_4_LINE = GRADE_4_LINE_V2   # 기본값
ANCHOR_5 = "- 5점: 원문 내용을 표현만 바꿔 정확히 요약함"


def rubric_with_4(prompt: str, line: Optional[str] = None) -> str:
    """척도 정의 목록에 4점 줄을 끼워 넣는다. 다른 문구는 건드리지 않는다."""
    line = line if line is not None else GRADE_4_LINE
    i = prompt.find(ANCHOR_5)
    if i < 0:
        raise SystemExit("5점 정의를 못 찾았다 — 프롬프트가 바뀌었는지 확인할 것")
    j = prompt.find("\n", i)
    return prompt[:j + 1] + line + "\n" + prompt[j + 1:]


# ── 스키마 순서 (H2의 처방) ────────────────────────────────────────────────
def _reorder_schema(order: list[str]) -> dict:
    """`properties` 와 `required` 를 주어진 순서로 재배열한 스키마.

    ## 왜 운영 스키마를 기준선으로 쓰지 않는가

    처음에는 조건 A(기준선)를 "운영 스키마 그대로"로 정의했다. 그런데 실험 결과로
    운영 코드를 고치자(결함 M 수정) **운영이 조건 D가 되어 A를 만들 수 없게 됐다.**
    테스트 8개가 깨진 것이 그 신호였다.

    실험 조건은 운영 상태에 상대적으로 정의하면 안 된다. 운영이 바뀌면 과거 측정과
    비교할 수 없게 된다. 그래서 **두 방향을 모두 명시적으로 구성**한다 — 수정 전
    상태를 언제든 재현할 수 있어야 수정 효과를 다시 검증할 수 있다.

    required 순서도 함께 바꾼다 — Router에서 required 가 생성 순서에 영향을 주는
    것이 확인됐다.
    """
    s = copy.deepcopy(V.GRADE_SCHEMA)
    sch = s["json_schema"]["schema"]
    assert set(sch["properties"]) == set(order), f"스키마 필드가 바뀌었다: {list(sch['properties'])}"
    sch["properties"] = {k: sch["properties"][k] for k in order}
    sch["required"] = list(order)
    return s


def schema_score_first() -> dict:
    """수정 전 순서 — 점수를 근거보다 먼저 내놓게 한다 (결함 M 상태)."""
    return _reorder_schema(["score", "reasoning"])


def schema_reasoning_first() -> dict:
    """수정 후 순서 — 근거를 먼저 쓰게 한다 (현 운영)."""
    return _reorder_schema(["reasoning", "score"])


_LEVEL = re.compile(r"^- (\d)점:", re.M)


def rubric_without_4(prompt: str) -> str:
    """루브릭에서 4점 정의를 **제거**한다 (결함 L 상태 재현).

    수정 후에는 운영 루브릭에 4점이 있으므로, "4점 미정의" 조건은 지우는 방향으로
    만들어야 한다. 문구를 상수로 복사해 두는 대신 지우는 쪽을 택한 이유는, 운영
    문구가 개선되면 그 개선된 문구를 기준으로 비교가 이어지기 때문이다.
    """
    m = re.search(r"\n- 4점:.*?(?=\n- \d점:)", prompt, re.S)
    if not m:
        raise SystemExit("4점 정의를 못 찾았다 — 이미 없는지 확인할 것")
    return prompt[:m.start()] + prompt[m.end():]


def rubric_with_4_variant(prompt: str, variant: str) -> str:
    """운영 4점 정의를 다른 문구로 **교체**한다 (문구 비교용)."""
    return re.sub(r"\n- 4점:.*?(?=\n- \d점:)",
                  "\n" + GRADE_4_VARIANTS[variant], prompt, count=1, flags=re.S)


# (설명, reasoning 먼저인가, 4점 정의가 있는가)
#
# D 가 현 운영 상태다(결함 L·M 수정 후). A 는 수정 전 상태이며 루브릭에서 4점을
# 지우고 스키마 순서를 되돌려 재현한다.
ANCHOR_R1 = "■ 규칙 1 (최우선)"

# ── 규칙 0 (결함 N 후보의 처방) ─────────────────────────────────────────────
#
# ## 왜 필요한가
#
# 과다 기각 10건(기계 기각 / 사람 채택)의 근거 문장을 읽었더니 **9건이 같은 이유**였다.
#
#   "fact 문장에 포함된 '유럽 B2B 유통 시장'이라는 고유명사와 '친환경 포장재 분야'라는
#    내용은 원문에 언급되지 않았습니다. … 규칙 1 위반(2점 이하)에 해당합니다."
#
#   "'1000억원' 및 '2020년' 수치는 원문에 동일한 값으로 명시되어 있으나,
#    '한국 시니어 케어푸드 시장 진출'이라는 고유명사는 원문에 없는 지어낸 내용입니다."
#
# 파이프라인이 fact 문장에 목표시장 서술을 주입하는데, 근거지지도 루브릭은 그것이
# **질문 쪽에서 온 맥락**이라는 것을 말하지 않는다. 그래서 기계가 "지어낸 고유명사"로
# 보고 규칙 1로 기각한다. ②있음(수치 전부 원문에 있음) 29건 중 11건을 기각했다
# (사람은 3건).
#
# **같은 문제를 후보 추출기에서 이미 만났다.** `build_groundedness_sample.py`에서
# `B2B`·`케어푸드`가 후보로 올라와 "맥락 서술어는 출처가 주장한 내용이 아니다"라며
# 걸러냈다. **코드에서는 고쳤는데 루브릭에는 반영하지 않았다** —
# "사양이 실행 경로에 없다"의 다섯 번째다.
#
# ## 규칙 1보다 앞에 놓는 이유
#
# 지금 기계가 이 서술을 **규칙 1로** 처리하고 있다. 예외를 규칙 1보다 뒤에 두면
# 이미 적용된 규칙을 되돌려야 하는데, Router 결함 J에서 그 방식이 실패했다
# (규칙 안에 예외를 삽입해도 90.0%에서 멈췄다). 그래서 별도 규칙으로 앞에 세운다.
#
# ## 위험 — 지역 조작은 여전히 잡아야 한다
#
# "주입된 맥락"과 "fact가 주장하는 지역"의 경계가 애매하다. 원문이 유럽 얘기인데
# fact가 "북미 시장에서"라고 쓴 경우는 **잡아야 한다.** 그래서 문구에 그 구분을
# 명시했다. 다만 지역 판정의 주 담당은 관련성 축(결함 G 수정으로 `region` 필드 신설)
# 이므로, 근거지지도가 지역을 이중으로 벌하고 있었을 가능성이 있다 —
# 결함 A("두 축을 한 판단에 섞음")의 잔재다.
RULE0_TEXT = """■ 규칙 0 (규칙 1보다 먼저 적용) — 주입된 맥락은 감점하지 않는다
fact 문장에는 이 조사의 연구대상·목표시장 서술이 함께 들어 있습니다
(예: "한국 시니어 케어푸드 시장에서", "유럽 B2B 유통 시장에서", "북미 시니어 건강관리
시장에서"). 이것은 **질문 쪽에서 주어진 맥락**이며 출처가 주장한 내용이 아닙니다.
따라서 **원문에 없어도 감점 사유가 아니고, 규칙 1의 "지어낸 고유명사"에 해당하지
않습니다.**

원문에 있어야 하는 것은 fact가 **주장하는 내용** — 금액·비율·성장률·개수, 연도·날짜,
기업·기관·제품의 고유명사 — 입니다.

단, 다음은 규칙 0의 예외이며 규칙 1을 그대로 적용합니다.
- 원문이 다른 지역을 말하는데 fact가 목표시장 지역에서 일어난 일처럼 서술한 경우
  (원문 "유럽에서 35%" → fact "북미에서 35%")
- 목표시장 서술 안에 원문에 없는 **수치**가 붙은 경우
  (원문에 연도가 없는데 fact가 "2026년 북미 시장에서"라고 쓴 경우의 그 연도)

"""


def rubric_with_rule0(prompt: str) -> str:
    """규칙 0을 규칙 1 앞에 삽입한다."""
    i = prompt.find(ANCHOR_R1)
    if i < 0:
        raise SystemExit("규칙 1을 못 찾았다 — 프롬프트가 바뀌었는지 확인할 것")
    if "규칙 0" in prompt:
        raise SystemExit("이미 규칙 0이 있다")
    return prompt[:i] + RULE0_TEXT + prompt[i:]


def rubric_without_rule0(prompt: str) -> str:
    """규칙 0을 제거한다 (운영에 반영된 뒤 기준선을 만들 때 쓴다)."""
    i = prompt.find("■ 규칙 0")
    if i < 0:
        raise SystemExit("규칙 0이 없다")
    j = prompt.find(ANCHOR_R1, i)
    return prompt[:i] + prompt[j:]


def apply_rule0(want: bool):
    """조건이 요구하는 상태로 맞추는 패치 함수를 준다 (운영 상태와 무관하게 절대 지정).

    결함 L·M 때 조건을 운영 상태에 상대적으로 정의해 테스트 8개가 깨졌다.
    이번에는 처음부터 "있어야 한다 / 없어야 한다"로 정의한다.
    """
    def patch(prompt: str) -> str:
        has = "■ 규칙 0" in prompt
        if want and not has:
            return rubric_with_rule0(prompt)
        if not want and has:
            return rubric_without_rule0(prompt)
        return prompt
    return patch


# (설명, reasoning 먼저인가, 4점 정의가 있는가, 규칙 0이 있는가)
#
# D 가 현 운영 상태다(결함 L·M 수정 후, 규칙 0 전). E·F 가 규칙 0을 시험한다.
# 조건은 **운영 상태와 무관하게 절대적으로** 구성한다 — 결함 L·M 때 상대적으로
# 정의해 운영을 고치자 기준선을 만들 수 없게 됐다.
CONDITIONS = {
    "A": ("수정 전 — score · 4점 없음 · 규칙0 없음", False, False, False),
    "B": ("순서만 — reasoning · 4점 없음 · 규칙0 없음", True, False, False),
    "C": ("루브릭만 — score · 4점 있음 · 규칙0 없음", False, True, False),
    "D": ("현 운영 — reasoning · 4점 있음 · 규칙0 없음", True, True, False),
    "E": ("규칙0 추가 — reasoning · 4점 있음 · 규칙0 있음", True, True, True),
    "F": ("규칙0만 — score · 4점 있음 · 규칙0 있음", False, True, True),
}

# 기본 실행 조건 — D vs E 두 개면 규칙 0의 효과를 잰다(50건 × 2 × 3회 = 300호출).
# 여섯 조건을 다 돌리면 900호출이라, 필요할 때만 --conditions 로 지정한다.
DEFAULT_CONDITIONS = "D,E"


# ── 실행 ───────────────────────────────────────────────────────────────────
# 주제 → 목표시장. `eval/export_dataset.py` 가 쓰는 것과 같은 값이다.
#
# fact 스키마에 target_market 이 없다(결함 H와 같은 계열의 공백이다). 처음에는
# 리서치 질문에서 정규식으로 복원했는데 `2028년 유럽 B2B 친환경 포장재 시장` 처럼
# 연도가 붙어 나왔다. 원래 실행에 쓴 값과 다르면 조건 간 비교는 되어도 **원 실행과
# 비교할 수 없다.**
#
# 그리고 이 맵은 이미 저장소에 있었다. 471쌍 민감도 분석·데이터셋 추출이 같은 값을
# 쓰고 있으므로, 그것을 재사용하는 것이 이전 측정과의 연속성도 지킨다.
# `eval/export_dataset.KNOWN` 이 원본이다. 여기에 값을 복사하지 않는다 —
# 복사하면 한쪽만 고쳐져 언젠가 어긋난다. 이 실험이 이전 측정(471쌍 민감도 분석,
# 데이터셋 추출)과 **같은 목표시장**을 쓰는 것이 연속성의 조건이다.
TARGET_MARKETS = {topic: market for topic, (_, market) in _KNOWN.items()}


def target_market_for(topic: str) -> str:
    """주제에 해당하는 목표시장. 모르는 주제는 즉시 중단한다.

    조용히 대체값을 쓰면 네 조건에는 같은 값이 들어가 실험은 돌아가지만, 원 실행과
    다른 값으로 채점한 것을 **아무도 모르게** 된다. 실험이 조용히 무효가 되는 것보다
    멈추는 편이 낫다.
    """
    t = topic.replace(" [구버전 2026-07-28]", "").strip()
    if t not in TARGET_MARKETS:
        raise SystemExit(
            f"목표시장을 모르는 주제: {topic!r}\n"
            f"  eval/schema_order.py 의 TARGET_MARKETS 에 추가할 것 "
            f"(eval/export_dataset.py 의 맵과 같은 값을 쓸 것)")
    return TARGET_MARKETS[t]


class RecordingClient:
    """LLM 없이 배선을 확인하는 대역.

    `grade_fact()` 가 **교체된 스키마를 실제로 쓰는지**를 본다. 이번 라운드에서
    "함수는 고쳤는데 호출되는 경로가 아니었다"를 네 번 만났다. 스키마를 바꿔
    넘겼는데 운영 코드가 모듈 상수를 직접 참조하면 실험이 조용히 무효가 된다.
    """

    def __init__(self, score: int = 3):
        self.seen: list[dict] = []
        self.score = score
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kw):
        self.seen.append({
            "response_format": kw.get("response_format"),
            "prompt": kw["messages"][0]["content"],
            "model": kw.get("model"),
        })
        body = json.dumps({"score": self.score, "reasoning": "대역 응답"}, ensure_ascii=False)

        class M:  # noqa: D401
            content = body
        class C:
            message = M()
        class R:
            choices = [C()]
            usage = None
        return R()


def grade_with(client, schema: dict, prompt_patch, item: dict, market: str):
    """운영 `grade_fact()` 를 그대로 호출하되 모듈 상수만 일시 교체한다.

    `judge_self_test.grade_fact_with_model()` 과 같은 방식이다. 프로덕션 코드에
    평가 전용 파라미터를 추가하지 않으려는 것이고, 그래야 **실제 경로**를 잰다.
    """
    orig_schema = V.GRADE_SCHEMA
    orig_prompt = V.PERSPECTIVE_PROMPTS["groundedness"]
    V.GRADE_SCHEMA = schema
    if prompt_patch:
        V.PERSPECTIVE_PROMPTS["groundedness"] = prompt_patch(orig_prompt)
    try:
        return V.grade_fact(client, item["text"], item["source_excerpt"],
                            item["topic"], market, "groundedness", item.get("region"))
    finally:
        V.GRADE_SCHEMA = orig_schema
        V.PERSPECTIVE_PROMPTS["groundedness"] = orig_prompt


def wiring_check() -> None:
    """교체가 실제로 반영되는지 확인한다. 여기서 실패하면 실험 결과가 무의미하다."""
    print("배선 확인")
    # 검사 개수를 공식으로 세다가 틀렸다(고정 검사가 5개인데 4로 셌다). 조건을 추가할
    # 때마다 공식을 고쳐야 하는 구조 자체가 문제이므로 **실제로 센다.**
    ok = total = 0
    def chk(c, m):
        nonlocal ok, total
        total += 1
        print(f"  {'OK ' if c else '★  '} {m}")
        ok += bool(c)

    item = {"text": "시장은 2조 원 규모다", "source_excerpt": "시장은 2조 원 규모다",
            "topic": "테스트", "region": "한국"}
    for name, (_, reorder, add4, add_r0) in CONDITIONS.items():
        cl = RecordingClient()
        sch = schema_reasoning_first() if reorder else schema_score_first()
        r0 = apply_rule0(add_r0)
        grade_with(cl, sch, r0 if add4 else (lambda p: r0(rubric_without_4(p))), item, "테스트 시장")
        seen = cl.seen[-1]
        props = list(seen["response_format"]["json_schema"]["schema"]["properties"])
        req = seen["response_format"]["json_schema"]["schema"]["required"]
        want = ["reasoning", "score"] if reorder else ["score", "reasoning"]
        chk(props == want, f"{name}: properties 순서 {props}")
        chk(req == want, f"{name}: required 순서 {req}")
        has4 = "- 4점:" in seen["prompt"]
        chk(has4 == add4, f"{name}: 4점 정의 {'있음' if has4 else '없음'}")
        hr0 = "■ 규칙 0" in seen["prompt"]
        chk(hr0 == add_r0, f"{name}: 규칙 0 {'있음' if hr0 else '없음'}")

    chk(list(V.GRADE_SCHEMA["json_schema"]["schema"]["properties"]) == ["reasoning", "score"],
        "호출 후 운영 스키마가 원상 복구됨 (reasoning 먼저)")
    chk("- 4점:" in V.PERSPECTIVE_PROMPTS["groundedness"],
        "호출 후 운영 프롬프트가 원상 복구됨 (4점 정의 있음)")
    chk(("■ 규칙 0" in V.PERSPECTIVE_PROMPTS["groundedness"]) == RULE0_IN_PRODUCTION,
        f"호출 후 규칙 0 상태 유지 ({'있음' if RULE0_IN_PRODUCTION else '없음'})")

    # ── 여기까지는 "스키마가 전달되는가"만 본다 ──────────────────────────
    #
    # 변조실험에서 이 검사의 구멍이 드러났다. `grade_fact()` 를 우회해 직접
    # `client.create()` 를 부르도록 고쳐도 위 검사는 전부 통과한다. 전달된 스키마는
    # 여전히 맞기 때문이다. **"스키마가 맞다"와 "운영 경로를 거쳤다"는 다른 주장이다.**
    #
    # 이번 라운드에서 "함수는 고쳤는데 호출되는 경로가 아니었다"를 네 번 만났는데,
    # 그것을 잡으려고 만든 검사에 같은 구멍이 있었다.
    #
    # 아래 둘은 운영 함수 안에서만 일어나는 일을 확인한다.
    cl = RecordingClient()
    grade_with(cl, schema_reasoning_first(), None, item, "테스트 시장")
    want_prompt = V.build_grading_prompt(item["text"], item["source_excerpt"],
                                         item["topic"], "테스트 시장",
                                         "groundedness", item.get("region"))
    chk(cl.seen[-1]["prompt"] == want_prompt,
        "프롬프트가 운영 build_grading_prompt() 산출물과 동일 (프롬프트 조립을 거쳤다)")

    # 범위 밖 점수가 보정되는가 — clamp_score() 는 grade_fact() 안에서만 불린다
    cl9 = RecordingClient(score=9)
    score9, _ = grade_with(cl9, schema_reasoning_first(), None, item, "테스트 시장")
    chk(score9 == V.SCORE_MAX,
        f"범위 밖 점수 9 → {score9} 로 보정 (clamp_score 를 거쳤다)")

    print(f"\n  {ok}/{total} 통과")
    if ok != total:
        raise SystemExit("배선 확인 실패 — 실험을 진행하면 안 된다")


def cites_source(reasoning: str, excerpt: str) -> Optional[bool]:
    """근거 문장이 원문의 수치를 실제로 인용했는지.

    원문에 수치가 없으면 판정 대상이 아니므로 None을 준다 — "해당 없음"을
    "인용 안 함"으로 세면 조건 간 비교가 왜곡된다.
    """
    # 단위를 포함해 뽑는다. 맨숫자만 뽑으면 `2조 원`이 `2`가 되어 한 자리 필터에
    # 걸린다 — 정작 중요한 금액 표기를 놓친다. 표본 생성기와 같은 패턴을 쓴다.
    nums = [m.group(0).strip() for m in NUM_PAT.finditer(excerpt)]
    nums = [n for n in nums if len(norm(n)) >= 2 and any(c.isdigit() for c in n)]
    if not nums:
        return None
    ne = norm(reasoning)
    return any(norm(n) in ne for n in nums)


def run(conditions: list[str], repeat: int, limit: Optional[int], model: Optional[str]) -> dict:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    items = {it["id"]: it for it in sample["items"]}
    labels = {l["id"]: l for l in json.loads(LABELS.read_text(encoding="utf-8"))["labels"]}
    targets = [items[i] for i in labels if i in items]
    if limit:
        targets = targets[:limit]
    markets = {it["topic"]: target_market_for(it["topic"]) for it in targets}
    print(f"대상 {len(targets)}건 (사람 라벨 있는 것만) × 조건 {len(conditions)} × {repeat}회"
          f" = {len(targets)*len(conditions)*repeat}회 호출")
    for t, m in sorted(markets.items()):
        print(f"  목표시장: {t} → {m!r}")

    # 다른 eval 스크립트(rescore_relevance·router_goldenset·relevance_guard)가 모두
    # 이 함수를 쓴다. 처음에 `agents.llm.get_client` 를 썼는데 **그런 모듈이 없다** —
    # 확인하지 않고 이름을 지어냈다. 이미 있는 것을 찾아보는 편이 빨랐다.
    from eval.judge_self_test import client_for  # 지연 임포트 — dry-run에는 불필요
    client = client_for(model or V.VERIFICATION_MODEL)
    if model:
        V.VERIFICATION_MODEL = model
    print(f"  모델: {V.VERIFICATION_MODEL}\n")

    res: dict = {c: {} for c in conditions}
    for c in conditions:
        _, reorder, add4, add_r0 = CONDITIONS[c]
        sch = schema_reasoning_first() if reorder else schema_score_first()
        r0 = apply_rule0(add_r0)
        patch = r0 if add4 else (lambda p: r0(rubric_without_4(p)))
        print(f"[{c}] {CONDITIONS[c][0]}")
        for k, it in enumerate(targets, 1):
            runs = []
            for _ in range(repeat):
                try:
                    score, reasoning = grade_with(client, sch, patch, it,
                                                  markets[it["topic"]])
                except Exception as e:                       # noqa: BLE001
                    print(f"    ! {it['id']} 실패: {type(e).__name__}: {e}")
                    continue
                runs.append({"score": int(score), "reasoning": reasoning,
                             "cites": cites_source(reasoning, it["source_excerpt"]),
                             "rlen": len(reasoning)})
            res[c][it["id"]] = runs
            print(f"    {k:>3}/{len(targets)}  {[r['score'] for r in runs]}", end="\r")
        print(" " * 60, end="\r")
        sc = [r["score"] for v in res[c].values() for r in v]
        print(f"    분포 {dict(sorted(Counter(sc).items()))}  1·4점 "
              f"{sum(1 for s in sc if s in (1,4))}/{len(sc)}")
    return res


# ── 집계 ───────────────────────────────────────────────────────────────────
def report(res: dict, meta: dict) -> None:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    items = {it["id"]: it for it in sample["items"]}
    labels = {l["id"]: l for l in json.loads(LABELS.read_text(encoding="utf-8"))["labels"]}

    def human(fid: str) -> int:
        l = labels[fid]
        return int(l.get("human_groundedness") or combine(l["claim_scope"], l["numeric_scope"]))

    print("\n" + "=" * 78)
    print("2×2 요인 실험 결과 — 척도 붕괴의 원인")
    print("=" * 78)

    print("\n[1] ★ 주 지표 — 1점·4점 사용률")
    print(f"    {'조건':<34}{'4점':>6}{'1점':>6}{'1·4 합':>8}{'표준편차':>9}   분포")
    base = None
    for c, runs in res.items():
        sc = [r["score"] for v in runs.values() for r in v]
        if not sc:
            continue
        n4 = sum(1 for s in sc if s == 4); n1 = sum(1 for s in sc if s == 1)
        pct = (n1 + n4) / len(sc) * 100
        if c == "A":
            base = pct
        mark = ""
        if base is not None and c != "A":
            d = pct - base
            mark = f"  ({d:+.0f}%p)" if abs(d) >= 1 else "  (변화 없음)"
        print(f"    {c} {CONDITIONS[c][0]:<32}{n4:>4}{n1:>6}{pct:>7.0f}%{st.pstdev(sc):>9.2f}"
              f"   {dict(sorted(Counter(sc).items()))}{mark}")
    # 라벨 수를 문자열에 박아두면 라벨을 늘렸을 때 조용히 거짓이 된다.
    # 실제로 30 → 50 으로 늘린 뒤 출력이 "사람 라벨(30건)"으로 남아 있었다.
    print(f"\n    사람 라벨({len(labels)}건)의 1·4점 비율: "
          f"{sum(1 for i in labels if human(i) in (1,4))/len(labels)*100:.0f}%"
          f"  분포 {dict(sorted(Counter(human(i) for i in labels).items()))}")

    print("\n[2] 사람 라벨 대비 정렬도 (반복은 최빈값으로 대표)")
    print(f"    {'조건':<34}{'κ':>7}{'일치율':>8}{'정밀도':>8}{'재현율':>8}")
    for c, runs in res.items():
        pairs = [(status_of(human(i)),
                  status_of(Counter(r["score"] for r in v).most_common(1)[0][0]))
                 for i, v in runs.items() if v]
        if len(pairs) < 2:
            continue
        H = [a for a, _ in pairs]; M = [b for _, b in pairs]
        k = cohen_kappa(H, M, STATUSES)
        ag = sum(1 for a, b in pairs if a == b) / len(pairs) * 100
        p, r, *_ = prf(H, M, "기각")
        print(f"    {c} {CONDITIONS[c][0]:<32}{k:>7.3f}{ag:>7.0f}%{p*100:>7.0f}%{r*100:>7.0f}%"
              f"  ({landis_koch(k)})")
    print("    기준: 관련성 축 κ=0.551 · 근거지지도 사전 측정 κ=0.217")

    print("\n[3] 근거 품질 — reasoning 이 원문 수치를 인용하는가")
    print(f"    {'조건':<34}{'인용률':>8}{'평균 길이':>10}")
    for c, runs in res.items():
        rs = [r for v in runs.values() for r in v]
        cit = [r["cites"] for r in rs if r["cites"] is not None]
        if not rs:
            continue
        print(f"    {c} {CONDITIONS[c][0]:<32}"
              f"{(sum(cit)/len(cit)*100 if cit else float('nan')):>7.0f}%"
              f"{st.mean(r['rlen'] for r in rs):>10.0f}자")

    print("\n[4] 판정이 뒤집힌 항목 수 (기준선 A 대비)")
    if "A" in res:
        for c, runs in res.items():
            if c == "A":
                continue
            flip = 0
            for i, v in runs.items():
                a = res["A"].get(i)
                if not a or not v:
                    continue
                sa = status_of(Counter(r["score"] for r in a).most_common(1)[0][0])
                sb = status_of(Counter(r["score"] for r in v).most_common(1)[0][0])
                flip += sa != sb
            print(f"    A → {c}: {flip}건")

    print("\n[5] 해석 지침")
    for line in (
        "C·D에서만 4점이 늘면 → 원인은 루브릭. 프롬프트 한 줄로 고친다.",
        "B·D에서만 늘면 → 원인은 스키마 순서. Router와 같은 처방.",
        "둘 다 늘면 → 독립적으로 더한다. 교차항(D − B − C + A)을 보면 상호작용을 알 수 있다.",
        "아무것도 안 변하면 → 두 가설 모두 기각. 다른 원인을 찾아야 한다.",
    ):
        print(f"    - {line}")

    print("\n[6] 한계")
    for line in (
        f"표본 {len(labels)}건 · 반복 {meta.get('repeat')}회. 실행 간 변동은 이 한 번으로 알 수 없다"
        " (Router 골든셋에서 같은 설정 두 실행이 99.5%와 99.0%였다).",
        "4점 정의 문구는 내가 썼다. 효과가 없어도 H1이 기각되는 것은 아니고 '이 문구로는 안 된다'까지다.",
        "채점자가 한 명이고 관련성 축과 달리 3자 라벨이 아니다.",
        "target_market 을 리서치 질문에서 복원해 넣었다 — 네 조건에 같은 값이 들어가므로"
        " 조건 간 비교는 성립하지만 절대값은 원 실행과 다를 수 있다.",
    ):
        print(f"    - {line}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", default=DEFAULT_CONDITIONS)
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model")
    ap.add_argument("--grade4", choices=["운영", "v1", "v2"], default="운영",
                    help="4점 정의 문구. 기본은 운영 루브릭 그대로. v1·v2는 과거 실험 문구")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    global GRADE_4_LINE
    if a.grade4 != "운영":
        GRADE_4_LINE = GRADE_4_VARIANTS[a.grade4]

    if a.dry_run:
        print(f"4점 정의 문구: {a.grade4}\n")
        wiring_check()
        print("\n--- 현 운영 루브릭 (조건 C·D) ---")
        p = V.PERSPECTIVE_PROMPTS["groundedness"]
        print(p[p.find(ANCHOR_5):][:520])
        print("\n--- 4점을 지운 루브릭 (조건 A·B) ---")
        q = rubric_without_4(p)
        print(q[q.find(ANCHOR_5):][:360])
        return

    if a.report_only:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        report(d["results"], d)
        return

    wiring_check()
    conds = [c.strip().upper() for c in a.conditions.split(",")]
    for c in conds:
        if c not in CONDITIONS:
            raise SystemExit(f"모르는 조건: {c} (A/B/C/D)")
    print()
    res = run(conds, a.repeat, a.limit, a.model)

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {"created_at": created, "model": V.VERIFICATION_MODEL,
               "repeat": a.repeat, "conditions": conds,
               "grade_4_variant": a.grade4, "grade_4_line": GRADE_4_LINE, "results": res}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    OUT.write_text(body, encoding="utf-8")
    # 실행마다 별도 보관 — 골든셋에서 두 번째 실행이 첫 번째를 덮는 일을 겪었다.
    stamp = created.replace(":", "").replace("-", "").replace("+0000", "Z")
    arch = OUT_DIR / f"schema_order_{stamp}_{V.VERIFICATION_MODEL}_r{a.repeat}.json"
    arch.write_text(body, encoding="utf-8")
    print(f"\n저장: {OUT}\n보관: {arch}")
    report(res, payload)


if __name__ == "__main__":
    main()
