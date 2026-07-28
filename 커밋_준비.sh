#!/usr/bin/env bash
# 커밋 직전 상태로 만드는 스크립트 (2026-07-28, 같은 날 보강)
#
# 왜 스크립트인가: 개발 샌드박스의 연결 폴더는 파일 삭제가 막혀 있고, git은 인덱스를
# 갱신할 때 기존 index 파일을 교체(=삭제)해야 하므로 거기서는 staging이 불가능하다.
# .gitignore 정리는 이미 끝나 있으니, 이 스크립트는 git 조작만 한다.
#
# 이 스크립트는 커밋하지 않는다. 스테이징까지만 하고 멈춘다.
#
# [보강 내역]
#  - .gitignore에 frontend/node_modules(95MB)·dist가 빠져 있던 것을 사전 반영함.
#    스크립트에서도 실행 전에 그 사실을 재확인한다(0-1단계).
#  - 인덱스에 남아 있는 유니코드 정규화(NFC/NFD) 중복 항목을 정리한다(2-1단계).
#    macOS에서 실행해야 안전하므로 여기서 처리한다.

set -euo pipefail
cd "$(dirname "$0")"

echo "== 0/5  잔여 락 정리 =="
# 샌드박스에서 이름만 바꿔둔 잔여물. 있으면 지운다.
rm -f .git/_stale-lock-2 .git/index.lock.stale-20260727 .git/index.lock 2>/dev/null || true
# 실패한 임시 객체도 함께 (git이 지우려다 권한이 없어 남긴 것들)
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null || true
echo "   완료"

echo "== 0-1/5  .gitignore 사전 확인 =="
# node_modules가 무시되지 않은 상태로 git add -A를 하면 95MB가 스테이징된다.
# 사후 점검(3단계)으로도 잡히지만 되돌리는 비용이 크므로 여기서 먼저 막는다.
miss=0
for pat in 'frontend/node_modules/' 'frontend/dist/' 'fact_store/fact_store.db'; do
  grep -qxF "$pat" .gitignore || { echo "   !! .gitignore에 '$pat' 없음"; miss=1; }
done
if [ "$miss" -ne 0 ]; then
  echo "   중단합니다. .gitignore를 먼저 채우세요."
  exit 1
fi
echo "   이상 없음"

echo "== 1/5  fact_store.db 추적 해제 =="
if git ls-files --error-unmatch fact_store/fact_store.db >/dev/null 2>&1; then
  git rm --cached fact_store/fact_store.db -q
  echo "   인덱스에서 제거 (디스크 파일과 fact 650건은 그대로)"
else
  echo "   이미 추적 해제됨"
fi

echo "== 2/5  전체 스테이징 =="
git add -A
echo "   $(git diff --cached --name-only | wc -l | tr -d ' ')개 스테이징"

echo "== 2-1/5  유니코드 정규화 중복 정리 =="
# 배경: macOS(NFC)와 Linux/FUSE(NFD)의 한글 파일명 인코딩이 달라, 같은 파일이
# 인덱스에 두 이름으로 들어가 있다. 파일 실체는 하나뿐이라 데이터 손실은 없지만,
# 그대로 두면 저장소에 유령 항목이 영구히 남는다.
# 안전장치: NFC 쌍이 인덱스에 함께 있을 때만 NFD 쪽을 제거한다.
python3 - <<'PY'
import subprocess, unicodedata, collections, sys

out = subprocess.run(['git','-c','core.quotePath=false','ls-files','-z'],
                     capture_output=True, check=True).stdout
paths = [p.decode('utf-8') for p in out.split(b'\0') if p]

groups = collections.defaultdict(list)
for p in paths:
    groups[unicodedata.normalize('NFC', p)].append(p)

targets = []
for nfc, variants in groups.items():
    if len(variants) < 2:
        continue
    # NFC 형태가 실제로 인덱스에 있을 때만, 나머지(NFD)를 제거 대상으로 삼는다
    if nfc in variants:
        targets += [v for v in variants if v != nfc]

if not targets:
    print("   중복 없음")
    sys.exit(0)

