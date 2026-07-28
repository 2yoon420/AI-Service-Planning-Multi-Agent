#!/usr/bin/env bash
# 야간 백업. crontab: 0 3 * * *  /opt/planner/app/deploy/backup.sh
#
# SQLite는 파일을 그냥 cp 하면 쓰기 도중 스냅샷을 떠서 깨질 수 있다.
# .backup 명령은 잠금을 올바로 잡으므로 이쪽을 쓴다.
set -euo pipefail

DATA_DIR=${DATA_DIR:-/mnt/data}
BUCKET=${BACKUP_BUCKET:?BACKUP_BUCKET 환경변수가 필요합니다}
STAMP=$(date +%Y%m%d-%H%M%S)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for db in fact_store sessions checkpoints; do
  src="$DATA_DIR/$db.db"
  [ -f "$src" ] || continue
  sqlite3 "$src" ".backup '$TMP/$db.db'"
done

# 산출물 DOCX도 함께. 없으면 건너뛴다.
[ -d "$DATA_DIR/outputs" ] && cp -r "$DATA_DIR/outputs" "$TMP/outputs" || true

tar -czf "$TMP/backup-$STAMP.tar.gz" -C "$TMP" $(cd "$TMP" && ls | grep -v '\.tar\.gz$')

# snap으로 깔린 gsutil은 $HOME이 /opt/planner처럼 /home 밖에 있으면 막힌다.
# ("Sorry, home directories outside of /home needs configuration.") 이건 snapd가
# 실행 전에 실제 계정 홈(/etc/passwd)을 직접 확인하는 것이라 $HOME 재정의로도 못 피한다.
# venv에 pip로 설치한 gsutil은 순수 파이썬 패키지라 이 제약 자체가 없다.
GSUTIL="/opt/planner/venv/bin/gsutil"
[ -x "$GSUTIL" ] || GSUTIL=gsutil   # venv에 없으면(로컬 테스트 등) PATH의 것으로 폴백
"$GSUTIL" -q cp "$TMP/backup-$STAMP.tar.gz" "gs://$BUCKET/backups/"
echo "백업 완료: gs://$BUCKET/backups/backup-$STAMP.tar.gz"
