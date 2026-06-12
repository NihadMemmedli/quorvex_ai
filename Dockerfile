# ============================================
# Stage 1: Base image with Python + Node + Playwright
# ============================================
FROM mcr.microsoft.com/playwright/python:v1.57.0-jammy AS base

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
        x11-utils \
        fluxbox \
        supervisor \
        git \
        unzip \
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

# Install ProjectDiscovery Nuclei for template-based security scans.
# The latest release is resolved at build time so multi-arch Docker builds work
# without requiring Go in the runtime image.
RUN python - <<'PY'
import json
import os
import platform
import stat
import tempfile
import urllib.request
import zipfile

arch_map = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
arch = arch_map.get(platform.machine())
if not arch:
    raise SystemExit(f"Unsupported architecture for nuclei install: {platform.machine()}")

with urllib.request.urlopen("https://api.github.com/repos/projectdiscovery/nuclei/releases/latest", timeout=30) as response:
    release = json.load(response)

asset = next(
    (
        item
        for item in release.get("assets", [])
        if f"linux_{arch}.zip" in item.get("name", "")
    ),
    None,
)
if not asset:
    raise SystemExit(f"No nuclei linux_{arch} release asset found")

with tempfile.TemporaryDirectory() as tmpdir:
    archive_path = os.path.join(tmpdir, asset["name"])
    urllib.request.urlretrieve(asset["browser_download_url"], archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extract("nuclei", tmpdir)
    target = "/usr/local/bin/nuclei"
    os.replace(os.path.join(tmpdir, "nuclei"), target)
    os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
PY

# Copy requirements first to leverage caching
# Use requirements.lock for pinned versions (reproducible builds)
COPY requirements.lock /app/requirements.lock
COPY orchestrator/requirements.txt /app/orchestrator/requirements.txt

# Copy package.json to install node dependencies
COPY package.json package-lock.json /app/
RUN npm ci

# Ensure the Node Playwright browser cache matches package.json.
# The base image has browsers, but this keeps the debug image aligned with npm deps.
ENV PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=300000
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV TEMPORAL_BROWSER_WORKFLOW_TASK_QUEUE=quorvex-browser-workflows
RUN npx playwright install chromium && \
    if [ -f /app/node_modules/@playwright/mcp/node_modules/playwright/cli.js ]; then \
      node /app/node_modules/@playwright/mcp/node_modules/playwright/cli.js install chromium; \
    fi

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

# Reuse the Playwright image's UID/GID 1000 user so shared volumes have the
# same numeric owner in both full and slim backend images.
RUN if id -u pwuser >/dev/null 2>&1; then \
      usermod --login agent --home /home/agent --move-home pwuser && \
      groupmod --new-name agent pwuser; \
    else \
      groupadd --gid 1000 agent && \
      useradd --create-home --uid 1000 --gid 1000 agent; \
    fi

# Copy only runtime application inputs. Large generated/demo/frontend artifacts
# stay out of the backend debug image.
COPY --chown=agent:agent orchestrator/ /app/orchestrator/
COPY --chown=agent:agent schemas/ /app/schemas/
COPY --chown=agent:agent .claude/ /app/.claude/
COPY --chown=agent:agent specs/ /app/specs/
COPY --chown=agent:agent tests/ /app/tests/
COPY --chown=agent:agent prds/ /app/prds/
COPY --chown=agent:agent playwright.config.ts pyproject.toml README.md CLAUDE.md /app/
COPY --chown=agent:agent scripts/load/ /app/scripts/load/

# Copy supervisor configuration for VNC mode
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY scripts/vnc/ /usr/local/bin/vnc/
RUN chmod +x /usr/local/bin/vnc/*.sh

# Install Playwright skill dependencies (if skill mode is used)
RUN if [ -d "/app/.claude/skills/playwright" ]; then \
      cd /app/.claude/skills/playwright && npm install --omit=dev; \
    fi

# Copy entrypoint script for fixing volume permissions
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create required writable directories
# Note: logs, runs, data, specs, prds, tests directories need to be writable by agent user
# Also grant agent user access to X11 and VNC directories for non-root VNC operation
RUN mkdir -p /app/logs /app/runs /app/data /app/specs /app/prds /app/tests /app/test-results /app/scripts/load && \
    chown -R agent:agent /app/logs /app/runs /app/data /app/specs /app/prds /app/tests /app/test-results /app/scripts && \
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