# macOS는 파일명을 NFC로 정규화해 전달하는 경우가 있어, NFD 경로를 git이 못 찾을 수
# 있다. 그때 스크립트 전체가 멈추면 안 되므로(이 단계는 위생 작업이지 필수가 아님)
# 실패는 경고만 남기고 넘어간다. 남은 중복은 커밋 후 따로 정리해도 무방하다.
done_n = 0
for t in targets:
    r = subprocess.run(['git','rm','--cached','-q','--',t],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"   제거: {t}")
        done_n += 1
    else:
        print(f"   건너뜀(경로 매칭 실패): {t}")

print(f"   {done_n}/{len(targets)}건 정리 (파일 실체는 그대로)")
if done_n < len(targets):
    print("   ※ 남은 항목은 커밋을 막지 않습니다. 나중에 정리해도 됩니다.")
PY

echo "== 3/5  안전 점검 =="
fail=0
# 비밀키가 섞이지 않았는지
if git diff --cached --name-only | grep -qx '.env'; then
  echo "   !! .env가 스테이징됐습니다. 중단하세요."; fail=1
fi
if git diff --cached | grep -qE 'tvly-[A-Za-z0-9]|up_[A-Za-z0-9]{20}'; then
  echo "   !! API 키로 보이는 문자열이 diff에 있습니다. 확인하세요."; fail=1
fi
# 큰 파일이 섞이지 않았는지
big=$(git diff --cached --name-only | while read -r f; do
        [ -f "$f" ] && [ "$(wc -c < "$f")" -gt 2000000 ] && echo "$f"
      done || true)
[ -n "$big" ] && { echo "   !! 2MB 넘는 파일: $big"; fail=1; }
# node_modules / dist / db
git diff --cached --name-only | grep -q 'node_modules' && { echo "   !! node_modules 포함됨"; fail=1; }
git diff --cached --name-only | grep -q '^frontend/dist/' && { echo "   !! frontend/dist 포함됨"; fail=1; }
git diff --cached --name-only | grep -qE '\.db$' && { echo "   !! .db 파일 포함됨"; fail=1; }
# 배포에 반드시 필요한 것이 빠지지 않았는지 (가이드 1-3절)
for need in 'paths.py' 'frontend/package-lock.json'; do
  if ! git ls-files --error-unmatch "$need" >/dev/null 2>&1; then
    echo "   !! $need 가 인덱스에 없습니다"; fail=1
  fi
done
[ "$fail" -eq 0 ] && echo "   이상 없음"

echo "== 4/5  배포 필수 경로 확인 (가이드 1-3절) =="
echo "   -- api/·frontend/·tests/·paths.py·deploy/ --"
git ls-files | grep -E '^(api/|frontend/|tests/|paths\.py|deploy/)' | head -8
echo "   -- .db 파일 (아무것도 안 나와야 정상) --"
git ls-files | grep '\.db$' || echo "   (없음 — 정상)"

echo "== 5/5  요약 =="
git status --short
echo
echo "-----------------------------------------------------------"
echo "여기까지가 '커밋 직전' 상태입니다. 확인 후 아래를 실행하세요."
echo
cat <<'MSG'
git commit -m "FastAPI·프론트엔드·pytest 54종·Tavily 연동·배포 설정 (7/25~7/28)

- api/: FastAPI 11개 엔드포인트, 진행 이벤트 버스, 백그라운드 실행
- frontend/: React+Vite 3단 레이아웃, 메인 화면 차별점 개편
- tests/: pytest 54개 (상태전이·API계약·로그버스·fact store·Tavily)
- fact_store: 프로젝트 간 근거 유실 버그 수정 (topic 스코핑)
- web_search: Brave 제거, Tavily 검색·추출 2계층 도입
- paths.py: DATA_DIR로 저장 경로 분리 (배포 시 데이터 보호)
- deploy/: systemd·Caddy·배포/백업 스크립트
- 설계 문서를 프로젝트 상위 폴더로 이동 (저장소는 코드만 유지)
- fact_store.db 추적 해제 (배포 시 덮어쓰기 방지)"
MSG
echo
echo "그다음 main 병합:"
echo "  git checkout main && git merge feature/router-orchestrator && git push origin main"
echo "-----------------------------------------------------------"
