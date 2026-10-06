#!/usr/bin/env bash
# 운영 compose 래퍼. 지금 배포된 이미지(.image.env 의 API_IMAGE)로 docker compose 를 실행한다
#   ~/chagok/deploy/compose.sh ps
#   ~/chagok/deploy/compose.sh logs -f api
#   ~/chagok/deploy/compose.sh run --rm api python -m app.jobs.block_alert
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
touch "$APP_DIR/.image.env"
exec docker compose --project-directory "$APP_DIR" --env-file "$APP_DIR/.image.env" \
    -f "$APP_DIR/docker-compose.prod.yml" "$@"
