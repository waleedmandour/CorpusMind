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
COPY engine/sentiment /build/sentiment
COPY engine/vision /build/vision
COPY engine/multimodal /build/multimodal
COPY engine/storage /build/storage
COPY engine/reference_corpus /build/reference_corpus
COPY engine/export_queue /build/export_queue
# v1.2.0: learner (CAF/CIA/error-patterns, imported by api/learner.py) and
# semantic (Vector KWIC, imported by api/analysis.py) — both were missing
# here, so the v1.2.0 image shipped a wheel without them and the engine
# died at boot with ModuleNotFoundError: No module named 'learner'.
COPY engine/learner /build/learner
COPY engine/semantic /build/semantic

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
# v1.2.10: bake the spaCy pipeline model so a freshly pulled image can
# parse/tokenize with zero out-of-band downloads (the runtime stage has no
# spacy CLI step, and /health/resources reports it). ~12 MB wheel.
    python -m spacy download en_core_web_sm


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="corpusmind-engine"
LABEL org.opencontainers.image.description="Local-first, AI-native research environment for corpus linguistics and multimodal discourse analysis."
LABEL org.opencontainers.image.licenses="AGPL-3.0-only"
LABEL org.opencontainers.image.source="https://github.com/waleedmandour/CorpusMind"

WORKDIR /app

# Copy the venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# v1.2.10: bake the bundled reference-data pack (USAS tagsets, wordlists,
# reference corpora, framework YAMLs — ~1.5 MB) into the image. Before this,
# EVERY Docker deployment ran with the USAS lens 503ing and the Academic
# Word List silently degraded, because no site-packages-relative walk can
# find repo-root data and nothing mounted it. The resolver picks this up
# via CORPUSMIND_REFERENCE_DATA_DIR (see app/resource_paths.py). Labs can
# still mount a custom pack over /app/reference-data.
COPY reference-data /app/reference-data
ENV CORPUSMIND_REFERENCE_DATA_DIR=/app/reference-data

# Storage for projects — mount as a volume in production.
RUN mkdir -p /data
ENV CORPUSMIND_DATA_DIR=/data
ENV CORPUSMIND_HOST=0.0.0.0
ENV CORPUSMIND_PORT=8765

VOLUME ["/data"]

EXPOSE 8765

# Issue 4 fix: the runtime image is python:3.12-slim, which ships no curl/wget —
# the previous curl-based healthcheck could never pass. Use a stdlib probe instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health'); sys.exit(0)"]

CMD ["corpusmind-engine"]
