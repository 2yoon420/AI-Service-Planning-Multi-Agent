"""
Day 1 연결 테스트 스크립트

.env에 채워 넣은 API 키들이 정상 작동하는지 확인하는 최소 스크립트.
Gemini, Upstage 순으로 테스트하며, 키가 비어있으면 해당 항목은 건너뛴다.

실행 방법:
    pip install -r requirements.txt
    cp .env.example .env   # 그 다음 .env를 열어 실제 키 값 채우기
    python test_connection.py
"""

import os
from dotenv import load_dotenv

load_dotenv()


def test_gemini():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[Gemini] 건너뜀 - GOOGLE_API_KEY가 .env에 없습니다.")
        return

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            "한 문장으로 답해줘: 멀티에이전트 시스템이란 무엇인가?"
        )
        print("[Gemini] 연결 성공")
        print("  응답:", response.text.strip())
    except Exception as e:
        print("[Gemini] 연결 실패:", e)


def test_upstage():
    api_key = os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        print("[Upstage] 건너뜀 - UPSTAGE_API_KEY가 .env에 없습니다.")
        return

    try:
        # Upstage는 OpenAI SDK와 호환되는 REST 인터페이스를 제공한다.
        # base_url만 Upstage 엔드포인트로 바꾸면 openai 패키지를 그대로 쓸 수 있다.
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url="https://api.upstage.ai/v1")
        response = client.chat.completions.create(
            model="solar-pro2",  # 하이픈 없이 solar-pro2 / solar-pro3
            messages=[
                {"role": "user", "content": "한 문장으로 답해줘: PESTEL 분석이란 무엇인가?"}
            ],
        )
        content = response.choices[0].message.content
        print("[Upstage Solar Pro 2] 연결 성공")
        print("  응답:", content.strip())
    except Exception as e:
        print("[Upstage] 연결 실패:", e)


def test_fact_schema():
    """fact_store 스키마가 정상적으로 로드되는지 확인"""
    from datetime import date
    from fact_store.schema import Fact, SourceTier

    sample = Fact(
        id="fact_0001",
        text="EU 65세 이상 인구 비율이 2024년 21%에서 2050년 29%로 증가할 전망",
        source_url="https://example.com/report",
        source_tier=SourceTier.SECONDARY,
        retrieved_date=date.today(),
        region="유럽",
    )
    print("[Fact Store] 스키마 정상 - 샘플 Fact 생성 성공:", sample.id)


if __name__ == "__main__":
    print("=== Day 1 연결 테스트 시작 ===\n")
    test_gemini()
    print()
    test_upstage()
    print()
    test_fact_schema()
    print("\n=== 테스트 종료 ===")
