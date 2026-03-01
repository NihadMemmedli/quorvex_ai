# K6 Load Test Worker
# Lightweight image for running K6 load tests via Redis queue
# ~200-300MB (no browser, no Node.js, no Playwright)

FROM python:3.10-slim-bookworm

# Install curl for K6 download
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Grafana K6 load testing tool (multi-arch: works on both amd64 and arm64)
RUN K6_VERSION="v0.54.0" && \
    ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/grafana/k6/releases/download/${K6_VERSION}/k6-${K6_VERSION}-linux-${ARCH}.tar.gz" \
        -o /tmp/k6.tar.gz && \
    tar -xzf /tmp/k6.tar.gz -C /tmp && \
    mv /tmp/k6-${K6_VERSION}-linux-${ARCH}/k6 /usr/local/bin/k6 && \
    chmod +x /usr/local/bin/k6 && \
    rm -rf /tmp/k6*

WORKDIR /app

# Install minimal Python dependencies
RUN pip install --no-cache-dir \
    redis[hiredis] \
    sqlmodel \
    psycopg2-binary \
    python-dotenv \
    pydantic

# Copy application code
COPY orchestrator/ /app/orchestrator/

# Create directories
RUN mkdir -p /app/runs/load /app/scripts/load

# Set PYTHONPATH so imports work
ENV PYTHONPATH=/app

# Entry point
CMD ["python", "-m", "orchestrator.services.k6_worker"]
