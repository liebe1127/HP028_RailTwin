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

# 실험 중 판정 코드만 올릴 때는 Grafana를 다시 설치하지 않는다.
# 그 설치는 FastAPI를 잠시 멈추고 8000번 앞의 경로 나눔을 다시 만든다.
# 지난 주행 화면을 다시 깔 때만 INSTALL_GRAFANA=1 로 실행한다.
grafana_failed=0
if [[ "${INSTALL_GRAFANA:-0}" == "1" && -f "$APP_DIR/scripts/install_grafana_edge.sh" ]]; then
  bash "$APP_DIR/scripts/install_grafana_edge.sh" || grafana_failed=1
else
  echo "[deploy] Grafana 재설치는 건너뜁니다. FastAPI만 재시작합니다."
fi

if systemctl list-unit-files "$SERVICE" --no-legend 2>/dev/null | grep -q "$SERVICE"; then
  systemctl restart "$SERVICE"
  systemctl --no-pager --full status "$SERVICE" | head -20
else
  echo "[deploy] WARN: $SERVICE 없음 — 코드만 갱신됨."
fi

echo "[deploy] done @ $(git rev-parse --short HEAD)"
if [[ "$grafana_failed" == 1 ]]; then
  echo "[deploy] Grafana 설치가 실패했습니다. 실시간 화면은 원래 8000번으로 되돌렸습니다." >&2
  exit 1
fi
