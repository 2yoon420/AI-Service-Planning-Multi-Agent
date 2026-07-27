# FastAPI 서버 설계도 (Task #7) — 구현 지시서

> 2026-07-27 작성 / 같은 날 v2 갱신(진행 상황 관측 반영).
> `router_orchestrator_설계안.md` 3-7절에서 "계약만 정해두고 구현은 나중에"로 미뤄둔
> FastAPI 계층을, **다른 사람(또는 다른 모델)이 이 문서만 보고 그대로 구현할 수 있는
> 수준**으로 확정하는 문서. 신규 파일은 전체 코드를, 기존 파일은 정확한 수정 지점을 싣는다.

---

## 이 문서를 읽는 구현자에게 — 작업 규칙

**반드시 지킬 것**

1. **이 문서에 있는 코드를 그대로 쓴다.** "더 좋은 방법"이 떠올라도 임의로 바꾸지 않는다. 각 설계 결정에는 이 프로젝트의 이력에서 나온 근거가 붙어 있고, 문서에 그 근거를 함께 적어뒀다.
2. **기존 파일은 이 문서가 지정한 지점만 수정한다.** `orchestrator/graph.py`와 `agents/*.py`는 실기기 검증을 마친 코드다. 지정되지 않은 줄을 건드리면 그 검증이 무효가 된다.
3. **한 단계씩 진행하고, 각 단계의 "검증" 항목을 통과한 뒤 다음으로 넘어간다.** (11절)
4. **CLI 동작이 깨지면 안 된다.** `python -m orchestrator.graph "주제" "시장"`이 지금과 똑같이 동작해야 한다. 이것이 모든 수정의 통과 기준이다.

**절대 하지 말 것 (12절에 전체 목록)**

- `AsyncSqliteSaver`로 바꾸거나 `agents/*.py`에 `async`를 붙이는 것 → 6-3절 참고
- 그래프 노드를 추가·삭제·분할하는 것
- 로그 응답을 문자열 배열로 만드는 것 → 7-3절 참고
- DOCX 파일 경로를 파일시스템 검색으로 알아내는 것 → 5-4절 참고

---

## 1. 확정된 설계 결정

착수 전 사용자와 확정한 사항이다. 이 다섯 가지가 아래 모든 설계를 규정한다.

| # | 결정 항목 | 확정 내용 | 근거 |
|---|---|---|---|
| 1 | 실행 모델 | **백그라운드 실행 + 상태 폴링** | 초기 실행이 수 분~십수 분이라 HTTP 요청 하나로 감당 불가 (4-1절) |
| 2 | 비동기 전환 | **하지 않는다.** 동기 코드 유지 + `asyncio.to_thread()` | 6-3절 — 기존 `graph.py` 주석의 계획을 의도적으로 철회 |
| 3 | 화면 | **FastAPI 단계에서 UI를 만들지 않는다.** 프론트엔드는 별도 설계 | PRD "MVP는 별도 UI 없이 진행". 단, 프론트가 붙기 좋은 형태로 API를 설계 |
| 4 | 엔드포인트 범위 | **운영 편의 기능까지 포함** | 목록·삭제·채팅이력·fact 통계까지. 표에서 필수/편의 구분 |
| 5 | 진행 상황 관측 | **A안(로그 파이프라인) + 로그 3지점 추가.** SSE는 나중에 승격 | 7절 — 지금 안 해두면 나중에 파괴적 변경이 되는 두 가지만 미리 못 박음 |

---

## 2. 사전 확인 — 현재 코드가 어디까지 준비돼 있는가

### 2-1. 환경

- `requirements.txt`에 `fastapi` **없음**. `main.py`/`app.py`도 없음 — Task #7은 완전 미착수 상태가 맞다.
- 다만 `venv`에 `uvicorn 0.51.0`이 이미 깔려 있다(다른 패키지의 전이 의존성). 실제로 새로 설치할 것은 `fastapi` 하나다.
- langgraph 1.2.9. Python은 3.10 이상(`X | Y` 타입 문법, `asyncio.to_thread` 모두 사용 가능).

### 2-2. 이미 준비돼 있어 그대로 재사용하는 것

Task #4에서 그래프를 확장할 때 이미 이 계층을 예상하고 짜둔 부분이 있다. 새로 만들지 않는다.

| 기존 자산 | 위치 | FastAPI에서의 역할 |
|---|---|---|
| `start_project(topic, target_market, thread_id, checkpointer=None)` | `orchestrator/graph.py:444` | `POST /projects`의 실체 |
| `submit_message(thread_id, message, checkpointer=None)` | `orchestrator/graph.py:465` | `POST /projects/{id}/messages`의 실체 |
| `_extract_response(result)` | `orchestrator/graph.py:425` | 응답 변환기. docstring에 이미 "FastAPI(Task #7)와 지금의 CLI 루프가 함께 재사용할 응답 요약"이라고 적혀 있음 |
| `_check_existing_session(thread_id)` | `orchestrator/graph.py:480` | 상태 조회의 원형 — `graph.get_state()`로 interrupt 여부를 읽는 패턴이 이미 구현돼 있음 |
| `interrupt()` + `SqliteSaver` | `orchestrator/graph.py` | 요청 사이에 세션이 살아남는 근거. HTTP의 무상태성을 이걸로 메운다 |
| `agents/*.py`의 `print` 약 120개 | 전역 | **CLI의 진행 표시 화면 그 자체.** 버리지 않고 API로 흘려보낸다 (7절) |

즉 **"그래프를 어떻게 멈추고 이어갈 것인가"는 이미 풀려 있고**, 이번 작업은 그 위에 HTTP 표현 계층 하나를 얹는 것이다.

---

## 3. 전체 구조 한눈에 보기

```
                                                        ┌─────────────────────────┐
[클라이언트]              [FastAPI · async]              │ [백그라운드 스레드·동기] │
                                                        └─────────────────────────┘
POST /projects     ──►  project_id(UUID) 발급
  {topic, market}       registry: running 기록
                        asyncio.to_thread(...)  ─────────►  start_project()
                   ◄──  202 {project_id}                     │ research      ─┐
                                                              │ pestel        │ log.info(...)
GET /projects/{id} ──►  graph.get_state().next 조회           │ competitor    │   ↓
                   ◄──  200 {status, current_step}            │ writer        │ ProjectLogHandler
                                                              │               │   ↓
GET /{id}/events   ──►  EVENT_BUS.events_since(seq)           │               │ EVENT_BUS
  ?since=142       ◄──  200 {events:[{seq,kind,message,url}]} ▼               │ (프로젝트별 버퍼)
                                                        interrupt()에서 정지  ─┘
GET /{id}/draft    ──►  FileResponse(docx)              registry: awaiting_review
```

세 가지 저장소가 각각 다른 것을 책임진다. 섞지 않는다.

| 저장소 | 소유자 | 담는 것 |
|---|---|---|
| `fact_store/fact_store.db` | 도메인 | fact, 경쟁사, 시장규모 |
| `orchestrator/checkpoints.db` | LangGraph | 그래프 상태(재개용). **우리 테이블을 넣지 않는다** |
| `api/sessions.db` | API | 프로젝트 메타(topic, status, docx 경로) |
| `EVENT_BUS` (메모리) | API | 진행 로그. **영속화하지 않는다**(서버 재시작 시 소실 — 의도된 한계) |

---

## 4. 원인 — 지금 구조를 그대로 HTTP에 올릴 수 없는 이유

### 4-1. 실행 시간이 HTTP 요청의 수명을 넘는다 (핵심)

`start_project()` 한 번은 시장조사(웹검색 수십 회 + LLM 호출 수십 회) → PESTEL → 경쟁사비교(심층조사 5개사 × 질의 3개) → Writer(LLM 3회)를 순차 수행한다. 07-24 실행 기준 fact 119건을 수집했고, 실측 소요는 수 분~십수 분이다.

브라우저 fetch, 리버스 프록시, uvicorn, 프론트엔드 HTTP 클라이언트 — 이 중 **어느 한 층의 타임아웃만 먼저 걸려도 요청은 실패**한다. 그때 서버 쪽 작업은 계속 돌고 있어서, 사용자에게는 실패로 보이는데 LLM API 비용은 계속 나간다.

**이 문제는 두 번째 엔드포인트에서 더 고약해진다.** `POST /messages`의 소요 시간은 Router 판단 결과에 따라 극단적으로 갈린다.

| Router action | 실제 하는 일 | 대략 소요 |
|---|---|---|
| `approve` | 없음 (finalize) | 즉시 |
| `capability_question` | RAG 검색 1회 + LLM 1회 | 수 초 |
| `unclear` | LLM 1회 (재질문 생성) | 수 초 |
| `revise_pestel` | PESTEL 재태깅·재요약 (검색 없음) | 수십 초~수 분 |
| `revise_market_research` | 표적 검색 + fact 추출·검증 + TAM/SAM/SOM 재계산 | 수 분 |
| `revise_competitor` | 경쟁사 분석 **통째로** 재실행 | 수 분~십수 분 |

