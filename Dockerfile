# Zeloo Agent Dockerfile
# Multi-stage build for production deployment
#
# Usage:
#   docker build -t zeloo:latest .
#   docker run -e ZELOO_MODE=gateway -p 8080:8080 zeloo:latest
#
# With s6-overlay (multi-service):
#   docker build -f Dockerfile -t zeloo:s6 --target s6 .
#   docker run -p 8080:8080 zeloo:s6

# ─── Build stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# ─── Production stage ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS production

# Security: create non-root user
RUN groupadd --gid 1000 zeloo \
    && useradd --uid 1000 --gid zeloo --shell /bin/bash --create-home zeloo

WORKDIR /app

# Runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    nodejs \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtualenv from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Copy application code
COPY --chown=zeloo:zeloo . .

# ── Docker support scripts ───────────────────────────────────────────────────
COPY --chmod=0755 docker/entrypoint-dispatch.sh /usr/local/bin/
COPY --chmod=0755 docker/main-wrapper.sh /usr/local/bin/
COPY --chmod=0755 docker/tini-shim.sh /usr/local/bin/
COPY --chown=zeloo:zeloo docker/config.docker.yaml /app/

# s6-overlay service definitions
COPY --chmod=0755 docker/s6-rc.d/ /etc/s6-overlay/s6-rc.d/
COPY --chmod=0755 docker/cont-init.d/ /etc/cont-init.d/

# ── Data directories ─────────────────────────────────────────────────────────
RUN mkdir -p /var/lib/zeloo/.zeloo \
    && mkdir -p /var/lib/zeloo/skills \
    && mkdir -p /var/lib/zeloo/logs \
    && mkdir -p /var/lib/zeloo/memory \
    && chown -R 1000:1000 /var/lib/zeloo

ENV ZELOO_MODE=cli
ENV ZELOO_DATA_DIR=/var/lib/zeloo

# ── Entrypoint ─────────────────────────────────────────────────────────────
ENTRYPOINT ["/usr/local/bin/entrypoint-dispatch.sh"]
CMD ["cli"]

# ── Ports & health ─────────────────────────────────────────────────────────
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=5)"

# ── Labels ────────────────────────────────────────────────────────────────
LABEL org.opencontainers.image.title="Zeloo Agent"
LABEL org.opencontainers.image.description="Self-evolving AI Agent runtime"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.source="https://github.com/zeloo/zeloo"
LABEL org.opencontainers.image.licenses="MIT"

# ── s6 multi-service target ───────────────────────────────────────────────
FROM production AS s6
COPY --from=ghcr.io/just-containers/s6-overlay:latest / /
ENTRYPOINT ["/init"]
CMD ["/bin/sh", "-l"]
