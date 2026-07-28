"""judge self-test 케이스 — 정답을 **우리가 만들어서** 넣는다.

## 왜 이런 방식인가

2026-07-28 사후 집계(`심사대응_환각근거` 2절)에는 순환 논리가 있었다. "검증기가 조작을
잡았다"는 근거가 **검증기 자신의 채점**이었기 때문이다. 실제로 조작이었는지 확인하려면
원문을 봐야 하는데 원문이 저장돼 있지 않다.

여기서는 원문과 fact를 **둘 다 우리가 지어낸다.** 정답을 아는 상태로 넣으므로 순환이 없다.

## 케이스 설계 원칙

- **극단만 넣는다.** 애매한 경계는 일부러 피했다. 이 테스트의 목적은 "명백한 것도 못
  가리는가"를 보는 것이고, 극단에서 실패하면 그 아래 미세 조정은 의미가 없다.
- **표현이 다른 요약을 채택 쪽에 넣는다.** 파이프라인 13-8절에서 "정상 fact가 오기각"
  되는 사고가 있었다. 그 회귀를 여기서 잡는다.
- 두 관점(relevance / groundedness)을 **따로** 시험한다. 실제 파이프라인이 그렇게 부른다.

## 정답 기준

`expect`는 "이 점수 이상/이하여야 한다"는 경계다. 정확한 점수를 요구하지 않는다 —
1~5 척도에서 4와 5의 차이는 채점자마다 갈릴 수 있지만, 5와 1의 차이는 갈리면 안 된다.
"""

# 원문 지문 — 케이스들이 공유한다
SRC_PKG = """EU 집행위원회는 포장재 및 포장폐기물 규정(PPWR) 개정안을 통해 2030년까지
역내에 유통되는 모든 포장재를 재활용 가능한 형태로 전환하도록 의무화한다고 밝혔다.
개정안은 재사용 가능 포장재 비율을 단계적으로 높이는 내용을 담고 있으며, 일부 일회용
플라스틱 포장은 사용이 제한된다. 업계는 전환 비용 부담을 이유로 유예 기간 연장을
요구하고 있다."""

SRC_WEAR = """스마트워치 제조사 가민은 최근 실적 발표에서 웨어러블 부문 매출이 전년
대비 증가했다고 밝혔다. 회사는 피트니스 추적 기능과 배터리 수명을 주요 경쟁력으로
꼽았으며, 북미 시장에서 판매 채널을 확대하고 있다고 설명했다."""

TOPIC_PKG, MARKET_PKG = "친환경 포장재", "유럽 B2B 유통 시장"
TOPIC_WEAR, MARKET_WEAR = "웨어러블 헬스케어 기기", "북미 시니어 건강관리 시장"

# ─────────────────────────────────────────────────────────────
# groundedness — "원문에 근거하는가"
# ─────────────────────────────────────────────────────────────
GROUNDEDNESS_CASES = [
    # ── 명백히 근거 있음 (>=4점이어야) ──
    dict(id="G-OK-1", expect_min=4, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="EU는 2030년까지 역내 유통 포장재를 모두 재활용 가능한 형태로 전환하도록 의무화한다.",
         note="원문 첫 문장의 거의 그대로"),
    dict(id="G-OK-2", expect_min=4, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="일부 일회용 플라스틱 포장은 사용이 제한된다.",
         note="원문에 명시"),
    # 표현을 크게 바꾼 요약 — 13-8절 오기각 회귀 방지
    dict(id="G-OK-3", expect_min=4, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="포장재 업계는 비용 문제를 들어 규제 시행을 늦춰 달라고 요청하는 중이다.",
         note="원문 '전환 비용 부담을 이유로 유예 기간 연장을 요구' 를 완전히 다른 표현으로 재구성"),
    dict(id="G-OK-4", expect_min=4, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="재사용 가능 포장재의 비중을 점진적으로 확대하는 방안이 포함되어 있다.",
         note="'단계적으로 높이는' → '점진적으로 확대' 동의 표현"),
    dict(id="G-OK-5", expect_min=4, src=SRC_WEAR, topic=TOPIC_WEAR, market=MARKET_WEAR,
         fact="가민은 배터리 수명을 자사 웨어러블의 경쟁력으로 제시했다.",
         note="원문에 명시"),

    # ── 명백히 근거 없음 (<=2점이어야) ──
    dict(id="G-NG-1", expect_max=2, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="EU는 포장재 기업에 연 매출의 3%를 환경부담금으로 부과한다.",
         note="원문에 부담금·3% 라는 말 자체가 없음 — 구체적 수치 조작"),
    dict(id="G-NG-2", expect_max=2, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="유럽 친환경 포장재 시장은 2024년 기준 약 420억 유로 규모다.",
         note="원문에 시장 규모 언급 없음 — 가장 흔한 환각 유형"),
    dict(id="G-NG-3", expect_max=2, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="2029년 1월 1일까지 모든 회원국이 포장재 보증금 반환 시스템을 구축해야 한다.",
         note="2026-07-28 실운영에서 실제로 나온 환각(관련성 5점/근거 1점)을 재현"),
    dict(id="G-NG-4", expect_max=2, src=SRC_WEAR, topic=TOPIC_WEAR, market=MARKET_WEAR,
         fact="가민의 웨어러블 부문 매출은 전년 대비 17.4% 증가했다.",
         note="원문은 '증가했다'만 말함 — 없는 수치를 붙임"),
    dict(id="G-NG-5", expect_max=2, src=SRC_WEAR, topic=TOPIC_WEAR, market=MARKET_WEAR,
         fact="가민은 독일과 프랑스의 수면 연구소와 협력해 AI 수면 분석 기능을 개발했다.",
         note="파이프라인 13-9절의 실제 환각 유형 재현 — 실재 지명·기관으로 그럴듯하게"),
]

