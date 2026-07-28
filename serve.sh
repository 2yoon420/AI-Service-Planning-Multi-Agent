#!/usr/bin/env bash
# 로컬 개발 서버 실행 스크립트.
#
# 왜 이 스크립트가 있는가 (2026-07-28):
#   `uvicorn api.main:app --reload` 로 띄운 상태에서 파이프라인을 돌리는 중에 누군가
#   .py 파일을 저장하면, uvicorn이 서버 프로세스를 죽이고 재시작한다. 실행 중이던
#   그래프는 백그라운드 스레드에서 돌고 있으므로 프로세스와 함께 사라진다.
#   실제로 이 사고가 났다 — 한국 시장 실행이 시작 2분 만에 중단됐고(fact 0건),
#   원인은 같은 소스 트리에서 eval/ 스크립트를 수정하고 있었던 것이었다.
#
#   uvicorn이 감시하는 것은 `*.py` 뿐이다(DB·docx 쓰기는 무해하다). 확인:
#     python -c "from uvicorn.config import Config; \
#                from uvicorn.supervisors.watchfilesreload import FileFilter; \
#                print(FileFilter(Config('api.main:app', reload=True)).includes)"
#     → ['*.py']
#
# 사용법:
#   ./serve.sh          기본 — 실제 실행용. 리로드 없음. 어떤 파일을 고쳐도 안 죽는다
#   ./serve.sh dev      개발용 — 리로드 켜되 tests/·eval/ 변경은 무시한다
#
# 실제 파이프라인을 돌릴 때는 반드시 기본 모드를 쓸 것.

set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
MODE="${1:-run}"

if [ ! -d venv ]; then
  echo "!! venv가 없습니다. python -m venv venv && pip install -r requirements.txt"
  exit 1
fi
source venv/bin/activate

echo "검증 모델: $(python -c 'import agents.verification as V; print(V.VERIFICATION_MODEL)')"

if [ "$MODE" = "dev" ]; then
  echo "== 개발 모드 (리로드 O) — 파이프라인 실행 중에는 쓰지 말 것 =="
  # 앱 코드가 아닌 곳(tests·eval·outputs)의 변경으로는 재시작되지 않게 한다.
  # agents/·api/ 등 앱 코드는 여전히 감시 대상이다 — 그게 개발 모드의 목적이므로.
  exec uvicorn api.main:app --port "$PORT" --reload \
    --reload-exclude 'tests/*' \
    --reload-exclude 'eval/*' \
    --reload-exclude 'outputs/*' \
    --reload-exclude 'venv/*'
else
  echo "== 실행 모드 (리로드 X) — 소스를 고쳐도 진행 중 작업이 죽지 않습니다 =="
  exec uvicorn api.main:app --port "$PORT"
fi
