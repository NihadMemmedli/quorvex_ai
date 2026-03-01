# ============================================
# Stage 1: Base image with Python + Node + Playwright
# ============================================
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy AS base

# Set working directory
WORKDIR /app

# Set timezone non-interactively (prevents tzdata from blocking the build)
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install Node.js 20.x (Required for 'npx playwright test' and @playwright/mcp)
# Ubuntu's default Node.js is too old and doesn't support optional chaining (?.)
# Also install VNC stack for live browser view (admin-only feature)
RUN apt-get update && \
    apt-get install -y ca-certificates curl gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y \
        nodejs \
        # VNC stack for live browser view
        xvfb \
        x11vnc \
        fluxbox \
        supervisor \
        git \
        # gosu for dropping privileges in entrypoint
        gosu && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Grafana K6 load testing tool (multi-arch: works on both amd64 and arm64)
RUN K6_VERSION="v0.54.0" && \
    ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/grafana/k6/releases/download/${K6_VERSION}/k6-${K6_VERSION}-linux-${ARCH}.tar.gz" \
        -o /tmp/k6.tar.gz && \
    tar -xzf /tmp/k6.tar.gz -C /tmp && \
    mv /tmp/k6-${K6_VERSION}-linux-${ARCH}/k6 /usr/local/bin/k6 && \
    chmod +x /usr/local/bin/k6 && \
    rm -rf /tmp/k6*

# Copy requirements first to leverage caching
# Use requirements.lock for pinned versions (reproducible builds)
COPY requirements.lock /app/requirements.lock
COPY orchestrator/requirements.txt /app/orchestrator/requirements.txt

# Copy package.json to install node dependencies
COPY package.json package-lock.json /app/
RUN npm ci

# Install Playwright browsers for Node.js (must match @playwright/test version in package.json)
# Increase timeout to 5 minutes (300000ms) to handle slow networks
ENV PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=300000
RUN npx playwright install chromium

# Install Python dependencies
# Upgrade pip first
# Also install websockify for VNC WebSocket bridge
# Install from lockfile first (pinned versions), then remaining from requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.lock && \
    pip install --no-cache-dir -r /app/orchestrator/requirements.txt && \
    pip install --no-cache-dir websockify

# Clone noVNC for websockify --web option (HTML5 VNC client)
RUN git clone --depth 1 https://github.com/novnc/noVNC.git /opt/noVNC

# Copy the entire project
COPY . /app

# Copy supervisor configuration for VNC mode
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Install Playwright skill dependencies (if skill mode is used)
RUN if [ -d "/app/.claude/skills/playwright" ]; then \
      cd /app/.claude/skills/playwright && npm install --omit=dev; \
    fi

# Copy entrypoint script for fixing volume permissions
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create required directories and non-root user
# Note: logs, runs, data, specs, prds, tests directories need to be writable by agent user
# Also grant agent user access to X11 and VNC directories for non-root VNC operation
RUN useradd -m agent && \
    mkdir -p /app/logs /app/runs /app/data /app/specs /app/prds /app/tests /app/scripts/load && \
    chown -R agent:agent /app && \
    # Grant agent user access to X11 and VNC (for non-root VNC operation)
    mkdir -p /tmp/.X11-unix && \
    chown -R agent:agent /tmp/.X11-unix && \
    chmod 1777 /tmp/.X11-unix && \
    mkdir -p /var/log/supervisor /var/run/xvfb /home/agent/.vnc && \
    chown -R agent:agent /var/log/supervisor /var/run/xvfb /home/agent/.vnc

# Note: We do NOT switch to agent user here because volumes mount AFTER the image is built.
# The entrypoint script runs as root to fix volume permissions, then drops to agent user.

# Set python path
ENV PYTHONPATH=/app

# ============================================
# Stage 2: Backend API server (for production)
# ============================================
FROM base AS backend

# Stay as agent user - VNC stack runs as non-root for security
# Note: VNC directories are already set up in the base stage

# Expose API port and VNC WebSocket port
EXPOSE 8001 6080

# Environment for VNC display
ENV DISPLAY=:99

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Entrypoint fixes volume permissions (runs as root), then drops to agent user
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
# Default: Run uvicorn directly (VNC disabled)
# For VNC mode, use: command: ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
CMD ["uvicorn", "orchestrator.api.main:app", "--host", "0.0.0.0", "--port", "8001"]

# ============================================
# Stage 3: CLI (original behavior for local use)
# ============================================
FROM base AS cli

# Entrypoint fixes volume permissions, then drops to agent user
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh", "python", "-m", "orchestrator.cli"]
CMD ["--help"]