같은 엔드포인트가 3초일 때도 있고 10분일 때도 있다. 동기 방식으로는 타임아웃 값을 하나로 정할 방법이 없다.

### 4-2. CLI는 "프로세스 하나 = 세션 하나"를 가정한다

`orchestrator/graph.py`의 `__main__`은 `while response.get("paused"): ... input()` 루프다. 프로세스가 살아있는 동안만 세션이 유지된다. HTTP는 요청마다 독립적이므로 이 가정이 깨진다.

**다만 이건 이미 해결돼 있다.** checkpointer가 `thread_id` 단위로 상태를 파일에 남기므로, 서로 다른 HTTP 요청이 같은 `thread_id`를 넘기면 LangGraph가 알아서 이어붙인다.

### 4-3. 체크포인터 연결을 요청마다 열고 닫는다

`_open_checkpointer()`는 contextmanager라서 `start_project()`/`submit_message()`/`_check_existing_session()`이 호출될 때마다 sqlite 연결을 새로 열고 `build_graph()`로 그래프를 다시 컴파일한다. CLI에서는 무해하지만 서버에서는 요청마다 반복되는 낭비이고, 동시 요청 시 sqlite 잠금 경합의 원인이 된다.

### 4-4. DOCX 파일 경로가 어디에도 남지 않는다

PRD의 MVP 완료 기준이 "사용자가 FastAPI 엔드포인트를 호출하면 파일이 다운로드 응답으로 반환된다"인데, **지금 코드는 생성된 DOCX의 경로를 반환하지 않는다.**

```python
# agents/writer.py:447-463 (현재)
        docx_path = export_to_docx(...)
        print(f"[Writer 에이전트] 저장 완료(docx, 제출용): {docx_path}")

    return doc          # ← 마크다운 문자열만 반환. docx_path는 print하고 버려짐
```

`writer_node`도 `{"draft_markdown": doc, ...}`만 state에 담으므로 그래프 상태 어디에도 파일 경로가 없다.

> **파일시스템을 뒤져서 최신 파일을 찾는 방법으로 우회하지 말 것.** 파일명 규칙(`_versioned_base_name()`이 `revision_note`를 슬러그로 붙임)을 API 쪽에 다시 구현하는 셈이라, 22절에서 겪은 "같은 구조를 두 곳에 두고 한쪽만 고쳐 재발한" 실패 패턴을 그대로 재생산한다. 경로를 명시적으로 전달한다(9-1절).

### 4-5. 진행 상황이 프로세스 밖으로 나가지 않는다

`agents/*.py`의 진행 표시는 전부 `print`, 즉 **stdout**이다. CLI에서는 그게 곧 화면이지만, 서버에서는 서버 콘솔로 흘러갈 뿐 HTTP 응답에 실을 방법이 없다. 7절이 이 문제를 다룬다.

---

## 5. 실행 모델 — 백그라운드 + 폴링

### 5-1. 상태 머신

| status | 의미 | 진입 조건 |
|---|---|---|
| `running` | 백그라운드에서 그래프가 도는 중 | `POST /projects` 또는 `POST /messages` 직후 |
| `awaiting_review` | `interrupt()`로 멈춰 사용자 입력 대기 | 백그라운드 작업이 `paused=True`로 반환 |
| `completed` | `finalize` → `END` 도달 | 백그라운드 작업이 `paused=False`로 반환 |
| `failed` | 예외 또는 타임아웃 | 예외 포착 시 (메시지를 `error` 컬럼에 보존) |
| `interrupted` | 서버 재시작으로 실행이 유실됨 | lifespan startup의 좀비 복구 (10-2절) |

`_extract_response()`가 이미 `paused` 불리언을 돌려주므로 매핑은 그대로 쓴다.

### 5-2. 진행 단계는 LangGraph에서 공짜로 얻는다

`graph.get_state(config).next`가 "다음에 실행할 노드 이름 튜플"을 준다. `research_node`가 5분 도는 동안 계속 `("research",)`를 돌려주므로, 그게 곧 "지금 시장조사 중"이다.

**팬아웃 구간에서는 튜플에 둘이 들어온다.** `research → {pestel, competitor}` 구조라 그 구간에서는 `("pestel", "competitor")`가 나오고, 이를 **"PESTEL 분석 · 경쟁사 분석 진행 중"**으로 표시한다. 멀티에이전트 병렬 실행이 화면으로 증명되는 지점이다.

노드 이름 → 한글 라벨 매핑은 `api/schemas.py`에 상수로 둔다(9-3절 `NODE_LABELS`).

### 5-3. 동시성 제어 — 프로젝트당 하나의 실행만

LangGraph 상태는 같은 `thread_id`에 두 실행이 동시에 붙으면 꼬인다. **이중 안전장치**로 막는다(이 프로젝트가 "프롬프트 지시 + 코드 필터"로 반복해온 패턴의 연장).

1. **레지스트리 검사**: `status == "running"`인 프로젝트에 `POST /messages`가 오면 `409 Conflict`로 즉시 거절. 대기시키는 것보다 정직하다.
2. **`asyncio.Lock`**: `project_id`별 락. 위 검사와 실제 실행 사이의 경합(race)을 막는다.

`sqlite3.connect(..., check_same_thread=False)`는 이미 `_open_checkpointer()`에 있어서 스레드 간 연결 공유 자체는 가능하다. 동시 쓰기는 위 락으로 직렬화한다.

### 5-4. 실패·타임아웃·재시작

| 상황 | 처리 |
|---|---|
| 백그라운드 예외 | `status="failed"`, `error`에 `f"{type(e).__name__}: {e}"`. 체크포인터에 직전까지 상태가 남아 재개 가능 |
| 실행이 비정상적으로 길어짐 | `asyncio.wait_for(timeout=GRAPH_TIMEOUT_SECONDS)`. 기본 1800초(30분) |
| 서버 재시작 | lifespan startup에서 `running` 좀비 레코드를 훑어, 체크포인터에 interrupt가 남아 있으면 `awaiting_review`로 복구, 아니면 `interrupted` 표시 |

**서버가 죽어도 이미 완료된 노드의 결과는 체크포인터에 남는다** — 처음부터 다시 돌지 않는다.

---

## 6. 왜 이렇게 하는가 — 뒤집은 결정과 그 근거

### 6-1. project_id는 UUID로 한다

CLI는 `f"{topic}_{target_market}"`을 thread_id로 쓰지만 API에서는 UUID를 쓴다.

- URL에 한글이 들어가면 인코딩 문제가 생긴다.
- 같은 주제로 두 번 실험하고 싶을 때 CLI 방식은 기존 세션을 덮어쓴다.

설계안 3-7절의 `project_id == thread_id` 등식은 유지하되, 그 값을 UUID로 정한다.

### 6-2. 프로젝트 메타를 별도 DB에 둔다

`checkpoints.db`는 LangGraph가 소유한 스키마다. 우리 테이블을 섞으면 langgraph 버전업 시 마이그레이션 충돌 위험이 있다. `fact_store.db`는 도메인 데이터 저장소라 성격이 다르다. 저장소가 하나 늘어나는 건 비용이지만 소유권이 명확한 편이 낫다.

### 6-3. AsyncSqliteSaver 전환을 철회한다 (중요)

`orchestrator/graph.py` 상단 주석에는 이렇게 적혀 있다.

> "지금은 동기 SqliteSaver로 CLI에서 바로 테스트 가능한 상태로 구현하고, Task #7에서 FastAPI를 실제로 붙일 때 AsyncSqliteSaver + ainvoke()로 교체한다"

**이 계획을 철회한다.** 이유 세 가지.

1. **목적이 이미 달성된다.** 비동기로 바꾸려던 목적은 "긴 작업이 이벤트 루프를 막지 않게" 하는 것인데, `asyncio.to_thread(start_project, ...)`로 별도 스레드에서 돌리면 이벤트 루프는 애초에 막히지 않는다.
2. **비용이 비대칭적으로 크다.** 노드 함수 12개가 전부 `async def`가 되어야 하고, 그 안에서 부르는 `agents/*.py`의 모든 함수(웹검색·LLM·SQLite)에 `async`/`await`가 전파된다. 실제 이득을 보려면 `openai`를 `AsyncOpenAI`로, `ddgs`도 비동기 대안으로 바꿔야 한다. 그렇게 하지 않고 `async def` 껍데기만 씌우면 **동기 블로킹 코드가 이벤트 루프 안에서 도는 최악의 조합**이 된다.
3. **그 주석 스스로 위험을 인정하고 있다.** "MVP 막바지에 위험이 큰 변경"이라는 판단은 지금도 유효하다. 달라진 건 "FastAPI를 붙이면 어차피 해야 한다"는 전제가 사라졌다는 것뿐이다.

