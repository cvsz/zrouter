# Dockerfile — NVIDIA Free-Model Router
# Multi-stage build for production deployment

# Stage 1: Build dependencies
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.13-slim AS runtime

WORKDIR /app

# Install runtime dependencies (ca-certificates for HTTPS, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -s /bin/false appuser

# Copy application files (NOT provider.json — keys must come from env)
COPY --chown=appuser:appuser zrouter.py zrouter_core.py zrouter_bot.py zrouter_bot_models.py zrouter_bot_storage.py zrouter_runtime.py models.json ./

# Create data directory
RUN mkdir -p /app/data /app/logs && chown appuser:appuser /app/data /app/logs

USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
ENV NVIDIA_RPM=35
ENV NVIDIA_CACHE_TTL=3600
ENV NVIDIA_TIMEOUT=90
ENV NVIDIA_MAX_WAIT=60
# ROUTER_TOKEN must be set at runtime (docker run -e ROUTER_TOKEN=...).
# Binding to 0.0.0.0 without a token causes serve() to fail closed.
ENV ROUTER_TOKEN=""

# Expose port for the OpenAI-compatible proxy
EXPOSE 8000

# Healthcheck runs on localhost (loopback), where no token is required.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f -H "Authorization: Bearer ${ROUTER_TOKEN}" http://localhost:8000/health || exit 1

# Default command: run the OpenAI-compatible proxy.
# Binding to 0.0.0.0 exposes the proxy on all interfaces; ROUTER_TOKEN is
# required (serve() fails closed without it). Always set ROUTER_TOKEN at runtime.
ENTRYPOINT ["python", "zrouter.py"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
