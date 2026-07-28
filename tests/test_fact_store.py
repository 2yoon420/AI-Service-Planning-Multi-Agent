"""(4) Fact Store 회귀 테스트.

2026-07-28에 고친 '프로젝트 간 근거 유실' 버그를 여기 박제한다. 인접 팀
(team07-sequel)의 관례를 따라 각 테스트에 '언제 발견한 무슨 버그인지'를 남긴다 —
테스트가 실행 가능한 개발 기록이 되도록."""

from datetime import date

from fact_store.schema import Fact, SourceTier

T1 = "북미 웨어러블 시장 규모는 2024년 84억 4천만 달러이다."
T2 = "북미 웨어러블 시장 규모는 2024년 84억 4천만 달러입니다."   # 표현만 다름
A = "웨어러블 헬스케어 기기"
B = "스마트 반려동물 건강관리 기기"


def _fact(fid, text, topic, rel="시장 규모"):
    return Fact(
        id=fid,
        text=text,
        source_url="https://example.com/a",
        source_tier=SourceTier.SECONDARY,
        retrieved_date=date.today(),
        topic_relevance=rel,
        topic=topic,
    )


def test_다른_프로젝트의_같은_문장이_근거를_잃지_않는다(fact_db):
    """2026-07-28 발견 — find_similar_fact()가 list_facts()를 필터 없이 호출해
    전체 프로젝트를 훑었다. 서로 다른 주제가 우연히 같은 문장을 만나면 나중
    프로젝트가 '중복'으로 판정돼 저장을 건너뛰는데, 반환된 fact는 앞 프로젝트의
    topic을 달고 있어 조회도 안 됐다. 저장도 조회도 안 되니 기획서에서 근거가
    통째로 사라졌다. 재현 당시 프로젝트B로 조회한 fact 수 = 0건."""
    fact_db.save_fact_if_new(_fact("f1", T1, A))
    _, is_new = fact_db.save_fact_if_new(_fact("f2", T2, B))

    assert is_new is True
    assert len(fact_db.list_facts(topic=B)) == 1
    assert len(fact_db.list_facts(topic=A)) == 1


def test_같은_프로젝트_안에서는_중복이_제거된다(fact_db):
    """위 수정이 원래 기능(중복 제거)을 죽이지 않았는지. 이쪽이 깨지면 같은
    fact가 여러 번 저장돼 기획서에 같은 문장이 반복된다."""
    fact_db.save_fact_if_new(_fact("f1", T1, A))
    _, is_new = fact_db.save_fact_if_new(_fact("f2", T2, A))

    assert is_new is False
    assert len(fact_db.list_facts(topic=A)) == 1


def test_레거시_fact의_topic이_점진적으로_백필된다(fact_db):
    """topic 필드 도입(2026-07-24) 이전 저장분은 topic이 비어 있다. topic으로
    엄격히 거르면 이 백필이 영영 동작하지 않으므로, 후보에 레거시(topic=None)를
    함께 넣어야 한다. topic_relevance에 주제어가 없는 경우까지 커버한다."""
    fact_db.save_fact(_fact("legacy", T1, None, rel="관련 없는 질문 문구"))

    got, is_new = fact_db.save_fact_if_new(_fact("f2", T2, A))

    assert is_new is False
    assert got.id == "legacy"
    assert fact_db.get_fact("legacy").topic == A


def test_topic을_안_넘기면_종전대로_전체를_훑는다(fact_db):
    """호출부 하위 호환. topic 인자 없이 부르는 코드가 나중에 생겨도
    예전 동작 그대로여야 한다."""
    fact_db.save_fact(_fact("f1", T1, A))

    hit = fact_db.find_similar_fact(T2)
    assert hit is not None and hit.id == "f1"


def test_내용이_다르면_같은_프로젝트라도_각자_저장된다(fact_db):
    fact_db.save_fact_if_new(_fact("f1", T1, A))
    _, is_new = fact_db.save_fact_if_new(
        _fact("f2", "반려동물 웨어러블은 완전히 다른 시장이다.", A)
    )

    assert is_new is True
    assert len(fact_db.list_facts(topic=A)) == 2
