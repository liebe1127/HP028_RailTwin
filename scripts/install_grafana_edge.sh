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
install_docker() {
  echo "[grafana] Docker가 없어 설치합니다. 실시간 화면은 이 동안 그대로 둡니다."
  apt-get update
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

if ! command -v docker >/dev/null 2>&1; then
  if ! install_docker; then
    echo "[grafana] Docker 설치 실패. 실시간 화면은 그대로 둡니다." >&2
    exit 0
  fi
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "[grafana] docker compose 플러그인이 없습니다. 실시간 화면은 그대로 둡니다." >&2
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

set_env() {
  local key="$1"
  local value="$2"
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
}

ensure_env INFLUX_TOKEN "your-influxdb-api-token-here"
ensure_env INFLUX_ADMIN_PASSWORD "replace-with-long-password"
set_env GRAFANA_ADMIN_USER "railtwin"
set_env GRAFANA_ADMIN_PASSWORD "11111111"

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

if ! curl -fsSk --max-time 3 https://127.0.0.1:8000/ >/dev/null 2>&1; then
  echo "[grafana] 8000번이 꺼져 있어 FastAPI를 먼저 다시 켭니다."
  rm -f /etc/systemd/system/fastapi.service.d/edge.conf
  systemctl daemon-reload
  systemctl restart fastapi.service || true
fi

echo "[grafana] 패키지 캐시만 지웁니다. 받아 둔 Grafana 이미지는 남깁니다."
apt-get clean || true
docker builder prune -af || true
journalctl --vacuum-size=20M || true
find /var/log -xdev -type f \( -name '*.gz' -o -name '*.1' -o -name '*.old' \) -delete || true
df -h /
avail_kb="$(df -Pk / | awk 'NR==2 {print $4}')"
echo "[grafana] 남은 용량 ${avail_kb} KB"
need_kb=1400000
if docker image inspect grafana/grafana-oss:11.4.0 >/dev/null 2>&1 \
  && docker image inspect influxdb:2.7 >/dev/null 2>&1; then
  need_kb=200000
  echo "[grafana] Grafana와 InfluxDB 이미지가 이미 있습니다."
fi
if (( avail_kb < need_kb )); then
  echo "[grafana] 남은 용량이 부족해 화면을 바꾸지 않습니다. 실시간 화면은 그대로 둡니다."
  exit 0
fi

restore_fastapi() {
  rm -f /etc/systemd/system/fastapi.service.d/edge.conf
  systemctl daemon-reload
  systemctl restart fastapi.service || true
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
ExecStart=${UVICORN} main:app --host 0.0.0.0 --port 8001
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

grafana_login_ok() {
  local code
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 \
    -u "${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}" \
    https://127.0.0.1:8000/grafana/api/user || true)"
  [[ "$code" == "200" ]]
}

if ! grafana_login_ok; then
  echo "[grafana] 기존 관리자 계정을 지우고 로그인 이름을 다시 만듭니다. 저장된 주행 기록은 남습니다."
  docker compose -f docker-compose.grafana.yml stop grafana
  docker compose -f docker-compose.grafana.yml rm -f grafana
  docker volume rm railtwin-grafana_grafana-data
  if ! docker compose -f docker-compose.grafana.yml up -d grafana; then
    echo "[grafana] Grafana를 새 로그인으로 다시 켜지 못했습니다." >&2
    exit 1
  fi
  login_ok=0
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if grafana_login_ok; then
      login_ok=1
      break
    fi
    sleep 2
  done
  if [[ "$login_ok" != 1 ]]; then
    echo "[grafana] 새 로그인으로 들어가지 못했습니다." >&2
    exit 1
  fi
fi

echo "[grafana] 실시간 화면은 그대로이고, 지난 주행은 ${GRAFANA_ROOT_URL} 입니다."
echo "[grafana] Grafana 로그인 이름은 ${GRAFANA_ADMIN_USER} 입니다."
