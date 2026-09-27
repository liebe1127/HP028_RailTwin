#!/bin/sh
set -e
ok=0
warn=0
fail() { echo "FAIL  $1"; ok=1; }
note() { echo "WARN  $1"; warn=1; }
good() { echo "OK    $1"; }

echo "RailTwin 개발 환경 점검"
echo

if [ "$(uname -m)" = "arm64" ]; then
  good "CPU $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo arm64)"
else
  note "CPU가 arm64가 아닙니다. Unity는 Apple Silicon 에디터를 쓰세요."
fi

HUB="/Applications/Unity Hub.app"
UNITY="/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app"
WEBGL="/Applications/Unity/Hub/Editor/6000.6.0f1/PlaybackEngines/WebGLSupport"
if [ -d "$HUB" ]; then good "Unity Hub"; else fail "Unity Hub 없음"; fi
if [ -d "$UNITY" ]; then good "Unity 6000.6.0f1"; else fail "Unity 6000.6.0f1 없음"; fi
if [ -d "$WEBGL" ]; then good "WebGL 모듈"; else fail "WebGL(Web Build Support) 모듈 없음 — Hub에서 Add modules"; fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/unity/RailTwinRails/ProjectSettings/ProjectVersion.txt" ]; then
  good "Unity 프로젝트 unity/RailTwinRails"
else
  fail "unity/RailTwinRails 없음"
fi
if [ -f "$ROOT/frontend/unity/Build/WebGL.wasm" ]; then
  good "대시보드 WebGL 산출물 frontend/unity/Build"
else
  note "frontend/unity/Build/WebGL.wasm 없음 — 빌드 후 scripts/sync_unity_webgl.sh"
fi

if python3 -c "import fastapi, uvicorn, numpy" >/dev/null 2>&1; then
  good "Python FastAPI/uvicorn/numpy ($(python3 --version 2>&1))"
else
  fail "python3 에서 fastapi/uvicorn/numpy import 실패 — pip3 install -r requirements.txt"
fi
if [ -f "$ROOT/.env" ]; then
  good ".env 존재"
else
  note ".env 없음 — cp .env.example .env"
fi
if python3 -c "import pytest" >/dev/null 2>&1; then
  good "pytest"
else
  note "pytest 없음 — python3 -m pip install --user pytest"
fi

if [ -d "/Applications/Arduino IDE.app" ]; then
  good "Arduino IDE"
else
  note "Arduino IDE 없음 (펌웨어 작업 시)"
fi
if command -v arduino-cli >/dev/null 2>&1; then
  good "arduino-cli"
else
  note "arduino-cli 없음 (펌웨어 작업 시)"
fi

if command -v docker >/dev/null 2>&1; then
  good "Docker"
else
  note "Docker 없음 — 로컬 더미 시연에는 필요 없음"
fi

echo
if [ "$ok" -ne 0 ]; then
  echo "필수 항목이 빠졌습니다. docs/mac-m5-unity-onboarding.md 를 보세요."
  exit 1
fi
if [ "$warn" -ne 0 ]; then
  echo "필수 엔진은 있습니다. WARN은 해당 역할을 할 때만 채우면 됩니다."
  exit 0
fi
echo "필수 엔진 준비됨. Unity Hub에서 unity/RailTwinRails 를 여세요."
