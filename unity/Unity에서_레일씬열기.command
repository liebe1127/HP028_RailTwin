#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNITY_APP="/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app"
PROJECT="$ROOT/unity/RailTwinRails"

if [[ ! -d "$UNITY_APP" ]]; then
  echo "Unity 6000.6.0f1 이 없습니다: $UNITY_APP"
  echo "Unity Hub → Installs 에서 이 버전을 설치하세요."
  exit 1
fi
if [[ ! -d "$PROJECT/Assets" ]]; then
  echo "Unity 프로젝트가 없습니다: $PROJECT"
  exit 1
fi

open -a "$UNITY_APP" --args -projectPath "$PROJECT"
echo "Unity에서 여는 중: $PROJECT"
