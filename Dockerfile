# RailTwin FastAPI — Naver Cloud / demo 시연용 (CPU torch)
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RBF_MODEL_PATH=rbf_dummy_model.pth

WORKDIR /app

# 시스템 의존성 (PyWavelets/numpy 빌드·런타임)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# CPU용 PyTorch 먼저 설치 (CUDA 휠보다 이미지·메모리 부담이 작음)
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu

# torch를 제외한 나머지 앱 의존성
COPY requirements.txt .
RUN grep -v -E '^torch|^#' requirements.txt | grep -v -E '^[[:space:]]*$' > /tmp/req.docker.txt \
    && pip install -r /tmp/req.docker.txt

COPY . .

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
