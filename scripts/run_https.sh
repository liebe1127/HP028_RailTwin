#!/usr/bin/env bash
# Nginx 없이 Uvicorn에 Let's Encrypt 인증서를 직접 붙여 HTTPS/WSS 기동
# 사용 (서버에서, 프로젝트 루트):
#   sudo bash scripts/run_https.sh
#
# 필요: Certbot으로 발급된 인증서
#   /etc/letsencrypt/live/<DOMAIN>/fullchain.pem
#   /etc/letsencrypt/live/<DOMAIN>/privkey.pem

set -euo pipefail

DOMAIN="${SSL_DOMAIN:-hp028-railtwin.duckdns.org}"
CERT="${SSL_CERTFILE:-/etc/letsencrypt/live/${DOMAIN}/fullchain.pem}"
KEY="${SSL_KEYFILE:-/etc/letsencrypt/live/${DOMAIN}/privkey.pem}"
HOST="${HOST:-0.0.0.0}"
PORT="${HTTPS_PORT:-443}"

if [[ ! -f "$CERT" ]]; then
  echo "[run_https] 인증서 없음: $CERT" >&2
  exit 1
fi
if [[ ! -f "$KEY" ]]; then
  echo "[run_https] 개인키 없음: $KEY" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

echo "[run_https] https://${DOMAIN}/  ·  wss://${DOMAIN}/ws  (port ${PORT})"
exec uvicorn main:app \
  --host "$HOST" \
  --port "$PORT" \
  --ssl-certfile "$CERT" \
  --ssl-keyfile "$KEY"
