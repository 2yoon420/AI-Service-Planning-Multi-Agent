"""원문 조각 저장 회귀 테스트 (2026-07-29 결함 H — 원문 미저장).

## 무엇이 문제였는가

`Fact` 스키마에 원문이 없었다. 그래서 세 가지가 원리적으로 막혀 있었다.

  · **근거지지도 재채점** — 모델이나 루브릭을 바꾼 뒤 같은 표본을 다시 채점할 수 없다.
  · **근거지지도 사람 라벨** — 사람이 판단할 근거가 없다. 검증 총정리 한계 ①이며,
    3차 외부 검토가 4순위로 꼽은 항목이다("스키마 변경 선행 필요").
  · **결함 수정 전후 같은 표본 비교** — 한계 ⑨. κ=0.153이 수정 전 값인데도
    재측정할 수 없었던 이유다.

즉 이것은 기능 결함이 아니라 **측정 능력의 결함**이었다. 눈에 보이는 오동작이 없어서
결함 A~G와 달리 검증 활동으로도 드러나지 않았고, "무엇을 못 재는가"를 물었을 때만
드러났다.

## 무엇을 저장하는가 — 그리고 왜 전체가 아닌가

`source_content[:SOURCE_EXCERPT_CHARS]` — **근거지지도 채점기에 제시된 것과 동일한
문자열**이다. 원문 전체가 아니다.

전체를 저장하면 나중에 사람이 이 excerpt로 라벨할 때 **심판보다 많은 정보를 보게 된다.**
그러면 "사람이 맞고 기계가 틀렸다"가 판단력 차이 때문인지 정보량 차이 때문인지
구분되지 않는다. 정렬도 실험에서 검증기 점수를 라벨러에게 숨겼던 것과 같은 종류의
통제다.

그래서 절단 길이는 **프롬프트와 저장이 같은 상수를 써야 한다.** 두 값이 어긋나면
저장된 것이 심판이 본 것과 달라진다. 이 파일이 그 일치를 지킨다.
"""

import inspect

import pytest

from agents.verification import (
    SOURCE_EXCERPT_CHARS,
    build_grading_prompt,
    make_source_excerpt,
)
from fact_store.schema import Fact, SourceTier, VerificationStatus


# ------------------------------------------------------------------ ① 계약
def test_스키마에_source_excerpt_필드가_있다():
    assert "source_excerpt" in Fact.model_fields


def test_원문이_없으면_None을_저장한다():
    assert make_source_excerpt("") is None
    assert make_source_excerpt(None) is None  # type: ignore[arg-type]


def test_짧은_원문은_그대로_보존된다():
    text = "유럽 친환경 포장재 시장은 2024년 116억 USD 규모였다."
    assert make_source_excerpt(text) == text


def test_긴_원문은_상한까지_자른다():
    excerpt = make_source_excerpt("가" * (SOURCE_EXCERPT_CHARS + 5000))
    assert excerpt is not None
    assert len(excerpt) == SOURCE_EXCERPT_CHARS


def test_절단_길이가_프롬프트와_저장에서_같다():
    """이 시험이 이 파일의 핵심이다.

    프롬프트가 3000자를 넣는데 저장이 2000자만 하면, 저장된 excerpt로 라벨한 사람은
    심판보다 적게 보고 판단한 것이 된다. 반대면 더 많이 본 것이 된다. 어느 쪽이든
    정렬도가 왜곡되고, 그 왜곡은 숫자만 봐서는 드러나지 않는다.
    """
    marker = "★여기부터는_심판에게_보이지_않아야_한다★"
    본문 = "가" * SOURCE_EXCERPT_CHARS + marker

    prompt = build_grading_prompt(
        "어떤 fact", 본문, "친환경 포장재", "유럽 B2B 유통 시장", "groundedness",
    )
    excerpt = make_source_excerpt(본문)

    assert marker not in prompt, "상한을 넘은 부분이 프롬프트에 들어갔다"
    assert excerpt is not None and marker not in excerpt, "상한을 넘은 부분이 저장됐다"
    assert excerpt in prompt, (
        "저장된 excerpt가 프롬프트에 그대로 들어 있지 않다 — "
        "심판이 본 것과 저장된 것이 다르다"
    )


def test_옛_데이터에도_역직렬화된다():
    """source_excerpt가 없던 시절의 data_json이 그대로 읽혀야 한다.

    운영 DB에 fact 489건이 이 필드 없이 저장돼 있다. 필드 추가가 그것들을 읽지 못하게
    만들면 배포와 동시에 서비스가 죽는다.
    """
    옛_json = Fact(
        id="legacy-1", text="옛 fact", source_url="https://example.com",
        source_tier=SourceTier.SECONDARY, topic="친환경 포장재",
        retrieved_date="2026-07-20",
    ).model_dump_json()
    # 필드를 물리적으로 제거해 옛 저장 형태를 만든다
    import json
    d = json.loads(옛_json)
    d.pop("source_excerpt", None)
    restored = Fact.model_validate_json(json.dumps(d, ensure_ascii=False))
    assert restored.source_excerpt is None
    assert restored.text == "옛 fact"


# ------------------------------------------------------------------ ② 배선
def _fact(text: str = "유럽 포장재 시장은 2024년 116억 USD였다") -> Fact:
    return Fact(
        id=f"f-{abs(hash(text)) % 10**8}", text=text,
        source_url="https://example.com/a", source_tier=SourceTier.SECONDARY,
        topic="친환경 포장재", retrieved_date="2026-07-29", region="유럽",
    )


