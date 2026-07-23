#!/bin/sh
set -e

MODEL_PATH="${RBF_MODEL_PATH:-rbf_dummy_model.pth}"

# git clone 시 *.pth 가 없을 수 있음 → 더미 모델 자동 학습
if [ ! -f "$MODEL_PATH" ]; then
  echo "[entrypoint] 모델 없음 ($MODEL_PATH) — ml/train_rbf_surrogate.py 실행"
  python ml/train_rbf_surrogate.py
fi

exec "$@"
