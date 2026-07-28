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
gsutil -q cp "$TMP/backup-$STAMP.tar.gz" "gs://$BUCKET/backups/"
echo "백업 완료: gs://$BUCKET/backups/backup-$STAMP.tar.gz"