> **구현자에게**: `AsyncSqliteSaver`, `ainvoke`, `astream`을 쓰지 않는다. `agents/*.py`와 `orchestrator/graph.py`에 `async` 키워드를 추가하지 않는다. 비동기는 `api/` 패키지 안에서만 존재한다.

---

## 7. 진행 상황 관측 (v2 신규)

### 7-1. 문제 — CLI도 "읽은 사이트"를 안 보여준다

검색 한 건이 처리될 때 지금 찍히는 것은 이게 전부다.

```
  검색결과 6건                                    ← 건수만, URL 없음
  [청크필터] 관련 청크 없음 — 건너뜀: https://...  ← 버린 URL만 보임
  [fact 저장] (2차) 북미 반려동물 웨어러블 시장은…  ← fact 텍스트만, 출처 URL 없음
```

**읽고 버린 사이트의 URL은 보이는데, 실제로 fact를 뽑아낸 사이트의 URL은 안 보인다**(`market_research.py:440~468`). `source_url`은 `Fact` 객체에 저장되지만 화면에는 안 나온다. 즉 "어느 사이트를 읽었나"는 API 이전에 **로그 자체에 없는 정보**다.

### 7-2. 해결 — A안: print를 로그 파이프라인으로

`agents/*.py`의 `print` 약 120개가 사실상 CLI의 진행 표시 화면이다. 버리지 않고 API로 흘려보낸다.

- `print(...)` → `log.info(...)` 기계적 치환
- 프로젝트별 링버퍼(`EVENT_BUS`) + `GET /projects/{id}/events?since=N`
- CLI는 `logging.basicConfig(format="%(message)s")` 한 줄로 **지금과 100% 동일한 출력**을 유지

**"어느 프로젝트의 로그인가"는 `ContextVar`로 푼다.** 백그라운드 실행 진입 직후 스레드 안에서 `current_project_id.set(project_id)`를 호출하면, 그 스레드에서 발생하는 모든 로그 레코드가 해당 프로젝트로 귀속된다. 스레드↔프로젝트 매핑 테이블을 따로 관리하지 않는다.

### 7-3. 지금 못 박아둘 두 가지 (나중에 되돌릴 수 없음)

SSE 승격과 URL 카드 UI로 갈 길을 열어두기 위해, 지금 반드시 이렇게 만든다.

**(1) 응답은 문자열 배열이 아니라 객체 배열로.**

```json
// 금지 — 나중에 프론트가 문자열을 정규식 파싱해야 함 (22절 실패 패턴 재발)
{ "logs": ["검색결과 6건", "..."] }

// 필수 — 나중에 kind와 필드를 늘리는 것만으로 확장, 기존 클라이언트가 안 깨짐
{ "events": [
    { "seq": 142, "ts": "...", "kind": "text",  "message": "검색결과 6건" },
    { "seq": 143, "ts": "...", "kind": "fetch", "message": "웹페이지 읽음",
      "url": "https://precedenceresearch.com/...", "tier": "2차" }
]}
```

**(2) 스레드 → async 브리지 자리를 비워둔다.**

로그는 백그라운드 **스레드**에서 발생하는데 `asyncio.Queue`는 스레드 안전하지 않다. SSE로 승격할 때 `loop.call_soon_threadsafe()`로 건너와야 하므로, `EVENT_BUS`가 이벤트 루프 참조와 구독자 목록을 미리 들고 있게 만든다(9-2절 `bind_loop`/`subscribe`). 지금은 구독자가 0이라 실질적으로 아무 일도 안 하지만, 나중에 SSE 엔드포인트 하나만 추가하면 된다.

### 7-4. 구조화 이벤트로 승격하는 방법 (나중에)

`logging`의 `extra=` 인자를 쓴다. 같은 한 줄이 텍스트로도 읽히고 구조화 데이터로도 읽힌다.

```python
log.info("웹페이지 읽음", extra={"kind": "fetch", "url": url, "tier": tier})
```

**한 지점씩 점진적으로 승격할 수 있다** — 전면 개편이 아니다. 이번에는 아래 3지점만 승격한다.

### 7-5. 이번에 추가하는 로그 3지점

사용자가 원한 "어느 사이트에 접속해 읽어왔는지"를 만드는 최소 집합이다.

| # | 위치 | kind | 내용 |
|---|---|---|---|
| ① | `web_search.search_web()` — 결과 1건마다 | `search_result` | 제목 + URL + tier |
| ② | `web_search.fetch_page_text()` — 성공/실패 | `fetch` / `fetch_failed` | URL + 읽은 글자 수 |
| ③ | `market_research._search_extract_and_save():468` — fact 저장 시 | `fact` | fact 텍스트 + **출처 URL**(현재 누락) |

정확한 코드는 9-9절.

---

## 8. API 계약

### 8-1. 설계 원칙

PRD가 "TTAK.KO-10.0771/R1(RESTful API 지침) 참고 설계"를 명시하므로 그 관례를 따른다.

- **리소스는 복수형 명사**: `/projects`, `/projects/{id}/messages`. 동사(`/createProject`)를 URL에 쓰지 않는다.
- **행위는 HTTP 메서드로**: 생성 `POST`, 조회 `GET`, 삭제 `DELETE`.
- **상태 코드로 의미 전달**: 즉시 완료 `200`, 접수 후 비동기 처리 `202`, 없음 `404`, 상태 충돌 `409`.

### 8-2. 엔드포인트 목록

| 우선 | 메서드 | 경로 | 역할 | 성공 코드 |
|---|---|---|---|---|
| 필수 | `POST` | `/projects` | 프로젝트 생성 + 파이프라인 시작 | `202` |
| 필수 | `GET` | `/projects/{id}` | 상태·진행단계·초안 미리보기 | `200` |
| 필수 | `POST` | `/projects/{id}/messages` | 사용자 메시지 전달 → 그래프 재개 | `202` |
| 필수 | `GET` | `/projects/{id}/events` | **진행 로그 폴링** (`?since=` 커서) | `200` |
| 필수 | `GET` | `/projects/{id}/draft` | **DOCX 다운로드** (PRD MVP 완료 기준) | `200` |
| 편의 | `GET` | `/projects` | 프로젝트 목록 | `200` |
| 편의 | `GET` | `/projects/{id}/messages` | 채팅 이력 | `200` |
| 편의 | `GET` | `/projects/{id}/draft/markdown` | 초안 마크다운 전문 | `200` |
| 편의 | `GET` | `/projects/{id}/facts` | fact 통계 (채택/애매/기각, tier 분포) | `200` |
| 편의 | `DELETE` | `/projects/{id}` | 세션 삭제 | `204` |
| 편의 | `GET` | `/health` | 헬스체크 | `200` |

> SSE로 승격할 때는 `GET /projects/{id}/events/stream`을 **추가**한다. 위 폴링 엔드포인트는 지우지 않는다 — SSE 연결이 끊겼을 때의 폴백이자, 재접속 시 놓친 구간을 복구하는 통로다.

### 8-3. 상태 코드 정책

| 코드 | 언제 |
|---|---|
| `200` | 조회 성공, 파일 반환 |
| `202` | 백그라운드 작업 접수 (`POST /projects`, `POST /messages`) |
| `204` | 삭제 성공 |
| `404` | 없는 project_id / DOCX가 아직 없는 상태에서 `/draft` 호출 |
| `409` | 이미 `running`인 프로젝트에 메시지 전송, 또는 `completed`/`failed` 프로젝트에 메시지 전송 |
| `422` | 요청 본문 검증 실패 (Pydantic 자동) |
| `500` | 예상 못 한 서버 오류 |

---

## 9. 신규 파일 — 전체 코드

파일 구조는 다음과 같다.

```
multi-agent-system/
├── api/                     ← 신규 패키지
│   ├── __init__.py          (빈 파일)
│   ├── logbus.py            진행 이벤트 버스 + 로깅 핸들러
│   ├── registry.py          프로젝트 메타 저장소 (SQLite)
│   ├── runner.py            백그라운드 실행 · 락 · 상태 전이
│   ├── schemas.py           Pydantic 요청/응답 모델
│   ├── routes.py            엔드포인트
│   ├── main.py              FastAPI 앱 · lifespan
│   └── sessions.db          (자동 생성, gitignore)
```

**`orchestrator/` 안에 넣지 않는 이유**: 이 프로젝트는 "에이전트 로직은 `agents/`, 그래프 배선은 `orchestrator/`"라는 계층 분리를 지켜왔다(`router_node` 주석에 명시). HTTP 표현은 세 번째 층이므로 별도 패키지로 둔다. 이렇게 하면 **`api/`를 통째로 지워도 CLI가 그대로 동작한다.**

