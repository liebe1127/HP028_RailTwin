#!/usr/bin/env bash
# NCP 서버에서 GitHub main을 받아 반영한 뒤 FastAPI 서비스를 재시작한다.
# GitHub Actions (push to main) 또는 수동: bash scripts/ncp_deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/HP028_RailTwin}"
BRANCH="${DEPLOY_BRANCH:-main}"
SERVICE="${SERVICE_NAME:-fastapi.service}"

cd "$APP_DIR"

echo "[deploy] $(date -Is) dir=$APP_DIR branch=$BRANCH"

git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

# 서버 전용 인증서(깃에 없음)가 pull 후에도 남아 있는지 확인
if [[ ! -f "$APP_DIR/cert.pem" || ! -f "$APP_DIR/key.pem" ]]; then
  echo "[deploy] WARN: cert.pem/key.pem 없음 — HTTPS 기동 전 인증서를 배치하세요." >&2
fi

if [[ -x "$APP_DIR/venv/bin/python" ]] && ! "$APP_DIR/venv/bin/python" -c "import paho.mqtt.client" >/dev/null 2>&1; then
  echo "[deploy] paho-mqtt missing — installing MQTT dependency"
  "$APP_DIR/venv/bin/pip" install --no-cache-dir 'paho-mqtt>=2.1.0'
fi

if [[ "${INSTALL_DEPS:-0}" == "1" && -x "$APP_DIR/venv/bin/pip" ]]; then
  echo "[deploy] pip install (no-cache) INSTALL_DEPS=1"
  "$APP_DIR/venv/bin/pip" install --no-cache-dir -r "$APP_DIR/requirements.txt"
fi

if [[ -f "$APP_DIR/scripts/install_grafana_edge.sh" ]]; then
  bash "$APP_DIR/scripts/install_grafana_edge.sh"
fi

if systemctl list-unit-files "$SERVICE" --no-legend 2>/dev/null | grep -q "$SERVICE"; then
  systemctl restart "$SERVICE"
  systemctl --no-pager --full status "$SERVICE" | head -20
else
  echo "[deploy] WARN: $SERVICE 없음 — 코드만 갱신됨."
fi

echo "[deploy] done @ $(git rev-parse --short HEAD)"