# ─────────────────────────────────────────────────────────────
# relevance — "연구대상·목표시장과 관련 있는가"
# ─────────────────────────────────────────────────────────────
RELEVANCE_CASES = [
    # ── 명백히 관련 있음 (>=4점이어야) ──
    dict(id="R-OK-1", expect_min=4, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="EU는 2030년까지 역내 유통 포장재를 모두 재활용 가능한 형태로 전환하도록 의무화한다.",
         note="연구대상·목표시장에 정확히 부합"),
    dict(id="R-OK-2", expect_min=4, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="유럽 B2B 유통업체들은 재사용 포장재 도입에 따른 물류 비용 증가를 우려한다.",
         note="목표시장 그 자체"),
    dict(id="R-OK-3", expect_min=4, src=SRC_WEAR, topic=TOPIC_WEAR, market=MARKET_WEAR,
         fact="북미 시니어 소비자는 웨어러블 기기의 낙상 감지 기능을 중요하게 평가한다.",
         note="연구대상·목표시장 모두 부합"),
    dict(id="R-OK-4", expect_min=4, src=SRC_WEAR, topic=TOPIC_WEAR, market=MARKET_WEAR,
         fact="미국 고령층의 스마트워치 보급률이 최근 상승하고 있다.",
         note="'북미'와 '미국', '시니어'와 '고령층' — 동의 관계를 인식해야 함"),

    dict(id="R-OK-5", expect_min=4, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="일회용 플라스틱 포장 규제는 유럽 유통업체의 포장재 조달 방식에 영향을 준다.",
         note="규제 → 유통업체 영향, 목표시장에 직결"),

    # ── 명백히 무관 (<=2점이어야) ──
    dict(id="R-NG-1", expect_max=2, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="일본 자동차 업계는 전기차 배터리 공급망 다변화를 추진하고 있다.",
         note="주제·지역 모두 다름"),
    dict(id="R-NG-2", expect_max=2, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="이 페이지의 쿠키 설정을 변경하려면 하단 링크를 클릭하십시오.",
         note="웹 네비게이션 텍스트 — 정규식 추출의 부작용으로 실제로 섞여 들어옴"),
    dict(id="R-NG-3", expect_max=2, src=SRC_WEAR, topic=TOPIC_WEAR, market=MARKET_WEAR,
         fact="브라질 농업용 드론 시장이 연평균 12% 성장할 전망이다.",
         note="주제·지역 모두 다름"),
    dict(id="R-NG-4", expect_max=2, src=SRC_WEAR, topic=TOPIC_WEAR, market=MARKET_WEAR,
         fact="유럽연합은 의료기기 규정(MDR)을 2021년부터 시행했다.",
         note="인접해 보이지만 목표시장(북미)이 아님 — 지역 불일치 케이스"),
    # 2026-07-28 교체. 옛 케이스는 "제공된 본문에는 해당 정보가 포함되어 있지 않습니다."였다.
    # 그 문장은 market_research._is_no_info_statement()의 NO_INFO_PATTERNS에 걸려 추출
    # 직후 제거되므로, 실제 운영에서는 검증기까지 도달하지 못한다. 즉 검증기의 능력을 재는
    # 케이스가 아니었다(세 모델 전부 판정이 흔들렸으나 그 흔들림은 무해했다).
    # 정규식으로는 못 잡는 메타발언으로 바꿔야 검증기를 실제로 시험한다 —
    # 면책 조항은 시장조사 보고서 페이지에 거의 항상 붙어 있어 현실성도 높다.
    # (옛 케이스는 버리지 않고 tests/test_verification_grading.py의 정규식 회귀 테스트로 옮겼다.)
    dict(id="R-NG-5", expect_max=2, src=SRC_PKG, topic=TOPIC_PKG, market=MARKET_PKG,
         fact="본 자료는 참고용으로 작성되었으며 투자 판단의 근거로 사용될 수 없다.",
         note="면책 조항 — 문서에 대한 메타발언이지 시장 내용이 아님. 정규식 필터를 통과함"),
]

ALL_CASES = [("groundedness", c) for c in GROUNDEDNESS_CASES] + \
            [("relevance", c) for c in RELEVANCE_CASES]
