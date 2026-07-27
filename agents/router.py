"""
Router 에이전트 (신설, 2026-07-24)

Orchestrator를 "고정 파이프라인"에서 "LLM이 실시간으로 판단하는 감독자"로 확장하는
작업의 첫 조각. 이 파일은 우선 capability_qa(서비스 기능 Q&A) 하나만 구현한다 — 나머지
(완전성 체크 -> 재실행 분기, run_targeted_research 트리거 등 구조화된 단일 판단)는
Task #4(orchestrator/graph.py 확장)에서 이어서 만든다. router_orchestrator_설계안.md
3-3·3-6절 참고.

capability_qa는 fact_store나 TTA/NCS RAG와 무관한 메타 질문("이 서비스 뭘 할 수
있어요?")을 처리한다 — 파이프라인(시장조사/PESTEL/경쟁사) 노드를 전혀 건드리지 않고
capability_corpus.md 코퍼스에서만 답을 찾아온다는 게 핵심이다.
"""

import json
import os

from openai import OpenAI

from rag.query import search_capability_corpus

LIGHT_MODEL = os.getenv("LIGHT_MODEL", "solar-mini")
HEAVY_MODEL = os.getenv("HEAVY_MODEL", "solar-pro2")

# await_review에서 사용자가 몇 번이나 되돌아와도 되는지의 상한(설계안 3-2절, 6절 — 임의로
# 정한 값이라 실증 검증은 안 됨. 무한 재작업 루프를 막는 안전장치가 목적).
REVISION_CAP = 5

ROUTER_DECISION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "router_decision",
        "schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "approve",
                        "revise_market_research",
                        "revise_pestel",
                        "revise_competitor",
                        "capability_question",
                        "unclear",
                    ],
                    "description": (
                        "사용자 채팅 한 마디를 보고 다음 행동을 딱 하나만 고를 것. "
                        "approve=승인/완료/만족 의사. revise_market_research=시장 규모·투자·매출 "
                        "등 시장 데이터 추가 요청. revise_pestel=PESTEL/환경분석 재검토 요청. "
                        "revise_competitor=경쟁사 정보 추가/재검토 요청. capability_question="
                        "이 서비스 자체가 뭘 할 수 있는지 묻는 질문(기획서 내용과 무관). "
                        "unclear=위 다섯 중 무엇에도 뚜렷이 안 맞을 만큼 애매함."
                    ),
                },
                "target_query": {
                    "type": "string",
                    "description": (
                        "action이 revise_market_research/revise_competitor/capability_question일 "
                        "때만 채울 것 — 무엇을 검색/조회할지 구체적인 검색어나 질문. 그 외 "
                        "action이면 빈 문자열."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": "이렇게 판단한 이유 한두 문장. 사용자 화면에 그대로 노출되어 판단 근거를 확인할 수 있게 함.",
                },
                "user_facing_reply": {
                    "type": "string",
                    "description": (
                        "action이 unclear일 때만, 사용자에게 무엇을 구체적으로 알려달라고 "
                        "되물을 문구를 채울 것. 그 외 action이면 빈 문자열."
                    ),
                },
            },
            "required": ["action", "target_query", "reasoning", "user_facing_reply"],
        },
    },
}


def _router_decision_prompt(user_message: str, revision_count: int) -> str:
    """2026-07-24: capability_qa 버그([[structured_output_schema_instruction_weak]] 메모리)에서
    배운 대로, 스키마 description에만 판단 규칙을 적어두지 않고 프롬프트 본문에도 행동별
    정의와 예시를 명시적으로 중복 기재한다 — description 하나만 믿으면 가벼운/빠른 모델이
    미묘한 구분을 놓칠 수 있었기 때문."""
    return f"""당신은 AI 서비스 기획 보조 시스템의 Router입니다. 사용자가 기획서 초안을
확인한 뒤 아래처럼 채팅으로 답했습니다. 이 한 마디를 보고 다음에 무엇을 할지 하나만
정확히 판단하세요.

사용자 채팅: {user_message}

지금까지 재작업 횟수: {revision_count}회 (상한 {REVISION_CAP}회 도달 시 자동 종료됩니다)

판단 규칙(반드시 지킬 것):
1. 사용자가 승인/완료/만족을 표현하면(예: "좋아요", "이대로 최종본으로 해주세요", "완료",
   "승인") action=approve. target_query는 빈 문자열.
2. 시장 규모·투자·매출 등 "시장조사" 데이터를 더 찾거나 다시 계산해달라는 요청이면
   action=revise_market_research. target_query에 무엇을 검색할지 구체적으로 채우세요
   (예: "웨어러블 헬스케어 기기 미국 시장 투자 유치 현황").
3. PESTEL/환경분석을 다시 봐달라는 요청이면 action=revise_pestel. 이건 새 웹검색이
   아니라 기존 자료 재분석이므로 target_query는 빈 문자열로 둬도 됩니다.
4. 경쟁사 정보를 더 찾거나 다시 봐달라는 요청이면 action=revise_competitor.
   target_query에 무엇을 검색할지 채우세요(예: "경쟁사 A 가격 정보").
5. "이 서비스가 뭘 할 수 있는지/어디까지 되는지"를 묻는 질문(기획서 내용과 무관한, 서비스
   자체에 대한 질문. 예: "PPTX도 만들어줘?", "이거 SWOT도 돼?")이면
   action=capability_question. target_query에 사용자의 질문을 그대로 채우세요.
6. 위 다섯 경우 중 어디에도 뚜렷이 안 맞을 만큼 애매하면(예: "전체적으로 좀 더 좋게
   해줘") action=unclear로 하고, user_facing_reply에 "구체적으로 무엇을 수정하면
   될지" 되묻는 문구를 채우세요. 애매한데 대충 짐작해서 다른 action을 고르지 마세요 —
   잘못 넘겨짚어 엉뚱한 재작업을 시작하는 것보다 되묻는 편이 훨씬 낫습니다."""


