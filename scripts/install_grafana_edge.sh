#!/usr/bin/env bash
# 8000번 앞에 경로 나눔을 두고 /grafana 를 연다.
# FastAPI는 127.0.0.1:8001 로 옮긴다. InfluxDB 8086은 루프백만 연다.
# .env 에 비밀번호·토큰이 없으면 값을 만들어 .env에 넣고, 화면 비밀번호는 로그에 찍지 않는다.
# 조건이 안 되면 아무것도 바꾸지 않고 끝난다.
set -euo pipefail

APP_DIR="${APP_DIR:-/var/www/HP028_RailTwin}"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "[grafana] .env 없음. 실시간 화면은 그대로 둡니다."
  exit 0
fi
if [[ ! -f cert.pem || ! -f key.pem ]]; then
  echo "[grafana] cert.pem 또는 key.pem 없음. 실시간 화면은 그대로 둡니다."
  exit 0
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "[grafana] docker 없음. 실시간 화면은 그대로 둡니다."
  exit 0
fi
if ! systemctl cat fastapi.service >/dev/null 2>&1; then
  echo "[grafana] fastapi.service 없음. 실시간 화면은 그대로 둡니다."
  exit 0
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

ensure_env() {
  local key="$1"
  local reject="${2:-}"
  local current="${!key:-}"
  if [[ -n "$current" && "$current" != "$reject" ]]; then
    return 0
  fi
  local value
  value="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  python3 - "$key" "$value" << 'PY'
import pathlib, sys
key, value = sys.argv[1], sys.argv[2]
path = pathlib.Path(".env")
lines = path.read_text().splitlines()
found = False
out = []
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    if out and out[-1] != "":
        out.append("")
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n")
PY
  export "${key}=${value}"
  echo "[grafana] ${key} 를 서버 .env에 넣었습니다. 값은 로그에 남기지 않습니다."
}

ensure_env INFLUX_TOKEN "your-influxdb-api-token-here"
ensure_env INFLUX_ADMIN_PASSWORD "replace-with-long-password"
ensure_env GRAFANA_ADMIN_PASSWORD "replace-with-long-password"

if [[ -z "${INFLUX_ORG:-}" ]]; then
  echo "[grafana] INFLUX_ORG 가 비어 있습니다. 실시간 화면은 그대로 둡니다."
  exit 0
fi

export INFLUX_BUCKET="${INFLUX_BUCKET:-crane_data}"
export GRAFANA_ROOT_URL="${GRAFANA_ROOT_URL:-https://223.130.128.198:8000/grafana/}"
export GRAFANA_DOMAIN="${GRAFANA_DOMAIN:-223.130.128.198}"
export EDGE_CERT_FILE="${APP_DIR}/cert.pem"
export EDGE_KEY_FILE="${APP_DIR}/key.pem"
export API_UPSTREAM="host.docker.internal:8001"
export GRAFANA_ADMIN_USER="${GRAFANA_ADMIN_USER:-admin}"
export INFLUX_ADMIN_USER="${INFLUX_ADMIN_USER:-admin}"

UVICORN="$(python3 - << 'PY'
import re, subprocess, sys
text = subprocess.check_output(["systemctl", "cat", "fastapi.service"], text=True)
match = re.search(r"(/\S*uvicorn)\b", text)
if not match:
    sys.exit(1)
print(match.group(1))
PY
)" || true

if [[ -z "$UVICORN" || ! -x "$UVICORN" ]]; then
  echo "[grafana] uvicorn 실행 파일을 찾지 못했습니다. 실시간 화면은 그대로 둡니다."
  exit 0
fi

restore_fastapi() {
  rm -f /etc/systemd/system/fastapi.service.d/edge.conf
  systemctl daemon-reload
  systemctl start fastapi.service || true
}

echo "[grafana] 8000번을 경로 나눔으로 바꿉니다. 잠시 대시보드가 끊깁니다."
systemctl stop fastapi.service

if ! docker compose -f docker-compose.grafana.yml up -d --build; then
  echo "[grafana] 컨테이너 기동 실패. FastAPI를 원래 포트로 되돌립니다." >&2
  docker compose -f docker-compose.grafana.yml stop edge >/dev/null 2>&1 || true
  restore_fastapi
  exit 1
fi

install -d /etc/systemd/system/fastapi.service.d
cat > /etc/systemd/system/fastapi.service.d/edge.conf << EOF
[Service]
WorkingDirectory=${APP_DIR}
Environment=INFLUX_URL=http://127.0.0.1:8086
ExecStart=
ExecStart=${UVICORN} main:app --host 127.0.0.1 --port 8001
EOF

systemctl daemon-reload
if ! systemctl start fastapi.service; then
  echo "[grafana] FastAPI를 8001에서 켜지 못했습니다. 원래대로 되돌립니다." >&2
  docker compose -f docker-compose.grafana.yml stop edge >/dev/null 2>&1 || true
  restore_fastapi
  exit 1
fi

ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsSk --max-time 5 https://127.0.0.1:8000/ >/dev/null; then
    ok=1
    break
  fi
  sleep 2
done

if [[ "$ok" != 1 ]]; then
  echo "[grafana] https://127.0.0.1:8000/ 이 응답하지 않습니다. 원래대로 되돌립니다." >&2
  docker compose -f docker-compose.grafana.yml stop edge >/dev/null 2>&1 || true
  restore_fastapi
  exit 1
fi

echo "[grafana] 실시간 화면은 그대로이고, 지난 주행은 ${GRAFANA_ROOT_URL} 입니다."
echo "[grafana] Grafana 로그인 이름은 ${GRAFANA_ADMIN_USER} 이고, 비밀번호는 서버 .env 의 GRAFANA_ADMIN_PASSWORD 입니다."