---

### 9-1. `api/__init__.py`

빈 파일.

---

### 9-2. `api/logbus.py`

```python
"""프로젝트별 진행 이벤트 버스 (설계도 7절).

agents/*.py가 logging으로 남기는 진행 로그를 project_id 단위로 모아 API가 조회할 수
있게 한다. 백그라운드 스레드에서 발생하는 로그를 어느 프로젝트 것인지 구분하는 문제는
ContextVar로 푼다 — runner.py가 스레드 진입 직후 current_project_id를 세팅하면,
그 스레드에서 발생하는 모든 로그 레코드가 해당 프로젝트로 귀속된다.

SSE 승격 대비(설계도 7-3절): 이벤트는 처음부터 객체(dict)로 만들고, 이벤트 루프
참조와 구독자 큐를 들고 있을 자리를 비워둔다. 지금은 구독자가 0이라 실질적으로
아무 일도 하지 않지만, 나중에 SSE 엔드포인트를 추가할 때 이 자리만 쓰면 된다.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

# 프로젝트 하나당 보관할 최대 이벤트 수. 넘으면 오래된 것부터 버린다(deque maxlen).
# fact 119건 실행에서 로그가 대략 500~800줄이었으므로 2000이면 한 세션은 충분히 담긴다.
MAX_EVENTS_PER_PROJECT = 2000

# 지금 이 스레드가 어느 프로젝트를 처리 중인지. runner.py가 세팅한다.
current_project_id: ContextVar[Optional[str]] = ContextVar("current_project_id", default=None)

# logging 레코드에서 이벤트로 옮겨 실을 구조화 필드. 여기 없는 extra는 무시된다.
_STRUCTURED_FIELDS = ("url", "tier", "title", "step", "count")


class ProjectEventBus:
    """프로젝트별 이벤트 링버퍼. 스레드에서 write, 이벤트 루프에서 read 하므로
    threading.Lock으로 보호한다(asyncio.Lock이 아니다 — 쓰는 쪽이 스레드다)."""

    def __init__(self) -> None:
        self._buffers: dict[str, deque] = {}
        self._seq: dict[str, int] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """FastAPI lifespan에서 한 번 호출. SSE 승격 시 스레드→async 브리지에 필요하다."""
        self._loop = loop

    def publish(self, project_id: str, event: dict) -> None:
        with self._lock:
            seq = self._seq.get(project_id, 0) + 1
            self._seq[project_id] = seq
            full_event = {"seq": seq, **event}
            buffer = self._buffers.setdefault(
                project_id, deque(maxlen=MAX_EVENTS_PER_PROJECT)
            )
            buffer.append(full_event)
            subscribers = list(self._subscribers.get(project_id, []))

        # --- SSE 승격 자리 (지금은 subscribers가 항상 비어 있어 아무 일도 안 함) ---
        if self._loop is not None and subscribers:
            for queue in subscribers:
                self._loop.call_soon_threadsafe(queue.put_nowait, full_event)

    def events_since(self, project_id: str, since: int = 0) -> list[dict]:
        with self._lock:
            buffer = self._buffers.get(project_id)
            if not buffer:
                return []
            return [e for e in buffer if e["seq"] > since]

    def latest_seq(self, project_id: str) -> int:
        with self._lock:
            return self._seq.get(project_id, 0)

    def clear(self, project_id: str) -> None:
        with self._lock:
            self._buffers.pop(project_id, None)
            self._seq.pop(project_id, None)
            self._subscribers.pop(project_id, None)

    # --- 아래 둘은 SSE 승격 시에만 쓴다. 지금은 호출되지 않는다. ---
    def subscribe(self, project_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.setdefault(project_id, []).append(queue)
        return queue

    def unsubscribe(self, project_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            subscribers = self._subscribers.get(project_id)
            if subscribers and queue in subscribers:
                subscribers.remove(queue)


EVENT_BUS = ProjectEventBus()


class ProjectLogHandler(logging.Handler):
    """logging 레코드를 EVENT_BUS로 옮기는 핸들러.

    current_project_id가 None이면(= CLI 실행이거나 API의 요청 처리 스레드) 아무것도
    하지 않는다. 즉 이 핸들러를 루트 로거에 붙여둬도 CLI 동작에는 영향이 없다."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            project_id = current_project_id.get()
            if project_id is None:
                return
            event = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": getattr(record, "kind", "text"),
                "level": record.levelname,
                "message": record.getMessage(),
            }
            for field in _STRUCTURED_FIELDS:
                value = getattr(record, field, None)
                if value is not None:
                    event[field] = value
            EVENT_BUS.publish(project_id, event)
        except Exception:  # 로깅이 앱을 죽이면 안 된다
            self.handleError(record)


def install_log_handler() -> None:
    """FastAPI lifespan에서 한 번 호출. agents/orchestrator 로거에만 붙인다
    (루트에 붙이면 uvicorn 내부 로그까지 이벤트로 섞여 들어온다)."""
    handler = ProjectLogHandler()
    handler.setLevel(logging.INFO)
    for logger_name in ("agents", "orchestrator", "fact_store", "rag"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        # 서버 콘솔에도 그대로 보이도록 propagate는 켜둔다(기본값 True).
```

---

### 9-3. `api/registry.py`

```python
"""프로젝트 메타 저장소 (설계도 6-2절).

checkpoints.db(LangGraph 소유)나 fact_store.db(도메인 데이터)와 섞지 않고
독립 SQLite 파일을 쓴다. 담는 것은 "이 project_id가 무슨 주제이고 지금 무슨
상태인가"뿐이다 — 그래프 상태 자체는 여전히 checkpointer가 소유한다."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "sessions.db"

STATUS_RUNNING = "running"
STATUS_AWAITING = "awaiting_review"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"

# 이 상태에서는 새 메시지를 받을 수 없다(409 Conflict).
BUSY_STATUSES = {STATUS_RUNNING}
CLOSED_STATUSES = {STATUS_COMPLETED}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id     TEXT PRIMARY KEY,
                topic          TEXT NOT NULL,
                target_market  TEXT NOT NULL,
                status         TEXT NOT NULL,
                docx_path      TEXT,
                error          TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
            """
        )


def create_project(project_id: str, topic: str, target_market: str) -> dict:
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO projects (project_id, topic, target_market, status,"
            " docx_path, error, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)",
            (project_id, topic, target_market, STATUS_RUNNING, now, now),
        )
    return get_project(project_id)  # type: ignore[return-value]


def get_project(project_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
    return dict(row) if row else None


def list_projects() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_project(
    project_id: str,
    *,
    status: Optional[str] = None,
    docx_path: Optional[str] = None,
    error: Optional[str] = None,
    clear_error: bool = False,
) -> None:
    """지정한 필드만 갱신한다. error를 지우려면 clear_error=True를 쓴다
    (None을 넘기는 것과 '지운다'를 구분하기 위함)."""
    sets: list[str] = ["updated_at = ?"]
    params: list = [_now()]
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if docx_path is not None:
        sets.append("docx_path = ?")
        params.append(docx_path)
    if clear_error:
        sets.append("error = NULL")
    elif error is not None:
        sets.append("error = ?")
        params.append(error)
    params.append(project_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE project_id = ?", params
        )


def delete_project(project_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))


def running_project_ids() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT project_id FROM projects WHERE status = ?", (STATUS_RUNNING,)
        ).fetchall()
    return [r["project_id"] for r in rows]
```

---

### 9-4. `api/runner.py`

