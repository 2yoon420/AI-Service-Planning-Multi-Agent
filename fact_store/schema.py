"""
Fact Store 스키마 정의

시장조사 에이전트가 수집한 정보를 구조화된 Fact 객체로 저장하기 위한 데이터 모델.
PESTEL·경쟁사비교·검증출처 에이전트가 이 Fact들을 근거로 판단하며,
출처 추적성(traceability)을 확보하는 것이 이 스키마의 핵심 목적이다.

참고: TTAK.KO-10.1595(메타데이터), TTAK.KO-10.1601(저작권정보 구성 지침) 기반
"""

from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class SourceTier(str, Enum):
    """자료 출처 신뢰도 계층 (파이프라인 문서 3-1절 기준)"""
    PRIMARY = "1차"      # 인터뷰, 설문, 현장조사
    SECONDARY = "2차"    # 통계청, KOTRA, 산업연구원, 상장사 IR 등
    TERTIARY = "3차"     # 뉴스, 블로그, SNS 트렌드


class PestelAxis(str, Enum):
    """PESTEL 6축"""
    POLITICAL = "Political"
    ECONOMIC = "Economic"
    SOCIAL = "Social"
    TECHNOLOGICAL = "Technological"
    ENVIRONMENTAL = "Environmental"
    LEGAL = "Legal"


class ImpactDirection(str, Enum):
    OPPORTUNITY = "기회"
    THREAT = "위협"
    NEUTRAL = "중립"


class Urgency(str, Enum):
    IMMEDIATE = "즉시"
    SHORT_TERM = "단기"
    LONG_TERM = "장기"


class VerificationStatus(str, Enum):
    """검증·출처 에이전트의 최종 판정 (CRAG의 Correct/Incorrect/Ambiguous 3단계를
    fact 단위로 재해석 — 파이프라인 문서 13절 참고)"""
    ACCEPTED = "채택"      # 관련성·근거지지도 두 관점 모두 통과
    AMBIGUOUS = "애매"     # 두 관점이 엇갈리거나 재시도 후에도 판단이 갈림 — 저장은 하되 요약에서 제외
    REJECTED = "기각"      # 두 관점 모두 실패 (명백한 노이즈 또는 조작 의심)


class Fact(BaseModel):
    """시장조사 에이전트가 수집하는 최소 단위 사실 정보"""

    id: str = Field(..., description="Fact 고유 ID (예: fact_0001)")
    text: str = Field(..., description="사실 하나당 한 줄로 압축된 내용")
    source_url: str = Field(..., description="출처 URL")
    source_tier: SourceTier
    published_date: Optional[date] = Field(None, description="원자료 발행일")
    retrieved_date: date = Field(..., description="수집(조회)일 - 출처 메타데이터 필수 항목")
    region: Optional[str] = Field(None, description="관련 지역 (예: 국내, 북미, 유럽)")
    topic_relevance: Optional[str] = Field(None, description="이 fact가 어떤 리서치 질문에 답하는지")
    topic: Optional[str] = Field(
        None,
        description=(
            "이 fact가 속한 연구대상(topic) 원문. topic_relevance(검색 질문 문구, 매번 재구성됨)와 "
            "달리 실행 시 입력된 topic 값을 그대로 저장해, 이후 조회 시 정확히 일치시키기 위한 필드. "
            "이 필드가 없는(None) 레거시 fact는 topic_relevance 부분 문자열 매칭으로 폴백한다."
        ),
    )

    # PESTEL 에이전트가 채우는 필드 (선택)
    pestel_axis: Optional[list[PestelAxis]] = Field(default=None, description="중복 태깅 허용")
    impact_direction: Optional[ImpactDirection] = None
    urgency: Optional[Urgency] = None

    # 검증·출처 에이전트가 채우는 필드
    # verification_status가 최종 판정(3단계)이고, citation_verified/needs_source_check는
    # 그 판정을 하위 호환 가능한 bool 필드로도 노출한 것 — 기존에 이 필드들만 보고 필터링하는
    # 코드가 있어도 깨지지 않도록 유지한다.
    citation_verified: bool = Field(default=False, description="LLM-as-judge 사실검증 통과 여부 (verification_status==채택일 때만 True)")
    verification_score: Optional[int] = Field(
        None, ge=1, le=5,
        description="관련성/근거지지도 두 관점 채점의 보수적 결합값(min). 3점 미만=불일치로 간주.",
    )
    needs_source_check: bool = Field(default=False, description="[출처확인필요] 태그 부착 여부 (애매/기각 판정 시 True)")
    verification_status: Optional[VerificationStatus] = Field(
        None,
        description=(
            "검증·출처 에이전트의 최종 판정(채택/애매/기각). None이면 아직 검증을 거치지 않은 "
            "fact(검증 에이전트 도입 이전 레거시 fact 포함) — 이 경우 하위 호환을 위해 "
            "citation_verified=False/needs_source_check=False 상태로 두되, 다운스트림에서는 "
            "'검증 미실시'와 '기각'을 구분해서 다뤄야 한다."
        ),
    )
    verification_reasoning: Optional[str] = Field(
        None, description="검증 에이전트가 이 판정을 내린 근거 요약 (사람이 재확인할 때 참고용)"
    )


class CompetitorType(str, Enum):
    DIRECT = "직접 경쟁자"
    INDIRECT = "간접 경쟁자(대체재)"
    POTENTIAL = "잠재 진입자"


class Competitor(BaseModel):
    """경쟁사비교 에이전트 산출물"""

    name: str
    type: CompetitorType
    price: Optional[str] = None
    key_features: list[str] = Field(default_factory=list)
    target_customer: Optional[str] = None
    channel: Optional[str] = None
    funding_or_revenue: Optional[str] = None
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list, description="근거가 된 Fact ID 목록")


class MarketSizing(BaseModel):
    """시장조사 에이전트의 TAM/SAM/SOM 계산 결과"""

    tam_topdown: Optional[float] = None
    sam_topdown: Optional[float] = None
    som_topdown: Optional[float] = None

    som_bottomup: Optional[float] = None
    sam_bottomup: Optional[float] = None
    tam_bottomup: Optional[float] = None

    unit: str = Field(default="KRW", description="통화 단위")
    assumptions: list[str] = Field(default_factory=list, description="비중·전환율 등 가정치와 근거")
    discrepancy_flag: bool = Field(default=False, description="Top-down/Bottom-up 10배 이상 차이 여부")
    source_fact_ids: list[str] = Field(default_factory=list)
