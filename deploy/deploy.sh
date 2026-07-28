#!/usr/bin/env bash
# 서버에서 실행하는 배포 스크립트. 목요일 CI/CD(#45)가 이걸 그대로 호출한다.
#
# 수동 배포를 먼저 성공시킨 뒤 자동화하는 순서를 지키기 위해, 오늘은 사람이
# 직접 돌리고 목요일에 GitHub Actions가 같은 스크립트를 부르게 한다.
# 그래야 실패했을 때 "배포 절차가 틀린 것"인지 "CI 설정이 틀린 것"인지 구분된다.

set -euo pipefail

APP_DIR=/opt/planner/app
VENV=/opt/planner/venv
WEB_DIR=/opt/planner/web
BRANCH="${1:-main}"

echo "== 1/6  소스 갱신 ($BRANCH) =="
cd "$APP_DIR"
git fetch --prune origin
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"     # 서버에서 손댄 흔적이 있어도 저장소 상태로 맞춘다

echo "== 2/6  데이터가 소스 트리 밖에 있는지 확인 =="
# 이 검사가 없으면 git reset --hard 가 fact_store.db를 되돌린다.
# DATA_DIR이 안 잡힌 채 배포되는 사고를 여기서 잡는다.
if [ -z "${DATA_DIR:-}" ]; then
  DATA_DIR=$(grep -Po '(?<=^Environment=DATA_DIR=).*' /etc/systemd/system/planner-api.service || true)
fi
if [ -z "${DATA_DIR:-}" ] || [ ! -d "$DATA_DIR" ]; then
  echo "!! DATA_DIR이 설정되지 않았거나 없는 경로입니다: '${DATA_DIR:-미설정}'"
  echo "!! 이대로 두면 배포할 때마다 수집한 fact가 저장소 버전으로 덮입니다. 중단합니다."
  exit 1
fi
echo "   DATA_DIR=$DATA_DIR  ($(du -sh "$DATA_DIR" | cut -f1))"

echo "== 3/6  파이썬 의존성 =="
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r requirements.txt

echo "== 4/6  테스트 =="
# 배포 전 마지막 관문. 여기서 막히면 서비스를 재시작하지 않는다.
( cd "$APP_DIR" && "$VENV/bin/python" -m pytest -q )

echo "== 5/6  프론트엔드 빌드 =="
cd "$APP_DIR/frontend"
npm ci --silent
# 같은 오리진에서 Caddy가 /api/* 를 백엔드로 넘기므로 상대경로면 충분하다.
VITE_API_BASE=/api npm run build --silent
rm -rf "$WEB_DIR".new && cp -r dist "$WEB_DIR".new
# 교체를 원자적으로 — 빌드 중간 상태가 사용자에게 보이지 않게 한다.
rm -rf "$WEB_DIR".old
[ -d "$WEB_DIR" ] && mv "$WEB_DIR" "$WEB_DIR".old
mv "$WEB_DIR".new "$WEB_DIR"
rm -rf "$WEB_DIR".old

echo "== 6/6  서비스 재시작 =="
sudo systemctl restart planner-api

# uvicorn이 모듈을 임포트하는 몇 초 동안은 포트가 비어 있다.
# 한 번만 찔러보면 이 정상적인 기동 구간을 장애로 오판할 수 있으므로 반복 확인한다.
# (2026-07-28 실측: 재시작~기동완료 4초. 15초·1초 간격은 그 위에 3배 이상 여유를 둔 값이며
#  근거 논문이나 SLA에서 온 수치가 아니다. 기동이 이보다 오래 걸리는 변경이 생기면 늘려야 한다.)
ATTEMPTS=15
until curl -fsS --max-time 2 http://127.0.0.1:8000/health > /dev/null 2>&1; do
  ATTEMPTS=$((ATTEMPTS - 1))
  if [ "$ATTEMPTS" -le 0 ]; then
    echo "!! /health 응답 없음(15초 경과). 로그:"
    sudo systemctl status planner-api --no-pager || true
    sudo journalctl -u planner-api -n 40 --no-pager
    exit 1
  fi
  sleep 1
done
echo "배포 완료 — $(date '+%F %T')"
