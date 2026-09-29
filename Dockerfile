# CV-Scope, CPU-only image. For NVIDIA GPUs use Dockerfile.gpu.
# Build:  docker build -t cv-scope:cpu .
# Run:    docker run -p 8420:8420 -v cvscope-data:/app/data cv-scope:cpu

# ---- frontend build -------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
# The in-app guides are bundled from docs/guides
COPY docs/guides /build/docs/guides
RUN npm run build

# ---- backend --------------------------------------------------------------
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATHSCOPE_HOST=0.0.0.0 \
    PATHSCOPE_PORT=8420 \
    PATHSCOPE_DATA_DIR=/app/data \
    PATHSCOPE_CORS_ORIGINS=http://localhost:8420,http://127.0.0.1:8420
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml backend/README.md backend/alembic.ini /app/backend/
COPY backend/alembic /app/backend/alembic
COPY backend/pathscope /app/backend/pathscope
# CPU build of PyTorch keeps the image small; ultralytics is AGPL-3.0 (see docs/models.md)
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install -e "/app/backend[ultralytics,onnx-cpu,export,postgres]"
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY README.md /app/README.md
VOLUME ["/app/data"]
EXPOSE 8420
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -fs http://127.0.0.1:8420/api/system/status || exit 1
CMD ["cvscope", "serve"]