def decide_next_action(user_message: str, revision_count: int, client: OpenAI | None = None) -> dict:
    """await_review에서 사용자가 채팅으로 답한 메시지 하나를 보고, 다음에 무엇을 할지
    구조화된 단일 판단을 내린다(설계안 3-3절 '옵션 B' — ReAct처럼 여러 턴에 걸쳐 스스로
    도구를 호출하는 자율 루프가 아니라, 메시지 하나당 LLM 호출 딱 한 번으로 행동을 하나만
    고른다. 여러 요청이 섞여 있으면 이번엔 하나만 처리하고, reasoning에 그 취지를 남겨
    다음 턴에 나머지를 처리하도록 유도한다).

    그래프 이동(Command(goto=...)) 자체는 이 함수의 책임이 아니다 — orchestrator/graph.py의
    router_node가 이 함수의 반환값을 보고 실제 이동을 결정한다(에이전트 LLM 로직과 그래프
    배선을 분리하는 이 프로젝트의 기존 관례를 따름 — market_research/pestel/competitor
    에이전트도 전부 "노드 함수는 얇게, 실제 로직은 agents/*.py에" 원칙을 지켜왔음).

    answer_capability_question()과 달리 LIGHT_MODEL이 아니라 HEAVY_MODEL을 쓴다 — 이
    판단이 틀리면 엉뚱한 에이전트를 재실행하는 비용(실제 웹검색+LLM 여러 번 호출)이 드는
    반면, 판단 자체의 LLM 호출 비용 차이는 미미해서 정확도를 비용보다 우선한 것.
    solar-mini(LIGHT_MODEL)는 capability_qa처럼 "주어진 문서 안에서 답하기"에는 충분했지만,
    이번처럼 6가지 행동을 구분하는 분류 판단에는 더 신뢰도 높은 모델을 쓰는 게 안전하다고
    판단했다(직접 실측 비교는 안 했음 — 시간 제약상의 보수적 선택)."""
    client = client or get_client()
    response = client.chat.completions.create(
        model=HEAVY_MODEL,
        messages=[{"role": "user", "content": _router_decision_prompt(user_message, revision_count)}],
        response_format=ROUTER_DECISION_SCHEMA,
    )
    return json.loads(response.choices[0].message.content)


CAPABILITY_ANSWER_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "capability_answer",
        "schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": (
                        "사용자의 질문에 대한 답변. 아래 제공된 근거 문서 내용만 근거로 삼고, "
                        "문서에 없는 기능을 있다고 지어내지 말 것. 문서에 '~는 지원하지 않는다/"
                        "아직 안 된다'처럼 명시적인 부정 설명이 있으면 그 사실을 그대로 답할 것 "
                        "(예: '아직 PPTX 생성은 지원하지 않고 DOCX만 지원합니다') — 이것도 "
                        "확인된 답변이지 '확인되지 않습니다'가 아님. 질문과 관련된 내용이 "
                        "문서에 전혀 없을 때만 '현재 안내 자료에서 확인되지 않습니다'라고 "
                        "솔직히 답할 것."
                    ),
                }
            },
            "required": ["answer"],
        },
    },
}


def get_client() -> OpenAI:
    api_key = os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 .env에 없습니다.")
    return OpenAI(api_key=api_key, base_url="https://api.upstage.ai/v1")


def answer_capability_question(question: str, client: OpenAI | None = None, k: int = 3) -> str:
    """서비스 기능/범위에 대한 질문("이 서비스 뭘 할 수 있어요?" 등)에, capability_corpus.md
    (rag/build_corpus.py:build_capability_corpus로 적재됨)에서 관련 내용을 찾아 답한다.

    fact_store나 다른 에이전트를 전혀 건드리지 않는다 — Router가 이 질문으로 판단되면
    파이프라인 재실행 없이 이 함수만 호출하고 바로 답을 돌려준다(설계안 3-6절).

    2026-07-24: capability_corpus 전용 컬렉션에서 검색한다(search_capability_corpus).
    tta_ncs_corpus를 doc_type 필터로 같이 쓰던 이전 방식은 대규모 컬렉션 속 극소수
    문서를 근사 검색이 놓치는 문제가 있어 별도 컬렉션으로 분리했다."""
    hits = search_capability_corpus(question, k=k)
    if not hits:
        return "현재 안내 자료에서 확인되지 않습니다. 담당자에게 직접 문의해 주세요."

    context = "\n\n".join(f"- {h['text']}" for h in hits)
    prompt = f"""아래는 이 AI 서비스의 기능 안내 문서에서 찾은 관련 내용입니다.

{context}

사용자 질문: {question}

답변 규칙:
1. 위 내용만 근거로 답하세요. 문서에 없는 기능을 있다고 지어내지 마세요.
2. 문서에 "~는 지원하지 않는다/아직 안 된다"처럼 명시적으로 나와 있으면, 그 사실을
   그대로 답하세요(예: "아직 PPTX 생성은 지원하지 않고 DOCX만 지원합니다"). 이건
   확인된 답변입니다 — "확인되지 않습니다"가 아닙니다.
3. 위 내용에 질문과 관련된 내용이 전혀 없을 때만 "현재 안내 자료에서 확인되지
   않습니다"라고 답하세요."""

    if client is None:
        client = get_client()
    response = client.chat.completions.create(
        model=LIGHT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=CAPABILITY_ANSWER_SCHEMA,
    )
    return json.loads(response.choices[0].message.content)["answer"]


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "이 서비스는 무엇을 어디까지 할 수 있어요?"
    print(answer_capability_question(q))
