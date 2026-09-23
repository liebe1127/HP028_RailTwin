#!/bin/sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/unity/RailTwinRails/Build/WebGL"
DST="$ROOT/frontend/unity"
if [ ! -d "$SRC/Build" ] && [ ! -d "$SRC" ]; then
  echo "Unity WebGL 산출물이 없습니다: $SRC"
  echo "unity/RailTwinRails/README.md 의 빌드 명령을 먼저 실행하세요."
  exit 1
fi
mkdir -p "$DST"
# Unity는 Build/WebGL/index.html + Build/ 또는 바로 wasm 폴더를 만든다.
if [ -d "$SRC/Build" ]; then
  rm -rf "$DST/Build"
  cp -R "$SRC/Build" "$DST/Build"
else
  mkdir -p "$DST/Build"
  cp -R "$SRC/"* "$DST/Build/"
fi
echo "copied to $DST/Build"
ls "$DST/Build"
