# corpusmind-engine — self-hosted lab deployment image.
#
# Multi-stage build:
#   1. builder: installs Python deps + the engine in editable mode
#   2. runtime: slim copy with only what's needed to run
#
# Tag with: docker build -t corpusmind/engine:0.1.0 -f infra/Dockerfile .

FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps for any C extensions (we keep engine deps pure-Python in
# the base install; Arabic/vision extras install their own as needed).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY engine/pyproject.toml engine/README.md /build/
COPY engine/app /build/app
COPY engine/ai /build/ai
COPY engine/api /build/api
COPY engine/ingestion /build/ingestion
COPY engine/nlp /build/nlp
COPY engine/stats /build/stats
COPY engine/discourse /build/discourse
COPY engine/vision /build/vision
COPY engine/multimodal /build/multimodal
COPY engine/storage /build/storage

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="corpusmind-engine"
LABEL org.opencontainers.image.description="Local-first, AI-native research environment for corpus linguistics and multimodal discourse analysis."
LABEL org.opencontainers.image.licenses="AGPL-3.0-only"
LABEL org.opencontainers.image.source="https://github.com/waleedmandour/CorpusMind"

WORKDIR /app

# Copy the venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Storage for projects — mount as a volume in production.
RUN mkdir -p /data
ENV CORPUSMIND_DATA_DIR=/data
ENV CORPUSMIND_HOST=0.0.0.0
ENV CORPUSMIND_PORT=8765

VOLUME ["/data"]

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fs http://127.0.0.1:8765/api/v1/health || exit 1

CMD ["corpusmind-engine"]
