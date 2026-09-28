#!/usr/bin/env bash
# 커밋된 main을 NCP FastAPI에 반영한다.
# rail_defect.py, main.py 등 판정 파이썬을 고친 뒤 커밋하고 이 스크립트를 실행한다.
# Grafana는 다시 설치하지 않고, 서버가 git pull 한 다음 fastapi.service만 재시작한다.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "[push_logic] main 브랜치에서만 올립니다. 지금: $(git branch --show-current)" >&2
  exit 1
fi

dirty="$(git status --porcelain -- rail_defect.py main.py sensor_contract.py run_export.py tests/test_pipeline.py)"
if [[ -n "$dirty" ]]; then
  echo "[push_logic] 판정 파이썬에 커밋되지 않은 수정이 있습니다. 커밋한 뒤 다시 실행하세요." >&2
  echo "$dirty" >&2
  exit 1
fi

git push origin main

echo "[push_logic] 배포가 끝날 때까지 기다립니다."
for _ in 1 2 3 4 5 6 7 8 9 10; do
  run_id="$(gh run list --workflow=deploy-ncp.yml --branch main --limit 1 --json databaseId,headSha,status --jq '.[0] | select(.headSha=="'"$(git rev-parse HEAD)"'") | .databaseId')"
  if [[ -n "$run_id" ]]; then
    break
  fi
  sleep 2
done

if [[ -z "${run_id:-}" ]]; then
  echo "[push_logic] GitHub 배포 실행을 찾지 못했습니다." >&2
  exit 1
fi

gh run watch "$run_id" --exit-status

local_sha="$(git rev-parse --short HEAD)"
remote_sha="$(ssh -o ConnectTimeout=8 railtwin-ncp "cd /var/www/HP028_RailTwin && git rev-parse --short HEAD && systemctl is-active fastapi.service")"
echo "[push_logic] 로컬 ${local_sha}"
echo "[push_logic] 서버 ${remote_sha}"
curl -fsSk --max-time 10 "https://223.130.128.198:8000/" | python3 -c 'import json,sys; body=json.load(sys.stdin); print("status", body.get("status"), "demo_mode", body.get("demo_mode"), "rule_engine", body.get("rule_engine"))'
