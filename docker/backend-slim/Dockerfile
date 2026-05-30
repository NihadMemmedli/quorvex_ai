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
ENV PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=300000
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV TEMPORAL_BROWSER_WORKFLOW_TASK_QUEUE=quorvex-browser-workflows

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
    unzip \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install ProjectDiscovery Nuclei for template-based security scans.
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

# Create the runtime user with the same UID/GID as the Playwright base image's
# agent user so shared volumes are writable from every backend container.
RUN groupadd --gid 1000 agent && \
    useradd --create-home --uid 1000 --gid 1000 agent

# Copy and install Python dependencies
COPY orchestrator/requirements.txt /app/orchestrator/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/orchestrator/requirements.txt

# Copy and install Node dependencies (for MCP communication)
COPY package.json package-lock.json /app/
RUN npm ci --omit=dev

# Preinstall the browser revisions required by both top-level Playwright and
# @playwright/mcp's nested Playwright dependency so agents never download
# Chromium during a run.
RUN if [ -f /app/node_modules/playwright/cli.js ]; then \
      node /app/node_modules/playwright/cli.js install --with-deps chromium; \
    fi && \
    if [ -f /app/node_modules/@playwright/mcp/node_modules/playwright/cli.js ]; then \
      node /app/node_modules/@playwright/mcp/node_modules/playwright/cli.js install --with-deps chromium; \
    fi

# Copy application code (NO browsers needed)
COPY --chown=agent:agent orchestrator/ /app/orchestrator/
COPY --chown=agent:agent .claude/ /app/.claude/
COPY --chown=agent:agent schemas/ /app/schemas/
COPY --chown=agent:agent playwright.config.ts /app/

# Create required directories
RUN mkdir -p /app/logs /app/runs /app/data /app/specs /app/prds /app/tests /app/test-results

# Copy entrypoint script for fixing volume permissions
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create non-root user (entrypoint will drop privileges to this user)
RUN chown -R agent:agent /app/logs /app/runs /app/data /app/specs /app/prds /app/tests /app/test-results
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
