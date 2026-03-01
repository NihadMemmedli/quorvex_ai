# ============================================
# Slim Backend Container
# FastAPI orchestrator WITHOUT Playwright browsers
# Reduces image from ~1.5GB to ~200MB
# Memory: 4G instead of 24G
# ============================================
FROM python:3.10-slim

WORKDIR /app

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV PYTHONPATH=/app
ENV BACKEND_MODE=slim
ENV BROWSER_WORKERS_ENABLED=true

# Install system dependencies
# - Node.js for MCP server communication
# - curl for health checks
# - gosu for dropping privileges in entrypoint
# - No Playwright browsers needed
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    gnupg \
    gosu \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY orchestrator/requirements.txt /app/orchestrator/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/orchestrator/requirements.txt

# Copy and install Node dependencies (for MCP communication)
COPY package.json package-lock.json /app/
RUN npm ci --omit=dev

# Copy application code (NO browsers needed)
COPY orchestrator/ /app/orchestrator/
COPY .claude/ /app/.claude/
COPY schemas/ /app/schemas/
COPY playwright.config.ts /app/

# Create required directories
RUN mkdir -p /app/logs /app/runs /app/data /app/specs /app/prds /app/tests /app/test-results

# Copy entrypoint script for fixing volume permissions
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create non-root user (entrypoint will drop privileges to this user)
RUN useradd -m agent && chown -R agent:agent /app
# Note: We do NOT switch to agent user here because volumes mount AFTER the image is built.
# The entrypoint script runs as root to fix volume permissions, then drops to agent user.

# Expose API port only (no VNC)
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Entrypoint fixes volume permissions (runs as root), then drops to agent user
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Run FastAPI server
CMD ["uvicorn", "orchestrator.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
