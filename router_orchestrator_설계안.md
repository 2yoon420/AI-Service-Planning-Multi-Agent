# Router 기반 Orchestrator 설계안

> 2026-07-24 작성. "B안"(Router가 실시간 판단 + Human-in-the-loop) 채택을 전제로, 현재
> 코드베이스(`multi-agent-system/`)를 실제로 어떻게 바꿔야 하는지 파일 단위로 정리한 문서.
> 이 문서는 계획 단계 산출물이며, 실제 코드 수정은 별도 확인 후 진행함.

---

## 0. 사전 확인 사항 (환경)

- 설치된 `langgraph` 버전: **1.2.9** (최신 안정 버전대). `interrupt()`, `Command(goto=...)`,
  checkpointer가 전부 정식 stable API로 지원되는 버전이라 실험적 기능에 기대는 리스크는 없음.
- Python 3.10.12, FastAPI는 아직 미설치(Task #3에서 추가 예정).

---

## 1. 원인 — 왜 지금 구조로는 B안을 못 담는가

`orchestrator/graph.py`는 `add_edge()`로만 구성된 **고정 방향 그래프**다. 실행 전에 이미
`research → {pestel, competitor} → join → writer → END`라는 경로가 확정되어 있고, 중간에
멈추거나 사용자 입력을 받는 지점이 코드 구조상 존재하지 않는다. 또한 각 노드는 "한 번 실행되고
끝"을 전제로 짜여 있어(예: `fact_store`의 조회 함수들이 topic으로 데이터를 구분하지 못함),
같은 프로젝트를 여러 차례 다시 방문하는 시나리오를 애초에 상정하지 않았다. B안은 이 두 가지
전제를 모두 깨야 한다 — ①실행 중간에 멈췄다가 나중에(다른 HTTP 요청에서) 이어갈 수 있어야 하고,
②같은 프로젝트를 여러 번 들여다봐도 데이터가 섞이지 않아야 한다.

---

## 2. 기술적 뼈대 — LangGraph가 이걸 어떻게 지원하는가

세 가지 핵심 기능을 조합한다. (근거는 문서 맨 아래 참고자료 참조)

1. **`interrupt()`**: 노드 안에서 호출하면 그 지점에서 그래프 실행이 멈추고, 호출한 쪽(우리의
   경우 FastAPI 핸들러)에 `payload`를 반환한다. 사용자가 응답하면 `Command(resume=사용자입력)`으로
   그래프를 다시 호출해 **정확히 멈췄던 지점부터** 이어간다. 처음부터 다시 도는 게 아니다.
2. **`Command(goto=...)`**: 노드 함수가 고정된 `add_edge` 대신 "다음엔 이 노드로 가라"를
   실행 시점에 직접 반환할 수 있다. Router의 판단 결과를 이걸로 그래프 이동에 반영한다.
3. **checkpointer**: `interrupt()`가 동작하려면 그래프 상태를 저장소에 남겨야 한다. FastAPI는
   비동기 프레임워크이므로 `AsyncSqliteSaver`를 쓰고, `graph.compile(checkpointer=...)`로
   붙인다. 모든 실행은 `thread_id`로 구분되며, 사용자의 HTTP 요청마다
   `config={"configurable": {"thread_id": project_id}}`를 넘기면 LangGraph가 알아서 그
   프로젝트의 마지막 상태를 불러와 이어간다. **이 `thread_id`가 사실상 FastAPI의
   프로젝트 ID와 같은 개념** — Task #3(FastAPI)의 API 계약이 여기서 자연스럽게 정해진다.

---

## 3. 파일별 변경 사항

### 3-1. 선행 작업(우선순위 급상승) — Fact Store의 topic 스코핑 버그

| 파일 | 무엇을 | 어떻게 | 왜 |
|---|---|---|---|
| `fact_store/schema.py` | `Competitor`, `MarketSizing`에 `topic: Optional[str]` 필드 추가 | `Fact`에는 이미 있는 필드를 동일하게 추가 | 지금 두 모델엔 topic이 아예 없음(직접 코드로 확인) |
| `fact_store/store.py` | `list_facts(topic=...)`, `list_competitors(topic=...)`, `latest_market_sizing(topic=...)` 필터 추가. `save_competitor()`의 기본키를 `name` 단독에서 `(topic, name)` 복합키로 변경 | WHERE 절 추가, competitors 테이블 PK 변경 | 지금은 `latest_market_sizing()`이 topic 구분 없이 "가장 최근 저장된 것"을 아무거나 반환하고, `competitors` 테이블은 이름이 같으면 다른 topic 것끼리 덮어씀 |

**왜 지금 이걸 먼저 해야 하는가(우선순위 재평가)**: 이 버그 자체는 예전부터 알고 있었고
([[project_recall_priority]] 계열), "CLI로 한 번 실행하고 끝"이라는 지금까지의 사용 패턴에서는
큰 문제가 안 됐다. 그런데 B안은 **하나의 서버 프로세스가 여러 프로젝트를 순차적으로, 또는 한
프로젝트를 여러 차례(재검색·재작성 루프) 다시 처리**한다. 이 순간부터는 topic 스코핑이 안 되어
있으면 실제로 다른 사용자/다른 주제의 데이터가 섞이는 진짜 버그가 된다. 그래서 이건 더 이상
"나중에 손보면 되는 저우선 항목"이 아니라 **B안의 선행 조건**이다.

### 3-2. `orchestrator/graph.py` — 그래프 구조 확장

| 항목 | 내용 |
|---|---|
| `PlanningState`에 필드 추가 | `chat_history: Annotated[list[dict], operator.add]`, `revision_count: int`, `awaiting_user: bool` |
| 신규 노드: `await_review` | `writer` 다음에 배치. `interrupt({"draft": ..., "prompt": "확인 후 수정사항을 채팅으로 입력하세요"})` 호출 |
| 신규 노드: `router` | `await_review`의 재개(resume) 값을 받아 구조화 출력 LLM 호출로 행동을 결정, `Command(goto=...)`로 분기 |
| 신규 노드(3개): `research_revision`, `pestel_revision`, `competitor_revision` | 기존 `run_market_research`/`run_pestel_analysis`/`run_competitor_analysis`를 그대로 호출하되, 끝나면 항상 `Command(goto="writer")`로 복귀 — **기존 초기 실행 경로(research→{pestel,competitor}→join→writer)는 손대지 않고 그대로 둔 채, 재실행 전용 노드를 별도로 추가**하는 방식 |
| 신규 노드: `capability_qa` | 서비스 기능 RAG 조회 후 답변을 `chat_history`에 추가하고 바로 `await_review`로 복귀(에이전트 재실행 없음) |
| `revision_count` 캡 | `router` 노드에서 `revision_count >= 5`(가안)면 강제로 `finalize`(END) 처리 — 무한 재작업 루프 방지 |
| `graph.compile(checkpointer=...)` | `AsyncSqliteSaver` 연결. `run()` 계열 함수가 `thread_id`를 받아 최초 실행/재개 두 경우를 모두 처리하도록 시그니처 확장 |

기존 `research`/`pestel`/`competitor`/`join`/`writer` 5개 노드와 그 사이 엣지는 **그대로
둔다.** 이번 변경은 "갈아엎기"가 아니라 "writer 뒤에 새로운 구간을 이어붙이는" 확장이다.

### 3-3. Router의 판단 방식 — 두 가지 옵션과 제 추천

**옵션 A. 완전 자율 tool-calling(교과서적 ReAct/Supervisor)**: Router가 여러 턴에 걸쳐
스스로 도구를 호출하고 결과를 보고 또 호출하는 루프. 유연하지만, 몇 턴을 돌지 예측이 안 되고
비용·시간이 통제하기 어렵다.

**옵션 B. 구조화된 단일 판단(제 추천)**: 사용자 채팅 한 번마다, Router가 **딱 한 번의 LLM
호출**로 `{action, target_query, reasoning, user_facing_reply}` 같은 고정 스키마를 출력하고,
그 결과에 따라 `Command(goto=...)` 한 번만 발생시킨다. 여러 도구가 동시에 필요하면(예: "PESTEL도
다시 보고 경쟁사 가격도 추가해줘") 이번 실행에서 하나만 처리하고 "이어서 나머지도 처리하겠다"고
답한 뒤 다음 사용자 확인 턴에서 나머지를 처리 — 즉 **한 번에 하나씩, 여러 턴에 걸쳐** 처리한다.

이 프로젝트엔 옵션 B를 권합니다. 이유는, 지금까지 이 프로젝트가 지켜온 원칙(스키마 강제 출력,
예측 가능한 재시도 횟수, "완주 보장")과 결이 같고, 2주 MVP 안에서 테스트·디버깅이 훨씬
쉽습니다. 옵션 A는 실제로 몇 번의 LLM 호출이 발생할지, 어디서 멈출지 예측이 안 돼 발표 직전에
디버깅하기 가장 어려운 종류의 버그를 만들 위험이 큽니다.

### 3-4. `agents/market_research.py` — 타겟 검색 공개 함수

이미 내부에 `_search_extract_and_save(client, query, topic, target_market, ...)`라는
비공개 함수가 정확히 "질의 하나 → 검색 → fact 추출 → 저장 → 검증"을 수행하고 있다. 이걸
그대로 재사용해서 공개 함수 하나만 추가하면 된다.

```python
def run_targeted_research(topic, target_market, focus_query, results_per_question=6):
    """Router가 '투자/매출 정보 더 찾아줘' 같은 요청을 받았을 때 호출.
    전체 리서치 질문을 새로 만들지 않고, 주어진 focus_query 하나만 검색해 기존
    Fact Store에 추가한다."""
    init_db(); client = get_client()
    all_facts = []
    counters = {"n_saved": 0, "n_duplicates": 0}
    _search_extract_and_save(client, focus_query, topic, target_market,
                              results_per_question, all_facts, counters)
    return all_facts
```

새로 만드는 코드가 아니라 **기존 로직을 노출만** 하는 것이라 리스크가 낮다.

### 3-5. `agents/writer.py` — 사실은 구조 변경이 거의 필요 없다

처음엔 "섹션별 부분 재조립"이 어려운 신규 엔지니어링이라고 봤는데, 코드를 다시 보니 그렇지
않다. `export_to_docx()` 자체는 LLM 호출이 없는 **순수 포매팅 함수**라 매번 통째로 다시
불러도 비용이 거의 안 든다. 진짜 비용이 드는 곳은 그 앞 단계(웹검색+fact추출, 그리고
`write_executive_summary`/`write_positioning_narrative`/`write_synthesis` 3개 LLM 호출)다.

그래서 결론은: **"이 섹션만 patch"하는 코드를 새로 짤 필요 없이**, Router가 "무엇이
바뀌었는지"만 알고 있으면(예: 경쟁사 데이터가 갱신됨) `run_writer()`를 다시 통째로
부르면 된다. `run_writer()`가 이미 `market_sizing`/`pestel_summaries`/`competitors`를
인자로 받아 최신 값만 넘기면 그대로 반영하는 구조라 추가 수정이 사실상 필요 없다. 다만
아래 한 가지는 변경한다.

| 파일 | 무엇을 | 왜 |
|---|---|---|
| `agents/writer.py` | `run_writer()`에 `revision_note: Optional[str]` 파라미터 추가, 문서 첫머리에 "N차 수정본" 표기 | 사용자가 여러 번 되돌아와 수정할 걸 감안하면, 어느 버전인지 문서 자체에 남기는 게 좋음 |

### 3-6. 신규 파일 — 서비스 기능 RAG

| 파일 | 내용 |
|---|---|
| `rag/capability_corpus.md`(신규) | "이 서비스가 뭘 하는지/어디까지 하는지" 설명을 사람이 직접 정리해 둔 소스 문서. 통합기획문서의 1~3절 내용을 재활용 |
| `rag/query.py` | 기존 `search_corpus()`에 `doc_type="CAPABILITY"` 한 종류만 추가 — 새 벡터스토어를 따로 만들지 않고 기존 Chroma 컬렉션에 문서 종류만 하나 늘림 |
| `agents/router.py`(신규) | `answer_capability_question(question)` — `search_corpus(question, doc_type="CAPABILITY")` 결과를 근거로 LLM이 짧게 답변 생성 |

이것도 새 인프라를 만드는 게 아니라, 이미 있는 RAG 파이프라인(TTA/NCS 코퍼스와 동일한
매커니즘)에 문서 종류 하나를 추가하는 정도의 작업이다.

### 3-7. FastAPI(Task #3)와의 연결 — 지금 확정해 둬야 할 계약

Task #3가 내일 진행 예정이지만, Router 설계가 API 모양을 직접 결정하므로 지금 계약만
정해둔다(구현은 내일).

- `POST /projects` — body: `{topic, target_market}` → 그래프를 `thread_id=project_id`로
  최초 실행, `await_review`에서 멈춘 상태로 반환 (초안 요약 + DOCX 다운로드 링크)
- `POST /projects/{project_id}/messages` — body: `{message}` → `Command(resume=message)`로
  재개, 다시 `await_review`에서 멈추거나(추가 대화 필요) 종료(END, 최종 승인) 상태로 반환
- `GET /projects/{project_id}/draft` — 최신 DOCX 다운로드

---

## 4. 장점

- **실제 상호작용형 멀티에이전트**: 고정 파이프라인이 아니라 사용자 채팅에 반응해 필요한
  부분만 다시 도는 구조 — 체크포인트①("유기적 수행")을 가장 강하게 입증하는 지점.
- **효율성**: `interrupt()`+`Command(goto=...)` 덕분에 START로 되돌아가지 않고, 필요한
  노드에만 재진입한다. 대표님이 처음부터 걱정하신 "매번 처음부터 다시 도는" 비효율이
  구조적으로 발생하지 않는다.
- **기존 코드 재사용률이 높음**: `_search_extract_and_save`, `run_writer`,
  `export_to_docx`, 4개 핵심 에이전트를 거의 그대로 재사용 — 갈아엎는 리팩토링이 아니라
  확장이다.
- **확장성**: 나중에 도구를 더 추가하고 싶으면(예: SWOT 재실행) Router의 스키마에 옵션
  하나, 재실행 노드 하나만 추가하면 됨.

## 5. 단점 / 비용

- **구현 항목이 한 번에 많이 늘어남**: DB topic 스코핑 수정, 그래프 재구성, checkpointer
  연동, Router 스키마·프롬프트, 서비스 기능 RAG, FastAPI 계약까지 최소 6갈래 작업이
  동시에 얽힌다.
- **비결정성 증가**: Router의 판단은 매번 같은 결과를 보장 못한다. 사용자가 애매하게
  말하면 엉뚱한 노드로 갈 위험이 있다 — 방어책으로 "판단 근거(reasoning)를 항상 같이
  출력하게 하고, 화면에 노출"하는 정도가 최소 안전장치.
- **비용·시간 증가**: 사용자가 채팅으로 되돌아올 때마다 Router LLM 호출 1회 + 실제
  재실행 에이전트의 LLM/웹검색 호출이 추가된다. 반복 왕복이 잦으면 시연 중 대기시간이
  길어질 수 있음.
- **세션 관리라는 새 운영 부담**: `AsyncSqliteSaver`로 체크포인트 파일이 계속 쌓인다 —
  지금의 `fact_store.db`와는 별개로 관리해야 할 상태 저장소가 하나 더 생긴다.
- **테스트가 어려워짐**: 지금까지는 "입력→출력"이 결정적이라 렌더링 테스트만 하면
  됐는데, 이제는 "특정 채팅 입력 시 올바른 노드로 가는가"까지 확인해야 한다.

## 6. 한계

- Router의 자연어 이해가 완벽할 수 없다 — "투자 정보 좀 더 찾아줘"는 잘 잡아도, 모호한
  요청("전체적으로 좀 더 좋게 해줘")은 어느 노드로 보내야 할지 Router도 판단하기 어렵다.
  이런 경우 "무엇을 구체적으로 수정할지 다시 물어보는" 재질문 경로도 필요할 수 있는데,
  이번 설계엔 아직 포함하지 않았다.
- `revision_count` 캡(예: 5회)은 임의로 정한 값이라 실증 검증이 안 된 상태다 — 지난번
  `adaptive_threshold`처럼 "왜 5인가"에 명확한 근거는 없다.
- 서비스 기능 RAG는 사람이 미리 채워 넣은 만큼만 답할 수 있다 — 자동으로 서비스 설명이
  갱신되지 않는다.
- 2주 MVP라는 일정 안에서, 이 정도 규모의 아키텍처 변경은 실제로는 하루 이틀로 끝나기
  어렵다. 오늘이 중간보고일이라는 점을 감안하면, 실제 구현 착수 시점은 신중히 정하는 게
  좋다.

## 7. 의의

이 구조가 완성되면 "LLM이 몇 군데 박힌 자동화 스크립트"에서 "사용자와 대화하며 스스로
판단하는 에이전트 시스템"으로 성격이 바뀐다. 특히 Fact Store 기반 근거 추적성(왜 이런
결론에 도달했는지 추적 가능)과 결합되면, 단순히 "그럴듯한 글을 만드는" 수준을 넘어 "사용자
피드백을 받아 스스로 개선하는" 시스템이라는 차별화 지점을 확보하게 된다.

---

## 8. 실행 순서 제안

1. Fact Store topic 스코핑 버그 수정 (3-1) — 다른 모든 작업의 전제조건
2. `market_research.py`에 `run_targeted_research()` 공개 (3-4) — 위험 낮고 독립적
3. 서비스 기능 RAG 코퍼스 + `answer_capability_question()` (3-6) — 위험 낮고 독립적
4. `orchestrator/graph.py`에 checkpointer + `await_review`/`router`/재실행 노드 3개 추가 (3-2, 3-3)
5. `writer.py`에 `revision_note` 파라미터 추가 (3-5)
6. FastAPI 계약대로 엔드포인트 구현 (Task #3, 내일)
7. Tavily 연동은 2번(`run_targeted_research`) 안의 검색 호출에 자연스럽게 끼워넣기 (Task #4)

---

## 참고 자료

- [LangGraph's interrupt() Function — Medium](https://medium.com/@areebahmed575/langgraphs-interrupt-function-the-simpler-way-to-build-human-in-the-loop-agents-faef98891a92)
- [How to Implement Human-in-the-Loop in LangGraph Using the interrupt() Pattern — BSWEN](https://docs.bswen.com/blog/2026-04-16-langgraph-human-in-the-loop/)
- [LangGraph Multi-Agent Supervisor — LangChain Reference](https://reference.langchain.com/python/langgraph-supervisor)
- [LangGraph Multi-Agent Collaboration in Practice: Supervisor Pattern and Task Dispatch](https://eastondev.com/blog/en/posts/ai/20260512-langgraph-multi-agent-supervisor/)
- [Persistence — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Simple LangGraph Implementation with Memory AsyncSqliteSaver Checkpointer — FastAPI — Medium](https://medium.com/@devwithll/simple-langgraph-implementation-with-memory-asyncsqlitesaver-checkpointer-fastapi-54f4e4879a2e)
