#!/usr/bin/env bash
# EC2 에서 실행한다 (GitHub Actions deploy.yml 이 ssh 로 부른다).
#   bash ~/chagok/deploy/deploy.sh <계정>.dkr.ecr.<리전>.amazonaws.com/chagok-api:<sha>
#
# 1) ECR 로그인 (EC2 Instance Role) → 2) pull → 3) alembic upgrade head
# 4) 재시작 → 5) /health 확인. 실패하면 이전 이미지로 되돌리고 exit 1
# 롤백은 이미지만 되돌린다. 마이그레이션은 이전 코드와도 호환되게 작성한다
set -euo pipefail

NEW_IMAGE="${1:?사용법: deploy.sh <이미지 URI:태그>}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_ENV="$APP_DIR/.image.env"
cd "$APP_DIR"

[ -f .env ] || { echo "❌ $APP_DIR/.env 가 없습니다. 운영 환경변수를 먼저 만들어 주세요"; exit 1; }

compose() { bash "$APP_DIR/deploy/compose.sh" "$@"; }

touch "$IMAGE_ENV"
PREV_IMAGE="$(sed -n 's/^API_IMAGE=//p' "$IMAGE_ENV")"

wait_healthy() {
    for _ in $(seq 1 15); do
        if curl -fsS http://127.0.0.1:8000/health > /dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

echo "▶ ECR 로그인"
REGISTRY="${NEW_IMAGE%%/*}"                      # <계정>.dkr.ecr.<리전>.amazonaws.com
REGION="$(echo "$REGISTRY" | cut -d. -f4)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"

echo "▶ pull $NEW_IMAGE"
docker pull "$NEW_IMAGE"

echo "▶ 마이그레이션 (alembic upgrade head)"
# 실패하면 set -e 로 여기서 멈춘다. 돌고 있던 컨테이너는 그대로 둔다
API_IMAGE="$NEW_IMAGE" compose run --rm --no-deps api alembic upgrade head

echo "▶ 재시작"
if API_IMAGE="$NEW_IMAGE" compose up -d --remove-orphans && wait_healthy; then
    echo "API_IMAGE=$NEW_IMAGE" > "$IMAGE_ENV"
    docker image prune -af --filter "until=72h" > /dev/null || true
    echo "✅ 배포 완료: $NEW_IMAGE"
    exit 0
fi

echo "❌ 헬스체크 실패. 최근 로그:"
API_IMAGE="$NEW_IMAGE" compose logs --tail 100 api || true

if [ -n "$PREV_IMAGE" ]; then
    echo "↩ 이전 이미지로 롤백: $PREV_IMAGE"
    API_IMAGE="$PREV_IMAGE" compose up -d --remove-orphans
    wait_healthy && echo "↩ 롤백 완료" || echo "⚠ 롤백 후에도 헬스체크 실패. 직접 확인이 필요합니다"
else
    echo "⚠ 첫 배포라 되돌릴 이미지가 없습니다"
fi
exit 1