```python
"""백그라운드 실행 · 동시성 제어 · 상태 전이 (설계도 5절).

여기가 "동기 그래프 코드"와 "비동기 FastAPI" 사이의 유일한 경계다.
asyncio.to_thread()로 동기 함수를 별도 스레드에서 돌리므로, agents/*.py와
orchestrator/graph.py는 async를 전혀 몰라도 된다(설계도 6-3절)."""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from api import registry
from api.logbus import current_project_id

# 그래프 실행 상한. 근거 없는 임의값이다(REVISION_CAP=5와 같은 종류의 안전장치).
GRAPH_TIMEOUT_SECONDS = 1800  # 30분

_locks: dict[str, asyncio.Lock] = {}
_tasks: dict[str, asyncio.Task] = {}


def lock_for(project_id: str) -> asyncio.Lock:
    lock = _locks.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[project_id] = lock
    return lock


def _run_with_context(project_id: str, fn: Callable[[], dict]) -> dict:
    """백그라운드 스레드 안에서 실행되는 래퍼.

    여기서 ContextVar를 세팅하는 것이 핵심이다 — asyncio.to_thread()가 컨텍스트를
    복사해 넘겨주므로, 이 스레드에서 발생하는 모든 로그 레코드가 이 project_id로
    귀속된다(logbus.ProjectLogHandler 참고)."""
    current_project_id.set(project_id)
    return fn()


async def _execute(project_id: str, fn: Callable[[], dict]) -> None:
    """그래프 호출 하나를 백그라운드에서 수행하고, 결과에 따라 레지스트리 상태를 옮긴다."""
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_run_with_context, project_id, fn),
            timeout=GRAPH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        registry.update_project(
            project_id,
            status=registry.STATUS_FAILED,
            error=f"실행 시간이 상한({GRAPH_TIMEOUT_SECONDS}초)을 초과했습니다.",
        )
        return
    except Exception as exc:  # noqa: BLE001 — 어떤 예외든 상태로 남겨야 한다
        registry.update_project(
            project_id,
            status=registry.STATUS_FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    docx_path = response.get("draft_docx_path")
    if response.get("paused"):
        registry.update_project(
            project_id,
            status=registry.STATUS_AWAITING,
            docx_path=docx_path,
            clear_error=True,
        )
    else:
        registry.update_project(
            project_id,
            status=registry.STATUS_COMPLETED,
            docx_path=docx_path,
            clear_error=True,
        )


async def launch(project_id: str, fn: Callable[[], dict]) -> None:
    """레지스트리를 running으로 옮기고 백그라운드 작업을 띄운다.
    호출부(routes.py)가 이미 409 검사를 마쳤다는 전제이며, 락은 그 검사와 이
    호출 사이의 경합을 막는 두 번째 안전장치다(설계도 5-3절)."""
    async with lock_for(project_id):
        registry.update_project(
            project_id, status=registry.STATUS_RUNNING, clear_error=True
        )
        task = asyncio.create_task(_execute(project_id, fn))
        _tasks[project_id] = task
        task.add_done_callback(lambda t: _tasks.pop(project_id, None))


def is_busy(project_id: str) -> bool:
    task = _tasks.get(project_id)
    return task is not None and not task.done()
```

---

### 9-5. `api/schemas.py`

```python
"""요청/응답 Pydantic 모델 + 노드 라벨 매핑."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# 초안 미리보기 길이. 전문은 GET /projects/{id}/draft/markdown 으로 받는다.
DRAFT_PREVIEW_CHARS = 1000

# graph.get_state().next에 담긴 노드 이름 → 사람이 읽는 한글 라벨 (설계도 5-2절).
# 팬아웃 구간에서는 여러 개가 동시에 나오므로 호출부가 " · "로 이어 붙인다.
NODE_LABELS: dict[str, str] = {
    "research": "시장조사 진행 중",
    "pestel": "PESTEL 분석 진행 중",
    "competitor": "경쟁사 분석 진행 중",
    "join": "중간 집계 중",
    "writer": "기획서 초안 작성 중",
    "await_review": "사용자 확인 대기",
    "router": "요청 판단 중",
    "research_revision": "시장조사 재실행 중",
    "pestel_revision": "PESTEL 재분석 중",
    "competitor_revision": "경쟁사 재분석 중",
    "capability_qa": "기능 질문 답변 중",
    "finalize": "마무리 중",
}


def describe_steps(node_names: tuple[str, ...]) -> Optional[str]:
    if not node_names:
        return None
    return " · ".join(NODE_LABELS.get(n, n) for n in node_names)


class CreateProjectRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="연구대상 (예: 스마트 반려동물 건강관리 기기)")
    target_market: str = Field(..., min_length=1, description="목표시장 (예: 북미 반려동물 오너 시장)")


class CreateProjectResponse(BaseModel):
    project_id: str
    status: str
    created_at: str


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="사용자가 초안을 보고 입력한 채팅")


class ProjectSummary(BaseModel):
    project_id: str
    topic: str
    target_market: str
    status: str
    created_at: str
    updated_at: str


class ProjectDetail(ProjectSummary):
    current_step: Optional[str] = Field(None, description="running일 때만 채워진다")
    revision_count: int = 0
    qa_count: int = 0
    prompt: Optional[str] = Field(None, description="interrupt() payload의 안내 문구")
    draft_preview: Optional[str] = None
    draft_available: bool = False
    latest_event_seq: int = Field(0, description="이 값을 다음 /events 호출의 since로 넘긴다")
    error: Optional[str] = None


class EventItem(BaseModel):
    seq: int
    ts: str
    kind: str
    level: str
    message: str
    # kind에 따라 선택적으로 채워지는 구조화 필드 (설계도 7-3절)
    url: Optional[str] = None
    tier: Optional[str] = None
    title: Optional[str] = None
    step: Optional[str] = None
    count: Optional[int] = None


class EventsResponse(BaseModel):
    project_id: str
    events: list[EventItem]
    latest_seq: int


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatHistoryResponse(BaseModel):
    project_id: str
    messages: list[ChatMessage]


class FactStatsResponse(BaseModel):
    """외부 검토보고서 ④ — 기각/애매 fact 통계를 초안 밖으로 노출하는 자리."""

    project_id: str
    total: int
    by_verification: dict[str, int]
    by_source_tier: dict[str, int]
    needs_source_check: int
```

---

### 9-6. `api/routes.py`