@pytest.mark.parametrize("rel,grd", [(5, 5), (5, 3), (1, 1)])
def test_단건_판정_경로가_실제로_excerpt를_채운다(monkeypatch, rel, grd):
    """계약 테스트만으로는 부족하다.

    make_source_excerpt()가 완벽해도 verify_fact()가 그것을 호출하지 않으면 운영에서는
    아무것도 저장되지 않는다. 이 프로젝트는 정확히 그 실수를 네 번 겪었다
    (결함 F·G, 그 진단, 판정 경계). 그래서 실제 함수를 호출해 결과를 본다.
    """
    import agents.verification as M

    본문 = "유럽 포장재 시장 보고서 본문. " * 200
    monkeypatch.setattr(M, "prescreen_fact", lambda t, s: None)
    monkeypatch.setattr(
        M, "grade_fact",
        lambda c, t, s, tp, tm, persp, region=None: (
            (rel if persp == "relevance" else grd), "채점"),
    )

    out = M.verify_fact(client=None, fact=_fact(), source_content=본문,
                        topic="친환경 포장재", target_market="유럽 B2B 유통 시장")

    assert out.source_excerpt is not None, "판정 경로가 excerpt를 채우지 않았다"
    assert out.source_excerpt == 본문[:SOURCE_EXCERPT_CHARS]


def test_사전기각된_fact도_excerpt를_남긴다(monkeypatch):
    """왜 모지바케로 판정됐는지 나중에 확인해야 한다.

    사전기각(결함 F)은 LLM을 부르지 않고 코드로 즉시 기각하는 경로다. 여기서 원문을
    버리면 "정말 깨진 문서였는가"를 사후에 검증할 수 없다. 오탐이 있어도 알 수 없다.
    """
    import agents.verification as M

    본문 = "í í¸ë¼Pak ìˆ˜ì§' " * 300   # 모지바케
    monkeypatch.setattr(M, "prescreen_fact", lambda t, s: "본문이 깨져 있습니다")

    out = M.verify_fact(client=None, fact=_fact(), source_content=본문,
                        topic="친환경 포장재", target_market="유럽 B2B 유통 시장")

    assert out.verification_status is VerificationStatus.REJECTED
    assert out.source_excerpt is not None, (
        "사전기각분의 원문이 버려졌다 — 오탐을 사후 검증할 수 없다"
    )
    assert out.source_excerpt == 본문[:SOURCE_EXCERPT_CHARS]


def test_배치_경로가_실제로_excerpt를_저장한다(monkeypatch):
    """save_fact()에 도달한 객체를 붙잡아 확인한다.

    배치 경로는 단건 경로와 코드가 별개다. 한쪽만 고치면 어느 경로를 탔는지에 따라
    excerpt가 있기도 없기도 하는데, 그 불일치는 로그를 봐도 드러나지 않는다.
    """
    import agents.verification as M

    본문 = {"a": "A 도메인 본문. " * 400, "b": "B 도메인 본문. " * 50}
    saved: list[Fact] = []
    monkeypatch.setattr(M, "prescreen_fact", lambda t, s: None)
    monkeypatch.setattr(
        M, "grade_fact",
        lambda c, t, s, tp, tm, persp, region=None: (5 if persp == "relevance" else 4, "채점"),
    )
    monkeypatch.setattr(M, "save_fact", lambda f: saved.append(f))

    M.verify_facts_batch(
        client=None,
        facts_with_content=[(_fact("a"), 본문["a"]), (_fact("b"), 본문["b"])],
        topic="친환경 포장재", target_market="유럽 B2B 유통 시장",
    )

    assert len(saved) == 2
    got = {f.text: f.source_excerpt for f in saved}
    assert got["a"] == 본문["a"][:SOURCE_EXCERPT_CHARS], "긴 본문이 잘려 저장돼야 한다"
    assert got["b"] == 본문["b"], "짧은 본문은 그대로 저장돼야 한다"
    assert all(v for v in got.values()), "저장 경로가 excerpt를 채우지 않았다"


def test_배치_사전기각분도_excerpt를_저장한다(monkeypatch):
    """배치 경로의 사전기각 리스트가 원문을 들고 다니는지 확인한다.

    이 튜플은 원래 (fact, reasoning) 두 칸이었다. 저장 루프에 도달했을 때
    source_content가 이미 스코프 밖이어서, 세 칸으로 늘리지 않으면 조용히 None이 된다.
    """
    import agents.verification as M

    본문 = "깨진 본문 " * 500
    saved: list[Fact] = []
    monkeypatch.setattr(M, "prescreen_fact", lambda t, s: "본문이 깨져 있습니다")
    monkeypatch.setattr(M, "save_fact", lambda f: saved.append(f))

    counts = M.verify_facts_batch(
        client=None, facts_with_content=[(_fact("x"), 본문)],
        topic="친환경 포장재", target_market="유럽 B2B 유통 시장",
    )

    assert counts["rejected"] == 1
    assert saved[0].source_excerpt == 본문[:SOURCE_EXCERPT_CHARS], (
        "배치 사전기각분의 excerpt가 유실됐다"
    )


def test_절단_길이가_한_곳에서만_정의된다():
    """3000이 소스에 흩어져 있으면 다시 어긋난다."""
    src = inspect.getsource(__import__("agents.verification", fromlist=["x"]))
    # 상수 정의 한 줄만 리터럴 3000을 갖는다
    정의줄 = [l for l in src.split("\n") if "SOURCE_EXCERPT_CHARS = " in l]
    assert len(정의줄) == 1, "상수 정의가 여러 곳에 있다"
    본문_절단 = [l for l in src.split("\n")
              if "source_content[:" in l and "SOURCE_EXCERPT_CHARS" not in l]
    assert not 본문_절단, f"상수를 쓰지 않고 직접 자르는 곳이 있다: {본문_절단}"
