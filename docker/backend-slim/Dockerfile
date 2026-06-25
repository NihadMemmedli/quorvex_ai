# ============================================
# Slim Backend Container
# FastAPI orchestrator WITHOUT Playwright browsers
# Reduces image from ~1.5GB to ~200MB
# Memory: 4G instead of 24G
# ============================================
FROM python:3.14-slim

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
ENV HOME=/home/agent
ENV USER=agent

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
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Optionally install ProjectDiscovery Nuclei for template-based security scans.
# Disabled by default so normal dev/prod image builds are not blocked by GitHub
# rate limits. Enable with: INSTALL_NUCLEI=true docker compose build ...
ARG INSTALL_NUCLEI=false
RUN <<'SH'
if [ "${INSTALL_NUCLEI}" = "true" ]; then
python - <<'PY'
import json
import os
import platform
import shutil
import stat
import tempfile
import time
import urllib.request
import zipfile

arch_map = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
arch = arch_map.get(platform.machine())
if not arch:
    raise SystemExit(f"Unsupported architecture for nuclei install: {platform.machine()}")

def fetch_json(url, retries=5):
    request = urllib.request.Request(url, headers={"User-Agent": "quorvex-docker-build"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 * attempt)

def download(url, target_path, expected_size=None, retries=5):
    request = urllib.request.Request(url, headers={"User-Agent": "quorvex-docker-build"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response, open(target_path, "wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            actual_size = os.path.getsize(target_path)
            if expected_size and actual_size != expected_size:
                raise RuntimeError(f"incomplete download: got {actual_size} out of {expected_size} bytes")
            return
        except Exception:
            try:
                os.remove(target_path)
            except FileNotFoundError:
                pass
            if attempt == retries:
                raise
            time.sleep(2 * attempt)

release = fetch_json("https://api.github.com/repos/projectdiscovery/nuclei/releases/latest")

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
    download(asset["browser_download_url"], archive_path, asset.get("size"))
    with zipfile.ZipFile(archive_path) as archive:
        corrupt_member = archive.testzip()
        if corrupt_member:
            raise RuntimeError(f"Corrupt nuclei archive member: {corrupt_member}")
        archive.extract("nuclei", tmpdir)
    target = "/usr/local/bin/nuclei"
    os.replace(os.path.join(tmpdir, "nuclei"), target)
    os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
PY
else
    echo "Skipping optional Nuclei install. Set INSTALL_NUCLEI=true to include it in the image."
fi
SH

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