```python
"""엔드포인트 정의. 로직은 registry/runner/graph로 위임하고 여기는 얇게 유지한다
(이 프로젝트가 지켜온 '노드 함수는 얇게, 실제 로직은 별도 모듈에' 원칙의 연장)."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, PlainTextResponse

from api import registry, runner
from api.logbus import EVENT_BUS
from api.schemas import (
    ChatHistoryResponse,
    ChatMessage,
    CreateProjectRequest,
    CreateProjectResponse,
    EventsResponse,
    FactStatsResponse,
    MessageRequest,
    ProjectDetail,
    ProjectSummary,
    DRAFT_PREVIEW_CHARS,
    describe_steps,
)
from fact_store.store import list_facts
from orchestrator.graph import get_session_state, start_project, submit_message

router = APIRouter()


def _require_project(project_id: str) -> dict:
    row = registry.get_project(project_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"프로젝트를 찾을 수 없습니다: {project_id}"
        )
    return row


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post(
    "/projects",
    response_model=CreateProjectResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_project(payload: CreateProjectRequest, request: Request):
    project_id = str(uuid.uuid4())
    row = registry.create_project(project_id, payload.topic, payload.target_market)

    graph = request.app.state.graph

    def _job() -> dict:
        return start_project(
            payload.topic, payload.target_market, project_id, graph=graph
        )

    await runner.launch(project_id, _job)
    return CreateProjectResponse(
        project_id=project_id,
        status=registry.STATUS_RUNNING,
        created_at=row["created_at"],
    )


@router.get("/projects", response_model=list[ProjectSummary])
def list_all_projects():
    return [ProjectSummary(**row) for row in registry.list_projects()]


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project_detail(project_id: str, request: Request):
    row = _require_project(project_id)
    snapshot = get_session_state(project_id, request.app.state.graph)

    draft_markdown = snapshot.get("draft_markdown")
    docx_path = row.get("docx_path") or snapshot.get("draft_docx_path")

    return ProjectDetail(
        project_id=row["project_id"],
        topic=row["topic"],
        target_market=row["target_market"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        current_step=(
            describe_steps(snapshot["next_nodes"])
            if row["status"] == registry.STATUS_RUNNING
            else None
        ),
        revision_count=snapshot.get("revision_count", 0),
        qa_count=snapshot.get("qa_count", 0),
        prompt=snapshot.get("prompt"),
        draft_preview=(draft_markdown or "")[:DRAFT_PREVIEW_CHARS] or None,
        draft_available=bool(docx_path and Path(docx_path).exists()),
        latest_event_seq=EVENT_BUS.latest_seq(project_id),
        error=row.get("error"),
    )


@router.post(
    "/projects/{project_id}/messages", status_code=status.HTTP_202_ACCEPTED
)
async def post_message(project_id: str, payload: MessageRequest, request: Request):
    row = _require_project(project_id)

    if row["status"] in registry.BUSY_STATUSES or runner.is_busy(project_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "이 프로젝트는 아직 처리 중입니다. 완료 후 다시 시도해 주세요.",
        )
    if row["status"] in registry.CLOSED_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "이미 종료된 프로젝트입니다."
        )

    graph = request.app.state.graph

    def _job() -> dict:
        return submit_message(project_id, payload.message, graph=graph)

    await runner.launch(project_id, _job)
    return {"project_id": project_id, "status": registry.STATUS_RUNNING}


@router.get("/projects/{project_id}/events", response_model=EventsResponse)
def get_events(project_id: str, since: int = 0):
    _require_project(project_id)
    return EventsResponse(
        project_id=project_id,
        events=EVENT_BUS.events_since(project_id, since),
        latest_seq=EVENT_BUS.latest_seq(project_id),
    )


@router.get("/projects/{project_id}/messages", response_model=ChatHistoryResponse)
def get_chat_history(project_id: str, request: Request):
    _require_project(project_id)
    snapshot = get_session_state(project_id, request.app.state.graph)
    return ChatHistoryResponse(
        project_id=project_id,
        messages=[ChatMessage(**m) for m in snapshot.get("chat_history", [])],
    )


@router.get("/projects/{project_id}/draft")
def download_draft(project_id: str):
    row = _require_project(project_id)
    docx_path = row.get("docx_path")
    if not docx_path or not Path(docx_path).exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "아직 생성된 기획서 초안(DOCX)이 없습니다."
        )
    return FileResponse(
        path=docx_path,
        filename=Path(docx_path).name,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )


@router.get("/projects/{project_id}/draft/markdown", response_class=PlainTextResponse)
def get_draft_markdown(project_id: str, request: Request):
    _require_project(project_id)
    snapshot = get_session_state(project_id, request.app.state.graph)
    markdown = snapshot.get("draft_markdown")
    if not markdown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "아직 초안이 없습니다.")
    return PlainTextResponse(markdown)


@router.get("/projects/{project_id}/facts", response_model=FactStatsResponse)
def get_fact_stats(project_id: str):
    row = _require_project(project_id)
    facts = list_facts(topic=row["topic"])

    by_verification: dict[str, int] = {}
    by_source_tier: dict[str, int] = {}
    needs_check = 0
    for fact in facts:
        # verification_status가 None인 레거시 fact는 '기각'과 구분해서 센다
        # (fact_store/schema.py의 필드 주석이 명시한 지시).
        label = fact.verification_status.value if fact.verification_status else "미검증"
        by_verification[label] = by_verification.get(label, 0) + 1
        tier = fact.source_tier.value
        by_source_tier[tier] = by_source_tier.get(tier, 0) + 1
        if fact.needs_source_check:
            needs_check += 1

    return FactStatsResponse(
        project_id=project_id,
        total=len(facts),
        by_verification=by_verification,
        by_source_tier=by_source_tier,
        needs_source_check=needs_check,
    )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str):
    _require_project(project_id)
    if runner.is_busy(project_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "실행 중인 프로젝트는 삭제할 수 없습니다."
        )
    registry.delete_project(project_id)
    EVENT_BUS.clear(project_id)
    # 체크포인터의 해당 thread 기록은 남는다 — LangGraph가 소유한 데이터를
    # 우리가 직접 지우지 않는다는 원칙(설계도 6-2절). 필요하면 별도 정리 스크립트로.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

---

### 9-7. `api/main.py`

```python
"""FastAPI 앱 진입점.

실행: uvicorn api.main:app --reload --port 8000  (반드시 워커 1개 — 설계도 13절 한계)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import registry
from api.logbus import EVENT_BUS, install_log_handler
from api.routes import router
from orchestrator.graph import (
    CHECKPOINT_DB_PATH,
    build_graph,
    get_session_state,
    open_checkpointer,
)


def _recover_zombie_sessions(graph) -> None:
    """서버가 죽었을 때 running으로 남은 레코드를 정리한다(설계도 5-4절).

    체크포인터에 interrupt가 남아 있으면 사용자 대기 상태로 복구할 수 있고,
    아니면 실행이 중간에 유실된 것이므로 interrupted로 표시해 사용자에게 알린다."""
    for project_id in registry.running_project_ids():
        try:
            snapshot = get_session_state(project_id, graph)
        except Exception:
            snapshot = {"interrupted": False}
        if snapshot.get("interrupted"):
            registry.update_project(project_id, status=registry.STATUS_AWAITING)
        else:
            registry.update_project(
                project_id,
                status=registry.STATUS_INTERRUPTED,
                error="서버가 재시작되어 실행이 중단되었습니다. 메시지를 다시 보내면 이어집니다.",
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.init_db()
    install_log_handler()
    EVENT_BUS.bind_loop(asyncio.get_running_loop())

    # 체크포인터 연결과 컴파일된 그래프를 앱 수명 동안 하나만 유지한다(설계도 4-3절).
    with open_checkpointer(str(CHECKPOINT_DB_PATH)) as saver:
        app.state.graph = build_graph(saver)
        _recover_zombie_sessions(app.state.graph)
        yield


app = FastAPI(
    title="AI 서비스 기획 보조 Multi-Agent API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)

# --- CORS 자리 (프론트엔드를 별도 포트로 띄울 때 채운다. 지금은 비워둔다) ---
# from fastapi.middleware.cors import CORSMiddleware
# app.add_middleware(CORSMiddleware, allow_origins=[...], allow_methods=["*"],
#                    allow_headers=["*"])
```

---

## 10. 기존 파일 수정 — 정확한 지점

**여기 적힌 곳만 수정한다.** 각 항목에 "왜"를 붙였으니, 왜 필요한지 모르겠으면 건드리지 말고 물어볼 것.

### 10-1. `agents/writer.py` — DOCX 경로를 반환값에 싣기

`run_writer()` 호출부는 실제로 **두 곳뿐**이다(`agents/writer.py:474`의 CLI, `orchestrator/graph.py:186`의 `writer_node`). 그래도 하위 호환을 지키는 쪽을 택한다.

```python
# 시그니처에 파라미터 하나 추가
def run_writer(
    topic: str,
    target_market: str,
    market_sizing: Optional[MarketSizing] = None,
    pestel_summaries: Optional[list[dict]] = None,
    competitors: Optional[list[Competitor]] = None,
    save: bool = True,
    revision_note: Optional[str] = None,
    return_paths: bool = False,          # ← 추가
):
```

```python
# 함수 끝부분 (현재 442~463행) 을 아래로 교체
    docx_path = None
    if save:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        base_name = f"{_slugify(topic)}_{_slugify(target_market)}_기획서초안"
        base_name = _versioned_base_name(OUTPUT_DIR, base_name, revision_note=revision_note)

        docx_path = export_to_docx(
            ...  # 기존 인자 그대로, 손대지 않는다
        )
        log.info(f"[Writer 에이전트] 저장 완료(docx, 제출용): {docx_path}")

    return (doc, docx_path) if return_paths else doc
```

### 10-2. `orchestrator/graph.py` — 5곳

**(a) `PlanningState`에 필드 2개 추가** (기존 필드는 손대지 않는다)

```python
    # --- 2026-07-27 추가 (FastAPI 설계도 10-2절) ---
    # writer_node가 만든 DOCX의 절대경로. 다운로드 엔드포인트가 이 값을 쓴다.
    draft_docx_path: Optional[str]
    # capability_qa 호출 횟수. revision_count와 달리 에이전트를 재실행하지 않으므로
    # 기존엔 아무 상한이 없었는데, API로 열면 무제한 LLM 비용이 된다(외부 검토 ⑥).
    qa_count: int
```

**(b) `_initial_state()`에 초기값 2개 추가**

```python
        "draft_docx_path": None,
        "qa_count": 0,
```

**(c) `writer_node()` — `run_writer` 호출부만 교체**

```python
    try:
        doc, docx_path = run_writer(
            state["topic"],
            state["target_market"],
            market_sizing=state.get("market_sizing") or None,
            pestel_summaries=state.get("pestel_summaries") or None,
            competitors=state.get("competitors") or None,
            revision_note=revision_note,
            return_paths=True,                      # ← 추가
        )
        return {
            "draft_markdown": doc,
            "draft_docx_path": str(docx_path) if docx_path else None,   # ← 추가
            "awaiting_user": True,
        }
    except Exception as e:
        return {"errors": [f"[Writer] {type(e).__name__}: {e}"], "awaiting_user": True}
```

**(d) `router_node()` — `capability_question` 분기에 상한 검사 추가**

기존 `REVISION_CAP` 처리와 똑같은 형태로 만든다(새 패턴을 도입하지 않는다).

```python
    if action == "capability_question":
        if state.get("qa_count", 0) >= QA_CAP:
            return Command(
                goto="await_review",
                update={
                    "chat_history": [{
                        "role": "assistant",
                        "content": f"기능 질문 답변 한도({QA_CAP}회)에 도달했습니다. "
                                   f"초안 수정 요청만 처리할 수 있습니다.",
                    }],
                    "awaiting_user": True,
                },
            )
        return Command(goto="capability_qa", update={"pending_action_query": target_query})
```

**(e) `capability_qa_node()` — 반환값에 카운터 증가 추가**

```python
    question = state.get("pending_action_query", "")
    next_qa_count = state.get("qa_count", 0) + 1
    try:
        answer = answer_capability_question(question)
        return {
            "chat_history": [{"role": "assistant", "content": answer}],
            "qa_count": next_qa_count,
        }
    except Exception as e:
        return {
            "chat_history": [{"role": "assistant", "content": "죄송합니다, 답변 생성 중 오류가 발생했습니다."}],
            "errors": [f"[capability_qa] {type(e).__name__}: {e}"],
            "qa_count": next_qa_count,
        }
```

**(f) 체크포인터·그래프 재사용 + 상태 조회 헬퍼**

`_open_checkpointer`의 이름을 `open_checkpointer`로 바꾸고(로직 변경 없음), 아래 함수들을 조정한다.

```python
# 이름만 변경 (앞의 밑줄 제거) — 로직은 그대로
@contextmanager
def open_checkpointer(conn_string: str):
    ...


def _extract_response(result: dict) -> dict:
    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value
        return {
            "paused": True,
            "draft_markdown": payload.get("draft_markdown"),
            "draft_docx_path": result.get("draft_docx_path"),   # ← 추가
            "prompt": payload.get("prompt"),
        }
    return {
        "paused": False,
        "draft_markdown": result.get("draft_markdown"),
        "draft_docx_path": result.get("draft_docx_path"),        # ← 추가
        "errors": result.get("errors", []),
    }


def start_project(topic, target_market, thread_id, checkpointer=None, graph=None) -> dict:
    """graph를 주면(FastAPI) 이미 컴파일된 그래프를 재사용한다 — 요청마다 sqlite 연결을
    열고 그래프를 재컴파일하는 낭비를 없애기 위함(설계도 4-3절). 아무것도 안 주면
    기존 CLI 동작 그대로."""
    config = {"configurable": {"thread_id": thread_id}}
    initial = _initial_state(topic, target_market)
    if graph is not None:
        return _extract_response(graph.invoke(initial, config=config))
    if checkpointer is not None:
        return _extract_response(build_graph(checkpointer).invoke(initial, config=config))
    with open_checkpointer(str(CHECKPOINT_DB_PATH)) as saver:
        return _extract_response(build_graph(saver).invoke(initial, config=config))


def submit_message(thread_id, message, checkpointer=None, graph=None) -> dict:
    """start_project()와 같은 규칙으로 graph 재사용을 지원한다."""
    config = {"configurable": {"thread_id": thread_id}}
    command = Command(resume=message)
    if graph is not None:
        return _extract_response(graph.invoke(command, config=config))
    if checkpointer is not None:
        return _extract_response(build_graph(checkpointer).invoke(command, config=config))
    with open_checkpointer(str(CHECKPOINT_DB_PATH)) as saver:
        return _extract_response(build_graph(saver).invoke(command, config=config))


def get_session_state(thread_id: str, graph) -> dict:
    """지금 이 세션이 어느 노드를 실행 중이고 어떤 상태인지 반환한다.
    _check_existing_session()이 하던 일을 일반화한 것 — 그 함수는 이 함수를 부르는
    얇은 래퍼로 바뀐다(CLI 동작은 그대로)."""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    values = snapshot.values or {}

    interrupted = False
    prompt = None
    for task in snapshot.tasks:
        if task.interrupts:
            interrupted = True
            prompt = task.interrupts[0].value.get("prompt")
            break

    return {
        "exists": bool(values),
        "next_nodes": tuple(snapshot.next or ()),
        "interrupted": interrupted,
        "prompt": prompt,
        "draft_markdown": values.get("draft_markdown"),
        "draft_docx_path": values.get("draft_docx_path"),
        "chat_history": values.get("chat_history", []),
        "revision_count": values.get("revision_count", 0),
        "qa_count": values.get("qa_count", 0),
    }


def _check_existing_session(thread_id: str) -> Optional[dict]:
    """CLI 전용. get_session_state()의 얇은 래퍼로 축소한다."""
    with open_checkpointer(str(CHECKPOINT_DB_PATH)) as saver:
        snapshot = get_session_state(thread_id, build_graph(saver))
    if not snapshot["next_nodes"]:
        return None
    if not snapshot["interrupted"]:
        return None
    return {
        "paused": True,
        "draft_markdown": snapshot["draft_markdown"],
        "prompt": snapshot["prompt"],
    }
```

**(g) `__main__` 블록 맨 앞에 로깅 설정 한 줄**

```python
if __name__ == "__main__":
    import logging
    import sys

    # print를 log.info로 바꾼 뒤에도 CLI 출력이 지금과 똑같이 보이도록 하는 설정.
    # format이 "%(message)s"라 접두어 없이 메시지만 찍힌다 = 기존 print와 동일.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ...
```

### 10-3. `agents/router.py` — `QA_CAP` 추가

```python
# REVISION_CAP 바로 아래에 추가
# capability_qa 호출 상한(외부 검토보고서 ⑥). CLI에서는 사람이 직접 타이핑하니
# 무해했지만, API로 열면 같은 질문을 무한 반복해 LLM 비용을 태울 수 있다.
# REVISION_CAP과 마찬가지로 실증 근거 없는 임의값이다.
QA_CAP = 20
```

`orchestrator/graph.py`의 import에 추가:

```python
from agents.router import QA_CAP, REVISION_CAP, answer_capability_question, decide_next_action
```

### 10-4. `print` → `log.info` 치환 (전 파일)

대상: `agents/web_search.py`, `agents/market_research.py`, `agents/pestel.py`, `agents/competitor.py`, `agents/writer.py`, `agents/verification.py`, `agents/router.py`, `orchestrator/graph.py`, `rag/query.py`

**각 파일 상단(import 아래)에 두 줄 추가:**

```python
import logging

log = logging.getLogger(__name__)
```

**치환 규칙:**

| 원본 | 치환 후 | 비고 |
|---|---|---|
| `print(f"...")` | `log.info(f"...")` | 대부분 |
| `print("...")` | `log.info("...")` | |
| `print()` | `log.info("")` | 빈 줄 |
| `if __name__ == "__main__":` 블록 안의 사용법 안내 `print` | **그대로 둔다** | 진행 로그가 아니라 CLI 사용법 출력 |

> **주의**: 치환 후 반드시 `python -m orchestrator.graph "주제" "시장"`을 돌려 출력이 이전과 같은지 확인한다. 로깅 설정(10-2 (g))이 빠지면 아무것도 안 찍힌다.

### 10-5. 로그 3지점 추가 (설계도 7-5절)

**① `agents/web_search.py` — `search_web()` 안, ddgs 결과 append 직후**

```python
                results.append({...})   # 기존 코드
                log.info(
                    f"  [검색결과] {r.get('title', '')[:60]}",
                    extra={
                        "kind": "search_result",
                        "url": url,
                        "tier": classify_source_tier(url).value,
                        "title": r.get("title", ""),
                    },
                )
```

Brave 보완 루프(`for r in brave_results:`)의 `results.append(r)` 직후에도 같은 로그를 넣는다.

**② `agents/web_search.py` — `fetch_page_text()` 반환 직전**

```python
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            log.info(f"  [본문없음] {url}", extra={"kind": "fetch_failed", "url": url})
            return None
        clipped = text[:max_chars]
        log.info(
            f"  [본문읽기] {url} ({len(clipped)}자)",
            extra={"kind": "fetch", "url": url, "count": len(clipped)},
        )
        return clipped
    except Exception:
        log.info(f"  [읽기실패] {url}", extra={"kind": "fetch_failed", "url": url})
        return None
```

> `fetch_page_text()`는 status != 200이나 non-HTML일 때도 `return None`을 하는 분기가 있다. 그 분기에도 `fetch_failed` 로그를 넣는다.

**③ `agents/market_research.py:468` — fact 저장 로그에 출처 URL 추가**

```python
            if is_new:
                log.info(
                    f"  [fact 저장] ({stored_fact.source_tier.value}) {text}",
                    extra={
                        "kind": "fact",
                        "url": stored_fact.source_url,
                        "tier": stored_fact.source_tier.value,
                    },
                )
```

**이 세 지점이 "어느 사이트에 접속해 무엇을 읽어왔는지"를 만드는 최소 집합이다.**

### 10-6. `requirements.txt`

```
fastapi>=0.115.0
# uvicorn은 다른 패키지의 전이 의존성으로 이미 설치돼 있으나, 직접 실행에 쓰므로 명시
uvicorn[standard]>=0.30.0
```

같은 작업 중에 외부 검토 ⑥의 나머지도 함께 처리한다.

- `anthropic>=0.40.0` → **삭제** (코드 어디에서도 참조되지 않는 완전한 죽은 의존성)
- `google-generativeai>=0.8.0` → 주석 추가: `# Day1 연결 테스트(test_connection.py) 전용. 실제 파이프라인은 Upstage만 사용`

### 10-7. `.gitignore`

```
api/sessions.db
```

---

## 11. 구현 순서 — 단계별 검증

**각 단계의 "검증"을 통과한 뒤에만 다음으로 넘어간다.** 사용자 확인을 받고 진행한다.

| 단계 | 작업 | 검증 | 대략 |
|---|---|---|---|
| 1 | `pip install fastapi` · `requirements.txt` 갱신(10-6) · `api/__init__.py`·`main.py` 뼈대 + `/health` | `uvicorn api.main:app --port 8000` 기동 → `/docs`에 `/health`가 보이고 200 반환 | 30분 |
| 2 | 10-4 `print` → `log.info` 치환 + 10-2(g) 로깅 설정 | **`python -m orchestrator.graph "테스트" "테스트"`의 콘솔 출력이 치환 전과 동일**해야 함. 다르면 진행 금지 | 1시간 |
| 3 | 10-5 로그 3지점 추가 | CLI 실행 시 `[검색결과]`·`[본문읽기]`·`[fact 저장] ... ` 줄이 새로 보이는지 눈으로 확인 | 30분 |
| 4 | 10-1 `writer.py return_paths` + 10-2(a)(b)(c) | `run_writer(..., save=False, return_paths=True)`가 `(str, None)` 튜플을 반환하는지 확인 | 30분 |
| 5 | 10-2(f) `open_checkpointer`·`get_session_state`·`graph=` 인자 | `MemorySaver`로 `build_graph()` 후 `get_session_state()`가 예외 없이 dict를 반환하는지 확인. **CLI 재확인 필수** | 1시간 |
| 6 | `api/logbus.py` + `api/registry.py` | LLM 없이 순수 단위 테스트 — 이벤트 seq 증가·`events_since` 필터링·레지스트리 상태 전이 | 1시간 |
| 7 | `api/runner.py` + 필수 엔드포인트 5개 | **가짜 실행 함수**(`lambda: {"paused": True, ...}`)를 넣어 `POST /projects` → `GET /projects/{id}` 상태 전이를 LLM 없이 확인 | 1.5시간 |
| 8 | 실제 파이프라인 연결 | `/docs`에서 실제 주제로 `POST /projects` → 폴링하며 `current_step`이 시장조사→PESTEL·경쟁사→초안작성으로 바뀌는지, `/events`에 URL이 흐르는지 확인 | 사용자 로컬 필수 |
| 9 | 10-2(d)(e) `QA_CAP` + 편의 엔드포인트 6개 + 좀비 복구 | 서버 강제 종료 후 재기동 시 `running`이 `interrupted`로 바뀌는지 | 1.5시간 |

> **샌드박스 제약**: 7단계까지는 외부 API 없이 검증 가능하다. 8단계의 "실제 파이프라인 완주"는 웹검색·LLM 호출이 필요하므로 **사용자 로컬 실행이 필수**다. 지금까지의 모든 작업과 동일한 패턴이다.

---

## 12. 금지 사항 체크리스트

구현 완료 전에 이 목록을 훑는다. 하나라도 위반했으면 되돌린다.

- [ ] `AsyncSqliteSaver` / `ainvoke` / `astream`을 쓰지 않았다
- [ ] `agents/*.py`와 `orchestrator/graph.py`에 `async` 키워드를 추가하지 않았다
- [ ] 그래프 노드를 추가·삭제·분할하지 않았다 (12개 그대로)
- [ ] `graph.add_edge` 배선을 바꾸지 않았다
- [ ] `/events` 응답이 문자열 배열이 아니라 객체 배열이다
- [ ] DOCX 경로를 파일시스템 검색(`glob`, `sorted(...)[−1]` 등)으로 알아내지 않았다
- [ ] `checkpoints.db`에 우리 테이블을 만들지 않았다
- [ ] `python -m orchestrator.graph "주제" "시장"`이 이전과 똑같이 동작한다
- [ ] `print` 치환 시 `__main__`의 사용법 안내는 그대로 뒀다
- [ ] `_versioned_base_name()`, `export_to_docx()`, 검증·채점 로직을 건드리지 않았다

---

## 13. 장점 / 단점 / 한계

**장점**

- PRD Must("FastAPI 단일 엔드포인트를 통한 DOCX 다운로드")와 MVP 완료 기준을 충족한다.
- 그래프 코드를 거의 건드리지 않는다 — Task #4의 실기기 검증 결과가 대부분 유효하게 남는다.
- 위험도가 가장 높았던 비동기 전환이 설계 판단 하나로 사라진다(6-3절).
- **CLI의 진행 표시가 그대로 API로 흘러간다** — 이미 있는 자산 120줄을 버리지 않는다.
- 팬아웃 구간에서 "PESTEL · 경쟁사 분석 동시 진행 중"이 화면에 뜬다 — 멀티에이전트 병렬성이 눈에 보인다.
- SSE·카드 UI로 가는 길이 파괴적 변경 없이 열려 있다(7-3절).

**단점**

- 관리할 저장소가 세 개가 된다(`fact_store.db`, `checkpoints.db`, `sessions.db`).
- 폴링은 실시간이 아니다 — 2~3초 지연이 있고, 주기만큼 불필요한 요청이 발생한다.
- `print` → `log.info` 치환은 약 120곳의 기계적 변경이라, 검증(11절 2단계)을 건너뛰면 조용히 출력이 사라지는 사고가 난다.

**한계**

- **단일 프로세스·단일 사용자 전제.** uvicorn 워커를 여러 개 띄우면 각 워커가 별도의 락·`EVENT_BUS`를 갖게 되어 동시성 제어가 깨진다. **워커 1개 고정이 전제다.**
- **인증·권한이 없다.** project_id만 알면 남의 초안을 다운로드할 수 있다. MVP는 로컬 전용이라는 PRD 전제 아래 의도적으로 생략하며, 외부 배포 시 반드시 추가해야 한다.
- **진행 로그는 메모리에만 있다.** 서버를 재시작하면 사라진다(그래프 상태는 checkpointer에 남으므로 작업 자체는 이어진다). 영속화는 의도적으로 하지 않았다 — 로그는 진행 표시용이지 감사 기록이 아니기 때문.
- **`QA_CAP=20`, 타임아웃 1800초, `MAX_EVENTS_PER_PROJECT=2000`은 근거 없는 임의값**이다. `REVISION_CAP=5`, `adaptive_threshold`의 계수 0.5와 같은 종류의 미검증 설계값이며, 그렇게 명시해 둔다.
- **진행 상황은 노드 단위 + 로그 줄 단위까지만** 보여준다. "경쟁사 5곳 중 3곳 심층조사 완료" 같은 계산된 진행률은 없다 — 그건 구조화 이벤트를 더 촘촘히 심어야 얻어진다.
- 서버가 죽으면 실행 중이던 백그라운드 작업 자체는 유실된다. 완료된 노드까지만 체크포인터에 남는다.

---

## 14. 프론트엔드 설계 때 확정할 열린 항목

FastAPI 단계에서는 결정하지 않고 넘긴다.

1. **폴링 주기** — 상태는 2~3초, 이벤트는 1초? 지수 백오프? API는 주기에 무관하게 동작하므로 클라이언트 결정이다.
2. **초안 미리보기 길이** — 지금 1000자(`DRAFT_PREVIEW_CHARS`). 레이아웃에 따라 조정하거나 `/draft/markdown` 전문으로 대체.
3. **어떤 이벤트를 카드로 승격할지** — 지금은 `search_result`/`fetch`/`fact` 3종만 구조화돼 있다. 화면 디자인을 보고 더 늘릴지 정한다(7-4절 방식으로 지점당 몇 분).
4. **경쟁사·PESTEL 구조화 데이터 노출 여부** — `GET /projects/{id}/competitors` 같은 엔드포인트가 필요한지는 프론트가 표를 직접 그릴지 DOCX만 보여줄지에 달렸다.
5. **CORS 허용 출처** — `api/main.py`에 자리만 만들어뒀다.
6. **SSE 승격 시점** — 폴링으로 시연해보고 답답하면 그때. `GET /projects/{id}/events/stream`을 추가하고 `EVENT_BUS.subscribe()`를 쓰면 되며, 폴링 엔드포인트는 폴백으로 남긴다.

---

## 참고

- 프로젝트 내부: `router_orchestrator_설계안.md` 3-7절(API 계약 초안), `AI서비스기획보조_MultiAgent_통합기획문서.md`(FastAPI Must·MVP 완료 기준·TTAK.KO-10.0771/R1 참고 지침), `검토보고서_외부리뷰_2026-07-24.md` ④·⑥, `시장조사-PESTEL-경쟁사분석-파이프라인.md` 17·22·33절, `orchestrator/graph.py`, `agents/writer.py`, `agents/web_search.py`, `agents/market_research.py`
- 이 문서에서 인용한 코드 위치·줄 번호는 2026-07-27 기준 실제 파일을 직접 확인한 것이다.
