#!/bin/zsh
# Gemini / ChatGPT에 올릴 md를 Finder에서 바로 집기 위한 버튼.
# 이 파일을 더블클릭하면 docs 폴더가 열리고, AI 학습용 파일이 선택된 상태로 나온다.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HERE/핵심기술스택과_작업절차_AI학습용_Tech-Stack-and-Workflow.md"

if [[ -f "$TARGET" ]]; then
  open -R "$TARGET"
else
  open "$HERE"
fi
